"""
Raduga cloud manager
"""

from raduga.aws import Target
from raduga.aws.ec2 import AWSEC2
from raduga.aws.cfn import AWSCfn
from raduga.distmgr import DistributionsManager

from cloudcast.iscm.phased import PURPOSE_BUILD, PURPOSE_RUN

class Environment(object):
    def __init__(self, **kwargs):
        self.env = dict(**kwargs)
        self.stack_vars = {}
    def set(self, **kwargs):
        self.env = dict(**kwargs)
    def setStackVar(self, name, valuesDict):
        self.stack_vars[name] = valuesDict
    def getEnvForStack(self, stack_name, **add_dict):
        from copy import copy
        ret = copy(self.env)
        ret.update(add_dict)
        #
        for (stack_var, vdict) in self.stack_vars.items():
            if vdict.has_key(stack_name):
                ret[stack_var] = vdict[stack_name]
            elif vdict.has_key("_default") and not ret.has_key(stack_var):
                ret[stack_var] = vdict["_default"]
        #
        return ret

from contextlib import contextmanager
class Raduga(object):
    def __init__(self):
        self.env = Environment()
        self.stacks = {}
        self.targets = {}
        self.req_modules = []
        self.distmgr = DistributionsManager()
        self._stack_names = {}

    def addStack(self, name, **stack_desc):
        self.stacks[name] = stack_desc
        if stack_desc.has_key('stack_name'):
            self._stack_names[name] = stack_desc['stack_name']
        else:
            self._stack_names[name] = name

    def setTarget(self, name, **target):
        self.targets[name] = Target(**target)

    def setRequiredModules(self, reqs):
        self.req_modules = reqs

    # ---- actions and helpers

    @contextmanager
    def _load_stack(self, stack_name, stack_desc):
        #
        def get_stack_class(class_path):        
            class_path_it = class_path.split(".")
            class_module = ".".join(class_path_it[0:-1])
            class_name = class_path_it[-1]
            mod = __import__(class_module, globals(), locals(), [ class_name ], 0)
            return getattr(mod, class_name)
        #
        with self.distmgr.requirement_loader(*self.req_modules):
            environ = self.env.getEnvForStack(stack_name, _this_stack_name=self._stack_names[stack_name], _stack_names=self._stack_names)
            if stack_desc.has_key('stack_class'):
                stack = stack_desc['stack_class'](environ)
            elif stack_desc.has_key('stack_class_name'):
                the_stack_class = get_stack_class(stack_desc['stack_class_name'])
                stack = the_stack_class(environ)
            #
            yield stack
        #

    def _find_ami_for_launchable(self, l, purpose=PURPOSE_RUN):
        """
        This helper method helps to find the most suitable ami for a launchable
        resource, taking into account previously built amis
        """
        ec2 = AWSEC2(self.targets["aws"])
        region = self.targets["aws"].get_region()
        # Compute all possible builds for the launchable configuration
        iscm_builds = l.iscm.get_possible_builds(purpose)
        build_status_ids = map(lambda b: b['status_id'], iscm_builds)
        # Resolve the base_ami for the region we are working on
        base_ami = l.resolve_ami(region=region)
        # Find the first status id with a match in AWS AMIs
        match_ami = base_ami
        run_phases = None
        targets = None
        for build in iscm_builds:
            if purpose == PURPOSE_RUN:
                run_phases = build['run_phases']
            elif purpose == PURPOSE_BUILD:
                targets = build['targets']
            #
            if build['status_id'] != "":
                ami = ec2.find_ami(base_ami=base_ami, target_id=build['status_id'])
                if ami is not None:
                    match_ami = ami
                    break
        
        if purpose == PURPOSE_RUN:
            return [ dict(launchable=l, base_ami=base_ami, run_ami=match_ami, run_phases=run_phases) ]
        elif purpose == PURPOSE_BUILD:
            return [ dict(launchable=l, base_ami=base_ami, build_ami=match_ami, target_id=t['target_id'], run_phases=t['run_phases']) for t in targets ]

    def _create_build_stack(self, target):
        from cloudcast import Stack
        from cloudcast.template import EC2Instance
        import os.path
        #
        build_stack = Stack(resources_file=os.path.join(os.path.dirname(__file__), "cfn", "build_stack.cfn.py"))
        build_instance = EC2Instance.standalone_from_launchable(target['launchable'])
        build_instance.el_attrs["Properties"]["ImageId"] = target['build_ami']
        build_instance.el_attrs["Properties"]["InstanceType"] = "c3.xlarge"     # build fast
        build_instance.iscm.set_phases_to_run(target['run_phases'])
        build_stack.add_element(build_instance, "BuildInstance")
        build_instance.iscm.iscm_wc_signal_on_end(build_stack.get_element("iSCMCompleteHandle"))
        build_stack.fix_broken_references()
        return build_stack

    def _build_state_machine(self, build_target):
        from time import sleep
        #
        cfn = AWSCfn(self.targets["aws"])
        ec2 = AWSEC2(self.targets["aws"])
        state = build_target['state']
        target = build_target['target']
        target_id = target['target_id']
        build_stack = build_target.has_key('build_stack') and build_target['build_stack'] or None
        cfn_stack = build_target.has_key('cfn_stack') and build_target['cfn_stack'] or None
        instance_id = build_target.has_key('instance_id') and build_target['instance_id'] or None
        ami_id = build_target.has_key('ami_id') and build_target['ami_id'] or None
        #
        if state == "initial":
            # Check if the target is already being built (previous run)
            match_cfn_stack = cfn.find_stacks(base_ami=target['base_ami'], target_id=target['target_id'])
            sleep(2)    # Avoid abusing AWS APIs
            if len(match_cfn_stack) == 0:
                # No matching stack, create one
                build_target['build_stack'] = self._create_build_stack(target)
                build_target['state'] = "cfn_launch_ready"
                return build_target
            else:
                # Matching stack, analyze state
                print "* Found matching CFN stack for target_id %s" % target_id
                self._running_stacks += 1   # count towards limits
                build_target['cfn_stack'] = match_cfn_stack[0]
                build_target['state'] = 'cfn_state_check'
                return build_target
        elif state == 'cfn_launch_ready':
            # Launch the build stack (but avoid having too many running build stacks)
            if self._running_stacks >= 8:
                return build_target     # Launch later
            build_stack_name = "raduga-build-%s" % target_id
            cfn_build_stack = cfn.create_stack_in_cfn(
                stack = build_stack,
                stack_name = build_stack_name,
                allow_update = False,
                tags = dict(
                    raduga_stack = target['stack_name'],
                    base_ami = target['base_ami'],
                    target_id = target_id
                )
            )
            sleep(2)    # Avoid abusing AWS APIs
            #
            self._running_stacks += 1   # count towards limits
            build_target['state'] = 'cfn_state_check'
            build_target['cfn_stack'] = cfn_build_stack
            print "* Launched CFN stack %s for building target_id %s" % (build_stack_name, target['target_id'])
            return build_target
        elif state == 'cfn_state_check':
            being_created = cfn_stack.is_being_created()
            sleep(2)
            if not being_created:
                build_target['state'] = 'cfn_creation_check'
            return build_target
        elif state == 'cfn_creation_check':
            is_created = cfn_stack.is_created()
            sleep(2)
            if is_created:
                build_target['state'] = 'check_instance_state'
                build_target['instance_id'] = \
                    cfn_stack.describe_resources()["BuildInstance"]["physical_resource_id"]
            else:
                build_target['state'] = 'cfn_failure_check'
            return build_target
        elif state == 'cfn_failure_check':
            is_failed = cfn_stack.is_failed_or_rollbacked()
            sleep(2)
            if is_failed:
                build_target['result'] = 'FAILED'
                build_target['state'] = 'cfn_cleanup'
            else:   # stack is probably being deleted, restart the build job
                self._running_stacks -= 1   # count towards limits
                build_target = { "target": target, "state": "initial" }
            return build_target
        elif state == 'check_instance_state':
            instance_state = ec2.get_instance_state(instance_id)
            sleep(2)
            if instance_state == 'running':
                print "* Stopping instance %s for target %s" % (instance_id, target)
                ec2.stop_instance(instance_id)
                sleep(2)
            elif instance_state == 'stopping':
                pass     # wait until it is indeed stopped
            elif instance_state == 'stopped':
                from datetime import datetime
                ts = (datetime.utcnow().isoformat().replace(":","_"))+"Z"
                ami_id = ec2.create_ami(instance_id,
                    name="raduga-%s-%s" % (target['stack_name'], ts),
                    description="Raduga build for stack %s built on %s" % (target['stack_name'], ts),
                    tags=dict(base_ami=target['base_ami'], target_id=target['target_id'], last_phase=target['last_phase'])
                )
                sleep(2)
                print "* Started creation of AMI %s for target %s" % (ami_id, target)
                build_target['ami_id'] = ami_id
                build_target['state'] = 'check_ami_state'
            else:
                print "[ERROR] unhandled instance state '%s' for build target '%s'" % (instance_state, str(build_target))
                build_target['result'] = 'FAILED'
                build_target['state'] = 'cfn_cleanup'
            return build_target
        elif state == 'check_ami_state':
            ami_state = ec2.get_ami_state(ami_id)
            sleep(2)
            if ami_state == 'available':
                build_target['result'] = 'OK'
                build_target['state'] = 'cfn_cleanup'
            elif ami_state == 'failed':
                build_target['result'] = 'FAILED'
                build_target['state'] = 'cfn_cleanup'
            return build_target
        elif state == 'cfn_cleanup':
            print "* Cleaning up stack with id %s" % cfn_stack.stack_id
            cfn.delete_stack(cfn_stack.stack_id)
            sleep(2)
            self._running_stacks -= 1   # count towards limits
            build_target['state'] = 'done'
            return build_target
        elif state == 'done':
            return build_target     # do  nothing

    def build_amis(self, stack_sel=None, build_next=False, build_all=False, dry_run=False):
        if stack_sel is None or len(stack_sel) == 0:
            stacks = self.stacks.keys()
        else:
            stacks = stack_sel
        #
        # Process all stacks and collect pending target ids
        build_targets = {}
        for name in stacks:
            desc = self.stacks[name]
            with self._load_stack(name, desc) as stack:
                buildables = filter(lambda l: l.is_buildable(), stack.get_launchable_resources())
                for l in buildables:
                    targets = self._find_ami_for_launchable(l, PURPOSE_BUILD)
                    # Keep only the first target if not build_all
                    if len(targets) > 0 and not build_all:
                        if build_next:
                            targets = [ targets[-1] ]
                        else:
                            targets = targets[0:1]
                    # Create build states for all targets, skip duplicates
                    for t in targets:
                        t['stack_name'] = name
                        t['last_phase'] = t['run_phases'][-1].phase_name
                        print str(t)
                        if build_targets.has_key(t['target_id']):     # skip
                            print "  ... skipped (target_id already in list build)"
                        else:
                            build_targets[t['target_id']] = { "target": t, "state": "initial" }
        #
        print "There are %d AMIs to be built" % len(build_targets)
        #
        if len(build_targets) == 0:     # nothing to do
            return
        #
        # Run the build target state machine on each target at a time
        self._running_stacks = 0
        while True:
            done_targets = 0
            for (target_id, target) in build_targets.items():
                if target['state'] == 'done':
                    done_targets += 1
                else:
                    build_targets[target_id] = self._build_state_machine(target)
            if done_targets == len(build_targets):
                break   # All done
        #
        from pprint import pprint
        pprint(build_targets)

    def deploy(self, stack_sel=None):
        cfn = AWSCfn(self.targets["aws"])
        if stack_sel is None or len(stack_sel) == 0:
            stacks = self.stacks.keys()
        else:
            stacks = stack_sel
        #
        for name in stacks:
            desc = self.stacks[name]
            with self._load_stack(name, desc) as stack:
                stack_name = name
                if desc.has_key('stack_name'):
                    stack_name = desc['stack_name']
                # Find out if there are any buildable launchables in the stack
                buildables = filter(lambda l: l.is_buildable(), stack.get_launchable_resources())
                for l in buildables:
                    # Which AMI is best to run for the buildable?
                    target = self._find_ami_for_launchable(l, PURPOSE_RUN)[0]
                    # If there is a built AMI different than the base AMI, modify the element
                    if target['base_ami'] != target['run_ami']:
                        print "Changing Resource %s to use AMI %s and phases to run %s" \
                            % (l.ref_name, target['run_ami'], target['run_phases'])
                        l.el_attrs["Properties"]["ImageId"] = target['run_ami']
                        l.iscm.set_phases_to_run(target['run_phases'])
                #
                cfn_stack = cfn.create_stack_in_cfn(
                    stack = stack,
                    stack_name = stack_name,
                    allow_update = True )
                print "* deployed/updated CFN stack with name: " + str(cfn_stack)

    def printS(self, stack_sel=None):
        if stack_sel is None or len(stack_sel) == 0:
            stacks = self.stacks.keys()
        else:
            stacks = stack_sel
        #
        for name in stacks:
            desc = self.stacks[name]
            with self._load_stack(name, desc) as stack:
                print "STACK: %s" % name
                print stack.dump_json()
                print "%s\n\n" % ("-"*79)

    def update(self, stack_sel=[]):
        pass

    def undeploy(self, stack_sel=[]):
        pass

    def describe(self):
        pass
