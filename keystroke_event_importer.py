import sys

from app.ui import event_importer as _impl

sys.modules[__name__] = _impl
