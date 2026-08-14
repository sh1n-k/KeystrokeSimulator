from __future__ import annotations

import os
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Any, Literal, Protocol, TypeAlias, TypedDict, cast

from dataclasses import replace as dataclass_replace

from PIL import Image, ImageTk

from app.utils.i18n import dual_text_width, txt
from app.ui.profile_event_list import EventListFrame, EventRow, ToolTip
from app.ui.profile_groups import GroupSelector
from app.ui.profile_settings import ProfileFrame, RuntimeToggleSettingsFrame
from app.core.models import ProfileModel, EventModel
from app.core.profile_events import EventFilterState, event_needs_attention
from app.core.validation import find_duplicate_event_names
from app.utils.keys import KeyUtils
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
    title_label: tk.Label
    body: tk.Frame
    expanded: bool


def _autosave_perf_enabled() -> bool:
    return os.getenv("KEYSIM_PROFILE_PERF") == "1"


def _image_identity(img: Image.Image | None) -> ImageIdentity:
    if img is None:
        return None
    return (id(img), img.size, img.mode)


# EventModel fields that participate in profile dirty/autosave detection.
# When adding a field to EventModel, include it here and in _event_fingerprint.
EVENT_DIRTY_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "event_name",
        "use_event",
        "capture_size",
        "latest_position",
        "clicked_position",
        "ref_pixel_value",
        "key_to_enter",
        "press_duration_ms",
        "randomization_ms",
        "match_mode",
        "invert_match",
        "region_size",
        "execute_action",
        "group_id",
        "priority",
        "conditions",
        "runtime_toggle_member",
        "held_screenshot",
    }
)


def event_dirty_field_names() -> frozenset[str]:
    """Return EventModel field names covered by dirty/fingerprint detection."""
    return EVENT_DIRTY_FIELD_NAMES


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
        self._status_action_after_id: str | None = None
        self._inspector_thumb: ImageTk.PhotoImage | None = None
        self._inspector_syncing = False
        self._inspector_synced_id: int | None = None
        self.filter_state = EventFilterState()

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
        # Undo affordance for destructive actions; hidden until one happens.
        self.btn_status_action = ttk.Button(f_status, text="", width=10)

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
        # The badge is a way in to the events it counts, not just a number.
        self.lbl_attention_badge.config(cursor="hand2")
        self.lbl_attention_badge.bind("<Button-1>", self._on_attention_badge_click)
        self._tip_attention_badge = ToolTip(self.lbl_attention_badge)

        # Workspace: left NavRail + right event list (+ inspector later).
        self.workspace = ttk.Frame(self.win)
        self.workspace.pack(
            fill="both", expand=True, padx=UI_PAD_MD, pady=(0, UI_PAD_SM)
        )
        self.nav_rail = self._build_nav_rail(self.workspace)
        self.nav_rail.pack(side=tk.LEFT, fill="y", padx=(0, UI_PAD_MD))

        # Both fixed-width panels claim their space before the list, which
        # expands. Packing the inspector last would let the list squeeze it
        # off the right edge of the window.
        self.inspector_panel = self._build_inspector(self.workspace)
        self.inspector_panel.pack(side=tk.RIGHT, fill="y", padx=(UI_PAD_MD, 0))

        self.e_frame = EventListFrame(
            self.workspace,
            self.profile,
            self._on_changed,
            name_getter=lambda: self.prof_name,
            status_cb=self._show_temp_status,
            select_cb=self._set_inspector_event,
            profiles_dir=self.prof_dir,
            host_window=self.win,
            filter_change_cb=self._on_filter_changed,
        )
        self.e_frame.pack(side=tk.LEFT, fill="both", expand=True)

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
        """좌측 NavRail: 이벤트 목록을 좁히는 필터 전용 패널.

        Actions used to be duplicated here and in the list toolbar; the toolbar
        is now the single home for them, so the rail only filters.
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

        # --- FILTER ----------------------------------------------------
        _section_label(txt("FILTER", "필터"))
        self.nav_filter_vars: dict[str, tk.BooleanVar] = {}
        for key, en, ko, tip_en, tip_ko in [
            (
                "active",
                "In use",
                "사용 중",
                "Show only events whose Use box is checked.",
                "사용 체크된 이벤트만 표시합니다.",
            ),
            (
                "grouped",
                "Grouped",
                "그룹 있음",
                "Show only events that belong to a group.",
                "그룹에 속한 이벤트만 표시합니다.",
            ),
            (
                "cond",
                "Condition only",
                "조건 전용",
                "Show only events that check conditions without pressing a key.",
                "키를 누르지 않고 조건만 확인하는 이벤트만 표시합니다.",
            ),
            (
                "attention",
                "Needs attention",
                "주의 필요",
                "Show only action events that are missing an input key.",
                "입력 키가 없는 실행 이벤트만 표시합니다.",
            ),
        ]:
            var = tk.BooleanVar(value=False)
            self.nav_filter_vars[key] = var
            cb = ttk.Checkbutton(
                rail,
                text=txt(en, ko),
                variable=var,
                command=self._on_nav_filter_changed,
            )
            cb.pack(anchor="w")
            ToolTip(cb, txt(tip_en, tip_ko))

        # --- GROUPS (clickable filters) --------------------------------
        _section_label(txt("GROUPS", "그룹"))
        self.nav_groups_frame = tk.Frame(rail, bg=theme.SURFACE_PANEL)
        self.nav_groups_frame.pack(fill="x")

        self.btn_nav_reset = ttk.Button(
            rail,
            text=txt("Clear filters", "필터 모두 해제"),
            command=self._clear_all_filters,
        )
        return rail

    def _refresh_nav_groups(self) -> None:
        if not getattr(self, "nav_groups_frame", None):
            return
        for child in self.nav_groups_frame.winfo_children():
            child.destroy()
        events = list(self.profile.event_list or [])
        counts: dict[str, int] = {}
        for event in events:
            group = (event.group_id or "").strip()
            if group:
                counts[group] = counts.get(group, 0) + 1
        f = theme.fonts()
        if not counts:
            tk.Label(
                self.nav_groups_frame,
                text=txt("(none)", "(없음)"),
                bg=theme.SURFACE_PANEL,
                fg=theme.INK_MUTED,
                font=f["caption"],
                anchor="w",
            ).pack(fill="x")
            self._sync_nav_reset_button()
            return
        selected = self.filter_state.group_ids
        for grp in sorted(counts):
            active = grp in selected
            label = tk.Label(
                self.nav_groups_frame,
                text=f"▣ {grp} ({counts[grp]})",
                bg=theme.SIGNAL_TINT if active else theme.SURFACE_PANEL,
                fg=theme.SIGNAL_BASE if active else theme.INK_PRIMARY,
                font=f["caption"],
                anchor="w",
                cursor="hand2",
                padx=theme.SPACE_1,
            )
            label.pack(fill="x")
            label.bind(
                "<Button-1>",
                lambda _e, name=grp: self._toggle_group_filter(name),
            )
            ToolTip(
                label,
                txt(
                    f"Click to show only '{grp}'. Click again to clear.",
                    f"클릭하면 '{grp}'만 표시합니다. 다시 누르면 해제됩니다.",
                ),
            )
        self._sync_nav_reset_button()

    def _sync_nav_reset_button(self) -> None:
        button = getattr(self, "btn_nav_reset", None)
        if button is None:
            return
        if self.filter_state.is_active():
            button.pack(fill="x", pady=(theme.SPACE_3, 0))
        else:
            button.pack_forget()

    # --- Filter plumbing ---------------------------------------------
    def _collect_nav_filter_state(self) -> EventFilterState:
        """Rail checkboxes + current group picks, keeping the search text."""
        variables = getattr(self, "nav_filter_vars", {})
        return dataclass_replace(
            self.filter_state,
            active_only=bool(variables.get("active") and variables["active"].get()),
            grouped_only=bool(variables.get("grouped") and variables["grouped"].get()),
            condition_only=bool(variables.get("cond") and variables["cond"].get()),
            attention_only=bool(
                variables.get("attention") and variables["attention"].get()
            ),
        )

    def _apply_filter_state(self, state: EventFilterState) -> None:
        self.filter_state = state
        e_frame = getattr(self, "e_frame", None)
        if e_frame is not None:
            e_frame.set_filter_state(state)
        self._sync_nav_filter_widgets()

    def _sync_nav_filter_widgets(self) -> None:
        variables = getattr(self, "nav_filter_vars", {})
        pairs = (
            ("active", self.filter_state.active_only),
            ("grouped", self.filter_state.grouped_only),
            ("cond", self.filter_state.condition_only),
            ("attention", self.filter_state.attention_only),
        )
        for key, value in pairs:
            var = variables.get(key)
            if var is not None and var.get() != value:
                var.set(value)
        self._refresh_nav_groups()

    def _on_nav_filter_changed(self) -> None:
        self._apply_filter_state(self._collect_nav_filter_state())

    def _on_filter_changed(self, state: EventFilterState) -> None:
        """The list's own search box changed the filter; mirror it in the rail."""
        self.filter_state = state
        self._sync_nav_filter_widgets()

    def _toggle_group_filter(self, group: str) -> None:
        selected = set(self.filter_state.group_ids)
        if group in selected:
            selected.discard(group)
        else:
            selected.add(group)
        self._apply_filter_state(
            dataclass_replace(self.filter_state, group_ids=frozenset(selected))
        )

    def _clear_all_filters(self) -> None:
        self._apply_filter_state(EventFilterState())

    def _on_attention_badge_click(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        """Jump from the warning count to the events it counts."""
        events = list(self.profile.event_list or [])
        if not any(event_needs_attention(event) for event in events):
            return
        turning_on = not self.filter_state.attention_only
        self._apply_filter_state(
            dataclass_replace(
                EventFilterState(),
                attention_only=turning_on,
            )
        )

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

        # --- Capture preview — the one thing the row cannot show -------
        self.inspector_capture_body = self._make_accordion_section(
            panel, "capture", txt("Capture", "캡처"), expanded=True
        )
        self.lbl_inspector_thumb = tk.Label(
            self.inspector_capture_body,
            text="",
            bg=theme.SURFACE_SUNKEN,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="center",
            justify="center",
            wraplength=200,
        )
        self.lbl_inspector_thumb.pack(fill="x")
        self.lbl_inspector_capture_meta = tk.Label(
            self.inspector_capture_body,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
            justify="left",
            wraplength=200,
        )
        self.lbl_inspector_capture_meta.pack(fill="x", pady=(theme.SPACE_1, 0))

        # --- Inline edit — avoids a round trip through the full editor --
        self.inspector_edit_body = self._make_accordion_section(
            panel, "edit", txt("Quick edit", "빠른 편집"), expanded=True
        )
        self._build_inspector_editor(self.inspector_edit_body)
        return panel

    def _build_inspector_editor(self, body: tk.Frame) -> None:
        f = theme.fonts()
        self.insp_use_var = tk.BooleanVar(value=True)
        self.insp_cond_var = tk.BooleanVar(value=False)
        self.insp_key_var = tk.StringVar(value="")
        self.insp_priority_var = tk.StringVar(value="0")

        self.insp_chk_use = ttk.Checkbutton(
            body,
            text=txt("In use", "사용"),
            variable=self.insp_use_var,
            command=self._on_inspector_use_changed,
        )
        self.insp_chk_use.pack(anchor="w")
        self.insp_chk_cond = ttk.Checkbutton(
            body,
            text=txt("Condition only", "조건 전용"),
            variable=self.insp_cond_var,
            command=self._on_inspector_cond_changed,
        )
        self.insp_chk_cond.pack(anchor="w", pady=(0, theme.SPACE_1))

        tk.Label(
            body,
            text=txt("Input key", "입력 키"),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
        ).pack(fill="x")
        self.insp_key_combo = ttk.Combobox(
            body,
            textvariable=self.insp_key_var,
            state="readonly",
            values=KeyUtils.get_key_name_list(),
            width=14,
        )
        self.insp_key_combo.pack(fill="x")
        self.insp_key_combo.bind("<<ComboboxSelected>>", self._on_inspector_key_changed)

        f_priority = tk.Frame(body, bg=theme.SURFACE_PANEL)
        f_priority.pack(fill="x", pady=(theme.SPACE_1, 0))
        tk.Label(
            f_priority,
            text=txt("Priority", "우선순위"),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
        ).pack(side=tk.LEFT)
        self.insp_priority_spin = ttk.Spinbox(
            f_priority,
            from_=0,
            to=999,
            width=5,
            textvariable=self.insp_priority_var,
            command=self._on_inspector_priority_changed,
        )
        self.insp_priority_spin.pack(side=tk.RIGHT)
        self.insp_priority_spin.bind("<FocusOut>", self._on_inspector_priority_changed)
        self.insp_priority_spin.bind("<Return>", self._on_inspector_priority_changed)

        self.insp_btn_group = ttk.Button(
            body,
            text=txt("▣ Group", "▣ 그룹"),
            command=self._on_inspector_group_clicked,
        )
        self.insp_btn_group.pack(fill="x", pady=(theme.SPACE_2, 0))
        self.insp_btn_open = ttk.Button(
            body,
            text=txt("Open full editor", "전체 편집기 열기"),
            command=self._on_inspector_open_editor,
            width=dual_text_width(
                "Open full editor", "전체 편집기 열기", padding=1, min_width=16
            ),
        )
        self.insp_btn_open.pack(fill="x", pady=(theme.SPACE_1, 0))

    # --- Inspector edit handlers -------------------------------------
    def _inspector_target(self) -> EventModel | None:
        """The selected event, but only while the widgets are user-driven."""
        if self._inspector_syncing:
            return None
        event = self._inspector_event
        if event is None:
            return None
        if not any(evt is event for evt in (self.profile.event_list or [])):
            return None
        return event

    def _commit_inspector_change(self, event: EventModel) -> None:
        index = next(
            (
                i
                for i, evt in enumerate(self.profile.event_list or [])
                if evt is event
            ),
            None,
        )
        if index is not None and index < len(self.e_frame.rows):
            self.e_frame.rows[index].update_display()
        self._on_changed(check_name=False)
        self._refresh_profile_overview()

    def _on_inspector_use_changed(self) -> None:
        event = self._inspector_target()
        if event is None:
            return
        event.use_event = self.insp_use_var.get()
        self._commit_inspector_change(event)

    def _on_inspector_cond_changed(self) -> None:
        event = self._inspector_target()
        if event is None:
            return
        event.execute_action = not self.insp_cond_var.get()
        self._commit_inspector_change(event)
        self._refresh_inspector()

    def _on_inspector_key_changed(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        event = self._inspector_target()
        if event is None:
            return
        event.key_to_enter = self.insp_key_var.get() or None
        self._commit_inspector_change(event)

    def _on_inspector_priority_changed(
        self, _event: tk.Event[tk.Misc] | None = None
    ) -> None:
        event = self._inspector_target()
        if event is None:
            return
        try:
            priority = int(self.insp_priority_var.get())
        except (TypeError, ValueError):
            self.insp_priority_var.set(str(event.priority))
            return
        priority = max(0, min(999, priority))
        if priority == event.priority:
            return
        event.priority = priority
        self.insp_priority_var.set(str(priority))
        self._commit_inspector_change(event)

    def _on_inspector_group_clicked(self) -> None:
        event = self._inspector_target()
        if event is None:
            return
        existing = sorted(
            {e.group_id for e in (self.profile.event_list or []) if e.group_id}
        )

        def on_selected(new_group: str | None) -> None:
            event.group_id = new_group
            self._commit_inspector_change(event)
            self._refresh_inspector()

        GroupSelector(self.win, event.group_id, existing, on_selected)

    def _on_inspector_open_editor(self) -> None:
        event = self._inspector_event
        if event is None:
            return
        index = next(
            (
                i
                for i, evt in enumerate(self.profile.event_list or [])
                if evt is event
            ),
            None,
        )
        if index is None:
            return
        self.e_frame.open_editor_for(index)

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
            "title_label": label,
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
        selected = getattr(self, "_inspector_event", None)
        selected = selected if any(evt is selected for evt in events) else None
        if selected is None:
            self._inspector_event = None
            self._show_inspector_placeholder()
            return
        self._show_inspector_event(selected)

    def _set_inspector_section_title(self, key: str, title: str) -> None:
        section = getattr(self, "_inspector_sections", {}).get(key)
        if section is not None:
            section["title_label"].config(text=title)

    def _show_inspector_placeholder(self) -> None:
        """No selection: say how to get one instead of repeating the counts
        already shown in the status bar badges."""
        self._set_inspector_section_title("summary", txt("Summary", "요약"))
        self.lbl_inspector_title.config(
            text=txt("No event selected", "선택된 이벤트 없음")
        )
        self.lbl_inspector_meta.config(
            text=txt(
                "Click a row to inspect and edit it here.\n"
                "⌘/Ctrl+click or Shift+click selects several at once.",
                "행을 클릭하면 여기에서 확인하고 편집할 수 있습니다.\n"
                "⌘/Ctrl+클릭 또는 Shift+클릭으로 여러 개를 선택합니다.",
            )
        )
        self._set_inspector_body_visible("capture", False)
        self._set_inspector_body_visible("edit", False)

    def _set_inspector_body_visible(self, key: str, visible: bool) -> None:
        section = getattr(self, "_inspector_sections", {}).get(key)
        if section is None:
            return
        section["wrapper"].pack_forget()
        if visible:
            section["wrapper"].pack(fill="x", pady=(0, theme.SPACE_2))

    def _show_inspector_event(self, selected: EventModel) -> None:
        key = (selected.key_to_enter or "").strip()
        group = selected.group_id or txt("No Group", "그룹 없음")
        cond_count = len(getattr(selected, "conditions", {}) or {})
        is_condition_only = not getattr(selected, "execute_action", True)
        mode = (
            txt("Condition only", "조건 전용")
            if is_condition_only
            else txt("Action", "실행")
        )
        self._set_inspector_section_title("summary", txt("Event", "이벤트"))
        self.lbl_inspector_title.config(
            text=selected.event_name or txt("(Unnamed)", "(이름 없음)")
        )
        meta_lines = [
            txt(f"{mode} · Group {group}", f"{mode} · 그룹 {group}"),
            txt(
                f"Key: {key if key else 'None'} · Priority {selected.priority}",
                f"키: {key if key else '없음'} · 우선순위 {selected.priority}",
            ),
            txt(f"Conditions: {cond_count}", f"조건: {cond_count}개"),
        ]
        if getattr(selected, "runtime_toggle_member", False):
            meta_lines.append(txt("In the toggle set", "토글 세트 포함"))
        self.lbl_inspector_meta.config(text="\n".join(meta_lines))

        self._set_inspector_body_visible("capture", True)
        self._set_inspector_body_visible("edit", True)
        self._refresh_inspector_capture(selected)
        self._sync_inspector_editor(selected)

    def _refresh_inspector_capture(self, selected: EventModel) -> None:
        """Show the captured reference image — otherwise only the full editor
        can tell the user what this event actually watches."""
        image = getattr(selected, "held_screenshot", None)
        if image is None:
            self._inspector_thumb = None
            self.lbl_inspector_thumb.config(
                image="",
                text=txt(
                    "No capture yet.\nOpen the editor to capture a target area.",
                    "캡처가 없습니다.\n편집기에서 대상 영역을 캡처하세요.",
                ),
                height=4,
            )
            self.lbl_inspector_capture_meta.config(
                text=txt(
                    "Screenless event: it runs on conditions only."
                    if selected.is_screenless_input()
                    else "",
                    "화면 없는 이벤트: 조건만으로 실행됩니다."
                    if selected.is_screenless_input()
                    else "",
                )
            )
            return
        try:
            preview = image.copy()
            preview.thumbnail((200, 150))
            self._inspector_thumb = ImageTk.PhotoImage(preview)
            self.lbl_inspector_thumb.config(
                image=cast(Any, self._inspector_thumb), text="", height=0
            )
        except (OSError, ValueError, tk.TclError):
            self._inspector_thumb = None
            self.lbl_inspector_thumb.config(
                image="",
                text=txt("Preview unavailable.", "미리보기를 표시할 수 없습니다."),
                height=3,
            )
        meta_parts: list[str] = []
        if selected.clicked_position:
            meta_parts.append(
                txt(
                    f"Reference point {selected.clicked_position}",
                    f"기준점 {selected.clicked_position}",
                )
            )
        if selected.ref_pixel_value:
            meta_parts.append(
                txt(
                    f"RGB {tuple(selected.ref_pixel_value)[:3]}",
                    f"RGB {tuple(selected.ref_pixel_value)[:3]}",
                )
            )
        match_mode = getattr(selected, "match_mode", "pixel")
        meta_parts.append(
            txt(f"Mode: {match_mode}", f"매칭: {match_mode}")
            + (txt(" (inverted)", " (반전)") if selected.invert_match else "")
        )
        self.lbl_inspector_capture_meta.config(text="\n".join(meta_parts))

    def _inspector_editor_has_focus(self) -> bool:
        try:
            widget = self.win.focus_get()
        except (KeyError, tk.TclError):
            return False
        return widget in (
            getattr(self, "insp_priority_spin", None),
            getattr(self, "insp_key_combo", None),
        )

    def _sync_inspector_editor(self, selected: EventModel) -> None:
        """Push model values into the edit widgets without echoing back as
        user edits. Autosave refreshes the inspector, so a half-typed value in
        a focused field must not be overwritten mid-edit."""
        if (
            getattr(self, "_inspector_synced_id", None) == id(selected)
            and self._inspector_editor_has_focus()
        ):
            return
        self._inspector_synced_id = id(selected)
        self._inspector_syncing = True
        try:
            self.insp_use_var.set(bool(getattr(selected, "use_event", True)))
            self.insp_cond_var.set(not getattr(selected, "execute_action", True))
            self.insp_key_var.set(selected.key_to_enter or "")
            self.insp_priority_var.set(str(selected.priority))
            key_state = "disabled" if self.insp_cond_var.get() else "readonly"
            self.insp_key_combo.config(state=key_state)
            self.insp_btn_group.config(
                text=txt(
                    f"▣ {selected.group_id}" if selected.group_id else "▣ No group",
                    f"▣ {selected.group_id}" if selected.group_id else "▣ 그룹 없음",
                )
            )
        finally:
            self._inspector_syncing = False

    def _set_inspector_event(self, event: EventModel | None) -> None:
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

    def _show_temp_status(
        self,
        text: str,
        duration_ms: int = 2000,
        *,
        action_label: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        """Transient status. With an action, it becomes an undo affordance and
        stays up long enough to be clicked."""
        self._hide_status_action()
        self.lbl_status.config(text=text, foreground=theme.STATUS_READY_FG)
        if action_label and action is not None:
            duration_ms = max(duration_ms, 8000)

            def run_action() -> None:
                self._hide_status_action()
                self.lbl_status.config(text="", foreground=theme.INK_MUTED)
                action()

            self.btn_status_action.config(
                text=action_label,
                command=run_action,
                width=dual_text_width(action_label, action_label, padding=2, min_width=8),
            )
            self.btn_status_action.pack(side=tk.LEFT, padx=(0, UI_PAD_SM))

        def expire() -> None:
            self._status_action_after_id = None
            self._hide_status_action()
            self.lbl_status.config(text="", foreground=theme.INK_MUTED)

        self._status_action_after_id = self.win.after(duration_ms, expire)

    def _hide_status_action(self) -> None:
        after_id = self._status_action_after_id
        self._status_action_after_id = None
        if after_id:
            try:
                self.win.after_cancel(after_id)
            except (ValueError, tk.TclError):
                pass
        button = getattr(self, "btn_status_action", None)
        if button is not None:
            button.pack_forget()

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
        missing_key_count = sum(1 for e in events if event_needs_attention(e))
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
            self._sync_attention_badge_tip(missing_key_count)
            return
        if condition_only_count:
            if toggle_member_count:
                self._overview_status_text = txt(
                    "Condition-only events: {cond_count}. Toggle set events: {toggle_count}.",
                    "조건 전용 이벤트: {cond_count}개. 토글 세트 이벤트: {toggle_count}개.",
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
                "Toggle set events are configured: {count}.",
                "토글 세트 이벤트가 {count}개 설정되어 있습니다.",
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
        self._sync_attention_badge_tip(0)

    def _sync_attention_badge_tip(self, missing_key_count: int) -> None:
        tip = getattr(self, "_tip_attention_badge", None)
        if tip is None:
            return
        if missing_key_count:
            tip.update_text(
                txt(
                    "Click to show only the events missing an input key.",
                    "클릭하면 입력 키가 없는 이벤트만 표시합니다.",
                )
                if not self.filter_state.attention_only
                else txt(
                    "Click to clear the attention filter.",
                    "클릭하면 주의 필터를 해제합니다.",
                )
            )
        else:
            tip.update_text(
                txt(
                    "Every action event has an input key.",
                    "모든 실행 이벤트에 입력 키가 있습니다.",
                )
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
