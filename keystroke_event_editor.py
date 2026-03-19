import sys

from app.ui import event_editor as _impl

sys.modules[__name__] = _impl
