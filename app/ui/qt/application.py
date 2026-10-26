"""Qt 앱 부트스트랩: 로그, 예외 훅, 스타일, 종료 신호."""

from __future__ import annotations

import signal
import sys
from pathlib import Path
from types import FrameType

from loguru import logger
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.ui.qt import style
from app.utils.exception_hooks import install_exception_hooks


def main() -> int:
    log_path = Path("logs")
    log_path.mkdir(exist_ok=True)
    log_handler_id = logger.add(
        log_path / "keysym.log",
        rotation="1 MB",
        level="INFO",
        enqueue=False,
    )
    install_exception_hooks()

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Keystroke Simulator")
    style.apply_app_style(qt_app)

    from app.ui.qt.main_window import RunWindow

    window: RunWindow | None = None

    def graceful_shutdown(_signum: int, _frame: FrameType | None) -> None:
        if window is not None:
            QTimer.singleShot(0, window.close)

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    # Qt's event loop does not return to Python on its own; wake it so
    # signal handlers run.
    wake = QTimer()
    wake.start(250)
    wake.timeout.connect(lambda: None)

    code = 0
    try:
        window = RunWindow()
        window.show()
        logger.info("Application started.")
        code = qt_app.exec()
    except (KeyboardInterrupt, Exception) as e:
        logger.info(f"Shutting down: {e}")
        if window is not None:
            window.close()
    finally:
        logger.info("Application terminated.")
        logger.remove(log_handler_id)
    return code
