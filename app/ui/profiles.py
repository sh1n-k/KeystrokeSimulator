from __future__ import annotations

import os
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Any, Literal, Protocol, TypeAlias, TypedDict, cast

from PIL import Image

from app.utils.i18n import txt
from app.ui.event_importer import EventImporter
from app.ui.profile_event_list import EventListFrame, EventRow
from app.ui.profile_settings import ProfileFrame, RuntimeToggleSettingsFrame
from app.core.models import ProfileModel, EventModel
from app.core.validation import find_duplicate_event_names
from app.storage.profile_storage import load_profile, rename_profile_files, save_profile
from app.utils.window_state import StateUtils, WindowUtils
from app.utils.runtime_toggle import (
    collect_runtime_toggle_validation_errors,
    runtime_toggle_member_count,
)
from app.ui import theme

UI_PAD_XS = theme.SPACE_1
UI_PAD_SM = theme.SPACE_1
UI_PAD_MD = theme.SPACE_2
PROFILE_WINDOW_DEFAULT_GEOMETRY = "1280x720"
PROFILE_WINDOW_MIN_SIZE = (1120, 680)
EVENT_NAME_COL_WIDTH = 34
EVENT_GROUP_COL_WIDTH = 10
EVENT_KEY_COL_WIDTH = 8
EVENT_COND_COL_WIDTH = 6
EVENT_EXTRA_COL_WIDTH = 7
EVENT_ACTIONS_COL_WIDTH = 18

BADGE_BG_INFO = theme.STATUS_INFO_BG
BADGE_FG_INFO = theme.STATUS_INFO_FG
BADGE_BG_OK = theme.STATUS_READY_BG
BADGE_FG_OK = theme.STATUS_READY_FG
BADGE_BG_WARN = theme.STATUS_WARN_BG
BADGE_FG_WARN = theme.STATUS_WARN_FG
BADGE_BG_ERR = theme.STATUS_ERROR_BG
BADGE_FG_ERR = theme.STATUS_ERROR_FG

ImageIdentity: TypeAlias = tuple[int, tuple[int, int], str] | None
EventFingerprint: TypeAlias = tuple[object, ...]
ProfileFingerprint: TypeAlias = tuple[object, ...]
ClickAction: TypeAlias = Literal["open", "copy", "remove"]
SortKey: TypeAlias = Callable[[EventModel], tuple[object, ...]]
KeySortOrder: TypeAlias = tuple[int, int, str]


class SaveCallback(Protocol):
    def __call__(self, check_name: bool = False) -> object: ...


class EventRowCallbacks(TypedDict, total=False):
    open: Callable[[int, EventModel | None], object]
    copy: Callable[[EventModel | None], object]
    remove: Callable[["EventRow", int], object]
    menu: Callable[[tk.Event[tk.Misc], int], object]
    group_select: Callable[[int, EventModel], object]
    save: Callable[[], object]
    select: Callable[[EventModel], object]


class AccordionSection(TypedDict):
    wrapper: tk.Frame
    header: tk.Frame
    glyph: tk.Label
    body: tk.Frame
    expanded: bool


def _autosave_perf_enabled() -> bool:
    return os.getenv("KEYSIM_PROFILE_PERF") == "1"


def _image_identity(img: Image.Image | None) -> ImageIdentity:
    if img is None:
        return None
    return (id(img), img.size, img.mode)


def _event_fingerprint(evt: EventModel) -> EventFingerprint:
    return (
        getattr(evt, "event_name", None),
        bool(getattr(evt, "use_event", True)),
        getattr(evt, "capture_size", None),
        getattr(evt, "latest_position", None),
        getattr(evt, "clicked_position", None),
        getattr(evt, "ref_pixel_value", None),
        getattr(evt, "key_to_enter", None),
        getattr(evt, "press_duration_ms", None),
        getattr(evt, "randomization_ms", None),
        getattr(evt, "match_mode", "pixel"),
        bool(getattr(evt, "invert_match", False)),
        getattr(evt, "region_size", None),
        bool(getattr(evt, "execute_action", True)),
        getattr(evt, "group_id", None),
        int(getattr(evt, "priority", 0) or 0),
        tuple(sorted(dict(getattr(evt, "conditions", {}) or {}).items())),
        bool(getattr(evt, "runtime_toggle_member", False)),
        _image_identity(getattr(evt, "held_screenshot", None)),
    )


def _profile_fingerprint(
    profile: ProfileModel, profile_name: str, favorite: bool
) -> ProfileFingerprint:
    return (
        profile_name,
        bool(favorite),
        bool(getattr(profile, "runtime_toggle_enabled", False)),
        getattr(profile, "runtime_toggle_key", None),
        tuple(_event_fingerprint(evt) for evt in (profile.event_list or [])),
    )



class KeystrokeProfiles:
    def __init__(
        self,
        main_win: tk.Misc,
        prof_name: str,
        save_cb: Callable[[str], object] | None = None,
        *,
        profiles_dir: Path,
    ) -> None:
        self.main_win, self.prof_name, self.ext_save_cb = main_win, prof_name, save_cb
        self.prof_dir = profiles_dir
        self._autosave_after_id: str | None = None
        self._last_saved_fingerprint: ProfileFingerprint | None = None
        self._overview_status_text = ""
        self._inspector_event: EventModel | None = None

        self.win = tk.Toplevel(main_win)
        self.win.title(f"{txt('Profile Manager', '프로필 관리자')} - {self.prof_name}")
        self.win.geometry(PROFILE_WINDOW_DEFAULT_GEOMETRY)
        self.win.minsize(*PROFILE_WINDOW_MIN_SIZE)
        cast(Any, self.win).transient(main_win)
        self.win.grab_set()
        self.win.bind("<Escape>", self._close)
        self.win.protocol("WM_DELETE_WINDOW", self._close)
        # Workstation tone: force light palette even in dark-mode hosts.
        try:
            self.win.configure(bg=theme.SURFACE_PAPER)
        except tk.TclError:
            pass
        theme.install_styles(self.win)

        self.profile = self._load()
        self.p_frame = ProfileFrame(
            self.win,
            prof_name,
            self.profile.favorite,
            on_change=self._on_changed,
            profiles_dir=self.prof_dir,
        )
        self.p_frame.pack(fill="x", padx=UI_PAD_MD, pady=(UI_PAD_MD, UI_PAD_SM))
        self.runtime_toggle_frame = RuntimeToggleSettingsFrame(
            self.win,
            self.profile,
            on_change=self._on_changed,
        )
        self.runtime_toggle_frame.pack(fill="x", padx=UI_PAD_MD, pady=(0, UI_PAD_SM))

        tk.Frame(self.win, bg=theme.SURFACE_DIVIDER, height=1).pack(
            side="bottom", fill="x"
        )
        f_status = tk.Frame(self.win, bg=theme.SURFACE_PANEL)
        f_status.pack(
            side="bottom", fill="x", padx=UI_PAD_MD, pady=(UI_PAD_SM, UI_PAD_MD)
        )
        tk.Label(
            f_status,
            text=txt("Save:", "저장:"),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
        ).pack(side=tk.LEFT)
        self.lbl_save_badge = tk.Label(
            f_status,
            text="",
            relief="flat",
            borderwidth=0,
            padx=theme.SPACE_2,
            pady=theme.SPACE_1,
            font=theme.fonts()["caption"],
            highlightthickness=1,
            highlightbackground=theme.SURFACE_DIVIDER,
        )
        self.lbl_save_badge.pack(side=tk.LEFT, padx=UI_PAD_SM)
        self.lbl_status = tk.Label(
            f_status,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
        )
        self.lbl_status.pack(side=tk.LEFT, padx=UI_PAD_MD)

        f_summary = tk.Frame(f_status, bg=theme.SURFACE_PANEL)
        f_summary.pack(side=tk.RIGHT)
        ttk.Button(f_summary, text=txt("Close", "닫기"), command=self._close).pack(
            side=tk.RIGHT, padx=(UI_PAD_SM, 0)
        )
        self.lbl_events_badge = self._make_chip(f_summary)
        self.lbl_events_badge.pack(side=tk.LEFT, padx=(0, UI_PAD_SM))
        self.lbl_groups_badge = self._make_chip(f_summary)
        self.lbl_groups_badge.pack(side=tk.LEFT, padx=(0, UI_PAD_SM))
        self.lbl_attention_badge = self._make_chip(f_summary)
        self.lbl_attention_badge.pack(side=tk.LEFT)

        # Workspace: left NavRail + right event list (+ inspector later).
        self.workspace = ttk.Frame(self.win)
        self.workspace.pack(
            fill="both", expand=True, padx=UI_PAD_MD, pady=(0, UI_PAD_SM)
        )
        self.nav_rail = self._build_nav_rail(self.workspace)
        self.nav_rail.pack(side=tk.LEFT, fill="y", padx=(0, UI_PAD_MD))

        self.e_frame = EventListFrame(
            self.workspace,
            self.profile,
            self._on_changed,
            name_getter=lambda: self.prof_name,
            status_cb=self._show_temp_status,
            select_cb=self._set_inspector_event,
            profiles_dir=self.prof_dir,
        )
        self.e_frame.pack(side=tk.LEFT, fill="both", expand=True)

        # Right-side Inspector — read-only preview / profile summary.
        self.inspector_panel = self._build_inspector(self.workspace)
        self.inspector_panel.pack(side=tk.LEFT, fill="y", padx=(UI_PAD_MD, 0))

        self._load_pos()
        self._refresh_profile_overview()
        self._last_saved_fingerprint = _profile_fingerprint(
            self.profile, self.prof_name, self.profile.favorite
        )
        self._set_save_status("saved")

    @staticmethod
    def _make_chip(parent: tk.Misc) -> tk.Label:
        return tk.Label(
            parent,
            text="",
            relief="flat",
            borderwidth=0,
            padx=theme.SPACE_2,
            pady=theme.SPACE_1,
            font=theme.fonts()["caption"],
            highlightthickness=1,
            highlightbackground=theme.SURFACE_DIVIDER,
        )

    def _build_nav_rail(self, parent: tk.Misc) -> tk.Frame:
        """좌측 NavRail: FILTER / GROUPS / ACTIONS.

        Filter checkboxes are disabled placeholders in this milestone, matching
        the SOT's visual slot without adding filter semantics. ACTIONS reuse the
        existing EventListFrame command callbacks so behaviour stays intact.
        """
        f = theme.fonts()
        rail = tk.Frame(
            parent,
            bg=theme.SURFACE_PANEL,
            padx=theme.SPACE_2,
            pady=theme.SPACE_3,
            width=180,
        )
        rail.pack_propagate(False)

        def _section_label(text: str) -> None:
            tk.Label(
                rail,
                text=text,
                bg=theme.SURFACE_PANEL,
                fg=theme.INK_MUTED,
                font=f["caption"],
                anchor="w",
            ).pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_1))

        # --- FILTER (visual placeholder) -------------------------------
        _section_label(txt("FILTER", "필터"))
        self.nav_filter_vars: dict[str, tk.BooleanVar] = {}
        for key, en, ko in [
            ("active", "Active", "활성"),
            ("grouped", "Grouped", "그룹화"),
            ("cond", "Condition only", "조건 전용"),
        ]:
            var = tk.BooleanVar(value=False)
            self.nav_filter_vars[key] = var
            cb = ttk.Checkbutton(
                rail,
                text=txt(en, ko),
                variable=var,
                state="disabled",
            )
            cb.pack(anchor="w")

        # --- GROUPS (read-only) ----------------------------------------
        _section_label(txt("GROUPS", "그룹"))
        self.nav_groups_frame = tk.Frame(rail, bg=theme.SURFACE_PANEL)
        self.nav_groups_frame.pack(fill="x")

        # --- ACTIONS ---------------------------------------------------
        _section_label(txt("ACTIONS", "액션"))
        for en, ko, callback in [
            ("＋ Add", "＋ 추가", self._nav_action_add),
            ("Import", "가져오기", self._nav_action_import),
            ("Sort", "정렬", self._nav_action_sort),
            ("Graph", "그래프", self._nav_action_graph),
        ]:
            btn = ttk.Button(
                rail,
                text=txt(en, ko),
                command=callback,
            )
            btn.pack(fill="x", pady=(0, theme.SPACE_1))

        return rail

    def _refresh_nav_groups(self) -> None:
        if not getattr(self, "nav_groups_frame", None):
            return
        for child in self.nav_groups_frame.winfo_children():
            child.destroy()
        events = list(self.profile.event_list or [])
        groups = sorted({e.group_id for e in events if e.group_id})
        f = theme.fonts()
        if not groups:
            tk.Label(
                self.nav_groups_frame,
                text=txt("(none)", "(없음)"),
                bg=theme.SURFACE_PANEL,
                fg=theme.INK_MUTED,
                font=f["caption"],
                anchor="w",
            ).pack(fill="x")
            return
        for grp in groups:
            tk.Label(
                self.nav_groups_frame,
                text=f"▣ {grp}",
                bg=theme.SURFACE_PANEL,
                fg=theme.INK_PRIMARY,
                font=f["caption"],
                anchor="w",
            ).pack(fill="x")

    # --- NavRail action forwards (preserve existing call sites) -------
    def _nav_action_add(self) -> None:
        e_frame = getattr(self, "e_frame", None)
        if e_frame:
            add_event = cast(Callable[[], None], e_frame._add_event)
            add_event()

    def _nav_action_import(self) -> None:
        # Mirror the call site already used by EventListFrame's import button.
        e_frame = getattr(self, "e_frame", None)
        if e_frame:
            import_events = cast(
                Callable[[list[EventModel]], None], e_frame._import
            )
            EventImporter(self.win, import_events, profiles_dir=self.prof_dir)

    def _nav_action_sort(self) -> None:
        e_frame = getattr(self, "e_frame", None)
        if e_frame:
            sort_events = cast(
                Callable[[], None], e_frame._sort_events_by_name
            )
            sort_events()

    def _nav_action_graph(self) -> None:
        e_frame = getattr(self, "e_frame", None)
        if e_frame:
            open_graph = cast(Callable[[], None], e_frame._open_graph)
            open_graph()

    # ------------------------------------------------------------------
    # Right-side Inspector
    # ------------------------------------------------------------------
    def _build_inspector(self, parent: tk.Misc) -> tk.Frame:
        f = theme.fonts()
        panel = tk.Frame(
            parent,
            bg=theme.SURFACE_PANEL,
            padx=theme.SPACE_3,
            pady=theme.SPACE_3,
            width=240,
        )
        panel.pack_propagate(False)
        tk.Label(
            panel,
            text=txt("DETAILS", "상세"),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
        ).pack(fill="x", pady=(0, theme.SPACE_2))

        # Accordion sections — each header toggles its body via _toggle_section.
        self._inspector_sections: dict[str, AccordionSection] = {}

        summary_body = self._make_accordion_section(
            panel, "summary", txt("Summary", "요약"), expanded=True
        )
        self.lbl_inspector_title = tk.Label(
            summary_body,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_PRIMARY,
            font=f["body_bold"],
            anchor="w",
            wraplength=200,
            justify="left",
        )
        self.lbl_inspector_title.pack(fill="x", pady=(0, theme.SPACE_1))
        self.lbl_inspector_meta = tk.Label(
            summary_body,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_SECONDARY,
            font=f["caption"],
            anchor="w",
            justify="left",
            wraplength=200,
        )
        self.lbl_inspector_meta.pack(fill="x")

        hint_body = self._make_accordion_section(
            panel, "activity", txt("Activity", "사용"), expanded=True
        )
        self.lbl_inspector_hint = tk.Label(
            hint_body,
            text=txt(
                "Use the rail on the left to review groups or run an action.\n\nClick a row's Edit button to open the full editor.",
                "왼쪽 네비로 그룹을 확인하거나 액션을 실행하고, 각 행의 편집 버튼으로 전체 편집기를 엽니다.",
            ),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
            justify="left",
            wraplength=200,
        )
        self.lbl_inspector_hint.pack(fill="x")
        return panel

    def _make_accordion_section(
        self, parent: tk.Misc, key: str, title: str, expanded: bool = True
    ) -> tk.Frame:
        """Build an expandable/collapsible Inspector section. Returns the
        body frame so callers can mount their content inside it."""
        f = theme.fonts()
        wrapper = tk.Frame(parent, bg=theme.SURFACE_PANEL)
        wrapper.pack(fill="x", pady=(0, theme.SPACE_2))

        header = tk.Frame(wrapper, bg=theme.SURFACE_PANEL, cursor="hand2")
        header.pack(fill="x")
        glyph = tk.Label(
            header,
            text="▾" if expanded else "▸",
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
        )
        glyph.pack(side="left", padx=(0, theme.SPACE_1))
        label = tk.Label(
            header,
            text=title,
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
        )
        label.pack(side="left", fill="x", expand=True)

        body = tk.Frame(wrapper, bg=theme.SURFACE_PANEL)
        if expanded:
            body.pack(fill="x", pady=(theme.SPACE_1, 0))

        section: AccordionSection = {
            "wrapper": wrapper,
            "header": header,
            "glyph": glyph,
            "body": body,
            "expanded": expanded,
        }
        self._inspector_sections[key] = section

        def _toggle(
            _e: tk.Event[tk.Misc] | None = None, _key: str = key
        ) -> None:
            self._toggle_accordion_section(_key)

        header.bind("<Button-1>", _toggle)
        glyph.bind("<Button-1>", _toggle)
        label.bind("<Button-1>", _toggle)
        return body

    def _toggle_accordion_section(self, key: str) -> None:
        section = self._inspector_sections.get(key)
        if not section:
            return
        section["expanded"] = not section["expanded"]
        if section["expanded"]:
            section["body"].pack(fill="x", pady=(theme.SPACE_1, 0))
            section["glyph"].config(text="▾")
        else:
            section["body"].pack_forget()
            section["glyph"].config(text="▸")

    def _refresh_inspector(self) -> None:
        if not hasattr(self, "lbl_inspector_title"):
            return
        events = list(self.profile.event_list or [])
        event_count = len(events)
        group_count = len({e.group_id for e in events if e.group_id})
        runtime_members = runtime_toggle_member_count(events)
        selected = getattr(self, "_inspector_event", None)
        selected = selected if any(evt is selected for evt in events) else None
        if selected is None:
            self._inspector_event = None
        else:
            key = (selected.key_to_enter or "").strip()
            group = selected.group_id or txt("No Group", "그룹 없음")
            cond_count = len(getattr(selected, "conditions", {}) or {})
            mode = txt("Condition only", "조건 전용") if not getattr(
                selected, "execute_action", True
            ) else txt("Action", "실행")
            self.lbl_inspector_title.config(text=selected.event_name or txt("(Unnamed)", "(이름 없음)"))
            self.lbl_inspector_meta.config(
                text="\n".join(
                    [
                        txt(
                            f"{mode} · Group {group}",
                            f"{mode} · 그룹 {group}",
                        ),
                        txt(
                            f"Key: {key if key else 'None'} · Priority {selected.priority}",
                            f"키: {key if key else '없음'} · 우선순위 {selected.priority}",
                        ),
                        txt(
                            f"Conditions: {cond_count}",
                            f"조건: {cond_count}개",
                        ),
                    ]
                )
            )
            return

        favorite_glyph = "★ " if self.profile.favorite else ""
        self.lbl_inspector_title.config(text=f"{favorite_glyph}{self.prof_name}")
        meta_lines = [
            txt(
                f"{event_count} events · {group_count} groups",
                f"이벤트 {event_count}개 · 그룹 {group_count}개",
            ),
        ]
        if runtime_members:
            meta_lines.append(
                txt(
                    f"Runtime extra: {runtime_members}",
                    f"실행 중 추가: {runtime_members}개",
                )
            )
        self.lbl_inspector_meta.config(text="\n".join(meta_lines))

    def _set_inspector_event(self, event: EventModel) -> None:
        self._inspector_event = event
        self._refresh_inspector()

    def _load(self) -> ProfileModel:
        try:
            return load_profile(self.prof_dir, self.prof_name, migrate=True)
        except Exception:
            return ProfileModel(name=self.prof_name, event_list=[], favorite=False)

    def _ensure_unique_event_names(self) -> None:
        duplicates = find_duplicate_event_names(self.profile.event_list or [])
        if duplicates:
            dup_text = ", ".join(duplicates)
            raise ValueError(
                txt(
                    "Duplicate event names are not allowed: {names}",
                    "중복 이벤트 이름은 허용되지 않습니다: {names}",
                    names=dup_text,
                )
            )

    def _save(self, check_name: bool = True, reload: bool = True) -> bool:
        started = time.perf_counter()
        if not self.profile.event_list:
            raise ValueError(
                txt(
                    "At least one event must be set",
                    "최소 1개 이상의 이벤트가 필요합니다",
                )
            )
        new_name, is_fav = self.p_frame.get_data()
        new_name = (new_name or "").strip()

        if check_name and not new_name:
            raise ValueError(txt("Enter profile name", "프로필 이름을 입력하세요"))
        if not new_name:
            # Auto-save 중 임시 공백 입력은 기존 파일명을 유지한다.
            new_name = self.prof_name
        self.profile.favorite = is_fav
        self.profile.name = new_name
        runtime_toggle_frame = getattr(self, "runtime_toggle_frame", None)
        if runtime_toggle_frame is not None:
            runtime_toggle_frame.apply_to_profile(self.profile)

        old_name = self.prof_name
        renamed = False
        if new_name != self.prof_name:
            if (self.prof_dir / f"{new_name}.json").exists():
                raise ValueError(
                    txt(
                        f"'{new_name}' already exists.",
                        f"'{new_name}' 이미 존재합니다.",
                    )
                )

            if (self.prof_dir / f"{self.prof_name}.json").exists():
                rename_profile_files(self.prof_dir, self.prof_name, new_name)
            self.prof_name = new_name
            renamed = True

        if reload:
            self.e_frame.update_events()
            self.e_frame.save_names()
        self._ensure_unique_event_names()
        validation_errors = collect_runtime_toggle_validation_errors(
            self.profile,
            list(self.profile.event_list or []),
            settings=getattr(getattr(self, "main_win", None), "settings", None),
        )
        if validation_errors:
            raise ValueError(validation_errors[0])
        next_fingerprint = _profile_fingerprint(self.profile, new_name, is_fav)
        if renamed or next_fingerprint != self._last_saved_fingerprint:
            save_profile(self.prof_dir, self.profile, name=self.prof_name)
            self._last_saved_fingerprint = _profile_fingerprint(
                self.profile, self.prof_name, self.profile.favorite
            )
        if reload:
            self.e_frame.update_events()
        if renamed and self.ext_save_cb:
            self.ext_save_cb(self.prof_name)
        if _autosave_perf_enabled():
            print(
                f"[perf] profile_save[{self.prof_name}]: {(time.perf_counter() - started) * 1000.0:.3f}ms"
            )
        return old_name != self.prof_name

    def _show_temp_status(self, text: str, duration_ms: int = 2000) -> None:
        self.lbl_status.config(text=text, foreground=theme.STATUS_READY_FG)
        self.win.after(
            duration_ms,
            lambda: self.lbl_status.config(text="", foreground=theme.INK_MUTED),
        )

    def _set_save_badge_bg(self, bg: str) -> None:
        badge = getattr(self, "lbl_save_badge", None)
        if badge is None:
            return
        try:
            if hasattr(badge, "winfo_exists") and not badge.winfo_exists():
                return
            badge.config(bg=bg)
        except (tk.TclError, AttributeError):
            return

    def _refresh_profile_overview(self) -> None:
        self._refresh_nav_groups()
        self._refresh_inspector()
        events = list(self.profile.event_list or [])
        event_count = len(events)
        group_count = len({e.group_id for e in events if e.group_id})
        condition_only_count = sum(
            1 for e in events if not getattr(e, "execute_action", True)
        )
        missing_key_count = sum(
            1
            for e in events
            if getattr(e, "execute_action", True) and not (e.key_to_enter or "").strip()
        )
        toggle_member_count = runtime_toggle_member_count(events)
        validation_errors = collect_runtime_toggle_validation_errors(
            self.profile,
            events,
            settings=getattr(getattr(self, "main_win", None), "settings", None),
        )
        warning_count = missing_key_count + len(validation_errors)

        self.lbl_events_badge.config(
            text=txt(f"⚙️ Events {event_count}", f"⚙️ 이벤트 {event_count}"),
            bg=BADGE_BG_INFO,
            fg=BADGE_FG_INFO,
        )
        self.lbl_groups_badge.config(
            text=txt(f"🧩 Groups {group_count}", f"🧩 그룹 {group_count}"),
            bg=theme.STATUS_READY_BG,
            fg=theme.STATUS_READY_FG,
        )
        if warning_count:
            warning_parts: list[str] = []
            if missing_key_count:
                warning_parts.append(
                    txt(
                        "missing key: {count}",
                        "입력 키 없음: {count}",
                        count=missing_key_count,
                    )
                )
            warning_parts.extend(validation_errors)
            self._overview_status_text = txt(
                "Review: {details}",
                "확인 필요: {details}",
                details=", ".join(warning_parts),
            )
            self.lbl_attention_badge.config(
                text=txt(f"⚠ Attention {warning_count}", f"⚠ 주의 {warning_count}"),
                bg=BADGE_BG_WARN,
                fg=BADGE_FG_WARN,
            )
            return
        if condition_only_count:
            if toggle_member_count:
                self._overview_status_text = txt(
                    "Condition-only events: {cond_count}. Runtime extra events: {toggle_count}.",
                    "조건 전용 이벤트: {cond_count}개. 실행 중 추가 이벤트: {toggle_count}개.",
                    cond_count=condition_only_count,
                    toggle_count=toggle_member_count,
                )
            else:
                self._overview_status_text = txt(
                    "Condition-only events are configured: {count}.",
                    "조건 전용 이벤트가 {count}개 설정되어 있습니다.",
                    count=condition_only_count,
                )
        elif toggle_member_count:
            self._overview_status_text = txt(
                "Runtime extra events are configured: {count}.",
                "실행 중 추가 이벤트가 {count}개 설정되어 있습니다.",
                count=toggle_member_count,
            )
        else:
            self._overview_status_text = txt(
                "All events are ready for autosave and run checks.",
                "모든 이벤트가 자동저장 및 실행 점검 기준을 통과했습니다.",
            )
        self.lbl_attention_badge.config(
            text=txt("✅ Attention 0", "✅ 주의 0"),
            bg=BADGE_BG_OK,
            fg=BADGE_FG_OK,
        )

    def _set_save_status(self, status: str, detail: str = "") -> None:
        self._refresh_profile_overview()
        if status == "saving":
            self.lbl_save_badge.config(
                text=txt("💾 Saving...", "💾 저장 중..."),
                bg=BADGE_BG_WARN,
                fg=BADGE_FG_WARN,
            )
            if not detail:
                self.lbl_status.config(text="", foreground=theme.INK_MUTED)
            return
        if status == "saved":
            saved_at = time.strftime("%H:%M:%S")
            self.lbl_save_badge.config(
                text=txt(f"✅ Saved {saved_at}", f"✅ 저장됨 {saved_at}"),
                bg=BADGE_BG_OK,
                fg=BADGE_FG_OK,
            )
            # Soft flash to communicate the "just saved" moment. Guarded so
            # headless tests that stub the class without a window don't crash.
            win = getattr(self, "win", None)
            if win is not None:
                win.after(
                    150,
                    lambda: self._set_save_badge_bg(theme.SIGNAL_TINT),
                )
                win.after(
                    900,
                    lambda: self._set_save_badge_bg(BADGE_BG_OK),
                )
            self.lbl_status.config(
                text=detail if detail else self._overview_status_text,
                foreground=theme.INK_MUTED,
            )
            return
        if status == "error":
            self.lbl_save_badge.config(
                text=txt("⚠ Save failed", "⚠ 저장 실패"),
                bg=BADGE_BG_ERR,
                fg=BADGE_FG_ERR,
            )
            self.lbl_status.config(
                text=detail if detail else "",
                foreground=theme.STATUS_ERROR_FG,
            )

    def _set_dirty(self, dirty: bool) -> None:
        star = "* " if dirty else ""
        self.win.title(
            f"{star}{txt('Profile Manager', '프로필 관리자')} - {self.prof_name}"
        )

    def _run_autosave(self, check_name: bool = False) -> None:
        self._autosave_after_id = None
        started = time.perf_counter()
        try:
            self.e_frame.save_names()
            self._save(check_name=check_name, reload=False)
            self._set_dirty(False)
            self._set_save_status("saved")
        except Exception as e:
            self._set_dirty(True)
            self._set_save_status("error", str(e))
        finally:
            if _autosave_perf_enabled():
                print(
                    f"[perf] autosave[{self.prof_name}]: {(time.perf_counter() - started) * 1000.0:.3f}ms"
                )

    def _schedule_autosave(
        self, delay_ms: int = 250, check_name: bool = False
    ) -> None:
        if self._autosave_after_id:
            self.win.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
        self._autosave_after_id = self.win.after(
            delay_ms, lambda: self._run_autosave(check_name=check_name)
        )

    def _on_changed(self, check_name: bool = False) -> None:
        self._set_dirty(True)
        self._set_save_status("saving")
        self._schedule_autosave(check_name=check_name)

    def _flush_autosave(self, check_name: bool = True) -> bool:
        if self._autosave_after_id:
            self.win.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
        try:
            self.e_frame.save_names()
            self._save(check_name=check_name, reload=False)
            self._set_dirty(False)
            self._set_save_status("saved")
            return True
        except Exception as e:
            self._set_dirty(True)
            self._set_save_status("error", str(e))
            messagebox.showerror(txt("Error", "오류"), str(e), parent=self.win)
            return False

    def _close(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if not self._flush_autosave(check_name=True):
            return
        StateUtils.save_main_app_state(
            prof_pos=f"{self.win.winfo_x()}/{self.win.winfo_y()}"
        )
        if self.ext_save_cb:
            self.ext_save_cb(self.prof_name)
        self.win.destroy()

    def _load_pos(self) -> None:
        pos = StateUtils.parse_slash_int_pair(
            StateUtils.load_main_app_state().get("prof_pos")
        )
        if pos is not None:
            self.win.geometry(f"+{pos[0]}+{pos[1]}")
        else:
            WindowUtils.center_window(self.win)
