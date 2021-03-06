from boto.exception import BotoServerError
from boto.cloudformation.connection import CloudFormationConnection
from json_tools import diff as json_diff
import json, logging

_log = logging.getLogger(__name__)
_non_delete_states = filter(lambda s: not s.startswith('DELETE_'), CloudFormationConnection.valid_states)

class AWSCfn(object):
    def __init__(self, target):
        self.bucket = target.ensure_bucket_exists()
        self.conn = target.get_cfn_conn()

    def create_stack_in_cfn(self, **kwargs):
        """
        Expected args:
            stack =
            stack_name =
        Additional args:
            parameters = list of tuples with parameter values
            allow_update = whether to allow update operations
        """
        if not kwargs.has_key('parameters') or kwargs['parameters'] is None:
            parameters=[]
        else:
            parameters = kwargs['parameters']
        if not kwargs.has_key('stack'):
            raise RuntimeError("stack not provided")
        if not kwargs.has_key('stack_name'):
            raise RuntimeError("stack name not provided")

        stack = kwargs['stack']
        stack_name = kwargs['stack_name']
        
        # Create the stack
        try:
            if not self.stack_exists(stack_name):
                cfn_api_call = self.conn.create_stack
            elif not kwargs['allow_update']:
                raise RuntimeError("Stack already exists but updates not allowed!")
            else:
                cfn_api_call = self.conn.update_stack

            template_url = self._upload_stack_template(stack, stack_name)
            api_call_args = dict(
                stack_name=kwargs['stack_name'],
                template_url=template_url,
                parameters=parameters,
                capabilities=stack.required_capabilities
            )
            if kwargs.has_key('tags'):
                api_call_args['tags'] = kwargs['tags']
            stack_id = cfn_api_call(**api_call_args)
            return self.AWSStack(stack_id)
        except BotoServerError as e:
            raise RuntimeError("AWS returned: " + str(e.args))

    def diff_stack_in_cfn(self, **kwargs):
        """
        Finds differences between a given stack and a deployed one.
        Expected args:
            stack = the stack code
            stack_name = stack name in CloudFormation
        Additional args:
            parameters = list of tuples with parameter values
        """
        if not kwargs.has_key('parameters') or kwargs['parameters'] is None:
            parameters=[]
        else:
            parameters = kwargs['parameters']
        if not kwargs.has_key('stack'):
            raise RuntimeError("stack not provided")
        if not kwargs.has_key('stack_name'):
            raise RuntimeError("stack name not provided")

        stack = kwargs['stack']
        stack_name = kwargs['stack_name']

        if not self.stack_exists(stack_name):
            raise RuntimeError("Stack %s is not deployed" % stack_name)

        try:
            cfn_stack = self.get_created_stack(stack_name).get_template()
            cfn_stack = json.loads(cfn_stack['GetTemplateResponse']['GetTemplateResult']['TemplateBody'])
            stack_template = json.loads(stack.dump_json(pretty=False))
            diff = json_diff(cfn_stack, stack_template)
            # TODO: compare parameters as well
            print "Difference cfn -> code"
            print json.dumps(diff, indent=2)
        except BotoServerError as e:
            raise RuntimeError("AWS returned: " + str(e.args))

    def _upload_stack_template(self, stack, stack_name):
        import random, time
        from boto.s3.key import Key
        k = Key(self.bucket)
        k.key = "raduga-%s-%d-%s" % ( stack_name, int(time.time()), "%04x" % random.randrange(16**4))
        template_body = stack.dump_json(pretty=False)
        #print "Uploading\n%s\n\n" % template_body
        #
        _log.info("Uploading stack template to S3 (size %dKB out of 300KB allowed)" % (len(template_body) / 1024))
        k.set_contents_from_string(template_body)
        return "https://s3.amazonaws.com/%s/%s" % (self.bucket.name, k.key)

    def stack_exists(self, stack_name):
        st = self.AWSStack(stack_name)
        try:
            if st.is_deleted():
                return False
            else:
                return True
        except BotoServerError as e:
            if e.code == 'ValidationError':
                return False

    def get_created_stack(self, stack_name):
        return self.AWSStack(stack_name)
    
    def list_stacks(self, **kwargs):
        ss = self.conn.list_stacks(_non_delete_states)
        return [ s.stack_name for s in ss ]

    def find_stacks(self, **tags):
        stacks = self.conn.describe_stacks()
        matches = filter(lambda s: all( map(lambda t: t in s.tags.items(), tags.items() ) ), stacks )
        return [ self.AWSStack(s.stack_id) for s in matches ]
    
    def delete_stack(self, stack_name, **kwargs):
        self.conn.delete_stack(stack_name)
        return self.AWSStack(stack_name)

    def AWSStack(self, stack_id):
        return _AWSStack(self, stack_id)

class _AWSStack:
    def __init__(self, cfn, stack_id):
        self.cfn = cfn
        self.stack_id = stack_id

    def describe(self):
        """
        Returns dictionary describing the stack status. Relevant entries:
            "stack_status" -- stack creation status
            "parameters" -- list of dictionaries describing provided
                            parameters. Each dictionary's relevant keys:
                "key" -- parameter name in the stack template
                "value" -- parameter assigned value
            "outputs" -- list of outputs generated by the stack. Each
                         output's relevant keys:
                "key" -- output name in the stack template
                "value" -- output value
                "description" -- description of the output
        """
        cfn = self.cfn.conn
        s = cfn.describe_stacks(stack_name_or_id=self.stack_id)[0]
        outputs = [vars(o) for o in s.outputs]
        params = [vars(p) for p in s.parameters]
        ret = vars(s)
        ret['parameters'] = params
        ret['outputs'] = outputs
        ret['tags'] = s.tags 
        return ret
        
    def describe_resources(self):
        """
        Returns a dictionary of resources. The key is the name of the
        resource and the value is a map with information about that
        stack resource. Relevant dictionary entries:
            "logical_resource_id" -- given name of the resource in the stack
            "resource_type" -- string representing resource type
            "resource_status" -- string specifying resources status (i.e. CREATE_COMPLETE)
            "physical_resource_id" -- name of the resource in the AWS infrastructure
            "description" -- resource description (often empty)
        """
        cfn = self.cfn.conn
        rr = cfn.describe_stack_resources(stack_name_or_id=self.stack_id)
        return dict([(r.logical_resource_id, vars(r)) for r in rr]);
        
    def describe_events(self, not_these=[]):
        """
        Returns a list of events. Each event is a dictionary with the
        following relevant entries:
            "event_id" -- unique event id
            "timestamp" -- region local
            "logical_resource_id" -- logical id of the resource involved in the event
            "resource_status" -- status of the involved resource
            "resource_type" -- type of the involved resource
            "resource_status_reason" -- explanation of status change (useful for errors)
        Events are returned ordered by timestamp. The not_these parameter
        serves the purpose for passing a list of events that shouldn't be
        included in the returned list (filtering is done based on event_id)
        """
        cfn = self.cfn.conn
        blocked_events = set(e['event_id'] for e in not_these)
        s = cfn.describe_stacks(stack_name_or_id=self.stack_id)[0]
        events = filter(lambda e: e['event_id'] not in blocked_events,
            [vars(e) for e in s.describe_events()])
        events.sort(key=lambda e: e['timestamp'])
        return events
        
    def describe_parameters(self):
        """
        Return a dictionary of parameters. Each parameter is a dictionary with
        the following relevant entries.
            "key" -- parameter name
            "value" -- parameter value at stack creation
        """
        st = self.describe()
        return dict([(p['key'],p) for p in st['parameters']])
        
    def describe_outputs(self):
        st = self.describe()
        return dict([(p['key'],p) for p in st['outputs']])
    
    def get_stack_status(self):
        status = self.describe()
        return status['stack_status']

    def get_tags(self):
        desc = self.describe()
        return desc['tags']

    def get_template(self):
        cfn = self.cfn.conn
        return cfn.get_template(stack_name_or_id=self.stack_id)
    
    def is_being_created(self):
        status = self.describe()
        return status['stack_status'] in ['CREATE_IN_PROGRESS', 'UPDATE_IN_PROGRESS']
        
    def is_being_deleted(self):
        status = self.describe()
        return (status['stack_status'] == 'DELETE_IN_PROGRESS')
        
    def is_created(self):
        status = self.describe()
        return status['stack_status'] in ['CREATE_COMPLETE' , 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE' ]

    def is_deleted(self):
        status = self.describe()
        return status['stack_status'] == 'DELETE_COMPLETE'

    def is_failed_or_rollbacked(self):
        status = self.describe()
        return (status['stack_status'] in ['CREATE_FAILED', 'ROLLBACK_IN_PROGRESS', 'ROLLBACK_FAILED', 'ROLLBACK_COMPLETE'])

    def is_rollback_triggered(self):
        status = self.describe()
        return (status['stack_status'] in ['ROLLBACK_IN_PROGRESS', 'ROLLBACK_FAILED', 'ROLLBACK_COMPLETE'])
        
    def is_delete_triggered(self):
        status = self.describe()
        return (status['stack_status'] in ['DELETE_IN_PROGRESS', 'DELETE_FAILED', 'DELETE_COMPLETE'])
