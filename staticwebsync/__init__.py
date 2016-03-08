__all__ = ('log', 'progress_callback', 'progress_callback_divisions',
    'BadUserError', 'setup')

import sys
REQUIRED_PYTHON_VERSION = (3,)
if sys.version_info < REQUIRED_PYTHON_VERSION:
    exit('Python version %s or higher is required.' % '.'.join(map(str, REQUIRED_PYTHON_VERSION)))
