import sys

from app.utils import sounds as _impl

sys.modules[__name__] = _impl
