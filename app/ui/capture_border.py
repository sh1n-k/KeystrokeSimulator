"""캡처 박스를 게임 화면 위에 표시하는 얇은 창 4개.

박스 바깥에 두므로 캡처본에 찍히지 않는다(UI 정책 3). 클릭은 아래 창으로
통과하고 포커스를 가져가지 않는다.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from app.domain.capture_geometry import Rect, border_rects
from app.ui import tokens
from app.ui.mac_window import keep_above_all_spaces


class _BorderPiece(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._color = QColor(tokens.CAPTURE_BORDER)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._color)


class CaptureBorder:
    """`show(box)`는 화면 논리 좌표의 박스를 받는다."""

    def __init__(self) -> None:
        self._box: Rect | None = None
        self.windows: list[QWidget] = [_BorderPiece() for _ in range(4)]

    def show(self, box: Rect) -> None:
        if box == self._box or not self.windows:
            return
        self._box = box
        rects = border_rects(box, tokens.CAPTURE_BORDER_WIDTH)
        for win, (x, y, w, h) in zip(self.windows, rects, strict=True):
            win.setGeometry(QRect(x, y, max(1, w), max(1, h)))
            if win.isHidden():
                win.show()
                keep_above_all_spaces(win)
        # macOS는 메뉴바 영역 등에 놓인 창을 스스로 옮긴다. 옮겨진 조각은
        # 캡처 박스 안으로 들어올 수 있으므로 숨긴다.
        for win, (x, y, _w, _h) in zip(self.windows, rects, strict=True):
            if (win.x(), win.y()) != (x, y):
                win.hide()

    def hide(self) -> None:
        self._box = None
        for win in self.windows:
            win.hide()

    def destroy(self) -> None:
        for win in self.windows:
            win.hide()
            win.deleteLater()
        self.windows = []
        self._box = None
