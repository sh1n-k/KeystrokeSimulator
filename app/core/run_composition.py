"""Compose multiple profiles into one processor session via internal namespaces."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.models import EventModel, ProfileModel
from app.core.profile_events import clone_event
from app.core.validation import find_duplicate_event_names, normalized_event_name
from app.utils.i18n import txt
from app.utils.runtime_toggle import (
    collect_runtime_toggle_validation_errors,
    normalize_runtime_toggle_trigger,
)


NAMESPACE_SEP = "/"


def namespaced_token(profile_name: str, token: str) -> str:
    """Build a stable internal id: ``{profile}/{token}``."""
    return f"{profile_name}{NAMESPACE_SEP}{token}"


def namespace_event(
    profile_name: str,
    event: EventModel,
    *,
    keep_runtime_toggle_member: bool = True,
) -> EventModel:
    """Clone *event* with profile-scoped name, group, and condition keys."""
    base_name = normalized_event_name(event.event_name) or "Unknown"
    cloned = clone_event(
        event, event_name=namespaced_token(profile_name, base_name)
    )
    group = (event.group_id or "").strip()
    cloned.group_id = namespaced_token(profile_name, group) if group else None
    rewritten: dict[str, bool] = {}
    for raw_key, expected in (event.conditions or {}).items():
        key = normalized_event_name(raw_key)
        if not key:
            continue
        rewritten[namespaced_token(profile_name, key)] = bool(expected)
    cloned.conditions = rewritten
    if not keep_runtime_toggle_member:
        # Stale members on toggle-disabled profiles must not join the session toggle.
        cloned.runtime_toggle_member = False
    return cloned


def namespace_profile_events(
    profile_name: str,
    events: list[EventModel],
    *,
    keep_runtime_toggle_member: bool = True,
) -> list[EventModel]:
    return [
        namespace_event(
            profile_name,
            evt,
            keep_runtime_toggle_member=keep_runtime_toggle_member,
        )
        for evt in events
    ]


@dataclass
class ComposedRunSession:
    """Result of composing one or more profiles for a single processor start."""

    profile_names: list[str]
    events: list[EventModel] = field(default_factory=list[EventModel])
    runtime_toggle_enabled: bool = False
    runtime_toggle_key: str | None = None
    errors: list[str] = field(default_factory=list[str])

    @property
    def ok(self) -> bool:
        return not self.errors


def compose_run_session(
    loaded: list[tuple[str, ProfileModel]],
    *,
    settings: object | None = None,
    os_name: str | None = None,
) -> ComposedRunSession:
    """
    Merge loaded ``(profile_name, profile)`` pairs into one run session.

    Event names, groups, and condition references are namespaced per profile so
    identical local names never collide. Cross-profile conditions are not
    supported (condition keys only rewrite within the same profile).
    """
    if not loaded:
        return ComposedRunSession(
            profile_names=[],
            errors=[
                txt(
                    "Select at least one profile to run.",
                    "실행할 프로필을 하나 이상 선택하세요.",
                )
            ],
        )

    profile_names = [name for name, _ in loaded]
    composed_events: list[EventModel] = []
    errors: list[str] = []

    for name, profile in loaded:
        raw_events = list(profile.event_list or [])
        dups = find_duplicate_event_names(raw_events)
        if dups:
            errors.append(
                txt(
                    "Duplicate event names in profile '{profile}': {names}",
                    "프로필 '{profile}'에 중복 이벤트 이름이 있습니다: {names}",
                    profile=name,
                    names=", ".join(dups),
                )
            )
            continue
        composed_events.extend(
            namespace_profile_events(
                name,
                raw_events,
                keep_runtime_toggle_member=bool(
                    getattr(profile, "runtime_toggle_enabled", False)
                ),
            )
        )

    if errors:
        return ComposedRunSession(
            profile_names=profile_names, events=composed_events, errors=errors
        )

    toggle_sources: list[tuple[str, str | None]] = []
    for name, profile in loaded:
        if getattr(profile, "runtime_toggle_enabled", False):
            toggle_sources.append(
                (name, getattr(profile, "runtime_toggle_key", None))
            )

    runtime_toggle_enabled = False
    runtime_toggle_key: str | None = None

    if toggle_sources:
        normalized_keys: list[str] = []
        missing_key_profiles: list[str] = []
        for name, raw_key in toggle_sources:
            trigger = normalize_runtime_toggle_trigger(raw_key)
            if not (raw_key or "").strip() or not trigger:
                missing_key_profiles.append(name)
            else:
                normalized_keys.append(trigger)

        if missing_key_profiles:
            errors.append(
                txt(
                    "Toggle set trigger is missing in: {profiles}",
                    "토글 세트 트리거가 비어 있습니다: {profiles}",
                    profiles=", ".join(missing_key_profiles),
                )
            )
        unique_keys = sorted(set(normalized_keys))
        if len(unique_keys) > 1:
            detail_parts = [
                f"{name}={normalize_runtime_toggle_trigger(key) or (key or '—')}"
                for name, key in toggle_sources
            ]
            errors.append(
                txt(
                    "Toggle set triggers differ across profiles: {detail}",
                    "프로필 간 토글 세트 트리거가 다릅니다: {detail}",
                    detail="; ".join(detail_parts),
                )
            )
        elif unique_keys:
            runtime_toggle_key = unique_keys[0]
            synthetic = ProfileModel(
                runtime_toggle_enabled=True,
                runtime_toggle_key=runtime_toggle_key,
            )
            toggle_errors = collect_runtime_toggle_validation_errors(
                synthetic,
                composed_events,
                settings=settings,  # type: ignore[arg-type]
                os_name=os_name,
            )
            if toggle_errors:
                errors.extend(toggle_errors)
            else:
                runtime_toggle_enabled = True

    return ComposedRunSession(
        profile_names=profile_names,
        events=composed_events,
        runtime_toggle_enabled=runtime_toggle_enabled,
        runtime_toggle_key=runtime_toggle_key,
        errors=errors,
    )


def format_run_profile_summary(names: list[str], *, max_names: int = 3) -> str:
    cleaned = [n for n in names if n]
    if not cleaned:
        return "—"
    if len(cleaned) <= max_names:
        return " · ".join(cleaned)
    head = " · ".join(cleaned[:max_names])
    rest = len(cleaned) - max_names
    return f"{head} (+{rest})"


def normalize_run_profile_list(
    names: list[str] | None, available: set[str] | list[str]
) -> list[str]:
    """Keep order, drop unknowns/duplicates."""
    avail = set(available)
    seen: set[str] = set()
    result: list[str] = []
    for name in names or []:
        if not name or name in seen or name not in avail:
            continue
        seen.add(name)
        result.append(name)
    return result
