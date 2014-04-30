'''
@author: David Losada Carballo <david@tuxpiper.com>
'''

from setuptools import setup, find_packages

setup(
    name = "raduga",
    version = "0.0.5",
    packages = find_packages(),

    description = ("Infrastructure-as-code framework for AWS"),
    author = "David Losada Carballo",
    author_email = "david@tuxpiper.com",
    install_requires = ['cloudcast>=0.0.8', 'docopt>=0.6.1', 'boto>=2.26.1', 'setuptools==3.3'],
    license = 'MIT',
    keywords = "aws internet cloud infrastructure deployment automation",
    long_description = open('README.md').read(),
    url = "http://github.com/tuxpiper/raduga",
    zip_safe = False,
    entry_points = {
        'console_scripts': [
            'raduga = raduga.main:main',
        ]
    },
    package_data = {
        # Script files that contain initial bootstrap sequences
        'raduga': ['cfn/*']
    },
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Topic :: System",
        "Environment :: Console",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python"
    ], 
)
