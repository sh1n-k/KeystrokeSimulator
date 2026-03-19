import sys

from app.ui import sort_events as _impl

sys.modules[__name__] = _impl
