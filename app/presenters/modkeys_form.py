"""수정키 세트 편집 상태와 저장. UI 툴킷과 무관하다.

세트는 프로필·실행 세트와 독립이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.domain.models import ModificationKeys
from app.storage.modkey_sets_storage import get_modkey_set, upsert_modkey_set

MODIFIER_NAMES = ("Alt", "Ctrl", "Shift")
MODKEY_VALID_KEYS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
PASS_VALUE = "Pass"
PLACEHOLDER_VALUE = "PressKey"


@dataclass
class ModKeyRow:
    name: str
    enabled: bool = False
    value: str = PLACEHOLDER_VALUE
    previous: str = PLACEHOLDER_VALUE
    pass_through: bool = False
    include_modifier: bool = True


class ModKeysForm:
    def __init__(self, set_name: str, sets_path: Path) -> None:
        self.set_name = set_name
        self.sets_path = Path(sets_path)
        self.rows = [ModKeyRow(name) for name in MODIFIER_NAMES]

    @classmethod
    def load(cls, set_name: str, sets_path: Path) -> ModKeysForm:
        form = cls(set_name, sets_path)
        try:
            keys = get_modkey_set(set_name, form.sets_path)
        except Exception as e:
            logger.error(f"Load failed: {e}")
            return form
        for row in form.rows:
            conf = keys.get(row.name.lower())
            if not conf:
                continue
            value = str(conf.get("value", PLACEHOLDER_VALUE))
            row.enabled = bool(conf.get("enabled", True))
            row.value = row.previous = value
            row.include_modifier = bool(conf.get("include_modifier", True))
            if conf.get("pass", False):
                form.set_pass(form.rows.index(row), True)
        logger.info(f"Loaded modkey set '{set_name}'")
        return form

    def set_pass(self, index: int, enabled: bool) -> None:
        """패스를 켜면 값을 Pass로 바꾸고, 끄면 이전 값을 되돌린다."""
        row = self.rows[index]
        if enabled == row.pass_through:
            return
        row.pass_through = enabled
        if enabled:
            row.previous = row.value
            row.value = PASS_VALUE
        else:
            row.value = (
                row.previous if row.previous != PASS_VALUE else PLACEHOLDER_VALUE
            )

    def capture_key(self, index: int, char: str) -> bool:
        """A-Z, 0-9 한 글자만 받는다. 패스 중에는 받지 않는다."""
        row = self.rows[index]
        key = char.upper()
        if row.pass_through or key not in MODKEY_VALID_KEYS:
            return False
        row.value = key
        return True

    def to_keys(self) -> ModificationKeys:
        return {
            row.name.lower(): {
                "enabled": row.enabled,
                "value": PASS_VALUE if row.pass_through else row.value,
                "pass": row.pass_through,
                "include_modifier": row.include_modifier,
            }
            for row in self.rows
        }

    def save(self) -> None:
        """저장 실패는 예외로 올린다(창이 오류를 보여주고 열린 채로 둔다)."""
        upsert_modkey_set(self.set_name, self.to_keys(), self.sets_path)
        logger.info(f"Saved modkey set '{self.set_name}'")
