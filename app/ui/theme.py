# ruff: noqa: F405 - tokens come from app.ui.tokens via star import.
"""Design tokens for Keystroke Simulator UI.

Single source of truth for colors, typography, spacing and icon vocabulary.
All UI modules should import tokens from here instead of redefining hex values.

See docs/maintainer-reference.md for the design rationale.
"""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont


from app.ui.tokens import *  # noqa: F403 - Tk callers read tokens via theme.


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
        # Standalone glyph buttons (⚙): the glyph draws small at text sizes.
        "icon": tkfont.Font(family=sans, size=22, weight="normal"),
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
            # SURFACE_PAPER equals INK_INVERSE, so using it here left disabled
            # buttons looking identical to enabled ones on macOS aqua.
            foreground=[("disabled", INK_MUTED)],
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

    # Event list rows — idle vs selected. Paired frame/label styles so the
    # tint covers the whole row instead of leaving label-shaped holes.
    for suffix, background in (("Row", ROW_BG), ("RowSelected", ROW_SELECTED_BG)):
        try:
            style.configure(f"{suffix}.TFrame", background=background)
            style.configure(f"{suffix}.TLabel", background=background)
        except tk.TclError:
            pass
