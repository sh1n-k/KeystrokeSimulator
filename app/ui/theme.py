"""Design tokens for Keystroke Simulator UI.

Single source of truth for colors, typography, spacing and icon vocabulary.
All UI modules should import tokens from here instead of redefining hex values.

See docs/maintainer-reference.md for the design rationale.
"""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Surface — background tones (paper / panel / canvas / sunken / divider)
# ---------------------------------------------------------------------------
SURFACE_PAPER = "#FAF7F2"        # main background
SURFACE_PANEL = "#F4F0E8"        # nav rail / side panel
SURFACE_CANVAS = "#FFFFFF"       # work area (lists, image previews, etc)
SURFACE_SUNKEN = "#EEE9DD"       # input fields / disabled area
SURFACE_DIVIDER = "#D9D2C1"      # 1px dividers


# ---------------------------------------------------------------------------
# Ink — text / icon tones
# ---------------------------------------------------------------------------
INK_PRIMARY = "#1A1816"
INK_SECONDARY = "#4A463E"
INK_MUTED = "#8A8474"
INK_INVERSE = "#FAF7F2"


# ---------------------------------------------------------------------------
# Signal — single accent color
# ---------------------------------------------------------------------------
SIGNAL_BASE = "#2A6B4A"
SIGNAL_HOVER = "#225A3D"
SIGNAL_TINT = "#E3EFE7"


# ---------------------------------------------------------------------------
# Status — bg / fg pairs with companion icons (color + glyph + label = 3 axes)
# ---------------------------------------------------------------------------
STATUS_READY_BG = "#E6F0E4"
STATUS_READY_FG = "#1F4A2E"
STATUS_READY_ICON = "●"      # ●

STATUS_RUNNING_BG = "#FFF1D6"
STATUS_RUNNING_FG = "#7A5500"
STATUS_RUNNING_ICON = "▶"    # ▶

STATUS_WARN_BG = "#FFE9CC"
STATUS_WARN_FG = "#7A4500"
STATUS_WARN_ICON = "⚠"       # ⚠

STATUS_ERROR_BG = "#F7DAD4"
STATUS_ERROR_FG = "#7A2820"
STATUS_ERROR_ICON = "✕"      # ✕

STATUS_INFO_BG = "#E5EAF2"
STATUS_INFO_FG = "#1F3760"
STATUS_INFO_ICON = "ⓘ"       # ⓘ

STATUS_DISABLED_BG = "#EAE5D8"
STATUS_DISABLED_FG = "#8A8474"
STATUS_DISABLED_ICON = "–"   # –


# ---------------------------------------------------------------------------
# Semantic — condition / danger
# ---------------------------------------------------------------------------
COND_ACTIVE_FG = SIGNAL_BASE
COND_ACTIVE_BG = "#D6E9DC"
COND_INACTIVE_FG = "#7A2820"
COND_INACTIVE_BG = "#F2D9D4"
COND_IGNORE_FG = INK_MUTED
COND_IGNORE_BG = SURFACE_SUNKEN

DANGER_BASE = "#A33627"


# ---------------------------------------------------------------------------
# Spacing — 4px base grid (use these instead of arbitrary padx/pady)
# ---------------------------------------------------------------------------
SPACE_0 = 0
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32


# ---------------------------------------------------------------------------
# Icon vocabulary — unicode glyphs that render across macOS and Windows.
# ---------------------------------------------------------------------------
ICON_FAVORITE = "★"          # ★
ICON_ADD = "＋"               # ＋ (fullwidth plus)
ICON_DELETE = "✕"            # ✕
ICON_COPY = "⧉"              # ⧉
ICON_EDIT = "✎"              # ✎
ICON_GRAPH = "◇"             # ◇
ICON_SORT = "↕"              # ↕
ICON_CONDITION = "◐"         # ◐
ICON_GROUP = "▣"             # ▣
ICON_KEY = "⌨"               # ⌨
ICON_INVERTED = "⇄"          # ⇄
ICON_STANDALONE = "⚡"        # ⚡
ICON_COND_ACTIVE = "●"       # ●
ICON_COND_INACTIVE = "○"     # ○
ICON_COND_IGNORE = "–"       # –
ICON_DRAG_HANDLE = "⠇"       # ⠇ (use vertical dots)
ICON_INFO = "ⓘ"              # ⓘ
ICON_WARN = "⚠"              # ⚠
ICON_HINT = "\U0001F4A1"          # 💡 (kept for parity with existing UI)


# ---------------------------------------------------------------------------
# Typography — single source for font construction.
# ---------------------------------------------------------------------------
def _korean_font_family() -> str:
    if sys.platform == "darwin":
        return "AppleSDGothicNeo"
    if sys.platform == "win32":
        return "Malgun Gothic"
    return "Noto Sans CJK KR"


KOREAN_FONT_FAMILY = _korean_font_family()


def _sans_family() -> str:
    if sys.platform == "darwin":
        return "SF Pro Text"
    if sys.platform == "win32":
        return "Segoe UI"
    return "DejaVu Sans"


def _mono_family() -> str:
    if sys.platform == "darwin":
        return "Menlo"
    if sys.platform == "win32":
        return "Consolas"
    return "DejaVu Sans Mono"


@dataclass(frozen=True)
class FontSpec:
    family: str
    size: int
    weight: str = "normal"  # "normal" | "bold"

    def as_tuple(self) -> tuple[str, int, str]:
        return (self.family, self.size, self.weight)


def make_fonts() -> dict[str, tkfont.Font]:
    """Build cached Font objects. Call once after the root window exists."""
    sans = _sans_family()
    mono = _mono_family()
    return {
        "display": tkfont.Font(family=sans, size=18, weight="bold"),
        "heading": tkfont.Font(family=sans, size=14, weight="bold"),
        "body": tkfont.Font(family=sans, size=12, weight="normal"),
        "body_bold": tkfont.Font(family=sans, size=12, weight="bold"),
        "caption": tkfont.Font(family=sans, size=11, weight="normal"),
        "mono": tkfont.Font(family=mono, size=12, weight="normal"),
    }


_cached_fonts: dict[str, tkfont.Font] | None = None


def fonts() -> dict[str, tkfont.Font]:
    """Lazily build the font cache after a Tk root exists."""
    global _cached_fonts
    if _cached_fonts is None:
        _cached_fonts = make_fonts()
    return _cached_fonts


def reset_font_cache() -> None:
    """Drop cached fonts (used in tests / language switching)."""
    global _cached_fonts
    _cached_fonts = None


# ---------------------------------------------------------------------------
# ttk Style helpers
# ---------------------------------------------------------------------------
def install_styles(root: tk.Misc) -> None:
    """Register named ttk styles used across the redesign.

    Idempotent: safe to call multiple times. Falls back gracefully if the
    underlying theme cannot honor a style.
    """
    from tkinter import ttk

    try:
        style = ttk.Style(root)
    except tk.TclError:
        return

    font_cache = fonts()

    try:
        style.configure(
            "Accent.TButton",
            background=SIGNAL_BASE,
            foreground=INK_INVERSE,
            font=font_cache["body_bold"],
            padding=(SPACE_3, SPACE_2),
            borderwidth=0,
            focusthickness=0,
        )
        style.map(
            "Accent.TButton",
            background=[("active", SIGNAL_HOVER), ("disabled", INK_MUTED)],
            foreground=[("disabled", SURFACE_PAPER)],
        )
    except tk.TclError:
        pass

    try:
        style.configure(
            "Outline.TButton",
            background=SURFACE_CANVAS,
            foreground=INK_PRIMARY,
            font=font_cache["body"],
            padding=(SPACE_3, SPACE_2),
        )
        style.map(
            "Outline.TButton",
            background=[("active", SURFACE_SUNKEN), ("disabled", SURFACE_SUNKEN)],
            foreground=[("disabled", INK_MUTED)],
        )
    except tk.TclError:
        pass

    try:
        style.configure(
            "Danger.TButton",
            background=SURFACE_CANVAS,
            foreground=DANGER_BASE,
            font=font_cache["body"],
            padding=(SPACE_3, SPACE_2),
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#F4D8D3"), ("disabled", SURFACE_SUNKEN)],
            foreground=[("disabled", INK_MUTED)],
        )
    except tk.TclError:
        pass

    try:
        style.configure(
            "Toolbar.TFrame",
            background=SURFACE_PANEL,
        )
        style.configure(
            "Paper.TFrame",
            background=SURFACE_PAPER,
        )
        style.configure(
            "Card.TLabelframe",
            background=SURFACE_CANVAS,
            bordercolor=SURFACE_DIVIDER,
            relief="flat",
            padding=SPACE_3,
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=SURFACE_CANVAS,
            foreground=INK_SECONDARY,
            font=font_cache["heading"],
        )
    except tk.TclError:
        pass


# ---------------------------------------------------------------------------
# Backward-compatible aliases for legacy constants.
# These keep existing references valid while the rest of the codebase
# migrates to the token names above.
# ---------------------------------------------------------------------------
STATUS_BG_INFO = STATUS_INFO_BG
STATUS_FG_INFO = STATUS_INFO_FG
STATUS_BG_OK = STATUS_READY_BG
STATUS_FG_OK = STATUS_READY_FG
STATUS_BG_WARN = STATUS_WARN_BG
STATUS_FG_WARN = STATUS_WARN_FG
STATUS_BG_ERR = STATUS_ERROR_BG
STATUS_FG_ERR = STATUS_ERROR_FG

BADGE_BG_INFO = STATUS_INFO_BG
BADGE_FG_INFO = STATUS_INFO_FG
BADGE_BG_OK = STATUS_READY_BG
BADGE_FG_OK = STATUS_READY_FG
BADGE_BG_WARN = STATUS_WARN_BG
BADGE_FG_WARN = STATUS_WARN_FG
BADGE_BG_ERR = STATUS_ERROR_BG
BADGE_FG_ERR = STATUS_ERROR_FG
