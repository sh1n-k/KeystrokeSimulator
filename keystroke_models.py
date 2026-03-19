import sys

from app.core import models as _impl

sys.modules[__name__] = _impl
