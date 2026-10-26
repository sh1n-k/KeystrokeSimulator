"""작업 공간 오른쪽 상세 패널: 선택한 이벤트를 바로 편집한다."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QIntValidator, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.capture_geometry import CaptureResult
from app.domain.capture_render import render_overlay
from app.domain.event_editing import capture_from_event, event_issues
from app.domain.key_codes import KeyCodes
from app.domain.models import EventModel, Position
from app.domain.profile_events import event_has_screen
from app.domain.validation import MAX_REGION_SIZE, MIN_REGION_SIZE
from app.presenters.workspace_model import BulkAction, WorkspaceModel
from app.ui import tokens
from app.ui import style
from app.utils.i18n import txt

if TYPE_CHECKING:
    from app.ui.capture_hud import CaptureHud

THUMB_MAX = 160
PANEL_WIDTH = 340


def pil_to_pixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(
        data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888
    )
    return QPixmap.fromImage(qimage.copy())


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    label.setContentsMargins(0, tokens.SPACE_3, 0, 0)
    return label


def _error_label() -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {style.status_colors('error')[1]};")
    label.hide()
    return label


def _set_message(label: QLabel, text: str) -> None:
    label.setText(text)
    label.setVisible(bool(text))


class EventDetailPanel(QScrollArea):
    def __init__(
        self,
        model: WorkspaceModel,
        *,
        running_getter: Callable[[], bool],
        selection_getter: Callable[[], list[EventModel]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = model
        self.running_getter = running_getter
        self.selection_getter = selection_getter
        # `event`는 QWidget.event와 겹치므로 쓰지 않는다.
        self.current: EventModel | None = None
        self.selection: list[EventModel] = []
        self.capture_hud: CaptureHud | None = None
        self._syncing = False

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(280)
        body = QWidget()
        self.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(
            tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3
        )
        root.setSpacing(tokens.SPACE_2)

        self.lbl_title = QLabel()
        self.lbl_title.setWordWrap(True)
        title_font = self.lbl_title.font()
        title_font.setBold(True)
        title_font.setPointSizeF(title_font.pointSizeF() + 2)
        self.lbl_title.setFont(title_font)
        root.addWidget(self.lbl_title)

        self.editor = QWidget()
        self._build_editor(self.editor)
        root.addWidget(self.editor)

        self.bulk = QWidget()
        self._build_bulk(self.bulk)
        root.addWidget(self.bulk)

        self.lbl_placeholder = QLabel(
            txt(
                "Select an event to edit it here. ↑/↓ moves between events.",
                "이벤트를 선택하면 여기에서 바로 편집합니다. ↑/↓로 이동합니다.",
            )
        )
        self.lbl_placeholder.setWordWrap(True)
        style.caption(self.lbl_placeholder)
        root.addWidget(self.lbl_placeholder)
        root.addStretch(1)
        self.show_events([])

    # ── layout ─────────────────────────────────────────────────────────

    def _build_editor(self, parent: QWidget) -> None:
        box = QVBoxLayout(parent)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(tokens.SPACE_1)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.entry_name = QLineEdit()
        self.entry_name.editingFinished.connect(self.commit_name)
        self.lbl_name_error = _error_label()
        name_box = QVBoxLayout()
        name_box.setSpacing(2)
        name_box.addWidget(self.entry_name)
        name_box.addWidget(self.lbl_name_error)
        form.addRow(txt("Name", "이름"), name_box)

        kind_row = QHBoxLayout()
        self.kind_group = QButtonGroup(self)
        self.radio_signal = QRadioButton(txt("Signal", "신호"))
        self.radio_rule = QRadioButton(txt("Rule", "규칙"))
        for button in (self.radio_signal, self.radio_rule):
            self.kind_group.addButton(button)
            kind_row.addWidget(button)
        kind_row.addStretch(1)
        self.kind_group.buttonClicked.connect(self._on_kind_changed)
        form.addRow(txt("Type", "종류"), kind_row)

        self.combo_key = QComboBox()
        self.combo_key.addItem("")
        self.combo_key.addItems(KeyCodes.get_key_name_list())
        self.combo_key.setMaxVisibleItems(20)
        self.combo_key.activated.connect(self._on_key_changed)
        self.lbl_key = QLabel(txt("Key", "키"))
        form.addRow(self.lbl_key, self.combo_key)

        self.combo_group = QComboBox()
        self.combo_group.setEditable(True)
        self.combo_group.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo_group.activated.connect(self._on_group_changed)
        line = self.combo_group.lineEdit()
        if line is not None:
            line.editingFinished.connect(self._on_group_changed)
        self.lbl_group_hint = QLabel()
        self.lbl_group_hint.setWordWrap(True)
        style.caption(self.lbl_group_hint)
        group_box = QVBoxLayout()
        group_box.setSpacing(2)
        group_box.addWidget(self.combo_group)
        group_box.addWidget(self.lbl_group_hint)
        self.lbl_group = QLabel(txt("Group", "그룹"))
        form.addRow(self.lbl_group, group_box)
        box.addLayout(form)

        flags = QHBoxLayout()
        self.chk_use = QCheckBox(txt("In use", "사용"))
        self.chk_use.toggled.connect(self._on_use_changed)
        self.chk_toggle = QCheckBox(txt("Hotkey on/off set", "단축키로 켜고 끄기"))
        self.chk_toggle.toggled.connect(self._on_toggle_changed)
        flags.addWidget(self.chk_use)
        flags.addWidget(self.chk_toggle)
        flags.addStretch(1)
        box.addLayout(flags)

        # --- conditions ---
        box.addWidget(_section_label(txt("Conditions", "조건")))
        self.cond_host = QWidget()
        self.cond_list = QVBoxLayout(self.cond_host)
        self.cond_list.setContentsMargins(0, 0, 0, 0)
        self.cond_list.setSpacing(2)
        box.addWidget(self.cond_host)
        self.btn_add_cond = QToolButton()
        self.btn_add_cond.setText(txt("＋ Add condition", "＋ 조건 추가"))
        self.btn_add_cond.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # macOS draws the menu arrow over the label; the ＋ already says "menu".
        self.btn_add_cond.setStyleSheet(
            "QToolButton::menu-indicator { image: none; width: 0; }"
        )
        self.cond_menu = QMenu(self.btn_add_cond)
        self.cond_menu.aboutToShow.connect(self._fill_condition_menu)
        self.btn_add_cond.setMenu(self.cond_menu)
        box.addWidget(self.btn_add_cond, 0, Qt.AlignmentFlag.AlignLeft)

        # --- screen ---
        box.addWidget(_section_label(txt("Screen", "화면")))
        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFrameShape(QFrame.Shape.StyledPanel)
        self.lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_thumb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        box.addWidget(self.lbl_thumb, 0, Qt.AlignmentFlag.AlignLeft)
        info = QHBoxLayout()
        self.lbl_swatch = QLabel()
        self.lbl_swatch.setFixedSize(16, 16)
        self.lbl_screen = QLabel()
        style.caption(self.lbl_screen)
        info.addWidget(self.lbl_swatch)
        info.addWidget(self.lbl_screen, 1)
        box.addLayout(info)
        buttons = QHBoxLayout()
        self.btn_capture = QPushButton(txt("Capture…", "캡처…"))
        self.btn_capture.setAutoDefault(False)
        self.btn_capture.clicked.connect(self.open_capture)
        self.btn_clear_screen = QPushButton(txt("Clear", "지우기"))
        self.btn_clear_screen.setAutoDefault(False)
        self.btn_clear_screen.clicked.connect(self._on_clear_screen)
        buttons.addWidget(self.btn_capture)
        buttons.addWidget(self.btn_clear_screen)
        buttons.addStretch(1)
        box.addLayout(buttons)

        # --- advanced ---
        self.btn_advanced = QToolButton()
        self.btn_advanced.setCheckable(True)
        self.btn_advanced.setAutoRaise(True)
        self.btn_advanced.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.btn_advanced.toggled.connect(self._toggle_advanced)
        box.addWidget(self.btn_advanced, 0, Qt.AlignmentFlag.AlignLeft)
        self.advanced = QWidget()
        self._build_advanced(self.advanced)
        self.advanced.hide()
        box.addWidget(self.advanced)

        self.lbl_issues = QLabel()
        self.lbl_issues.setWordWrap(True)
        self.lbl_issues.setStyleSheet(f"color: {style.status_colors('warn')[1]};")
        box.addWidget(self.lbl_issues)

    def _build_advanced(self, parent: QWidget) -> None:
        box = QVBoxLayout(parent)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(tokens.SPACE_1)
        form = QFormLayout()
        validator = QIntValidator(0, 999_999, parent)
        self.entry_duration = QLineEdit()
        self.entry_random = QLineEdit()
        for entry, label in (
            (
                self.entry_duration,
                txt("Press time (ms, min 50)", "누름 시간 (ms, 최소 50)"),
            ),
            (self.entry_random, txt("Random (ms, min 30)", "랜덤 (ms, 최소 30)")),
        ):
            entry.setValidator(validator)
            entry.setMaximumWidth(80)
            entry.editingFinished.connect(self._commit_timing)
            form.addRow(label, entry)
        box.addLayout(form)
        hint = QLabel(
            txt("Blank uses the global timing.", "비워 두면 전역 타이밍을 씁니다.")
        )
        style.caption(hint)
        box.addWidget(hint)
        self.lbl_timing_error = _error_label()
        box.addWidget(self.lbl_timing_error)

        self.chk_invert = QCheckBox(
            txt("Trigger when the color differs", "색이 다를 때")
        )
        self.chk_invert.toggled.connect(self._on_invert_changed)
        box.addWidget(self.chk_invert)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(txt("Match", "매칭")))
        self.mode_group = QButtonGroup(self)
        self.radio_pixel = QRadioButton(txt("Pixel", "픽셀"))
        self.radio_region = QRadioButton(txt("Region", "영역"))
        for button in (self.radio_pixel, self.radio_region):
            self.mode_group.addButton(button)
            mode_row.addWidget(button)
        mode_row.addStretch(1)
        self.mode_group.buttonClicked.connect(self._on_mode_changed)
        box.addLayout(mode_row)

        region_row = QHBoxLayout()
        region_row.addWidget(QLabel(txt("Region W×H", "영역 가로×세로")))
        self.spin_region_w = QSpinBox()
        self.spin_region_h = QSpinBox()
        for spin in (self.spin_region_w, self.spin_region_h):
            spin.setRange(MIN_REGION_SIZE, MAX_REGION_SIZE)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self._on_region_size_changed)
            region_row.addWidget(spin)
        region_row.addStretch(1)
        box.addLayout(region_row)

    def _build_bulk(self, parent: QWidget) -> None:
        box = QVBoxLayout(parent)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(tokens.SPACE_1)
        entries: tuple[tuple[str, BulkAction | None, bool], ...] = (
            (txt("Turn on", "사용 켜기"), "use", True),
            (txt("Turn off", "사용 끄기"), "use", False),
            (txt("Add to hotkey set", "단축키 묶음에 넣기"), "toggle", True),
            (txt("Remove from hotkey set", "단축키 묶음에서 빼기"), "toggle", False),
            (txt("Delete", "삭제"), None, False),
        )
        self.bulk_buttons: list[QPushButton] = []
        for text, action, value in entries:
            button = QPushButton(text)
            button.setAutoDefault(False)
            if action is None:
                button.clicked.connect(self._bulk_delete)
            else:
                button.clicked.connect(self._bulk_slot(action, value))
            box.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
            self.bulk_buttons.append(button)
        group_row = QHBoxLayout()
        group_row.addWidget(QLabel(txt("Group", "그룹")))
        self.combo_bulk_group = QComboBox()
        self.combo_bulk_group.setEditable(True)
        self.combo_bulk_group.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo_bulk_group.setMinimumWidth(120)
        group_row.addWidget(self.combo_bulk_group)
        self.btn_bulk_group = QPushButton(txt("Set", "지정"))
        self.btn_bulk_group.setAutoDefault(False)
        self.btn_bulk_group.clicked.connect(
            lambda: self._bulk(
                "group", self.combo_bulk_group.currentText().strip() or None
            )
        )
        group_row.addWidget(self.btn_bulk_group)
        group_row.addStretch(1)
        box.addLayout(group_row)

    # ── showing ────────────────────────────────────────────────────────

    def forget(self) -> None:
        """다른 프로필·실행 세트를 열 때: 확정하지 않고 선택을 비운다."""
        self.current = None
        self.selection = []

    def show_events(self, selection: list[EventModel]) -> None:
        """선택이 바뀔 때. 편집 중인 이름은 먼저 확정한다."""
        same = len(selection) == len(self.selection) and all(
            a is b for a, b in zip(selection, self.selection, strict=True)
        )
        if same and self.current is not None:
            self.refresh()
            return
        if self.current is not None and not self._syncing:
            self.commit_name()
        self.selection = list(selection)
        self.current = selection[0] if len(selection) == 1 else None
        self.editor.setVisible(self.current is not None)
        self.bulk.setVisible(len(selection) > 1)
        self.lbl_placeholder.setVisible(not selection)
        if self.current is not None:
            _set_message(self.lbl_name_error, "")
            _set_message(self.lbl_timing_error, "")
            self.refresh(force_name=True)
        elif selection:
            self.lbl_title.setText(
                txt("{count} selected", "{count}개 선택됨", count=len(selection))
            )
            current = self.combo_bulk_group.currentText()
            self.combo_bulk_group.clear()
            self.combo_bulk_group.addItems(self.model.group_names())
            self.combo_bulk_group.setEditText(current)
        else:
            self.lbl_title.setText(txt("Details", "상세"))

    def refresh(self, *, force_name: bool = False) -> None:
        event = self.current
        if event is None:
            if len(self.selection) > 1:
                self.lbl_title.setText(
                    txt(
                        "{count} selected",
                        "{count}개 선택됨",
                        count=len(self.selection),
                    )
                )
            return
        self._syncing = True
        try:
            is_rule = bool(event.execute_action)
            self.lbl_title.setText(event.event_name or txt("(unnamed)", "(이름 없음)"))
            if force_name or not self.entry_name.hasFocus():
                self.entry_name.setText(event.event_name or "")
            self.radio_rule.setChecked(is_rule)
            self.radio_signal.setChecked(not is_rule)
            index = self.combo_key.findText(event.key_to_enter or "")
            self.combo_key.setCurrentIndex(max(index, 0))
            self.combo_key.setEnabled(is_rule)
            self.lbl_key.setEnabled(is_rule)
            group_line = self.combo_group.lineEdit()
            editing_group = group_line is not None and group_line.hasFocus()
            if force_name or not editing_group:
                self.combo_group.clear()
                self.combo_group.addItems(self.model.group_names())
                self.combo_group.setEditText((event.group_id or "").strip())
            self.combo_group.setEnabled(is_rule)
            self.lbl_group_hint.setText(self._group_hint(event))
            self.chk_use.setChecked(bool(event.use_event))
            self.chk_toggle.setChecked(bool(event.runtime_toggle_member))
            self.chk_toggle.setVisible(bool(self.model.profile.runtime_toggle_enabled))
            self._refresh_conditions()
            self._refresh_screen()
            self._refresh_advanced()
            issues = event_issues(event)
            self.lbl_issues.setText(
                "\n".join(f"{tokens.STATUS_WARN_ICON} {i}" for i in issues)
            )
            self.lbl_issues.setVisible(bool(issues))
        finally:
            self._syncing = False

    @staticmethod
    def _group_hint(event: EventModel) -> str:
        if not event.execute_action:
            return txt(
                "Signals only feed conditions; groups apply to rules.",
                "신호는 조건으로만 쓰입니다. 그룹은 규칙에만 적용됩니다.",
            )
        if (event.group_id or "").strip():
            return txt(
                "Only one rule per group runs: the highest in the list.",
                "그룹에서는 목록 위쪽 규칙 하나만 실행됩니다.",
            )
        return txt(
            "No group: every matching rule runs, so order does not matter.",
            "그룹 없음: 조건이 맞는 규칙이 모두 실행되어 순서가 상관없습니다.",
        )

    @staticmethod
    def _state_label(state: bool) -> str:
        return txt("on", "켜짐") if state else txt("off", "꺼짐")

    def _refresh_conditions(self) -> None:
        while self.cond_list.count():
            item = self.cond_list.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                # 지우기 전에 바로 숨긴다(deleteLater는 다음 루프에서 지운다).
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        event = self.current
        if event is None:
            return
        if not event.conditions:
            none = QLabel(txt("None", "없음"))
            style.caption(none)
            self.cond_list.addWidget(none)
            return
        for name, state in list(event.conditions.items()):
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            label = QLabel(name)
            label.setObjectName("condition_name")
            line.addWidget(label, 1)
            combo = QComboBox()
            combo.addItems([self._state_label(True), self._state_label(False)])
            combo.setCurrentIndex(0 if state else 1)
            combo.activated.connect(self._condition_slot(name))
            line.addWidget(combo)
            remove = QToolButton()
            remove.setText(tokens.ICON_REMOVE)
            remove.setAutoRaise(True)
            remove.setToolTip(txt("Delete", "삭제"))
            remove.clicked.connect(
                lambda _checked=False, n=name: self._remove_condition(n)
            )
            line.addWidget(remove)
            self.cond_list.addWidget(row)

    def _refresh_screen(self) -> None:
        event = self.current
        if event is None:
            return
        image = event.held_screenshot
        if image is None:
            size = THUMB_MAX * 3 // 4
            self.lbl_thumb.setPixmap(QPixmap())
            self.lbl_thumb.setFixedSize(size, size // 2)
            self.lbl_thumb.setText(txt("No screen yet", "화면 없음"))
            style.caption(self.lbl_thumb)
        else:
            region = event.region_size if event.match_mode == "region" else None
            shown = render_overlay(image, event.clicked_position, region)
            shown.thumbnail((THUMB_MAX, THUMB_MAX))
            self.lbl_thumb.setText("")
            self.lbl_thumb.setPixmap(pil_to_pixmap(shown))
            self.lbl_thumb.setFixedSize(shown.width + 2, shown.height + 2)
        color = event.ref_pixel_value
        if color:
            hex_color = "#{:02x}{:02x}{:02x}".format(*(int(c) for c in color[:3]))
            self.lbl_swatch.setStyleSheet(
                f"background: {hex_color}; border: 1px solid palette(mid);"
            )
        else:
            self.lbl_swatch.setStyleSheet("border: 1px solid palette(mid);")
        if event_has_screen(event):
            pos = cast(Position, event.latest_position)
            pixel = cast(Position, event.clicked_position)
            rgb = ",".join(str(int(c)) for c in color[:3]) if color else "—"
            self.lbl_screen.setText(
                f"{rgb}  ({pos[0] + pixel[0]}, {pos[1] + pixel[1]})"
            )
            self.btn_clear_screen.setEnabled(True)
        else:
            self.lbl_screen.setText(
                txt("No screen trigger", "화면 트리거 없음")
                if event.execute_action
                else txt("No screen yet", "화면 없음")
            )
            self.btn_clear_screen.setEnabled(False)

    def _refresh_advanced(self) -> None:
        event = self.current
        if event is None:
            return
        if not self.entry_duration.hasFocus():
            self.entry_duration.setText(
                ""
                if event.press_duration_ms is None
                else str(int(event.press_duration_ms))
            )
        if not self.entry_random.hasFocus():
            self.entry_random.setText(
                ""
                if event.randomization_ms is None
                else str(int(event.randomization_ms))
            )
        self.chk_invert.setChecked(bool(event.invert_match))
        self.chk_invert.setEnabled(event_has_screen(event))
        is_region = event.match_mode == "region"
        self.radio_region.setChecked(is_region)
        self.radio_pixel.setChecked(not is_region)
        has_image = (
            event.held_screenshot is not None and event.clicked_position is not None
        )
        for button in (self.radio_pixel, self.radio_region):
            button.setEnabled(has_image)
        region = event.region_size or (100, 100)
        for spin, value in (
            (self.spin_region_w, region[0]),
            (self.spin_region_h, region[1]),
        ):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
            spin.setEnabled(is_region and has_image)
        customized = bool(
            event.press_duration_ms
            or event.randomization_ms
            or event.invert_match
            or event.match_mode == "region"
        )
        open_ = self.btn_advanced.isChecked()
        mark = tokens.ICON_EXPANDED if open_ else tokens.ICON_COLLAPSED
        dot = " ·" if customized else ""
        self.btn_advanced.setText(f"{mark} {txt('Advanced', '고급')}{dot}")

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced.setVisible(checked)
        self._refresh_advanced()

    # ── commits ────────────────────────────────────────────────────────

    def commit_name(self) -> bool:
        """입력한 이름을 확정한다. 거부되면 이유를 보이고 False."""
        event = self.current
        if event is None or self._syncing:
            return True
        error = self.model.rename_event(event, self.entry_name.text())
        _set_message(self.lbl_name_error, error)
        return not error

    def _on_kind_changed(self, *_args: object) -> None:
        if self.current is None or self._syncing:
            return
        self.model.set_event_kind(self.current, self.radio_rule.isChecked())

    def _on_key_changed(self, *_args: object) -> None:
        if self.current is None or self._syncing:
            return
        self.model.set_event_key(self.current, self.combo_key.currentText() or None)

    def _on_group_changed(self, *_args: object) -> None:
        if self.current is None or self._syncing:
            return
        self.model.set_event_group(self.current, self.combo_group.currentText())

    def _on_use_changed(self, checked: bool) -> None:
        if self.current is None or self._syncing:
            return
        self.model.set_event_use(self.current, checked)

    def _on_toggle_changed(self, checked: bool) -> None:
        if self.current is None or self._syncing:
            return
        self.model.set_event_toggle_member(self.current, checked)

    def _set_condition(self, name: str, state: bool) -> None:
        if self.current is not None:
            self.model.set_condition(self.current, name, state)

    def _remove_condition(self, name: str) -> None:
        if self.current is not None:
            self.model.remove_condition(self.current, name)

    def _fill_condition_menu(self) -> None:
        menu = self.cond_menu
        menu.clear()
        event = self.current
        candidates = self.model.condition_candidates(event) if event is not None else []
        if not candidates:
            action = menu.addAction(txt("No other events", "다른 이벤트가 없습니다"))
            action.setEnabled(False)
            return
        last_kind: bool | None = None
        for candidate, cycle in candidates:
            kind = bool(candidate.execute_action)
            if last_kind is not None and kind != last_kind:
                menu.addSeparator()
            last_kind = kind
            name = candidate.event_name or ""
            if cycle:
                action = menu.addAction(
                    txt(
                        "{name} — circular: {path}",
                        "{name} — 순환: {path}",
                        name=name,
                        path=" → ".join(cycle),
                    )
                )
                action.setEnabled(False)
            else:
                action = menu.addAction(name)
                action.triggered.connect(
                    lambda _checked=False, n=name: self._set_condition(n, True)
                )

    def _commit_timing(self) -> None:
        event = self.current
        if event is None or self._syncing:
            return
        dur_text = self.entry_duration.text().strip()
        rand_text = self.entry_random.text().strip()
        dur = int(dur_text) if dur_text else None
        rand = int(rand_text) if rand_text else None
        if not self.model.set_event_timing(event, dur, rand):
            _set_message(
                self.lbl_timing_error,
                txt(
                    "Press time must be at least 50 ms and random at least 30 ms.",
                    "누름 시간은 50ms, 랜덤은 30ms 이상이어야 합니다.",
                ),
            )
            return
        _set_message(self.lbl_timing_error, "")

    def _on_invert_changed(self, checked: bool) -> None:
        if self.current is None or self._syncing:
            return
        self.model.set_event_invert(self.current, checked)

    def _on_mode_changed(self, *_args: object) -> None:
        if self.current is None or self._syncing:
            return
        mode = "region" if self.radio_region.isChecked() else "pixel"
        self.model.set_match_mode(self.current, mode)

    def _on_region_size_changed(self, *_args: object) -> None:
        event = self.current
        if event is None or self._syncing:
            return
        self.model.set_region_size(
            event, self.spin_region_w.value(), self.spin_region_h.value()
        )
        self._refresh_advanced()

    def _on_clear_screen(self) -> None:
        if self.current is not None:
            self.model.clear_screen(self.current)

    def _bulk_slot(self, action: BulkAction, value: object) -> Callable[[], None]:
        return lambda: self._bulk(action, value)

    def _condition_slot(self, name: str) -> Callable[[int], None]:
        def on_activated(index: int) -> None:
            self._set_condition(name, index == 0)

        return on_activated

    def _bulk(self, action: BulkAction, value: object) -> None:
        self.model.bulk(action, value, self.selection_getter())

    def _bulk_delete(self) -> None:
        self.model.delete_events(self.selection_getter())

    # ── capture HUD ────────────────────────────────────────────────────

    def open_capture(self) -> None:
        event = self.current
        if event is None:
            return
        hud = self.capture_hud
        if hud is not None and hud.is_open():
            return  # 이미 열린 HUD를 쓴다(HUD 참조에는 is_open/close만 부른다)
        from app.ui.capture_hud import CaptureHud

        region = event.region_size if event.match_mode == "region" else None

        def on_apply(result: CaptureResult) -> None:
            self.model.apply_capture_to(event, result)

        def on_name_change(name: str) -> None:
            if self.current is event:
                self.entry_name.setText(name)

        def on_close() -> None:
            self.capture_hud = None
            if self.current is event:
                self.commit_name()

        self.capture_hud = CaptureHud(
            self.window(),
            mode="single",
            name=event.event_name or "",
            on_name_change=on_name_change,
            on_apply=on_apply,
            initial=capture_from_event(event),
            capture_size=event.capture_size or (100, 100),
            region_size=region,
            grab=True,
            border=not self.running_getter(),
            on_close=on_close,
        )
