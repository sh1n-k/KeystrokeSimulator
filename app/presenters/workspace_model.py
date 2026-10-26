"""작업 공간의 상태와 동작. UI 툴킷과 무관하다.

프로필·실행 세트 목록과 CRUD, 선택한 프로필의 이벤트 편집, 되돌리기 스택,
자동 저장(디바운스 타이머는 주입한 `Scheduler`)을 맡는다. 화면 갱신은
`WorkspaceView` 통지로 UI에 맡긴다.

실행은 시작 시점에 불러온 프로필을 쓰므로 실행 중 편집은 다음 시작부터
반영된다. 실행 중에는 프로필·실행 세트 이름 변경과 삭제를 막는다.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, Protocol

from loguru import logger

from app.domain.capture_geometry import CaptureResult
from app.domain.event_editing import apply_capture, clamp_region, clear_capture
from app.domain.models import EventModel, ProfileModel
from app.domain.profile_events import (
    apply_target_to_same_area,
    build_event_sections,
    clone_event,
    copy_event_name,
    event_needs_attention,
    move_in_section,
    next_available_event_name,
    profile_fingerprint,
    remove_condition_references,
    rename_colliding_events,
    rename_condition_references,
    snapshot_events,
    sort_sections_by_name,
    write_section_order,
)
from app.domain.runtime_toggle import (
    StartStopSettings,
    collect_runtime_toggle_validation_errors,
    normalize_runtime_toggle_trigger,
)
from app.domain.validation import (
    condition_cycle_if_added,
    event_name_taken,
    find_duplicate_event_names,
    normalized_event_name,
    timing_is_valid,
)
from app.presenters.workspace_sidebar import ItemKind
from app.storage.profile_display import QUICK_PROFILE_NAME
from app.storage.profile_storage import (
    copy_profile,
    delete_profile_files,
    list_profile_names,
    load_profile,
    ordered_profile_names,
    rename_profile_files,
    save_profile,
)
from app.storage.run_sets_storage import (
    copy_run_set,
    delete_run_set,
    get_run_set,
    list_run_set_names,
    rename_profile_in_run_sets,
    rename_run_set,
    upsert_run_set,
)
from app.utils.i18n import txt

AUTOSAVE_DELAY_MS = 250
UNDO_LIMIT = 30

CancelTimer = Callable[[], None]
# (지연 ms, 동작) → 취소 함수. UI가 자기 타이머로 구현한다.
Scheduler = Callable[[int, Callable[[], object]], CancelTimer]
SaveState = Literal["saved", "saving", "error"]
BulkAction = Literal["use", "toggle", "group"]


class WorkspaceError(ValueError):
    """사용자에게 그대로 보여 줄 거부 사유."""


class WorkspaceView(Protocol):
    """모델이 UI에 알리는 일."""

    def on_opened(self) -> None:
        """다른 프로필이나 실행 세트를 열었다. 화면 전체를 다시 그린다."""
        ...

    def on_events_changed(self, select: list[EventModel] | None) -> None:
        """이벤트 목록이 바뀌었다. `select`가 None이면 선택을 유지한다."""
        ...

    def on_catalog_changed(self) -> None:
        """프로필·실행 세트 목록이 바뀌었다."""
        ...

    def on_save_state_changed(self) -> None: ...

    def on_status(self, text: str) -> None:
        """잠깐 보여 줄 안내."""
        ...

    def show_error(self, message: str) -> None: ...

    def commit_pending_edits(self) -> None:
        """저장 직전에 입력 중인 값(이벤트 이름 등)을 확정한다."""
        ...


class WorkspaceModel:
    def __init__(
        self,
        view: WorkspaceView,
        *,
        profiles_dir: Path,
        run_sets_path: Path,
        scheduler: Scheduler,
        running_getter: Callable[[], bool],
        settings_getter: Callable[[], StartStopSettings | None] = lambda: None,
        on_catalog_changed: Callable[[str | None], object] | None = None,
        on_run_set_renamed: Callable[[str, str], object] | None = None,
    ) -> None:
        self.view = view
        self.profiles_dir = profiles_dir
        self.run_sets_path = run_sets_path
        self.scheduler = scheduler
        self.running_getter = running_getter
        self.settings_getter = settings_getter
        self.host_catalog_changed = on_catalog_changed
        self.host_run_set_renamed = on_run_set_renamed

        self.mode: ItemKind = "profile"
        self.prof_name = ""
        self.profile = ProfileModel(name="", event_list=[])
        # 헤더 입력값. 저장할 때 파일 이름·즐겨찾기에 반영한다.
        self.name_draft = ""
        self.favorite_draft = False
        self.run_set_name = ""
        self.run_set_members: list[str] = []
        self.profile_open = False

        self.save_state: SaveState = "saved"
        self.save_detail = ""
        self.saved_at = ""
        self._undo: list[tuple[str, list[EventModel]]] = []
        self._last_saved_fingerprint: tuple[object, ...] | None = None
        self._cancel_autosave: CancelTimer | None = None

    # ── catalog ────────────────────────────────────────────────────────

    def catalog(self) -> tuple[list[str], set[str], list[str]]:
        """(프로필 표시 순서, 즐겨찾기, 실행 세트)."""
        profiles, favorites = ordered_profile_names(self.profiles_dir)
        return profiles, favorites, list_run_set_names(self.run_sets_path)

    def current_item(self) -> tuple[ItemKind, str]:
        if self.mode == "profile":
            return ("profile", self.prof_name)
        return ("run_set", self.run_set_name)

    def all_profiles(self) -> list[str]:
        return ordered_profile_names(self.profiles_dir)[0]

    def _notify_catalog(self, selected: str | None = None) -> None:
        self.view.on_catalog_changed()
        if self.host_catalog_changed is not None:
            self.host_catalog_changed(selected)

    def _is_current_profile(self, name: str) -> bool:
        return self.mode == "profile" and self.profile_open and name == self.prof_name

    def guard_running(self) -> None:
        """실행 중에는 이름 변경·삭제를 막는다(이름을 묻기 전에 확인한다)."""
        if self.running_getter():
            raise WorkspaceError(
                txt(
                    "Stop the run before renaming or deleting.",
                    "실행 중에는 이름을 바꾸거나 삭제할 수 없습니다.",
                )
            )

    @staticmethod
    def _guard_quick(name: str) -> None:
        if name == QUICK_PROFILE_NAME:
            raise WorkspaceError(
                txt(
                    "The Quick profile cannot be renamed or deleted.",
                    "Quick 프로필은 이름을 바꾸거나 삭제할 수 없습니다.",
                )
            )

    @staticmethod
    def _exists_error(name: str) -> WorkspaceError:
        return WorkspaceError(
            txt("'{n}' already exists.", "'{n}' 이미 있습니다.", n=name)
        )

    # ── opening ────────────────────────────────────────────────────────

    def open_profile(self, name: str) -> bool:
        if self._is_current_profile(name):
            return True
        if self.mode == "profile" and self.profile_open and not self.flush():
            self.view.on_catalog_changed()
            return False
        if name not in list_profile_names(self.profiles_dir):
            name = QUICK_PROFILE_NAME
        self.mode = "profile"
        self.prof_name = name
        try:
            self.profile = load_profile(self.profiles_dir, name, migrate=True)
        except Exception as exc:
            logger.error(f"Workspace load failed for {name}: {exc}")
            self.profile = ProfileModel(name=name, event_list=[])
        self.profile_open = True
        self.name_draft = name
        self.favorite_draft = bool(self.profile.favorite)
        self._undo.clear()
        self._last_saved_fingerprint = profile_fingerprint(
            self.profile, self.prof_name, self.profile.favorite
        )
        self._set_save_state("saved")
        self.view.on_opened()
        return True

    def open_run_set(self, name: str) -> bool:
        if self.mode == "run_set" and name == self.run_set_name:
            return True
        if self.mode == "profile" and self.profile_open and not self.flush():
            self.view.on_catalog_changed()
            return False
        self.mode = "run_set"
        self.run_set_name = name
        self.run_set_members = get_run_set(name, self.run_sets_path)
        # 같은 프로필로 돌아오면 디스크에서 다시 읽는다.
        self.profile_open = False
        self._set_save_state("saved")
        self.view.on_opened()
        return True

    def open_item(self, kind: ItemKind, name: str) -> bool:
        if kind == "run_set" and name in list_run_set_names(self.run_sets_path):
            return self.open_run_set(name)
        if kind == "run_set":
            return self.open_profile(self.prof_name or QUICK_PROFILE_NAME)
        return self.open_profile(name or QUICK_PROFILE_NAME)

    # ── sidebar: new / copy / rename / delete ──────────────────────────

    def default_new_name(self, kind: ItemKind) -> str:
        if kind == "profile":
            return next_available_event_name(
                txt("New profile", "새 프로필"),
                set(list_profile_names(self.profiles_dir)),
            )
        return next_available_event_name(
            txt("Run set", "실행 세트"), set(list_run_set_names(self.run_sets_path))
        )

    def new_profile(self, name: str) -> None:
        name = name.strip()
        if not name:
            raise WorkspaceError(txt("Enter profile name", "프로필 이름을 입력하세요"))
        if name in list_profile_names(self.profiles_dir):
            raise self._exists_error(name)
        save_profile(
            self.profiles_dir, ProfileModel(name=name, event_list=[]), name=name
        )
        self._notify_catalog()
        self.open_profile(name)

    def new_run_set(self, name: str) -> None:
        name = name.strip()
        if not name:
            raise WorkspaceError(txt("Enter a name.", "이름을 입력하세요."))
        if name in list_run_set_names(self.run_sets_path):
            raise self._exists_error(name)
        members = (
            [self.prof_name]
            if self.mode == "profile" and self.prof_name
            else [QUICK_PROFILE_NAME]
        )
        upsert_run_set(name, members, self.run_sets_path)
        self._notify_catalog()
        self.open_run_set(name)

    def copy_profile_item(self, name: str) -> str | None:
        """복사본 이름. 지금 편집 중인 프로필이 저장되지 않으면 None."""
        if self._is_current_profile(name) and not self.flush():
            return None
        dst = next_available_event_name(
            f"{name} - {txt('Copy', '복사본')}",
            set(list_profile_names(self.profiles_dir)),
        )
        copy_profile(self.profiles_dir, name, dst)
        self._notify_catalog()
        self.view.on_status(txt("Copied to '{n}'", "'{n}'(으)로 복사했습니다", n=dst))
        return dst

    def toggle_favorite(self, name: str) -> None:
        if self._is_current_profile(name):
            self.set_favorite(not self.favorite_draft)
            return
        profile = load_profile(self.profiles_dir, name, migrate=False)
        profile.favorite = not profile.favorite
        save_profile(self.profiles_dir, profile, name=name)
        self._notify_catalog()

    def rename_profile(self, name: str, new: str) -> None:
        self._guard_quick(name)
        self.guard_running()
        new = new.strip()
        if not new or new == name:
            return
        if self._is_current_profile(name):
            if not self.flush():
                return
            if new in list_profile_names(self.profiles_dir):
                raise self._exists_error(new)
            self.name_draft = new
            self._cancel_timer()
            if not self._run_autosave(check_name=True):
                self.name_draft = self.prof_name
                raise WorkspaceError(self.save_detail)
            self.view.on_opened()
            return
        if new in list_profile_names(self.profiles_dir):
            raise self._exists_error(new)
        rename_profile_files(self.profiles_dir, name, new)
        rename_profile_in_run_sets(name, new, self.run_sets_path)
        self._notify_catalog(new)

    def delete_profile(self, name: str) -> None:
        """확인은 UI가 먼저 받는다."""
        self._guard_quick(name)
        self.guard_running()
        if self._is_current_profile(name) and not self.open_profile(QUICK_PROFILE_NAME):
            return
        delete_profile_files(self.profiles_dir, name)
        self._notify_catalog()

    def copy_run_set_item(self, name: str) -> str:
        dst = next_available_event_name(
            f"{name} - {txt('Copy', '복사본')}",
            set(list_run_set_names(self.run_sets_path)),
        )
        copy_run_set(name, dst, self.run_sets_path)
        self._notify_catalog()
        return dst

    def rename_run_set_item(self, name: str, new: str) -> None:
        self.guard_running()
        new = new.strip()
        if not new or new == name:
            return
        try:
            rename_run_set(name, new, self.run_sets_path)
        except Exception as exc:
            raise WorkspaceError(str(exc)) from exc
        self._announce_run_set_rename(name, new)
        if self.mode == "run_set" and self.run_set_name == name:
            self.run_set_name = new
            self.run_set_members = get_run_set(new, self.run_sets_path)
            self.view.on_opened()
        self._notify_catalog()

    def delete_run_set_item(self, name: str) -> None:
        """확인은 UI가 먼저 받는다."""
        self.guard_running()
        delete_run_set(name, self.run_sets_path)
        if self.mode == "run_set" and self.run_set_name == name:
            self.open_profile(self.prof_name or QUICK_PROFILE_NAME)
        self._notify_catalog()

    def _announce_run_set_rename(self, old: str, new: str) -> None:
        """실행 창이 고른 세트를 따라가도록 카탈로그 갱신 전에 알린다."""
        if self.host_run_set_renamed is not None:
            self.host_run_set_renamed(old, new)

    # ── run set editor ─────────────────────────────────────────────────

    def set_run_set_members(self, members: list[str]) -> bool:
        """비우면 거부한다. 체크를 바꾸면 바로 저장한다."""
        if not members:
            return False
        upsert_run_set(self.run_set_name, members, self.run_sets_path)
        self.run_set_members = list(members)
        self._set_save_state("saved")
        if self.host_catalog_changed is not None:
            self.host_catalog_changed(None)
        return True

    def rename_current_run_set(self, new: str) -> None:
        self.rename_run_set_item(self.run_set_name, new)

    # ── profile header / run options ───────────────────────────────────

    @property
    def name_locked(self) -> bool:
        """Quick과 실행 중에는 프로필 이름을 바꾸지 않는다."""
        return self.prof_name == QUICK_PROFILE_NAME or self.running_getter()

    def profile_name_problem(self, text: str) -> str:
        name = text.strip()
        if not name:
            return txt("Enter profile name", "프로필 이름을 입력하세요")
        if name != self.prof_name and (self.profiles_dir / f"{name}.json").exists():
            return txt("'{n}' already exists", "'{n}' 이미 존재합니다", n=name)
        return ""

    def set_profile_name(self, text: str) -> None:
        if text == self.name_draft:
            return
        self.name_draft = text
        self._changed()

    def set_favorite(self, value: bool) -> None:
        if bool(value) == self.favorite_draft:
            return
        self.favorite_draft = bool(value)
        self._changed()

    def set_runtime_toggle(self, enabled: bool, key: str | None) -> None:
        trigger = normalize_runtime_toggle_trigger(key) if key else None
        if (bool(enabled), trigger) == (
            bool(self.profile.runtime_toggle_enabled),
            self.profile.runtime_toggle_key,
        ):
            return
        self.profile.runtime_toggle_enabled = bool(enabled)
        self.profile.runtime_toggle_key = trigger
        self.view.on_events_changed(None)
        self._changed()

    # ── undo ───────────────────────────────────────────────────────────

    def push_undo(self, label: str) -> None:
        self._undo.append((label, snapshot_events(self.profile.event_list)))
        del self._undo[:-UNDO_LIMIT]

    @property
    def undo_label(self) -> str | None:
        return self._undo[-1][0] if self._undo else None

    def undo(self) -> bool:
        if self.mode != "profile" or not self._undo:
            return False
        label, snapshot = self._undo.pop()
        self.profile.event_list[:] = snapshot
        self.view.on_events_changed([])
        self._changed()
        self.view.on_status(txt("Undone: {l}", "되돌렸습니다: {l}", l=label))
        return True

    # ── list actions ───────────────────────────────────────────────────

    def counts_text(self) -> str:
        events = self.profile.event_list
        rules = sum(1 for e in events if e.execute_action)
        parts = [
            txt("Rules {n}", "규칙 {n}", n=rules),
            txt("Signals {n}", "신호 {n}", n=len(events) - rules),
        ]
        missing = sum(1 for e in events if event_needs_attention(e))
        if missing:
            parts.append(txt("No key {n}", "키 없음 {n}", n=missing))
        return " · ".join(parts)

    def names(self) -> set[str]:
        return {e.event_name or "" for e in self.profile.event_list}

    def group_names(self) -> list[str]:
        return sorted(
            {(e.group_id or "").strip() for e in self.profile.event_list} - {""}
        )

    def _append(self, events: list[EventModel], label: str) -> None:
        self.push_undo(label)
        self.profile.event_list.extend(events)
        self.view.on_events_changed(list(events))
        self._changed()

    def add_rule(self) -> EventModel:
        name = next_available_event_name(txt("Rule", "규칙"), self.names())
        event = EventModel(event_name=name, execute_action=True)
        self._append([event], txt("add rule", "규칙 추가"))
        return event

    def next_signal_name(self) -> str:
        return next_available_event_name(txt("Signal", "신호"), self.names())

    def add_signal(
        self, name: str, result: CaptureResult, fallback: str = ""
    ) -> EventModel:
        final = name.strip() or fallback or self.next_signal_name()
        if event_name_taken(self.profile.event_list, final):
            final = next_available_event_name(final, self.names())
        event = EventModel(event_name=final, execute_action=False)
        apply_capture(event, result)
        self._append([event], txt("add signal", "신호 추가"))
        return event

    def copy_events(self, events: Sequence[EventModel]) -> list[EventModel]:
        if not events:
            return []
        copies: list[EventModel] = []
        for event in events:
            name = copy_event_name(
                event.event_name or "", [*self.profile.event_list, *copies]
            )
            copies.append(clone_event(event, event_name=name))
        self._append(copies, txt("copy", "복사"))
        self.view.on_status(
            txt("Copied {n} event(s)", "이벤트 {n}개를 복사했습니다", n=len(copies))
        )
        return copies

    def delete_events(self, events: Sequence[EventModel]) -> None:
        if not events:
            return
        self.push_undo(txt("delete", "삭제"))
        doomed = {id(e) for e in events}
        self.profile.event_list[:] = [
            e for e in self.profile.event_list if id(e) not in doomed
        ]
        for event in events:
            name = event.event_name or ""
            if name and not event_name_taken(self.profile.event_list, name):
                remove_condition_references(self.profile.event_list, name)
        self.view.on_events_changed([])
        self._changed()
        self.view.on_status(
            txt(
                "Deleted {n} event(s). Undo with ⌘Z.",
                "이벤트 {n}개를 삭제했습니다. ⌘Z로 되돌립니다.",
                n=len(events),
            )
        )

    def bulk(
        self, action: BulkAction, value: object, events: Sequence[EventModel]
    ) -> None:
        if not events:
            return
        self.push_undo(txt("bulk change", "일괄 변경"))
        for event in events:
            if action == "use":
                event.use_event = bool(value)
            elif action == "toggle":
                event.runtime_toggle_member = bool(value)
            elif event.execute_action:
                event.group_id = (
                    value.strip() or None if isinstance(value, str) else None
                )
        self.view.on_events_changed(None)
        self._changed()

    def move_event(self, moved: EventModel, target: EventModel) -> bool:
        """`moved`를 `target` 자리로 옮긴다. 같은 묶음 안에서만 된다."""
        if moved is target:
            return False
        for section in build_event_sections(self.profile.event_list):
            members = [id(e) for e in section.events]
            if id(moved) in members and id(target) in members:
                index = members.index(id(target))
                return self.reorder(move_in_section(section.events, moved, index))
        return False

    def reorder(self, ordered: list[EventModel]) -> bool:
        self.push_undo(txt("reorder", "순서 변경"))
        if not write_section_order(ordered):
            self._undo.pop()
            return False
        self.view.on_events_changed(None)
        self._changed()
        return True

    def sort_by_name(self) -> None:
        self.push_undo(txt("sort by name", "이름순 정렬"))
        if not sort_sections_by_name(self.profile.event_list):
            self._undo.pop()
            self.view.on_status(txt("Already in name order.", "이미 이름순입니다."))
            return
        self.view.on_events_changed(None)
        self._changed()
        self.view.on_status(
            txt("Sorted each section by name.", "묶음마다 이름순으로 정렬했습니다.")
        )

    def rename_group(self, old: str, new: str) -> None:
        new = new.strip()
        if not new or new == old:
            return
        existing = {
            (e.group_id or "").strip().casefold() for e in self.profile.event_list
        }
        if new.casefold() != old.casefold() and new.casefold() in existing:
            raise self._exists_error(new)
        self.push_undo(txt("rename group", "그룹 이름 변경"))
        for event in self.profile.event_list:
            if (event.group_id or "").strip() == old:
                event.group_id = new
        self.view.on_events_changed(None)
        self._changed()

    def clear_group(self, group: str) -> None:
        self.push_undo(txt("ungroup", "그룹 해제"))
        for event in self.profile.event_list:
            if (event.group_id or "").strip() == group:
                event.group_id = None
        self.view.on_events_changed(None)
        self._changed()

    def copy_to_profile(self, target: str, events: Sequence[EventModel]) -> None:
        if not events:
            return
        try:
            profile = load_profile(self.profiles_dir, target, migrate=True)
            copies = [clone_event(e) for e in events]
            renamed = rename_colliding_events(
                copies, (e.event_name or "" for e in profile.event_list)
            )
            profile.event_list.extend(copies)
            save_profile(self.profiles_dir, profile, name=target)
        except Exception as exc:
            raise WorkspaceError(
                txt("Copy failed: {e}", "복사 실패: {e}", e=exc)
            ) from exc
        message = txt(
            "Copied {n} event(s) to '{p}'",
            "'{p}'에 이벤트 {n}개를 복사했습니다",
            n=len(copies),
            p=target,
        )
        if renamed:
            message += txt(" ({n} renamed)", " (이름 {n}개 변경)", n=len(renamed))
        self.view.on_status(message)

    def apply_target(self, source: EventModel) -> int:
        self.push_undo(txt("apply target", "대상 적용"))
        count = apply_target_to_same_area(self.profile.event_list, source)
        if not count:
            self._undo.pop()
            self.view.on_status(
                txt(
                    "No other events at that area.",
                    "같은 위치의 다른 이벤트가 없습니다.",
                )
            )
            return 0
        self.view.on_events_changed(None)
        self._changed()
        self.view.on_status(
            txt("Updated {n} event(s)", "이벤트 {n}개를 바꿨습니다", n=count)
        )
        return count

    # ── single event (detail panel) ────────────────────────────────────

    def _event_changed(self) -> None:
        self.view.on_events_changed(None)
        self._changed()

    def rename_event(self, event: EventModel, text: str) -> str:
        """이름을 바꾼다. 거부하면 그 이유, 받아들이면 빈 문자열."""
        if not self._owns(event):
            # 조건 참조를 바꾸면 지금 프로필이 오염되므로 무시한다.
            return ""
        new_name = normalized_event_name(text)
        old_name = event.event_name or ""
        if new_name == old_name:
            return ""
        if not new_name:
            return txt("Enter a name.", "이름을 입력하세요.")
        if event_name_taken(self.profile.event_list, new_name, ignore=event):
            return txt(
                "'{name}' already exists.",
                "'{name}' 이름이 이미 있습니다.",
                name=new_name,
            )
        event.event_name = new_name
        if old_name:
            rename_condition_references(self.profile.event_list, old_name, new_name)
        self._event_changed()
        return ""

    def set_event_kind(self, event: EventModel, is_rule: bool) -> None:
        if bool(event.execute_action) == is_rule:
            return
        event.execute_action = is_rule
        self._event_changed()

    def set_event_key(self, event: EventModel, key: str | None) -> None:
        key = key or None
        if key == event.key_to_enter:
            return
        event.key_to_enter = key
        self._event_changed()

    def set_event_group(self, event: EventModel, group: str | None) -> None:
        """그룹 변경은 실행 우선순위 묶음을 바꾸므로 되돌리기 대상이다."""
        value = (group or "").strip() or None
        if value == ((event.group_id or "").strip() or None):
            return
        self.push_undo(txt("group", "그룹"))
        event.group_id = value
        self._event_changed()

    def set_event_use(self, event: EventModel, value: bool) -> None:
        if bool(event.use_event) == value:
            return
        event.use_event = value
        self._event_changed()

    def set_event_toggle_member(self, event: EventModel, value: bool) -> None:
        if bool(event.runtime_toggle_member) == value:
            return
        event.runtime_toggle_member = value
        self._event_changed()

    def set_event_invert(self, event: EventModel, value: bool) -> None:
        if bool(event.invert_match) == value:
            return
        event.invert_match = value
        self._event_changed()

    def set_condition(self, event: EventModel, name: str, state: bool) -> None:
        if event.conditions.get(name) is state:
            return
        event.conditions[name] = state
        self._event_changed()

    def remove_condition(self, event: EventModel, name: str) -> None:
        if name not in event.conditions:
            return
        event.conditions.pop(name)
        self._event_changed()

    def condition_candidates(
        self, target: EventModel
    ) -> list[tuple[EventModel, list[str] | None]]:
        """추가할 수 있는 조건 후보와, 순환이 생기면 그 경로. 신호가 먼저다."""
        events = self.profile.event_list
        candidates = [
            e
            for e in events
            if e is not target
            and e.event_name
            and e.event_name not in target.conditions
        ]
        candidates.sort(
            key=lambda e: (bool(e.execute_action), (e.event_name or "").casefold())
        )
        return [
            (e, condition_cycle_if_added(events, target, e.event_name or ""))
            for e in candidates
        ]

    def set_event_timing(
        self, event: EventModel, duration_ms: int | None, randomization_ms: int | None
    ) -> bool:
        """규칙에 맞지 않으면 False. 그대로면 저장하지 않는다."""
        if not timing_is_valid(duration_ms, randomization_ms):
            return False
        if (duration_ms, randomization_ms) == (
            event.press_duration_ms,
            event.randomization_ms,
        ):
            return True
        event.press_duration_ms = duration_ms
        event.randomization_ms = randomization_ms
        self._event_changed()
        return True

    def set_match_mode(self, event: EventModel, mode: str) -> None:
        if mode == (event.match_mode or "pixel"):
            return
        event.match_mode = mode
        if mode == "region":
            clamp_region(event)
        self._event_changed()

    def set_region_size(self, event: EventModel, width: int, height: int) -> None:
        if event.match_mode != "region":
            return
        before = event.region_size
        event.region_size = (width, height)
        clamp_region(event)
        if event.region_size != before:
            self._event_changed()

    def _owns(self, event: EventModel) -> bool:
        """다른 프로필이나 되돌리기 전 스냅숏의 이벤트가 아니다."""
        return any(e is event for e in self.profile.event_list)

    def clear_screen(self, event: EventModel) -> None:
        """캡처본은 다시 입력할 수 없으므로 바꾸기 전에 되돌리기 지점을 남긴다."""
        if not self._owns(event):
            return
        self.push_undo(txt("screen", "화면"))
        clear_capture(event)
        self._event_changed()

    def apply_capture_to(self, event: EventModel, result: CaptureResult) -> None:
        if not self._owns(event):
            return
        self.push_undo(txt("screen", "화면"))
        apply_capture(event, result)
        self._event_changed()

    # ── saving ─────────────────────────────────────────────────────────

    def _cancel_timer(self) -> None:
        if self._cancel_autosave is not None:
            self._cancel_autosave()
            self._cancel_autosave = None

    def _changed(self, check_name: bool = False) -> None:
        if self.mode != "profile" or not self.profile_open:
            return
        self._set_save_state("saving")
        self._cancel_timer()
        self._cancel_autosave = self.scheduler(
            AUTOSAVE_DELAY_MS, lambda: self._run_autosave(check_name=check_name)
        )

    @property
    def save_pending(self) -> bool:
        return self._cancel_autosave is not None

    def _run_autosave(self, check_name: bool = False) -> bool:
        self._cancel_autosave = None
        try:
            self._save(check_name=check_name)
        except Exception as exc:
            self._set_save_state("error", str(exc))
            return False
        self._set_save_state("saved")
        return True

    def flush(self) -> bool:
        """예약된 저장을 지금 한다. 실패하면 이유를 보이고 False."""
        if self.mode != "profile" or not self.profile_open:
            return True
        self._cancel_timer()
        self.view.commit_pending_edits()
        self._cancel_timer()
        if self._run_autosave(check_name=True):
            return True
        self.view.show_error(self.save_detail)
        return False

    def _save(self, check_name: bool = False) -> None:
        new_name = self.name_draft.strip()
        if check_name and not new_name:
            raise WorkspaceError(txt("Enter profile name", "프로필 이름을 입력하세요"))
        if not new_name:
            new_name = self.prof_name
        duplicates = find_duplicate_event_names(self.profile.event_list)
        if duplicates:
            raise WorkspaceError(
                txt(
                    "Duplicate event names are not allowed: {names}",
                    "중복 이벤트 이름은 허용되지 않습니다: {names}",
                    names=", ".join(duplicates),
                )
            )
        errors = collect_runtime_toggle_validation_errors(
            self.profile, list(self.profile.event_list), settings=self.settings_getter()
        )
        if errors:
            raise WorkspaceError(errors[0])
        renamed = new_name != self.prof_name
        if renamed:
            self._guard_quick(self.prof_name)
            if self.running_getter():
                raise WorkspaceError(
                    txt(
                        "Stop the run before renaming.",
                        "실행 중에는 이름을 바꿀 수 없습니다.",
                    )
                )
            if (self.profiles_dir / f"{new_name}.json").exists():
                raise self._exists_error(new_name)
            rename_profile_files(self.profiles_dir, self.prof_name, new_name)
            rename_profile_in_run_sets(self.prof_name, new_name, self.run_sets_path)
            self.prof_name = new_name
            self.name_draft = new_name
        favorite_changed = self.favorite_draft != bool(self.profile.favorite)
        self.profile.favorite = self.favorite_draft
        self.profile.name = self.prof_name
        fingerprint = profile_fingerprint(
            self.profile, self.prof_name, self.profile.favorite
        )
        if renamed or fingerprint != self._last_saved_fingerprint:
            save_profile(self.profiles_dir, self.profile, name=self.prof_name)
            self._last_saved_fingerprint = fingerprint
            if renamed or favorite_changed:
                self._notify_catalog(self.prof_name)
            elif self.host_catalog_changed is not None:
                self.host_catalog_changed(None)

    def _set_save_state(self, state: SaveState, detail: str = "") -> None:
        self.save_state = state
        self.save_detail = detail
        if state == "saved":
            self.saved_at = time.strftime("%H:%M:%S")
        self.view.on_save_state_changed()

    def close(self) -> bool:
        """저장하지 못하면 False(창을 닫지 않는다)."""
        if not self.flush():
            return False
        self._cancel_timer()
        return True
