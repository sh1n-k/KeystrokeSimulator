"""작업 공간 목록과 실행 창 콤보에 쓰는 표시 문자열. UI 툴킷과 무관하다."""

from __future__ import annotations

from app.domain.models import EventModel
from app.domain.profile_events import (
    EventSection,
    event_has_screen,
    event_needs_attention,
)
from app.utils.i18n import txt

COND_SUMMARY_CHARS = 40
TARGET_COMBO_CHARS = 24


def section_title(section: EventSection) -> str:
    count = len(section.events)
    if section.kind == "signal":
        return txt("Signals ({count})", "신호 ({count})", count=count)
    if section.kind == "group":
        return txt(
            "Rules · group {group} ({count})",
            "규칙 · 그룹 {group} ({count})",
            group=section.group,
            count=count,
        )
    return txt("Rules · no group ({count})", "규칙 · 그룹 없음 ({count})", count=count)


def section_note(section: EventSection) -> str:
    """묶음 행의 설명 열. 제목은 이름 열에 들어가도록 짧게 두고 실행 방식은 여기 쓴다."""
    if section.kind == "signal":
        return txt("Conditions only", "조건에만 쓰임")
    if section.kind == "group":
        return txt("Top match runs", "맨 위 하나만 실행")
    return txt("All matches run", "맞는 것 모두 실행")


def condition_summary(event: EventModel, limit: int = COND_SUMMARY_CHARS) -> str:
    """조건 요약. 꺼짐이 필요한 조건은 앞에 !를 붙인다."""
    parts = [name if state else f"!{name}" for name, state in event.conditions.items()]
    text = " · ".join(parts)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def row_detail(event: EventModel) -> str:
    if event.execute_action:
        return condition_summary(event)
    if event.latest_position is not None and event.clicked_position is not None:
        x = event.latest_position[0] + event.clicked_position[0]
        y = event.latest_position[1] + event.clicked_position[1]
        return f"({x}, {y})"
    return ""


def row_badges(
    event: EventModel, *, referenced: bool, toggle_enabled: bool
) -> list[str]:
    badges: list[str] = []
    if not event.use_event:
        badges.append(txt("off", "꺼짐"))
    if event_needs_attention(event):
        badges.append(txt("no key", "키 없음"))
    if not event.execute_action and not event_has_screen(event):
        badges.append(txt("no screen", "화면 없음"))
    if (
        event.execute_action
        and not event_has_screen(event)
        and not event.conditions
    ):
        badges.append(txt("no trigger", "조건·화면 없음"))
    if event.execute_action and referenced:
        badges.append(txt("referenced", "참조됨"))
    if toggle_enabled and event.runtime_toggle_member:
        badges.append(txt("hotkey", "단축키"))
    return badges


def ellipsize_display(text: str, max_chars: int = TARGET_COMBO_CHARS) -> str:
    """Keep combobox labels within a fixed character budget (stable window width)."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars == 1:
        return "…"
    return text[: max_chars - 1] + "…"


def run_set_display(name: str) -> str:
    return ellipsize_display(f"{txt('Set', '세트')} · {name}")
