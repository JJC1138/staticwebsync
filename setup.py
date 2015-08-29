from setuptools import setup
import sys

extra_options = {}
if 'py2exe' in sys.argv:
    from glob import glob
    import py2exe
    extra_options.update(
        console=['staticwebsync/sws.py'],
        zipfile=None,
        options={'py2exe': {
            'bundle_files': 1,
            'packages': ['email'],
            'dll_excludes': ['w9xpopen.exe'],
            'ignores': ['_scproxy', 'email.Encoders', 'email.MIMEBase',
                'email.MIMEMultipart', 'email.MIMEText', 'email.Utils', 'lxml',
                'netbios', 'simplejson', 'win32evtlog', 'win32evtlogutil',
                'win32wnet'],
        }},
        data_files=[('Microsoft.VC90.CRT', glob(
            r'C:\Program Files (x86)\Microsoft Visual Studio 9.0\VC\redist\x86\Microsoft.VC90.CRT\*.*'))],
    )

if 'py2app' in sys.argv:
    extra_options.update(
        setup_requires=['py2app'],
        app=['staticwebsync/sws.py'],
        options={'py2app': {
            'packages': ['email'],
            'no_chdir': True,
        }},
    )

setup(
    name='staticwebsync',
    version='1.0.2',
    maintainer='Jon Colverson',
    maintainer_email='staticwebsync@jjc1138.net',
    packages=['staticwebsync'],
    url='http://staticwebsync.jjc1138.net/',
    license='MIT',
    description='Automates setting up S3/CloudFront for web site hosting',
    long_description=open('README.txt').read(),

    entry_points = {'console_scripts': ['sws = staticwebsync.sws:main']},
    install_requires = ['boto > 2.0b4'],

    **extra_options
)
