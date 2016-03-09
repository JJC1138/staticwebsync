from setuptools import setup

import staticwebsync # this is to invoke the Python version check in the package's __init__.py

setup(
    name='staticwebsync',
    version='1.1.0',
    maintainer='Jon Colverson',
    maintainer_email='staticwebsync@jjc1138.net',
    packages=['staticwebsync'],
    url='http://staticwebsync.jjc1138.net/',
    license='MIT',
    description='Automates setting up S3/CloudFront for web site hosting',
    long_description='staticwebsync is a command-line tool for automating the fiddly aspects of hosting your static web site on Amazon S3 or CloudFront. It automates the process of configuring the services for hosting web sites, and synchronizes the contents of a local folder to the site.',

    entry_points={'console_scripts': ['sws = staticwebsync.sws:main']},
    install_requires=['boto3', 'blessings', 'colorama'],
)
