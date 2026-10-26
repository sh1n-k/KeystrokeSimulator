"""수정키 세트 편집 창.

상태와 저장은 `ModKeysForm`이 맡는다. 모달로 열고 닫히면 돌아간다. Enter로
저장, Esc로 닫힌다. 세트는 프로필·실행 세트와 독립이다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.presenters.modkeys_form import PLACEHOLDER_VALUE, ModKeysForm
from app.ui import style
from app.ui.dialogs import KeyCaptureEdit
from app.utils.i18n import txt

_KEYCAPS = {"Alt": "⎇", "Ctrl": "⌃", "Shift": "⇧"}


def edit_modkey_set(parent: QWidget, set_name: str, sets_path: Path) -> None:
    dialog = ModKeysDialog(parent, set_name, sets_path)
    dialog.exec()
    dialog.deleteLater()


class _RowWidgets:
    def __init__(
        self,
        enabled: QCheckBox,
        key: KeyCaptureEdit,
        pass_check: QCheckBox,
        include_check: QCheckBox,
    ) -> None:
        self.enabled = enabled
        self.key = key
        self.pass_check = pass_check
        self.include_check = include_check


class ModKeysDialog(QDialog):
    def __init__(
        self, parent: QWidget | None, set_name: str, sets_path: Path
    ) -> None:
        super().__init__(parent)
        self.form = ModKeysForm.load(set_name, sets_path)
        self.setWindowTitle(
            txt("Modifier keys — {name}", "수정 키 — {name}", name=set_name)
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.rows: list[_RowWidgets] = []
        self._build()
        for index in range(len(self.form.rows)):
            self._refresh_row(index)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        subtitle = QLabel(
            txt(
                "Set: {name} · independent of profiles",
                "세트: {name} · 프로필과 무관합니다",
                name=self.form.set_name,
            )
        )
        style.caption(subtitle)
        root.addWidget(subtitle)

        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        for col, (en, ko) in enumerate(
            (
                ("Modifier", "수정키"),
                ("Key", "키"),
                ("Pass through", "패스"),
                ("Include modifier", "수정키 포함"),
            )
        ):
            header = QLabel(txt(en, ko))
            style.caption(header)
            grid.addWidget(header, 0, col)

        for index, row in enumerate(self.form.rows):
            enabled = QCheckBox(f"{_KEYCAPS.get(row.name, '')}  {row.name}")
            enabled.setToolTip(txt("Enabled", "사용"))
            key = KeyCaptureEdit()
            key.setFixedWidth(100)
            key.setToolTip(
                txt("Click, then press A-Z or 0-9.", "클릭한 뒤 A-Z 또는 0-9를 누르세요.")
            )
            pass_check = QCheckBox()
            include_check = QCheckBox()
            enabled.toggled.connect(self._bind(index, self._on_enabled))
            key.keyCaptured.connect(self._bind_key(index))
            pass_check.toggled.connect(self._bind(index, self._on_pass))
            include_check.toggled.connect(self._bind(index, self._on_include))
            grid.addWidget(enabled, index + 1, 0)
            grid.addWidget(key, index + 1, 1)
            grid.addWidget(pass_check, index + 1, 2, Qt.AlignmentFlag.AlignHCenter)
            grid.addWidget(include_check, index + 1, 3, Qt.AlignmentFlag.AlignHCenter)
            self.rows.append(_RowWidgets(enabled, key, pass_check, include_check))
        root.addWidget(card)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        assert save is not None and cancel is not None
        save.setText(txt("Save (Enter)", "저장 (Enter)"))
        save.setDefault(True)
        cancel.setText(txt("Cancel", "취소"))
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        self.save_button = save
        root.addWidget(buttons)

    def _bind(
        self, index: int, handler: Callable[[int, bool], None]
    ) -> Callable[[bool], None]:
        return lambda checked: handler(index, checked)

    def _bind_key(self, index: int) -> Callable[[str], None]:
        def on_key(name: str) -> None:
            if self.form.capture_key(index, name):
                self._refresh_row(index)

        return on_key

    def _refresh_row(self, index: int) -> None:
        row = self.form.rows[index]
        widgets = self.rows[index]
        for box in (widgets.enabled, widgets.pass_check, widgets.include_check):
            box.blockSignals(True)
        widgets.enabled.setChecked(row.enabled)
        widgets.pass_check.setChecked(row.pass_through)
        widgets.include_check.setChecked(row.include_modifier)
        for box in (widgets.enabled, widgets.pass_check, widgets.include_check):
            box.blockSignals(False)
        if row.value == PLACEHOLDER_VALUE:
            widgets.key.clear()
            widgets.key.setPlaceholderText(txt("Press Key", "키 입력"))
        else:
            widgets.key.setText(row.value)
        # Pass 중에는 키와 수정키 포함을 바꿀 수 없다(Tk와 같음).
        widgets.key.setEnabled(not row.pass_through)
        widgets.include_check.setEnabled(not row.pass_through)

    def _on_enabled(self, index: int, checked: bool) -> None:
        self.form.rows[index].enabled = checked

    def _on_pass(self, index: int, checked: bool) -> None:
        self.form.set_pass(index, checked)
        self._refresh_row(index)

    def _on_include(self, index: int, checked: bool) -> None:
        self.form.rows[index].include_modifier = checked

    def save(self) -> None:
        try:
            self.form.save()
        except Exception as e:
            QMessageBox.critical(
                self,
                txt("Error", "오류"),
                txt(
                    "Failed to save modifier key set: {error}",
                    "수정키 세트 저장 실패: {error}",
                    error=e,
                ),
            )
            return
        self.accept()
