"""Design tokens for Keystroke Simulator UI.

Single source of truth for colors, typography, spacing and icon vocabulary.
All UI modules should import tokens from here instead of redefining hex values.

See docs/maintainer-reference.md for the design rationale.
"""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont


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

# ---------------------------------------------------------------------------
# Semantic — condition / danger
# ---------------------------------------------------------------------------
COND_ACTIVE_FG = SIGNAL_BASE
COND_ACTIVE_BG = "#D6E9DC"
COND_INACTIVE_FG = "#7A2820"
COND_INACTIVE_BG = "#F2D9D4"
DANGER_BASE = "#A33627"


# ---------------------------------------------------------------------------
# Spacing — 4px base grid (use these instead of arbitrary padx/pady)
# ---------------------------------------------------------------------------
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12


# ---------------------------------------------------------------------------
# Icon vocabulary — unicode glyphs that render across macOS and Windows.
# ---------------------------------------------------------------------------
ICON_CONDITION = "◐"         # ◐
ICON_INVERTED = "⇄"          # ⇄


# ---------------------------------------------------------------------------
# Typography — single source for font construction.
# ---------------------------------------------------------------------------
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
