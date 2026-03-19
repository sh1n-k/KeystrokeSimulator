import sys

from app.utils import system as _impl

sys.modules[__name__] = _impl
