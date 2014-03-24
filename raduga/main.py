"""
Raduga commands

Usage:
  raduga credentials add [options] <id>
  raduga module install [options] <path>

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

log = logging.getLogger()
version = pkg_resources.require("raduga")[0].version

def main():
    args = docopt(__doc__, version=version)

    if args['--debug']:
        logging_level = logging.DEBUG
    if args['--verbose']:
        logging_level = logging.INFO
    else:
        logging_level = logging.WARNING
    logging.basicConfig(stream=sys.stderr, level=logging_level)

    log.info("raduga version %s ( https://github.com/tuxpiper/raduga )" % version)

    if args['module'] and args['install']:
        from raduga.distmgr import DistributionsManager
        distmgr = DistributionsManager()
        distmgr.install_dist(args['<path>'])
    elif args['credentials'] and args['add']:
        print "Adding credentials, id: " + args['<id>']
        from raduga.config import config
        from raduga.aws import Credentials
        creds = Credentials.from_interactive()
        config.add_credentials(args['<id>'], creds)

