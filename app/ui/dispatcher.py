"""Qt 메인 스레드 전달. `app.platform.input_router.Dispatcher` 구현."""

from __future__ import annotations

import threading
from collections.abc import Callable

from loguru import logger
from PySide6.QtCore import QObject, Qt, Signal, Slot


class QtDispatcher(QObject):
    """다른 스레드에서 넘긴 동작을 Qt 메인 스레드에서 넘긴 순서대로 실행한다.

    QObject 메서드 슬롯 + QueuedConnection이라 emit한 스레드와 상관없이
    이 객체가 속한(메인) 스레드의 이벤트 루프에서 실행된다. `stop`은 세대를
    올려 아직 실행하지 않은 동작을 버린다.
    """

    _posted = Signal(object, int)

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._active = False
        self._generation = 0
        self._posted.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def start(self) -> None:
        with self._lock:
            self._active = True

    def stop(self) -> None:
        with self._lock:
            self._active = False
            self._generation += 1

    def post(self, action: Callable[[], object]) -> None:
        with self._lock:
            if not self._active:
                return
            generation = self._generation
        self._posted.emit(action, generation)

    @Slot(object, int)
    def _run(self, action: Callable[[], object], generation: int) -> None:
        with self._lock:
            if not self._active or generation != self._generation:
                return
        try:
            action()
        except Exception:
            logger.exception("Dispatched action failed")
