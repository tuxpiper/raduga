"""
Raduga cloud manager
"""

from raduga.aws import Target
from raduga.aws.cfn import AWSCfn
from raduga.distmgr import DistributionsManager

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

    # Action methods
    def deploy(self, stack_sel=None):
        cfn = AWSCfn(self.targets["aws"])
        if stack_sel is None or len(stack_sel) == 0:
            stacks = self.stacks.keys()
        else:
            stacks = stack_sel
        #
        for name in stacks:
            with self._load_stack(name) as stack:
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
