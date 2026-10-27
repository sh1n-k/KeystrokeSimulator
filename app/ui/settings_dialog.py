"""설정 창.

상태·검증·저장은 `SettingsForm`이 맡는다. 열려 있는 동안 전역 단축키 리스너를
끄고, 닫힐 때(확인이든 취소든) 실행 창 설정을 다시 읽고 리스너를 되살린다. topmost가 아니며 Esc로 닫힌다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.presenters.settings_form import (
    TIMING_PREFIXES,
    FormError,
    SettingsForm,
    SettingsSection,
)
from app.storage.app_state import StateUtils
from app.ui import style
from app.ui.dialogs import KeyCaptureEdit
from app.utils.i18n import LANGUAGE_LABELS, SUPPORTED_LANGUAGES, txt
from app.utils.notification_sound_packs import (
    normalize_notification_sound_pack,
    notification_sound_pack_choices,
)
from app.utils.sounds import SoundPlayer

STATE_KEY = "settings_position"


class SettingsHost(Protocol):
    """실행 창(`RunWindow`)에서 쓰는 부분."""

    settings_dialog: QWidget | None
    sound_player: SoundPlayer

    def load_settings(self) -> None: ...
    def setup_event_handlers(self) -> None: ...
    def unbind_events(self) -> None: ...
    def is_alive(self) -> bool: ...


def open_settings(parent: QWidget) -> None:
    host = cast(SettingsHost, parent)
    existing = host.settings_dialog
    if existing is not None and existing.isVisible():
        existing.raise_()
        existing.activateWindow()
        return
    host.unbind_events()
    dialog = SettingsDialog(host, parent)
    host.settings_dialog = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


class _NumberValidator(QValidator):
    def validate(self, arg__1: str, arg__2: int, /) -> object:
        state = (
            QValidator.State.Acceptable
            if SettingsForm.timing_text_valid(arg__1)
            else QValidator.State.Invalid
        )
        return (state, arg__1, arg__2)


class SettingsDialog(QDialog):
    def __init__(
        self,
        host: SettingsHost,
        parent: QWidget | None = None,
        *,
        form: SettingsForm | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self.form = form or SettingsForm.load()
        self._finished = False
        self.setWindowTitle(txt("Settings", "설정"))
        # 앱 모달. WindowModal은 macOS에서 시트가 된다.
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.error_labels: dict[SettingsSection, QLabel] = {}
        self.timing_edits: dict[str, QLineEdit] = {}
        self._build()
        self._refresh_from_form()
        self._restore_position()

    # ── layout ─────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        root.addWidget(self._build_keys_group())
        root.addWidget(self._build_language_group())
        root.addWidget(self._build_timing_group())
        root.addWidget(self._build_sound_group())
        root.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Reset
        )
        self.ok_button = self._std_button(buttons, QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(txt("OK", "확인"))
        self.cancel_button = self._std_button(
            buttons, QDialogButtonBox.StandardButton.Cancel
        )
        self.cancel_button.setText(txt("Cancel", "취소"))
        self.reset_button = self._std_button(
            buttons, QDialogButtonBox.StandardButton.Reset
        )
        self.reset_button.setText(txt("Reset", "초기화"))
        self.ok_button.clicked.connect(self.on_ok)
        self.cancel_button.clicked.connect(self.reject)
        self.reset_button.clicked.connect(self.on_reset)
        root.addWidget(buttons)
        self.setMinimumWidth(520)

    @staticmethod
    def _std_button(
        box: QDialogButtonBox, which: QDialogButtonBox.StandardButton
    ) -> QPushButton:
        button = box.button(which)
        assert button is not None
        return button

    def _error_label(self, section: SettingsSection) -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setStyleSheet(style.badge_qss("warn"))
        label.hide()
        self.error_labels[section] = label
        return label

    def _build_keys_group(self) -> QGroupBox:
        group = QGroupBox(txt("Start / Stop", "시작 / 중지"))
        self.keys_group = group
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        row.addWidget(QLabel(txt("Start/Stop Key:", "시작/중지 키:")))
        self.key_edit = KeyCaptureEdit()
        self.key_edit.setPlaceholderText(txt("Press Key", "키 입력"))
        self.key_edit.setFixedWidth(120)
        self.key_edit.setToolTip(
            txt(
                "Click, then press a key (A-Z, 0-9, symbols, F1-F35).",
                "클릭한 뒤 키를 누르세요(A-Z, 0-9, 기호, F1-F35).",
            )
        )
        self.key_edit.keyCaptured.connect(self._on_key_captured)
        if self.form.is_windows:
            self.hotkey_check = QCheckBox(txt("Use Alt+Shift", "Alt+Shift 사용"))
            self.hotkey_check.toggled.connect(self._on_alt_shift_toggled)
            row.addWidget(self.key_edit)
            row.addWidget(self.hotkey_check)
            hint = txt(
                "Start/Stop: A-Z, 0-9, special keys only.",
                "시작/중지: A-Z, 0-9, 특수키만 허용됩니다.",
            )
        else:
            self.hotkey_check = QCheckBox(
                txt(
                    "Enable Start/Stop Key (Option+Shift)",
                    "시작/중지 키 사용 (Option+Shift)",
                )
            )
            self.hotkey_check.toggled.connect(self._on_mac_hotkey_toggled)
            layout.addWidget(self.hotkey_check)
            row.addWidget(self.key_edit)
            hint = txt(
                "macOS: Start/Stop is Option+Shift.",
                "macOS: 시작/중지는 Option+Shift입니다.",
            )
        row.addStretch(1)
        layout.addLayout(row)
        self.keys_hint = QLabel(hint)
        style.caption(self.keys_hint)
        layout.addWidget(self.keys_hint)
        layout.addWidget(self._error_label("keys"))
        return group

    def _build_language_group(self) -> QGroupBox:
        group = QGroupBox(txt("Language", "언어"))
        layout = QHBoxLayout(group)
        layout.addWidget(QLabel(txt("Language:", "언어:")))
        self.language_combo = QComboBox()
        for code in SUPPORTED_LANGUAGES:
            self.language_combo.addItem(LANGUAGE_LABELS[code], code)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        layout.addWidget(self.language_combo)
        layout.addStretch(1)
        return group

    def _build_timing_group(self) -> QGroupBox:
        group = QGroupBox(txt("Timing", "타이밍"))
        self.timing_group = group
        layout = QVBoxLayout(group)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        labels = {
            "key_pressed_time": txt("Key pressed time", "키 누름 시간"),
            "delay_between_loop": txt("Delay between loop", "루프 간 지연"),
        }
        for row, prefix in enumerate(TIMING_PREFIXES):
            grid.addWidget(
                QLabel(f"{labels[prefix]} ({txt('min, max', '최소, 최대')}):"), row, 0
            )
            for col, suffix in enumerate(("min", "max"), start=1):
                name = f"{prefix}_{suffix}"
                edit = QLineEdit()
                edit.setValidator(_NumberValidator(edit))
                edit.setFixedWidth(80)
                edit.setAlignment(Qt.AlignmentFlag.AlignRight)
                edit.textEdited.connect(self._timing_handler(name))
                grid.addWidget(edit, row, col)
                self.timing_edits[name] = edit
            grid.addWidget(QLabel("ms"), row, 3)
        grid.setColumnStretch(4, 1)
        layout.addLayout(grid)
        layout.addWidget(self._error_label("timing"))
        return group

    def _build_sound_group(self) -> QGroupBox:
        group = QGroupBox(txt("Notification Sound", "알림음"))
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(8)
        packs = notification_sound_pack_choices()

        def pack_combo() -> QComboBox:
            combo = QComboBox()
            for pack in packs:
                combo.addItem(txt(pack.label_en, pack.label_ko), pack.pack_id)
            return combo

        grid.addWidget(QLabel(txt("Start/Stop Sound:", "시작/종료 알림음:")), 0, 0)
        self.sound_pack_combo = pack_combo()
        self.sound_pack_combo.currentIndexChanged.connect(self._on_sound_pack_changed)
        grid.addWidget(self.sound_pack_combo, 0, 1)
        self.preview_start_button = QPushButton(txt("Preview Start", "시작 미리듣기"))
        self.preview_stop_button = QPushButton(txt("Preview Stop", "종료 미리듣기"))
        self.preview_start_button.clicked.connect(self._preview_start_sound)
        self.preview_stop_button.clicked.connect(self._preview_stop_sound)
        grid.addWidget(self.preview_start_button, 0, 2)
        grid.addWidget(self.preview_stop_button, 0, 3)

        self.toggle_sound_check = QCheckBox(txt("On/off alert", "켜고 끄기 알림음"))
        self.toggle_sound_check.toggled.connect(self._on_toggle_sound_enabled)
        grid.addWidget(self.toggle_sound_check, 1, 0)
        self.toggle_sound_pack_combo = pack_combo()
        self.toggle_sound_pack_combo.currentIndexChanged.connect(
            self._on_toggle_sound_pack_changed
        )
        grid.addWidget(self.toggle_sound_pack_combo, 1, 1)
        self.preview_on_button = QPushButton(txt("Preview On", "켜짐 미리듣기"))
        self.preview_off_button = QPushButton(txt("Preview Off", "꺼짐 미리듣기"))
        self.preview_on_button.clicked.connect(self._preview_toggle_on_sound)
        self.preview_off_button.clicked.connect(self._preview_toggle_off_sound)
        grid.addWidget(self.preview_on_button, 1, 2)
        grid.addWidget(self.preview_off_button, 1, 3)
        grid.setColumnStretch(4, 1)
        for button in (
            self.preview_start_button,
            self.preview_stop_button,
            self.preview_on_button,
            self.preview_off_button,
        ):
            button.setAutoDefault(False)
        return group

    # ── form ↔ widgets ─────────────────────────────────────────────────

    def _refresh_from_form(self) -> None:
        s = self.form.settings
        widgets: list[QWidget] = [
            self.hotkey_check,
            self.language_combo,
            self.sound_pack_combo,
            self.toggle_sound_pack_combo,
            self.toggle_sound_check,
        ]
        for widget in widgets:
            widget.blockSignals(True)
        self.hotkey_check.setChecked(
            s.use_alt_shift_hotkey if self.form.is_windows else s.toggle_start_stop_mac
        )
        self._set_combo_data(self.language_combo, s.language)
        self._set_combo_data(
            self.sound_pack_combo,
            normalize_notification_sound_pack(s.notification_sound_pack),
        )
        self._set_combo_data(
            self.toggle_sound_pack_combo,
            normalize_notification_sound_pack(s.runtime_toggle_sound_pack),
        )
        self.toggle_sound_check.setChecked(bool(s.runtime_toggle_sound_enabled))
        for widget in widgets:
            widget.blockSignals(False)
        for name, edit in self.timing_edits.items():
            edit.setText(self.form.timing[name])
        self._refresh_key()

    def _refresh_key(self) -> None:
        self.key_edit.setText(self.form.start_stop_key_display)
        self.key_edit.setEnabled(self.form.key_capture_enabled)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    @staticmethod
    def _combo_str(combo: QComboBox) -> str:
        data: object = combo.currentData()
        return data if isinstance(data, str) else ""

    def _timing_handler(self, name: str) -> Callable[[str], None]:
        def handler(text: str) -> None:
            self.form.set_timing(name, text)

        return handler

    def _on_key_captured(self, name: str) -> None:
        if self.form.capture_key(name):
            self._refresh_key()

    def _on_alt_shift_toggled(self, checked: bool) -> None:
        self.form.set_use_alt_shift(checked)
        self._refresh_key()

    def _on_mac_hotkey_toggled(self, checked: bool) -> None:
        self.form.set_mac_hotkey_enabled(checked)
        self._refresh_key()

    def _on_language_changed(self, _index: int) -> None:
        self.form.settings.language = self._combo_str(self.language_combo)

    def _on_sound_pack_changed(self, _index: int) -> None:
        self.form.settings.notification_sound_pack = self._combo_str(
            self.sound_pack_combo
        )

    def _on_toggle_sound_pack_changed(self, _index: int) -> None:
        self.form.settings.runtime_toggle_sound_pack = self._combo_str(
            self.toggle_sound_pack_combo
        )

    def _on_toggle_sound_enabled(self, checked: bool) -> None:
        self.form.settings.runtime_toggle_sound_enabled = checked

    # ── preview (shared player only) ───────────────────────────────────

    def _player(self) -> SoundPlayer | None:
        # A second miniaudio PlaybackDevice in one process can hard-crash
        # macOS, so preview only through the run window's single player.
        return getattr(self.host, "sound_player", None)

    def _preview_start_sound(self) -> None:
        if player := self._player():
            player.set_notification_pack(self._combo_str(self.sound_pack_combo))
            player.play_start_sound()

    def _preview_stop_sound(self) -> None:
        if player := self._player():
            player.set_notification_pack(self._combo_str(self.sound_pack_combo))
            player.play_stop_sound()

    def _preview_toggle_on_sound(self) -> None:
        if player := self._player():
            player.set_runtime_toggle_pack(self._combo_str(self.toggle_sound_pack_combo))
            player.play_runtime_toggle_on_sound()

    def _preview_toggle_off_sound(self) -> None:
        if player := self._player():
            player.set_runtime_toggle_pack(self._combo_str(self.toggle_sound_pack_combo))
            player.play_runtime_toggle_off_sound()

    # ── actions ────────────────────────────────────────────────────────

    def on_ok(self) -> None:
        result = self.form.submit()
        if isinstance(result, FormError):
            self.show_error(result)
            return
        self.accept()

    def show_error(self, error: FormError) -> None:
        for section, label in self.error_labels.items():
            label.setVisible(section == error.section)
        label = self.error_labels.get(error.section)
        if label is not None:
            label.setText(error.message)
        focus: QWidget = (
            self.timing_edits[f"{TIMING_PREFIXES[0]}_min"]
            if error.section == "timing"
            else self.key_edit
        )
        if focus.isEnabled():
            focus.setFocus()

    def ask_reset(self) -> bool:
        answer = QMessageBox.question(
            self,
            txt("Warning", "경고"),
            txt("Reset settings?", "설정을 초기화하시겠습니까?"),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Ok

    def on_reset(self) -> None:
        if not self.ask_reset():
            return
        # 화면 값만 기본값으로. 저장은 확인을 눌렀을 때만 한다.
        self.form.reset()
        for label in self.error_labels.values():
            label.hide()
        self._refresh_from_form()

    def done(self, arg__1: int, /) -> None:
        if not self._finished:
            self._finished = True
            self._save_position()
            host = self.host
            if host.settings_dialog is self:
                host.settings_dialog = None
            # 설정을 다시 읽고 리스너를 되살린다(종료 중이면 생략).
            if host.is_alive():
                host.load_settings()
                host.setup_event_handlers()
            self.deleteLater()
        super().done(arg__1)

    # ── position ───────────────────────────────────────────────────────

    def _restore_position(self) -> None:
        state = StateUtils.load_main_app_state()
        pos = StateUtils.parse_slash_int_pair(state.get(STATE_KEY))
        if pos is not None and QGuiApplication.screenAt(QPoint(pos[0] + 40, pos[1] + 20)):
            self.move(pos[0], pos[1])
            return
        parent = self.parentWidget()
        if parent is not None:
            self.adjustSize()
            center = parent.frameGeometry().center()
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def _save_position(self) -> None:
        pos = self.pos()
        StateUtils.save_main_app_state(**{STATE_KEY: f"{pos.x()}/{pos.y()}"})
