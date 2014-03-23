
"""
Raduga cloud manager
"""

from raduga.aws import Target
from raduga.aws.cfn import AWSCfn

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

class Raduga(object):
    def __init__(self):
        self.env = Environment()
        self.stacks = {}
        self.targets = {}

    def addStack(self, name, **stack):
        self.stacks[name] = stack

    def setTarget(self, name, **target):
        self.targets[name] = Target(**target)

    # Action methods
    def deploy(self, stack_sel=None):
        cfn = AWSCfn(self.targets["aws"])
        if stack_sel is None or len(stack_sel) == 0:
            stacks = self.stacks.keys()
        else:
            stacks = stack_sel
        #
        for name in stacks:
            environ = self.env.getEnvForStack(name)
            desc = self.stacks[name]
            the_stack = desc['stack_class'](environ)
            cfn_stack = cfn.create_stack_in_cfn(
                stack = the_stack,
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
            print "STACK: %s" % name
            environ = self.env.getEnvForStack(name)
            desc = self.stacks[name]
            the_stack = desc['stack_class'](environ)
            print the_stack.dump_json()
            print "%s\n\n" % ("-"*79)

    def update(self, stack_sel=[]):
        pass

    def undeploy(self, stack_sel=[]):
        pass

    def describe(self):
        pass
