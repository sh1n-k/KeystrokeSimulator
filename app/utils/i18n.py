from __future__ import annotations

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


def txt(en: str, ko: str, **fmt: object) -> str:
    base = ko if _current_language == "ko" else en
    return base.format(**fmt) if fmt else base
