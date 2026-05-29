import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, cast

from loguru import logger

from app.core.models import UserSettings
from app.utils.i18n import normalize_language

USER_SETTINGS_PATH = Path("user_settings.json")


def _coerce_bool(name: str, value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    logger.warning(f"Ignoring invalid boolean setting {name}: {value!r}")
    return default


def _coerce_int(name: str, value: Any, default: int | None) -> int | None:
    if value is None and default is None:
        return None
    if isinstance(value, bool):
        logger.warning(f"Ignoring invalid integer setting {name}: {value!r}")
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    logger.warning(f"Ignoring invalid integer setting {name}: {value!r}")
    return default


def _coerce_settings(raw: dict[str, Any]) -> UserSettings:
    defaults = UserSettings()
    values: dict[str, Any] = {}
    for field in fields(UserSettings):
        name = field.name
        if name not in raw:
            continue
        default = getattr(defaults, name)
        value = raw[name]
        if name == "language":
            values[name] = normalize_language(value)
        elif isinstance(default, bool):
            values[name] = _coerce_bool(name, value, default)
        elif isinstance(default, int) or default is None:
            values[name] = _coerce_int(name, value, default)
        else:
            values[name] = value
    settings = UserSettings(**values)
    settings.language = normalize_language(settings.language)
    return settings


def load_user_settings(path: Path = USER_SETTINGS_PATH) -> tuple[UserSettings, bool]:
    if not path.exists():
        return UserSettings(), True
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error(f"Load settings failed: {exc}")
        return UserSettings(), False
    if not isinstance(raw, dict):
        logger.error(f"Load settings failed: expected object, got {type(raw).__name__}")
        return UserSettings(), False
    return _coerce_settings(cast(dict[str, Any], raw)), True


def save_user_settings(
    settings: UserSettings, path: Path = USER_SETTINGS_PATH
) -> None:
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
