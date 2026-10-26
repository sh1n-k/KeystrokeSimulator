"""Qt 스타일: 플랫폼 기본 위젯 스타일과 시스템 밝기(라이트/다크)를 따른다.

색 토큰은 상태 배지·시작 버튼·캡처 테두리처럼 의미가 있는 곳에만 쓴다.
"""

from __future__ import annotations

import sys
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget

from app.ui import tokens

StatusTone = Literal["ready", "warn", "error", "running"]

# (bg, fg) per tone for light and dark appearance.
_STATUS_LIGHT: dict[StatusTone, tuple[str, str]] = {
    "ready": (tokens.STATUS_READY_BG, tokens.STATUS_READY_FG),
    "warn": (tokens.STATUS_WARN_BG, tokens.STATUS_WARN_FG),
    "error": (tokens.STATUS_ERROR_BG, tokens.STATUS_ERROR_FG),
    "running": (tokens.STATUS_RUNNING_BG, tokens.STATUS_RUNNING_FG),
}
_STATUS_DARK: dict[StatusTone, tuple[str, str]] = {
    "ready": ("#1F3A2A", "#A9E5BD"),
    "warn": ("#46330F", "#FFD58F"),
    "error": ("#4A201B", "#FFB3A6"),
    "running": ("#43360D", "#FFE08A"),
}
STATUS_ICONS: dict[StatusTone, str] = {
    "ready": tokens.STATUS_READY_ICON,
    "warn": tokens.STATUS_WARN_ICON,
    "error": tokens.STATUS_ERROR_ICON,
    "running": tokens.STATUS_RUNNING_ICON,
}

ACCENT = tokens.SIGNAL_BASE
ACCENT_HOVER = tokens.SIGNAL_HOVER
STOP = "#B7791F"
STOP_HOVER = "#9A6418"


def is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    return hints.colorScheme() == Qt.ColorScheme.Dark


def status_colors(tone: StatusTone) -> tuple[str, str]:
    return (_STATUS_DARK if is_dark() else _STATUS_LIGHT)[tone]


def apply_app_style(app: QApplication) -> None:
    """macOS는 기본 macOS 스타일, Windows 11은 windows11, 그 외 Fusion."""
    if sys.platform == "win32":
        keys = {k.lower() for k in QStyleFactory.keys()}
        app.setStyle("windows11" if "windows11" in keys else "Fusion")
    elif sys.platform != "darwin":
        app.setStyle("Fusion")


def badge_qss(tone: StatusTone) -> str:
    bg, fg = status_colors(tone)
    return (
        f"QLabel {{ background: {bg}; color: {fg}; border-radius: 6px;"
        f" padding: {tokens.SPACE_1 + 2}px {tokens.SPACE_2}px; font-weight: 600; }}"
    )


def run_button_qss(state: Literal["start", "stop", "disabled"]) -> str:
    if state == "disabled":
        return (
            "QPushButton { padding: 6px 18px; border-radius: 7px; font-weight: 600; }"
        )
    base, hover = (ACCENT, ACCENT_HOVER) if state == "start" else (STOP, STOP_HOVER)
    return (
        f"QPushButton {{ background: {base}; color: white; border: none;"
        " padding: 6px 18px; border-radius: 7px; font-weight: 600; }"
        f" QPushButton:hover {{ background: {hover}; }}"
    )


def caption(widget: QWidget) -> None:
    """작고 흐린 보조 문구."""
    font = widget.font()
    font.setPointSizeF(max(font.pointSizeF() - 1.5, 9.0))
    widget.setFont(font)
    widget.setStyleSheet("color: palette(placeholder-text);")
