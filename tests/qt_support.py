"""Qt 위젯 테스트 공용: offscreen QApplication 하나를 공유한다."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication


def qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        # Offscreen: no window server, no NSApplication, works headless in CI.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app
