__all__ = ('log', 'progress_callback_factory', 'progress_callback_divisions', 'BadUserError', 'setup')

import sys
REQUIRED_PYTHON_VERSION = (3,)
if sys.version_info < REQUIRED_PYTHON_VERSION:
    exit('Python version %s or higher is required.' % '.'.join(map(str, REQUIRED_PYTHON_VERSION)))

log = lambda msg: None
progress_callback_factory = lambda: None
progress_callback_divisions = 10 # this is no longer used, but is retained so as not to break the module API

from .main import BadUserError, setup
