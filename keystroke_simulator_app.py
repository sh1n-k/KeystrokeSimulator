import sys

from app.ui import simulator_app as _impl

sys.modules[__name__] = _impl
