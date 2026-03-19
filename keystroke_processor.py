import sys

from app.core import processor as _impl

sys.modules[__name__] = _impl
