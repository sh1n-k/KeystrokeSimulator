from __future__ import annotations

import unicodedata
from typing import Iterable

SUPPORTED_LANGUAGES = ("en", "ko")
LANGUAGE_LABELS = {
    "en": "English",
    "ko": "한국어",
}

_current_language = "en"


def normalize_language(value: str | None) -> str:
    if value in SUPPORTED_LANGUAGES:
        return value
    return "en"


def set_language(value: str | None) -> str:
    global _current_language
    _current_language = normalize_language(value)
    return _current_language


def get_language() -> str:
    return _current_language


def txt(en: str, ko: str, **fmt) -> str:
    base = ko if _current_language == "ko" else en
    return base.format(**fmt) if fmt else base


def display_width(text: str) -> int:
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def dual_text_width(en: str, ko: str, padding: int = 2, min_width: int = 0) -> int:
    width = max(display_width(en), display_width(ko)) + padding
    return max(width, min_width)


def max_dual_text_width(
    pairs: Iterable[tuple[str, str]], padding: int = 2, min_width: int = 0
) -> int:
    widths = [dual_text_width(en, ko, padding=padding, min_width=min_width) for en, ko in pairs]
    return max(widths) if widths else min_width
