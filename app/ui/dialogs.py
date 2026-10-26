"""보조 창 공용 위젯: 키 한 개를 눌러 지정하는 입력 칸."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLineEdit, QWidget

# 대화상자가 처리해야 하는 키(닫기·기본 버튼·포커스 이동)는 칸이 먹지 않는다.
_PASS_THROUGH_KEYS = frozenset(
    k.value
    for k in (
        Qt.Key.Key_Escape,
        Qt.Key.Key_Return,
        Qt.Key.Key_Enter,
        Qt.Key.Key_Tab,
        Qt.Key.Key_Backtab,
    )
)


def key_event_name(event: QKeyEvent) -> str:
    """Tk `(event.char or event.keysym).upper()`에 대응하는 키 이름.

    영문·숫자는 키 코드로 읽어 macOS Option 조합 문자(å 등)를 피한다. F키는
    "F1" 형식, 그 밖의 인쇄 가능한 한 글자는 그대로, 나머지는 빈 문자열.
    """
    key = event.key()
    if Qt.Key.Key_F1.value <= key <= Qt.Key.Key_F35.value:
        return f"F{key - Qt.Key.Key_F1.value + 1}"
    if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value or (
        Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value
    ):
        return chr(key)
    text = event.text()
    if len(text) == 1 and text.isprintable() and not text.isspace():
        return text.upper()
    return ""


class KeyCaptureEdit(QLineEdit):
    """읽기 전용 칸. 키를 누르면 `keyCaptured(name)`을 보낸다. 받을지는
    받는 쪽이 정하고 표시도 받는 쪽이 갱신한다."""

    keyCaptured = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in _PASS_THROUGH_KEYS:
            event.ignore()
            return
        if name := key_event_name(event):
            self.keyCaptured.emit(name)
        event.accept()
