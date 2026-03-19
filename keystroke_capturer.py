import sys

from app.core import capturer as _impl

sys.modules[__name__] = _impl
