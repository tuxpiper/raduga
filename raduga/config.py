#!/usr/bin/python
"""
Management of configuration files and their contents
"""
import os, stat, sys
from ConfigParser import SafeConfigParser

from raduga.aws import Credentials
    
def _locate_conf_file():
    """
    Returns absolute path to where the module config file should
    be located.
    """
    if os.getenv("VIRTUAL_ENV") != None:
        folder = os.getenv("VIRTUAL_ENV")
    elif os.getenv("HOME") != None:
        folder = os.getenv("HOME")
    else:
        raise RuntimeError("no VIRTUAL_ENV or HOME defined")
    return os.path.join(folder, ".raduga.cfg")

def _load_conf_file():
    """
    Returns ConfigParser object with conf file contents. If the conf
    file doesn't exist, the ConfigParser is empty
    """
    ret = SafeConfigParser()
    conf_path = _locate_conf_file()
    if (os.path.exists(conf_path)):
        f = open(conf_path)
        ret.readfp(f, conf_path)
        f.close()
    return ret
    
def _save_conf_file(cfg):
    """
    Given a ConfigParser object, it saves its contents to the config
    file location, overwriting any previous contents
    """
    conf_path = _locate_conf_file()
    f = open(conf_path, "w")
    cfg.write(f)
    f.close()
    # Make sure it has restricted permissons (since it tends to have stuff
    # like credentials in it)
    os.chmod(conf_path, stat.S_IRUSR + stat.S_IWUSR)

def _load_ini_file():
    """
    Loads the raduga.ini file from the current folder
    """
    ret = SafeConfigParser()
    conf_path = "raduga.ini"
    if (os.path.exists(conf_path)):
        f = open(conf_path)
        ret.readfp(f, conf_path)
        f.close()
    return ret

def _save_ini_file(ini):
    """
    Save the raduga.ini file contents
    """
    conf_path = "raduga.ini"
    f = open(conf_path, "w")
    ini.write(f)
    f.close()

class Config:
    def __init__(self):
        self.conf = _load_conf_file()

    def _save(self):
        _save_conf_file(self.conf)

    def add_credentials(self, name, creds):
        section_name = "cr-" + name
        self.conf.add_section(section_name)
        self.conf.set(section_name, "_class", "credentials")
        for (k,v) in creds.options.iteritems():
            if type(v) == str:
                self.conf.set(section_name, k, v)
            elif type(v) == dict:
                self.conf.set(section_name, k, "dict(%s)" % str(v))
            else:
                raise RuntimeError("Unhandled conf value type: %s" % str(type(v)))
        self._save()

    def get_credentials(self, name):
        section_name = "cr-" + name
        return self._decode_credentials(self.conf.items(section_name))

    def _decode_credentials(self, items):
        return Credentials.from_dict_items(
            map(lambda(k,v): (k,v.startswith("dict(") and eval(v) or v), items)
        )

    def find_credentials(self, **tags):
        ret = []
        def creds_match(creds):
            # Compare configure cred tags against given filter
            for (tk,tv) in tags.items():
                if not creds_tags.has_key(tk):
                    return False
                if creds_tags[tk] != tv:
                    return False
            return True
        for s in self.conf.sections():
            if self.conf.get(s, "_class") != "credentials":
                continue
            creds = self._decode_credentials(self.conf.items(s))
            creds_tags = creds.options.has_key("tags") and creds.options["tags"] or {}
            if creds_match(creds):
                ret.append(creds)
        if len(ret) > 1:
            raise RuntimeException("More than one set of credentials match the provided tags " + str(tags))
        if len(ret) == 0:
            return None
        return ret[0]

# Export the configuration via "config"
config = Config()
