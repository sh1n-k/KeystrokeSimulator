"""OS 입력 리스너 수명과 UI 메인 스레드 전달. UI 툴킷과 무관하다.

리스너 스레드는 `post(action)`만 부른다. 메인 스레드에서 실행하는 일은
주입받은 `Dispatcher`가 맡는다(Tk: `app/ui/tk_dispatcher.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.platform.system import ResponsivenessActivity


class InputListener(Protocol):
    def start(self) -> object: ...
    def stop(self) -> object: ...


class Dispatcher(Protocol):
    """다른 스레드에서 넘긴 동작을 UI 메인 스레드에서 넘긴 순서대로 실행한다.

    - `post`는 어느 스레드에서나 부를 수 있다. `start` 전이나 `stop` 뒤에는 버린다.
    - 실행 중 예외는 기록하고 다음 동작을 계속 실행한다.
    - `stop`은 아직 실행하지 않은 동작을 버린다. 동작 안에서 `stop`·`start`를
      불러도 된다.
    """

    def start(self) -> None: ...
    def post(self, action: Callable[[], object]) -> None: ...
    def stop(self) -> None: ...


class InputRouter:
    """Own global listeners and hand their actions to the UI thread dispatcher.

    Optional ResponsivenessActivity reduces App Nap timer coalescing while
    macOS hotkeys are armed.
    """

    def __init__(self, dispatcher: Dispatcher) -> None:
        self.dispatcher = dispatcher
        self._listeners: list[InputListener] = []
        self._responsiveness = ResponsivenessActivity()
        self._responsiveness_held = False

    def start(self) -> None:
        self.dispatcher.start()

    def begin_responsiveness(self) -> None:
        """Keep process timers responsive while macOS hotkeys are armed."""
        if self._responsiveness_held:
            return
        self._responsiveness.begin()
        self._responsiveness_held = True

    def end_responsiveness(self) -> None:
        if not self._responsiveness_held:
            return
        self._responsiveness_held = False
        self._responsiveness.end()

    def add(self, listener: InputListener, *, started: bool = False) -> InputListener:
        self._listeners.append(listener)
        if not started:
            listener.start()
        return listener

    def post(self, action: Callable[[], object]) -> None:
        self.dispatcher.post(action)

    def stop(self) -> None:
        # Drop new posts first so listener threads stopping below cannot queue more.
        self.dispatcher.stop()
        self.end_responsiveness()
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:
                pass
        self._listeners.clear()
