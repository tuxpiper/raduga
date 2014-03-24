"""
Handle distributions. These utilities allow several versions of the same
distributed package to be installed in our "raduga_modules" folder. Stacks
can specify which version they need, and that version be loaded in isolation
while that stack is being processed.
"""

import os, os.path
from contextlib import contextmanager
from pkg_resources import Environment, Distribution, Requirement, working_set

class DistributionsManager(object):
	def __init__(self):
		self.mod_folder = os.path.join(os.getcwd(), "raduga_modules")
		if not os.path.exists(self.mod_folder):
			os.mkdir(self.mod_folder)
		self._init_environment()

	def _init_environment(self):
		dist_folders = map(lambda d: os.path.join(os.getcwd(), self.mod_folder, d), os.listdir(self.mod_folder))
		dist_folders = filter(lambda f: os.path.exists(os.path.join(f, "EGG-INFO")), dist_folders)
		dists = map(lambda f: Distribution.from_filename(f) , dist_folders)
		#
		self.pkg_env = Environment()
		for dist in dists: self.pkg_env.add(dist)

	def _add_to_environment(self, egg_folder):
		dist = Distribution.from_filename(egg_folder)
		self.pkg_env.add(dist)

	def _match_req(self, req):
		return self.pkg_env.best_match(req, working_set)

	def _flatten_reqs(self, *req_sets):
		# req_sets further in the list take precedence
		reqs = {}
		for rset in req_sets:
			for sreq in rset:
				req = Requirement.parse(sreq)
				reqs[req.key] = req
		return reqs.values()

	@contextmanager
	def requirement_loader(self, *req_sets):
		# Save sys.path and sys.modules, to be restored later
		import sys, copy
		old_path = copy.copy(sys.path)
		old_sys_modules = sys.modules.keys()
		# Find distributions for all the requirements
		req_dists = []
		reqs = self._flatten_reqs(req_sets)
		for req in reqs:
			match = self._match_req(req)
			if match is None:
				raise RuntimeError("Unable to find distribution matching %s" % str(req))
			req_dists.append(match)
		# Activate the distributions, return control
		for req in req_dists: req.activate()
		yield
		# Restore sys path and modules
		sys.path = old_path
		for modname in sys.modules.keys():
			if not modname in old_sys_modules:
				del sys.modules[modname]

	def install_dist(self, path):
		setup_py = os.path.join(os.getcwd(), path, "setup.py")
		if not os.path.isfile(setup_py):
			raise RuntimeError("Folder %s doesn't have a setup file" % path)
		with self._build_egg_env(path) as tempdir:
			import subprocess, zipfile
			subprocess.check_call(["python", setup_py, "bdist_egg", "--dist-dir=%s" % tempdir])
			egg = os.listdir(tempdir)[0]    # egg will be the single entry in the temp folder
			# TODO: check if exactly that same egg is installed
			eggf = os.path.join(self.mod_folder, egg)   # target egg folder
			os.mkdir(eggf)
			eggz = zipfile.ZipFile(os.path.join(tempdir, egg))
			eggz.extractall(eggf)

	@contextmanager
	def _build_egg_env(self, path):
		import tempfile, shutil
		old_cwd = os.getcwd()
		os.chdir(path)
		tempdir = tempfile.mkdtemp()
		yield tempdir
		shutil.rmtree(tempdir)
		os.chdir(old_cwd)

