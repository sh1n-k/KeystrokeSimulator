"""캡처 HUD — 편집기와 빠른 이벤트가 함께 쓰는 작은 항상 위 캡처 창.

게임 화면과 캡처 영역을 비교하려고 항상 위를 유지하고(UI 정책 1), 대신 창을
작게 두고 캡처 박스와 겹치면 스스로 비켜난다. 상태와 동작은
`CaptureController`가 맡고 이 모듈은 표시와 입력 전달만 한다.

게임이 포커스를 가진 동안에도 ALT/CTRL을 읽어야 하므로 Qt 키 이벤트가 아니라
`QTimer`로 전역 키 상태를 폴링한다(100ms). 캡처 프레임은 50ms마다
`CaptureSession` 세대를 확인한다.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QCursor,
    QFontDatabase,
    QGuiApplication,
    QImage,
    QIntValidator,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.capture_geometry import (
    MAGNIFIER_SPAN,
    MAGNIFIER_ZOOM,
    MAX_CAPTURE_SIZE,
    MIN_CAPTURE_SIZE,
    CaptureResult,
    Rect,
)
from app.domain.capture_render import color_hex
from app.domain.models import Position
from app.engine.capture_session import CaptureBackend
from app.presenters.capture_controller import (
    CAPTURE_POLL_MS,
    KEY_POLL_MS,
    CaptureController,
    HudMode,
    Tone,
)
from app.ui import tokens
from app.ui import style
from app.ui.capture_border import CaptureBorder
from app.ui.mac_window import keep_above_all_spaces
from app.utils.i18n import txt

HUD_WRAP = 250
_MAGNIFIER_SIZE = MAGNIFIER_SPAN * MAGNIFIER_ZOOM
_RETURN_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------


def capture_scale() -> float:
    """캡처 좌표(화면 픽셀) / Qt 논리 좌표.

    macOS는 캡처도 포인트 좌표라 1이다. Windows는 프로세스가 DPI 인식(물리
    픽셀)으로 캡처하고 Qt는 논리 좌표를 쓰므로 주 모니터 배율을 곱한다. 캡처는
    주 모니터만 대상이다.
    """
    if sys.platform != "win32":
        return 1.0
    return float(QGuiApplication.primaryScreen().devicePixelRatio())


def _to_capture(value: int, scale: float) -> int:
    return round(value * scale)


def _to_logical_rect(rect: Rect, scale: float) -> Rect:
    """바깥 테두리가 박스를 덮지 않도록 왼쪽 위는 내리고 오른쪽 아래는 올린다."""
    if scale == 1.0:
        return rect
    x, y, w, h = rect
    left, top = int(x / scale), int(y / scale)
    right, bottom = -int(-(x + w) // scale), -int(-(y + h) // scale)
    return (left, top, right - left, bottom - top)


def pil_to_qimage(img: Image.Image) -> QImage:
    rgb = img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    return QImage(
        data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888
    ).copy()


def _is_text_input(widget: QWidget | None) -> bool:
    if isinstance(widget, QComboBox):
        return widget.isEditable()
    return isinstance(widget, QLineEdit | QAbstractSpinBox | QTextEdit | QPlainTextEdit)


def text_input_has_focus() -> bool:
    """앱이 활성이고 텍스트 입력칸에 포커스가 있다. 게임이 포커스면 False."""
    if QGuiApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
        return False
    return _is_text_input(QApplication.focusWidget())


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class _ImageView(QWidget):
    """1px 테두리 안에 PIL 이미지를 1:1로 그린다. 좌표는 이미지 기준으로 넘긴다."""

    def __init__(
        self,
        *,
        on_press: Callable[[Position], None],
        on_hover: Callable[[Position], None] | None = None,
        on_leave: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._image: QImage | None = None
        self._size: Position = (1, 1)
        self._on_press = on_press
        self._on_hover = on_hover
        self._on_leave = on_leave
        self.setMouseTracking(on_hover is not None)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_image(self, img: Image.Image | None, size: Position) -> None:
        self._image = None if img is None else pil_to_qimage(img)
        if size != self._size:
            self._size = size
            self.setFixedSize(size[0] + 2, size[1] + 2)
        self.update()

    @property
    def display_size(self) -> Position:
        return self._size

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.mid())
        inner = QRect(1, 1, self._size[0], self._size[1])
        if self._image is None:
            painter.fillRect(inner, palette.alternateBase())
        else:
            painter.drawImage(inner, self._image)

    @staticmethod
    def _point(event: QMouseEvent) -> Position:
        pos = event.position()
        return (int(pos.x()) - 1, int(pos.y()) - 1)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_press(self._point(event))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._on_press(self._point(event))
        elif self._on_hover is not None:
            self._on_hover(self._point(event))

    def leaveEvent(self, event: QEvent) -> None:
        if self._on_leave is not None:
            self._on_leave()
        super().leaveEvent(event)


class _CommitKeys(QObject):
    """입력칸의 Enter는 값만 확정한다. 창의 Enter(적용)로 번지지 않게 끊는다.

    Up/Down이 등록된 칸은 값을 1씩 바꾸고 확정한다.
    """

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._commit: dict[QObject, Callable[[], None]] = {}
        self._nudge: dict[QObject, Callable[[int], None]] = {}

    def bind(
        self,
        widget: QWidget,
        commit: Callable[[], None],
        nudge: Callable[[int], None] | None = None,
    ) -> None:
        self._commit[widget] = commit
        if nudge is not None:
            self._nudge[widget] = nudge
        widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress or not isinstance(event, QKeyEvent):
            return False
        key = event.key()
        if key in _RETURN_KEYS and watched in self._commit:
            self._commit[watched]()
            return True
        nudge = self._nudge.get(watched)
        if nudge is not None and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            nudge(1 if key == Qt.Key.Key_Up else -1)
            return True
        return False


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


class CaptureHud(QWidget):
    """단일 모드는 이벤트 하나의 화면을 고르고, 연속 모드는 Quick에 계속 추가한다."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        mode: Literal["single", "continuous"],
        name: str = "",
        on_name_change: Callable[[str], None] | None = None,
        on_apply: Callable[[CaptureResult], None] | None = None,
        profiles_dir: Path | None = None,
        initial: CaptureResult | None = None,
        capture_size: tuple[int, int] = (100, 100),
        region_size: tuple[int, int] | None = None,
        grab: bool = False,
        border: bool = True,
        on_close: Callable[[], object] | None = None,
        capturer: CaptureBackend | None = None,
    ) -> None:
        super().__init__(
            parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.mode: HudMode = mode
        self.on_name_change = on_name_change
        self.on_close = on_close
        self._closing = False
        self._capture_generation = -1
        self._scale = capture_scale()
        self.controller = CaptureController(
            mode=mode,
            pointer=self._pointer,
            capturer=capturer,
            profiles_dir=profiles_dir,
            region_size=region_size,
            capture_size=capture_size,
            on_apply=on_apply,
            close=self.close,
        )
        # 실행 중에는 테두리를 만들지 않는다(호출부가 border=False로 연다).
        self.border: CaptureBorder | None = CaptureBorder() if border else None
        self.setWindowTitle(
            txt("Capture", "캡처")
            if mode == "single"
            else txt("Quick Capture", "빠른 캡처")
        )
        self._keys = _CommitKeys(self)
        self._build(name)

        if initial is not None:
            self.controller.restore(initial)
        self._sync_size_spins()
        hud_pos = self.controller.load_state(restore_pointer=initial is None)
        self._render()
        self.adjustSize()
        self._place(hud_pos)

        if grab:
            self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.show()
        keep_above_all_spaces(self)
        # 이 앱이 활성일 때(버튼으로 연 직후)만 앞으로 가져온다. 게임에서
        # 포커스를 빼앗지 않는다.
        if QGuiApplication.applicationState() == Qt.ApplicationState.ApplicationActive:
            self.raise_()
            self.activateWindow()

        # 부모가 닫히며 close 없이 파괴돼도 캡처 스레드와 테두리를 정리한다.
        controller, border_ref = self.controller, self.border

        def on_destroyed(*_args: object) -> None:
            _release(controller, border_ref)

        self.destroyed.connect(on_destroyed)

        self.controller.start()
        self._capture_timer = QTimer(self)
        self._capture_timer.timeout.connect(self._poll_capture)
        self._capture_timer.start(CAPTURE_POLL_MS)
        self._key_timer = QTimer(self)
        self._key_timer.timeout.connect(self._check_keys)
        self._key_timer.start(KEY_POLL_MS)

    # -- layout ---------------------------------------------------------------

    def _build(self, name: str) -> None:
        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        root.setContentsMargins(
            tokens.SPACE_3, tokens.SPACE_2, tokens.SPACE_3, tokens.SPACE_3
        )
        root.setSpacing(tokens.SPACE_2)

        self.entry_name: QLineEdit | None = None
        self.lbl_title: QLabel | None = None
        if self.mode == "single":
            entry = QLineEdit(name)
            entry.setPlaceholderText(txt("Event name", "이벤트 이름"))
            entry.textEdited.connect(self._on_name_edit)
            self._keys.bind(entry, self._commit_name)
            root.addWidget(entry)
            self.entry_name = entry
        else:
            title = QLabel()
            font = title.font()
            font.setBold(True)
            title.setFont(font)
            root.addWidget(title)
            self.lbl_title = title

        images = QHBoxLayout()
        images.setSpacing(tokens.SPACE_2)
        self.preview = _ImageView(
            on_press=self._on_preview_press,
            on_hover=self._on_preview_hover,
            on_leave=self._on_preview_leave,
        )
        self.magnifier = _ImageView(on_press=self._on_magnifier_press)
        images.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        images.addWidget(self.magnifier, 0, Qt.AlignmentFlag.AlignTop)
        images.addStretch(1)
        root.addLayout(images)

        info = QHBoxLayout()
        info.setSpacing(tokens.SPACE_2)
        self.swatch = QFrame()
        self.swatch.setFixedSize(16, 16)
        self.lbl_info = QLabel()
        self.lbl_info.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.lbl_info.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        info.addWidget(self.swatch)
        info.addWidget(self.lbl_info, 1)
        root.addLayout(info)

        hint = QLabel(
            txt(
                "ALT move · CTRL freeze · click to pick",
                "ALT 이동 · CTRL 고정 · 클릭 지정",
            )
        )
        style.caption(hint)
        hint.setFixedWidth(HUD_WRAP)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setFixedWidth(HUD_WRAP)
        status_box = QVBoxLayout()
        status_box.setSpacing(2)
        status_box.addWidget(hint)
        status_box.addWidget(self.lbl_status)
        root.addLayout(status_box)

        self.btn_advanced = QToolButton()
        self.btn_advanced.setAutoRaise(True)
        # 접기 표시는 링크처럼 보인다(macOS 기본 툴 버튼 테두리 없이).
        self.btn_advanced.setStyleSheet(
            "QToolButton { border: none; padding: 0; color: palette(link); }"
        )
        self.btn_advanced.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_advanced.clicked.connect(self._toggle_advanced)
        root.addWidget(self.btn_advanced, 0, Qt.AlignmentFlag.AlignLeft)
        self.advanced = QWidget()
        self._build_advanced(self.advanced)
        self.advanced.hide()
        root.addWidget(self.advanced)
        self._sync_advanced_label()

        dock = QHBoxLayout()
        self.btn_recapture = QPushButton(txt("Recapture", "다시 캡처"))
        self.btn_recapture.setAutoDefault(False)
        self.btn_recapture.clicked.connect(self.recapture)
        self.btn_apply = QPushButton(txt("Apply ↵", "적용 ↵"))
        self.btn_apply.setAutoDefault(False)
        self.btn_apply.clicked.connect(self.apply)
        dock.addWidget(self.btn_recapture)
        dock.addStretch(1)
        dock.addWidget(self.btn_apply)
        root.addLayout(dock)

    def _build_advanced(self, parent: QWidget) -> None:
        grid = QGridLayout(parent)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(tokens.SPACE_1)
        grid.setVerticalSpacing(2)
        self.pos_entries: list[QLineEdit] = []
        self.pixel_entries: list[QLineEdit] = []
        rows = ((txt("Box", "위치"), "pos"), (txt("Pixel", "픽셀"), "pixel"))
        for row, (label, kind) in enumerate(rows):
            grid.addWidget(QLabel(label), row, 0)
            for col, axis in enumerate(("X", "Y")):
                axis_label = QLabel(axis)
                style.caption(axis_label)
                grid.addWidget(
                    axis_label, row, 1 + col * 2, Qt.AlignmentFlag.AlignRight
                )
                entry = QLineEdit()
                entry.setValidator(QIntValidator(-99999, 99999, entry))
                entry.setFixedWidth(56)
                grid.addWidget(entry, row, 2 + col * 2)
                if kind == "pos":
                    entry.editingFinished.connect(self._on_pos_entry)
                    commit = self._on_pos_entry
                    self.pos_entries.append(entry)
                else:
                    entry.textEdited.connect(self._on_pixel_entry)
                    commit = self._on_pixel_entry
                    self.pixel_entries.append(entry)
                self._keys.bind(
                    entry,
                    commit,
                    lambda delta, en=entry, c=commit: self._nudge_entry(en, c, delta),
                )
        grid.addWidget(QLabel(txt("Size", "크기")), 2, 0)
        self.size_spins: list[QSpinBox] = []
        for col, axis in enumerate(("W", "H")):
            axis_label = QLabel(axis)
            style.caption(axis_label)
            grid.addWidget(axis_label, 2, 1 + col * 2, Qt.AlignmentFlag.AlignRight)
            spin = QSpinBox()
            spin.setRange(MIN_CAPTURE_SIZE, MAX_CAPTURE_SIZE)
            spin.setKeyboardTracking(False)
            spin.setFixedWidth(64)
            spin.valueChanged.connect(self._on_capture_size_change)
            self._keys.bind(spin, spin.interpretText)
            grid.addWidget(spin, 2, 2 + col * 2)
            self.size_spins.append(spin)
        grid.setColumnStretch(5, 1)

    # -- coordinates ----------------------------------------------------------

    def _pointer(self) -> Position:
        pos = QCursor.pos()
        return (_to_capture(pos.x(), self._scale), _to_capture(pos.y(), self._scale))

    def _screen_size(self) -> Position:
        size = QGuiApplication.primaryScreen().geometry().size()
        return (
            _to_capture(size.width(), self._scale),
            _to_capture(size.height(), self._scale),
        )

    def _hud_rect(self) -> Rect | None:
        frame = self.frameGeometry()
        if frame.width() <= 1 or frame.height() <= 1:
            return None
        s = self._scale
        return (
            _to_capture(frame.x(), s),
            _to_capture(frame.y(), s),
            _to_capture(frame.width(), s),
            _to_capture(frame.height(), s),
        )

    def _place(self, saved: Position | None) -> None:
        """저장한 위치(캡처 좌표)로 옮긴다. 화면 밖이면 주 모니터 가운데."""
        if saved is not None:
            point = QPoint(int(saved[0] / self._scale), int(saved[1] / self._scale))
            screen = QGuiApplication.screenAt(point)
            if screen is not None and screen.availableGeometry().contains(point):
                self.move(point)
                return
        area = QGuiApplication.primaryScreen().availableGeometry()
        size = self.sizeHint()
        self.move(
            area.x() + (area.width() - size.width()) // 2,
            area.y() + (area.height() - size.height()) // 2,
        )

    # -- actions --------------------------------------------------------------

    def is_ready(self) -> bool:
        return self.controller.is_ready()

    def result(self) -> CaptureResult | None:
        return self.controller.result()

    def capture(self) -> None:
        self.controller.capture()
        self._render()

    def recapture(self) -> None:
        self.controller.recapture()
        self._render()

    def apply(self) -> None:
        self.controller.apply()
        self._render()

    def select(self, pixel: Position) -> None:
        if self.controller.select(pixel):
            self._render()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        if event.key() in _RETURN_KEYS:
            self.apply()
            return
        super().keyPressEvent(event)

    # -- input handlers -------------------------------------------------------

    def _on_name_edit(self, text: str) -> None:
        if self.on_name_change is not None:
            self.on_name_change(text)

    def _commit_name(self) -> None:
        if self.entry_name is not None:
            self._on_name_edit(self.entry_name.text())
        # 포커스를 입력칸에서 빼야 CTRL 캡처가 다시 동작한다.
        self.setFocus()

    def _on_preview_press(self, point: Position) -> None:
        if self.controller.click_preview(point, self.preview.display_size):
            self._render()

    def _on_magnifier_press(self, point: Position) -> None:
        if self.controller.click_magnifier(point):
            self._render()

    def _on_preview_hover(self, point: Position) -> None:
        if self.controller.hover_preview(point, self.preview.display_size):
            self._render_magnifier()

    def _on_preview_leave(self) -> None:
        if self.controller.leave_preview():
            self._render_magnifier()

    @staticmethod
    def _nudge_entry(entry: QLineEdit, commit: Callable[[], None], delta: int) -> None:
        try:
            value = int(entry.text()) + delta
        except ValueError:
            return
        entry.setText(str(value))
        commit()

    @staticmethod
    def _entry_pair(entries: list[QLineEdit]) -> Position | None:
        try:
            return (int(entries[0].text()), int(entries[1].text()))
        except ValueError:
            return None

    def _on_pos_entry(self) -> None:
        pos = self._entry_pair(self.pos_entries)
        if pos is None:
            return
        self.controller.set_box_position(pos)
        self._render()

    def _on_pixel_entry(self, *_args: object) -> None:
        pixel = self._entry_pair(self.pixel_entries)
        if pixel is not None and self.controller.set_pixel(pixel):
            self._render()

    def _on_capture_size_change(self, *_args: object) -> None:
        self.controller.set_capture_size(
            self.size_spins[0].value(), self.size_spins[1].value()
        )
        self._sync_border()

    def _sync_size_spins(self) -> None:
        for spin, value in zip(self.size_spins, self.controller.capture_size, strict=True):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def _toggle_advanced(self) -> None:
        self.advanced.setVisible(self.advanced.isHidden())
        self._sync_advanced_label()

    def _sync_advanced_label(self) -> None:
        mark = tokens.ICON_COLLAPSED if self.advanced.isHidden() else tokens.ICON_EXPANDED
        self.btn_advanced.setText(f"{mark} {txt('Advanced', '고급')}")

    # -- polling --------------------------------------------------------------

    def _check_keys(self) -> None:
        if self._closing:
            return
        update = self.controller.tick(text_focus=text_input_has_focus())
        if self._closing:
            return
        if update.render:
            self._render()
        else:
            if update.info:
                self._render_info()
            if update.status:
                self._render_status()
        self._avoid_capture_box()
        self._sync_border()

    def _poll_capture(self) -> None:
        if self._closing:
            return
        generation = self.controller.session.snapshot().generation
        if generation != self._capture_generation:
            self._capture_generation = generation
            if self.controller.shows_live():
                self._render()

    def _avoid_capture_box(self) -> None:
        hud = self._hud_rect()
        if hud is None:
            return
        target = self.controller.hud_target(hud, self._screen_size())
        if target is not None:
            self.move(int(target[0] / self._scale), int(target[1] / self._scale))

    def _sync_border(self) -> None:
        if self.border is None or self._closing:
            return
        self.border.show(_to_logical_rect(self.controller.box(), self._scale))

    # -- rendering ------------------------------------------------------------

    def _render(self) -> None:
        if self._closing:
            return
        img, size = self.controller.preview()
        self.preview.set_image(img, size)
        self._render_magnifier()
        self._render_info()
        self._render_status()

    def _render_magnifier(self) -> None:
        pad = self.palette().alternateBase().color().name()
        img = self.controller.magnifier(pad)
        self.magnifier.set_image(img, (_MAGNIFIER_SIZE, _MAGNIFIER_SIZE))

    def _render_info(self) -> None:
        color, point = self.controller.info()
        rgb = ",".join(str(int(c)) for c in color[:3]) if color else "—"
        fill = color_hex(color) if color else "palette(alternate-base)"
        self.swatch.setStyleSheet(
            f"QFrame {{ background: {fill}; border: 1px solid palette(mid); }}"
        )
        self.lbl_info.setText(f"{rgb}  ({point[0]}, {point[1]})")
        self._sync_entries()

    def _sync_entries(self) -> None:
        focus = QApplication.focusWidget()
        pos = self.controller.session.current_position()
        selected = self.controller.session.selected_position
        for entry, value in zip(self.pos_entries, pos, strict=True):
            if entry is not focus:
                self._set_entry(entry, value)
        for i, entry in enumerate(self.pixel_entries):
            if entry is not focus:
                self._set_entry(entry, None if selected is None else selected[i])

    @staticmethod
    def _set_entry(entry: QLineEdit, value: int | None) -> None:
        text = "" if value is None else str(value)
        if entry.text() != text:
            entry.setText(text)

    def _render_status(self) -> None:
        text, tone = self.controller.status()
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"QLabel {{ color: {_tone_color(tone)}; }}")
        self.btn_apply.setEnabled(self.controller.is_ready())
        if self.lbl_title is not None:
            self.lbl_title.setText(self.controller.title())

    # -- lifecycle ------------------------------------------------------------

    @property
    def saved_count(self) -> int:
        return self.controller.saved_count

    def is_open(self) -> bool:
        return not self._closing

    def close(self) -> bool:
        if self._closing:
            return False
        return super().close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closing:
            self._closing = True
            self._capture_timer.stop()
            self._key_timer.stop()
            pos = self.pos()
            self.controller.save_state(
                (_to_capture(pos.x(), self._scale), _to_capture(pos.y(), self._scale))
            )
            _release(self.controller, self.border)
            self.border = None
            if self.on_close is not None:
                self.on_close()
        event.accept()


def _release(controller: CaptureController, border: CaptureBorder | None) -> None:
    controller.stop()
    if border is not None:
        border.destroy()


def _tone_color(tone: Tone) -> str:
    if tone == "warn":
        return style.status_colors("warn")[1]
    if tone == "ready":
        return style.status_colors("ready")[1]
    if tone == "accent":
        return style.status_colors("ready")[1] if style.is_dark() else style.ACCENT
    return "palette(text)"


# ---------------------------------------------------------------------------
# Main window entry
# ---------------------------------------------------------------------------


def open_quick_capture(parent: QWidget) -> None:
    """실행 창의 "빠른 이벤트…": 연속 모드 HUD를 하나만 연다."""
    host: Any = parent
    existing = getattr(host, "quick_hud", None)
    if isinstance(existing, CaptureHud) and existing.is_open():
        existing.raise_()
        existing.activateWindow()
        return

    def closed() -> None:
        if getattr(host, "quick_hud", None) is hud:
            host.quick_hud = None
        host.update_ui()

    hud = CaptureHud(
        parent,
        mode="continuous",
        profiles_dir=host.profiles_dir,
        on_close=closed,
    )
    host.quick_hud = hud
