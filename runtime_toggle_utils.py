import sys

from app.utils import runtime_toggle as _impl

sys.modules[__name__] = _impl
