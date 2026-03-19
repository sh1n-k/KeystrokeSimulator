import sys

from app.utils import sound_assets as _impl

sys.modules[__name__] = _impl
