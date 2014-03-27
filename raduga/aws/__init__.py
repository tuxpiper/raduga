import sys

if sys.version_info >= (2,7):
    from collections import OrderedDict
else:
    from ordereddict import OrderedDict

def _tags_to_dict(s):
    """ "k1=v1,k2=v2" --> { "k1": "v1", "k2": "v2" } """
    return dict(map(lambda kv: kv.split('='), s.split(",")))

class Credentials:
    _recognized_options = OrderedDict([
        ('aws_access_key', { 'description': "Provided access key" } ),
        ('aws_secret_key', { 'description': "Provided secret key" } ),
        ('default_region', {
            'description': "Default AWS region to operate on",
            'default': 'us-east-1' }),
        ('tags', { 'description': "Tags, specified as comma separated key=value tokens" })
    ])
    def __init__(self, **options):
        self.options = options

    def __str__(self):
        opts = dict((k,self.options[k]) for k in ('aws_access_key','tags') if k in self.options)
        return "%s(%r)" % (self.__class__, opts)

    def get_iam_user_info(self):
        """
        Retrieves information from IAM about the configured user. The return
        value is a dictionary with the following keys:
            "user_name", "arn", "user_id", "path", "create_date"
        """
        from boto.iam.connection import IAMConnection
        iac = IAMConnection(self.options['aws_access_key'],self.options['aws_secret_key'])
        return iac.get_user()['get_user_response']['get_user_result']['user']

    def get_iam_login_url(self):
        """
        Returns login URL for the console
        """
        from boto.iam.connection import IAMConnection
        iac = IAMConnection(self.options['aws_access_key'],self.options['aws_secret_key'])
        alias = iac.get_account_alias()['list_account_aliases_response']['list_account_aliases_result']['account_aliases'][0]
        return "https://%s.signin.aws.amazon.com/console" % alias

    @classmethod
    def from_dict_items(cls, items):
        return cls(**dict(items))

    @classmethod
    def from_interactive(cls):
        """
        Queries the user interactively for cloud configuration parameters.
        Returns a dictionary with the results
        """
        ret = {}
        for (opt_name,opt) in cls._recognized_options.items():
            if ret.has_key(opt_name):
                print "%s [%s]?" % (opt['description'], ret[opt])
            elif opt.has_key('default'):
                print "%s [%s]?" % (opt['description'], opt['default'])
            else:
                print "%s ?" % opt['description']
            v = raw_input('--> ').strip()
            if v == "":
                if not opt.has_key("default") or opt["default"] is None:
                    continue
                v = opt["default"]
            if opt_name == "tags":
                v = _tags_to_dict(v)
            ret[opt_name] = v
        return cls(**ret)

class Target(object):
    def __init__(self, **kwargs):
        self.region = None
        self.access_key = None
        self.secret_key = None
        if kwargs.has_key("credentials"):
            creds = kwargs["credentials"]
            self.region = creds.options["default_region"]
            self.access_key = creds.options["aws_access_key"]
            self.secret_key = creds.options["aws_secret_key"]
            self.cfn_bucket_name = self._infer_cfn_bucket_name(creds)
        if kwargs.has_key("region"):
            self.region = kwargs["region"]

    def _infer_cfn_bucket_name(self, creds):
        import re
        iam_user_info = creds.get_iam_user_info()
        arn_tokens = iam_user_info["arn"].split(":")
        bucket_name = "raduga-cfn-%s-%s" % (arn_tokens[4], re.sub(r'[^\w\-]', "-", arn_tokens[5]))
        return bucket_name

    def ensure_bucket_exists(self):
        s3 = self.get_s3_conn()
        lookup = s3.lookup(self.cfn_bucket_name)
        if lookup is None:
            # The bucket does not exist yet, create
            return s3.create_bucket(self.cfn_bucket_name)
        else:
            return lookup

    def get_region(self):
        return self.region

    def get_ec2_conn(self):
        import boto.ec2
        return boto.ec2.connect_to_region(
            self.region,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key
        )

    def get_cfn_conn(self):
        import boto.cloudformation
        return boto.cloudformation.connect_to_region(
            self.region,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key
        )

    def get_s3_conn(self):
        from boto.s3.connection import S3Connection
        return S3Connection(self.access_key, self.secret_key)