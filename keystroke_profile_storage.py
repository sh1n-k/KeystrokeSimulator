import sys

from app.storage import profile_storage as _impl

sys.modules[__name__] = _impl
