import sys

from app.ui import event_graph as _impl

sys.modules[__name__] = _impl
