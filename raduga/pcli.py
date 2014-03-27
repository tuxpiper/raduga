"""
Raduga profile commands

Usage:
    pcli.py print [options] [<stack> [<stack> ...]]
    pcli.py deploy [options] [<stack> [<stack> ...]]
    pcli.py build [options] [<stack> [<stack> ...]]
    pcli.py update [options] [<stack> [<stack> ...]]
    pcli.py undeploy [options] [<stack> [<stack> ...]]

Options:
    -h --help     Show this screen
    -V --verbose  Be verbose
    -D --debug    Be extremely verbose
    --version     Show version
""" 
from docopt import docopt
import pkg_resources, sys, string
import logging

from raduga import Raduga

__doc__ = string.replace(__doc__, "pcli.py", sys.argv[0])
log = logging.getLogger()
version = pkg_resources.require("raduga")[0].version

def run(config_fn):
    args = docopt(__doc__, version=version)

    if args['--debug']:
        logging_level = logging.DEBUG
    if args['--verbose']:
        logging_level = logging.INFO
    else:
        logging_level = logging.WARNING
    logging.basicConfig(stream=sys.stderr, level=logging_level)

    log.info("raduga version %s ( https://github.com/tuxpiper/raduga )" % version)

    raduga = Raduga()
    config_fn(raduga)

    if args['print']:
        raduga.printS(args['<stack>'])
    elif args['deploy']:
        raduga.deploy(args['<stack>'])
    elif args['build']:
        raduga.build_amis(args['<stack>'])

