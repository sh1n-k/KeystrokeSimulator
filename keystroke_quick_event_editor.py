import sys

from app.ui import quick_event_editor as _impl

sys.modules[__name__] = _impl
