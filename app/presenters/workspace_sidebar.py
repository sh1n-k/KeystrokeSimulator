"""작업 공간 사이드바 항목 종류와 항목별 동작 목록. UI 툴킷과 무관하다."""

from __future__ import annotations

from typing import Literal

from app.storage.profile_display import QUICK_PROFILE_NAME
from app.utils.i18n import txt

ItemKind = Literal["profile", "run_set"]


def sidebar_actions(kind: ItemKind, name: str) -> list[tuple[str, str]]:
    """(action, 라벨). Quick은 이름 변경·삭제가 없다."""
    if kind == "run_set":
        return [
            ("rename", txt("Rename…", "이름 바꾸기…")),
            ("copy", txt("Duplicate", "복사")),
            ("delete", txt("Delete", "삭제")),
        ]
    actions = [
        ("copy", txt("Duplicate", "복사")),
        ("favorite", txt("Toggle favorite", "즐겨찾기 켜기/끄기")),
    ]
    if name != QUICK_PROFILE_NAME:
        actions.insert(0, ("rename", txt("Rename…", "이름 바꾸기…")))
        actions.append(("delete", txt("Delete", "삭제")))
    return actions
