from distutils.core import setup
from glob import glob
import py2exe

setup(
    console=['sws.py'],
    zipfile=None,
    options={'py2exe': {
        'bundle_files': 1,
        'packages': ['email'],
        'dll_excludes': ['w9xpopen.exe'],
        'ignores': ['_scproxy', 'email.Encoders', 'email.MIMEBase',
            'email.MIMEMultipart', 'email.MIMEText', 'email.Utils', 'lxml',
            'netbios', 'simplejson', 'win32evtlog', 'win32evtlogutil', 'win32wnet'],
    }},
    data_files=[('Microsoft.VC90.CRT', glob(
        r'C:\Program Files (x86)\Microsoft Visual Studio 9.0\VC\redist\x86\Microsoft.VC90.CRT\*.*'))],
)
