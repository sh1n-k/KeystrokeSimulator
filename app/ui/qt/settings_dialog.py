"""설정 창.

전환 중 자리표시자. 실제 화면은 P4에서 이 모듈에 구현한다.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from app.utils.i18n import txt


def open_settings(parent: QWidget) -> None:
    QMessageBox.information(
        parent,
        txt("Not ready", "준비 중"),
        txt("The Qt settings window is not built yet.", "Qt 설정 창은 아직 만들지 않았습니다."),
    )
