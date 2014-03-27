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
    def getEnvForStack(self,stack_name):
        from copy import copy
        ret = copy(self.env)
        for (stack_var, vdict) in self.stack_vars.items():
            if vdict.has_key(stack_name):
                ret[stack_var] = vdict[stack_name]
            elif vdict.has_key("_default") and not ret.has_key(stack_var):
                ret[stack_var] = vdict["_default"]
        return ret

from contextlib import contextmanager
class Raduga(object):
    def __init__(self):
        self.env = Environment()
        self.stacks = {}
        self.targets = {}
        self.req_modules = []
        self.distmgr = DistributionsManager()

    def addStack(self, name, **stack_desc):
        self.stacks[name] = stack_desc

    def setTarget(self, name, **target):
        self.targets[name] = Target(**target)

    def setRequiredModules(self, reqs):
        self.req_modules = reqs

    @contextmanager
    def _load_stack(self, stack_name):
        #
        def get_stack_class(class_path):        
            class_path_it = class_path.split(".")
            class_module = ".".join(class_path_it[0:-1])
            class_name = class_path_it[-1]
            mod = __import__(class_module, globals(), locals(), [ class_name ], 0)
            return getattr(mod, class_name)
        #
        with self.distmgr.requirement_loader(*self.req_modules):
            environ = self.env.getEnvForStack(stack_name)
            desc = self.stacks[stack_name]
            if desc.has_key('stack_class'):
                stack = desc['stack_class'](environ)
            elif desc.has_key('stack_class_name'):
                the_stack_class = get_stack_class(desc['stack_class_name'])
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
        match_ami = None
        run_phases = []
        for build in iscm_builds:
            if build['status_id'] != "":
                print "Looking for ami with base_ami=%s and target_id=%s" % (base_ami, build['status_id'])
                match_ami = ec2.find_ami(base_ami=base_ami, target_id=build['status_id'])
                if match_ami is not None:
                    print "Found ami %s" % match_ami
                    if build.has_key('run_phases'):
                        run_phases = build['run_phases']
                    elif build.has_key('targets') and build['targets'][0]['run_phases']:
                        run_phases = build['targets'][0]['run_phases']
                    break
            else:
                if build.has_key('run_phases'):
                    run_phases = build['run_phases']
                elif build.has_key('targets') and build['targets'][0]['run_phases']:
                    run_phases = build['targets'][0]['run_phases']
        if match_ami is None:
            match_ami = base_ami
        return (base_ami, match_ami, run_phases, build.has_key('targets') and build['targets'] or None)

    # Action methods
    def build_amis(self, stack_sel=None):
        cfn = AWSCfn(self.targets["aws"])
        ec2 = AWSEC2(self.targets["aws"])

        if stack_sel is None or len(stack_sel) == 0:
            stacks = self.stacks.keys()
        else:
            stacks = stack_sel
        #
        for name in stacks:
            with self._load_stack(name) as stack:
                # Find launchable and buildable resources in the stack
                buildables = filter(lambda l: l.is_buildable(), stack.get_launchable_resources())
                for l in buildables:
                    (base_ami, build_ami, run_phases, targets) = self._find_ami_for_launchable(l, PURPOSE_BUILD)
                    # From the selected build, select the first target (always longest)
                    if run_phases and targets:
                        # TODO: add option to build all targets (not just the first one)
                        target = targets[0]
                        # There is something to build
                        # 1. Create build stack for this resource
                        from cloudcast import Stack
                        from cloudcast.template import EC2Instance
                        import os.path
                        
                        build_stack = Stack(resources_file=os.path.join(os.path.dirname(__file__), "cfn", "build_stack.cfn.py"))
                        build_instance = EC2Instance.standalone_from_launchable(l)
                        build_instance.el_attrs["Properties"]["ImageId"] = build_ami
                        build_instance.el_attrs["Properties"]["InstanceType"] = "c3.xlarge"     # build fast
                        build_instance.iscm.set_phases_to_run(run_phases)
                        build_stack.add_element(build_instance, "BuildInstance")
                        build_instance.iscm.iscm_wc_signal_on_end(build_stack.get_element("iSCMCompleteHandle"))
                        build_stack.fix_broken_references()

                        # 2. Launch build stack
                        build_stack_name = "raduga-build-%s" % target['target_id']
                        cfn_build_stack = cfn.create_stack_in_cfn(
                            stack = build_stack,
                            stack_name = build_stack_name,
                            allow_update = False,
                            tags = { "raduga_stack": name, "base_ami": base_ami, "target_id": target['target_id'] }
                            )
                        print "Launched CFN stack %s for building stack %s to stage %s" % (build_stack_name, name, target['target_id'])
                    else:
                        print "Nothing to build for resource %s in stack %s" % (l.ref_name, name)
        #
        # Wait until build stack/s are ready
        for name in stacks:
            matching_cfn_stacks = cfn.find_stacks(raduga_stack=name)
            for cfn_stack in matching_cfn_stacks:
                build_tags = cfn_stack.get_tags()
                while True:
                    if cfn_stack.is_created():
                        # The instance is ready for image creation
                        from datetime import datetime
                        instance_id = cfn_stack.describe_resources()["BuildInstance"]["physical_resource_id"]
                        ts = (datetime.utcnow().isoformat().replace(":","_"))+"Z"
                        ec2.stop_instance(instance_id)
                        ec2.create_ami(instance_id,
                            name="raduga-%s-%s" % (name, ts),
                            description="Raduga build for stack %s built on %s" % (name, ts),
                            tags=dict(base_ami=build_tags['base_ami'], target_id=build_tags['target_id'])
                        )
                        cfn.delete_stack(cfn_stack.stack_id)
                        break
                    elif cfn_stack.is_failed_or_rollbacked():
                        # Bootstrap failed
                        print "Stack for building stack %s failed" % (name)
                        break


    def deploy(self, stack_sel=None):
        cfn = AWSCfn(self.targets["aws"])
        if stack_sel is None or len(stack_sel) == 0:
            stacks = self.stacks.keys()
        else:
            stacks = stack_sel
        #
        for name in stacks:
            with self._load_stack(name) as stack:
                # Find out if there are any buildable launchables in the stack
                buildables = filter(lambda l: l.is_buildable(), stack.get_launchable_resources())
                for l in buildables:
                    # Which AMI is best to run for the buildable?
                    (base_ami, run_ami, run_phases, targets) = self._find_ami_for_launchable(l, PURPOSE_RUN)
                    # If there is a built AMI different than the base AMI, modify the element
                    if base_ami != run_ami:
                        print "Changing Resource %s to use AMI %s and phases to run %s" \
                            % (l.ref_name, run_ami, map(lambda p: p.phase_name, run_phases)
                        l.el_attrs["Properties"]["ImageId"] = run_ami
                        l.iscm.set_phases_to_run(run_phases)
                cfn_stack = cfn.create_stack_in_cfn(
                    stack = stack,
                    stack_name = name,
                    allow_update = False )
                print "* [created] name: " + str(cfn_stack)

    def printS(self, stack_sel=None):
        if stack_sel is None or len(stack_sel) == 0:
            stacks = self.stacks.keys()
        else:
            stacks = stack_sel
        #
        for name in stacks:
            with self._load_stack(name) as stack:
                print "STACK: %s" % name
                print stack.dump_json()
                print "%s\n\n" % ("-"*79)

    def update(self, stack_sel=[]):
        pass

    def undeploy(self, stack_sel=[]):
        pass

    def describe(self):
        pass
