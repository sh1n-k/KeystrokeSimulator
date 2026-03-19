import sys

from app.ui import modkeys as _impl

sys.modules[__name__] = _impl
