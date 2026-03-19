import sys

from app.storage import profile_display as _impl

sys.modules[__name__] = _impl
