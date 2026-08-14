from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Callable
from dataclasses import replace as dataclass_replace
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Literal, Optional, Protocol, TypeAlias, TypedDict, cast

from app.core.models import EventModel, ProfileModel
from app.core.profile_events import (
    EventFilterState,
    clone_event,
    event_matches_filter,
    event_group_key_sort_key,
    event_group_name_sort_key,
    event_key_sort_key,
    event_name_sort_key,
    event_type_sort_order,
    filter_event_indices,
    key_sort_order,
    remove_condition_references,
    rename_condition_references,
)
from app.core.validation import normalized_event_name
from app.ui import theme
from app.ui.event_editor import KeystrokeEventEditor
from app.ui.event_importer import EventImporter
from app.ui.profile_graph_viewer import ProfileGraphViewer
from app.ui.profile_groups import GroupManagerDialog, GroupSelector
from app.utils.i18n import dual_text_width, txt

UI_PAD_XS = theme.SPACE_1
UI_PAD_SM = theme.SPACE_1
UI_PAD_MD = theme.SPACE_2
EVENT_NAME_COL_WIDTH = 34
EVENT_GROUP_COL_WIDTH = 10
EVENT_KEY_COL_WIDTH = 8
EVENT_COND_COL_WIDTH = 6
EVENT_EXTRA_COL_WIDTH = 7
EVENT_ACTIONS_COL_WIDTH = 18

ClickAction: TypeAlias = Literal["open", "copy", "remove"]
SortKey: TypeAlias = Callable[[EventModel], tuple[object, ...]]
KeySortOrder: TypeAlias = tuple[int, int, str]
SelectMode: TypeAlias = Literal["replace", "toggle", "range"]

# tk event.state modifier bits. macOS reports Command as Mod1 (0x8).
_STATE_SHIFT = 0x0001
_STATE_CONTROL = 0x0004
_STATE_COMMAND = 0x0008


def selection_mode_for_state(state: int) -> SelectMode:
    """Map a click's modifier bits onto a selection gesture."""
    if state & _STATE_SHIFT:
        return "range"
    if state & _STATE_CONTROL:
        return "toggle"
    if sys.platform == "darwin" and state & _STATE_COMMAND:
        return "toggle"
    return "replace"


def resolve_selection(
    current: set[int], anchor: int | None, index: int, mode: SelectMode
) -> tuple[set[int], int | None]:
    """Pure selection transition. Returns the new selection and anchor."""
    if mode == "toggle":
        updated = set(current)
        if index in updated:
            updated.discard(index)
        else:
            updated.add(index)
        return updated, index
    if mode == "range" and anchor is not None:
        low, high = sorted((anchor, index))
        return set(range(low, high + 1)), anchor
    return {index}, index


class SaveCallback(Protocol):
    def __call__(self, check_name: bool = False) -> object: ...


class StatusCallback(Protocol):
    def __call__(
        self,
        text: str,
        *,
        action_label: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None: ...


class EventRowCallbacks(TypedDict, total=False):
    open: Callable[[int, EventModel | None], object]
    copy: Callable[[EventModel | None], object]
    remove: Callable[["EventRow", int], object]
    menu: Callable[[tk.Event[tk.Misc], int], object]
    group_select: Callable[[int, EventModel], object]
    save: Callable[[], object]
    select: Callable[[int, SelectMode], object]


class ToolTip:
    """경량 툴팁: 위젯에 마우스를 올리면 설명 텍스트를 표시한다."""

    def __init__(self, widget: tk.Misc, text: str = "", delay: int = 400) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id: str | None = None
        self._tw: tk.Toplevel | None = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, event: tk.Event[tk.Misc] | None = None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _on_leave(self, event: tk.Event[tk.Misc] | None = None) -> None:
        self._cancel()
        self._hide()

    def _cancel(self) -> None:
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self) -> None:
        if not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except tk.TclError:
            return
        self._tw = tk.Toplevel(self.widget)
        self._tw.wm_overrideredirect(True)
        cast(Any, self._tw).wm_attributes("-topmost", True)
        self._tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._tw,
            text=self.text,
            justify=tk.LEFT,
            background=theme.STATUS_WARN_BG,
            foreground=theme.INK_PRIMARY,
            relief="solid",
            borderwidth=1,
            font=("TkDefaultFont", 9),
            padx=6,
            pady=4,
        ).pack()

    def _hide(self) -> None:
        if self._tw:
            self._tw.destroy()
            self._tw = None

    def update_text(self, text: str) -> None:
        self.text = text




class EventRow(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        row_num: int,
        event: Optional[EventModel],
        cbs: EventRowCallbacks,
    ) -> None:
        super().__init__(master, style="Row.TFrame")
        self.row_num, self.event, self.cbs = row_num, event, cbs
        self.use_var = tk.BooleanVar(value=event.use_event if event else True)
        self.runtime_toggle_var = tk.BooleanVar(
            value=bool(getattr(event, "runtime_toggle_member", False))
            if event
            else False
        )
        self.last_saved_name: str = (event.event_name or "") if event else ""
        self._bound_event_id = id(event) if event else None
        self.btn_delete: ttk.Button | None = None
        self.tip_delete: ToolTip | None = None
        self.selected = False

        # Compact one-line cell: selection marker | state color bar | index |
        # use | name | group | key/condition | extra | actions.
        # The marker floats with place() so hiding it never shifts the row.
        self.select_bar = tk.Frame(self, bg=theme.ROW_MARKER_SELECTED)
        self.color_bar = tk.Frame(self, bg=theme.SIGNAL_BASE, width=4)
        self.color_bar.pack(
            side=tk.LEFT, fill="y", padx=(theme.ROW_MARKER_WIDTH + 2, UI_PAD_SM)
        )
        self.color_bar.pack_propagate(False)

        row_body = ttk.Frame(self, style="Row.TFrame")
        self.row_body = row_body
        row_body.pack(side=tk.LEFT, fill="x", expand=True)
        for col, weight in [(2, 1)]:
            row_body.grid_columnconfigure(col, weight=weight)

        self.lbl_index = ttk.Label(
            row_body, text=str(row_num + 1), width=2, anchor="center", style="Row.TLabel"
        )
        self.lbl_index.grid(row=0, column=0, sticky="ew", padx=(0, UI_PAD_XS))
        ttk.Checkbutton(
            row_body, variable=self.use_var, command=self._on_toggle_use
        ).grid(row=0, column=1, sticky="w", padx=(0, UI_PAD_XS))

        self.entry = ttk.Entry(row_body, width=EVENT_NAME_COL_WIDTH)
        self.entry.grid(row=0, column=2, sticky="ew", padx=(0, UI_PAD_SM))
        if event:
            self.entry.insert(0, event.event_name or "")

        self.lbl_grp = ttk.Label(
            row_body,
            text="",
            width=EVENT_GROUP_COL_WIDTH,
            anchor="center",
            relief="sunken",
            cursor="hand2",
            padding=(theme.SPACE_1, 0),
        )
        self.lbl_grp.grid(row=0, column=3, sticky="ew", padx=(0, theme.SPACE_1))
        self.lbl_grp.bind("<Button-1>", self._on_group_click)
        self._tip_grp = ToolTip(self.lbl_grp)

        self.lbl_key = ttk.Label(
            row_body,
            text="",
            width=EVENT_KEY_COL_WIDTH,
            anchor="center",
            relief="groove",
            padding=(theme.SPACE_1, 0),
        )
        self.lbl_key.grid(row=0, column=4, sticky="ew", padx=(0, theme.SPACE_1))
        self.lbl_key.bind("<Button-1>", self._on_open_click)
        self._tip_key = ToolTip(self.lbl_key)

        self.lbl_cond = ttk.Label(
            row_body,
            text="",
            width=EVENT_COND_COL_WIDTH,
            anchor="center",
            style="Row.TLabel",
        )
        self.lbl_cond.grid(row=0, column=5, sticky="ew", padx=(0, theme.SPACE_1))
        self._tip_cond = ToolTip(self.lbl_cond)

        self.chk_runtime_toggle = ttk.Checkbutton(
            row_body,
            text=txt("Toggle", "토글"),
            variable=self.runtime_toggle_var,
            command=self._on_toggle_runtime_member,
        )
        self.chk_runtime_toggle.grid(
            row=0, column=6, sticky="w", padx=(0, theme.SPACE_1)
        )
        self._tip_runtime_toggle = ToolTip(self.chk_runtime_toggle)

        actions_frame = ttk.Frame(row_body, style="Row.TFrame")
        self.actions_frame = actions_frame
        actions_frame.grid(row=0, column=7, sticky="e")
        button_specs: tuple[tuple[str, str, ClickAction, int], ...] = (
            ("Edit", "편집", "open", 5),
            ("Copy", "복사", "copy", 5),
            ("Del", "삭제", "remove", 5),
        )
        for col, (en, ko, key, min_width) in enumerate(button_specs):
            btn = ttk.Button(
                actions_frame,
                text=txt(en, ko),
                width=dual_text_width(en, ko, padding=1, min_width=min_width),
                command=lambda k=key: self._on_click(k),
            )
            btn.grid(row=0, column=col, padx=(UI_PAD_XS, 0), sticky="ew")
            btn.bind("<Button-3>", self._on_context_menu)
            if key == "remove":
                self.btn_delete = btn
                self.tip_delete = ToolTip(btn)

        # Context Menu Binding
        self.entry.bind("<Button-3>", self._on_context_menu)
        self.entry.bind("<KeyRelease>", self._on_name_changed)
        self.entry.bind("<FocusOut>", self._on_name_changed)
        self.entry.bind("<FocusIn>", self._on_select)
        for widget in (
            self,
            self.select_bar,
            self.color_bar,
            row_body,
            self.lbl_index,
            self.lbl_cond,
        ):
            widget.bind("<Button-1>", self._on_select, add="+")

        # Initial Display
        self.update_display()

    def set_selected(self, selected: bool) -> None:
        """Tint the row and show its marker bar. The marker is a plain tk frame
        so selection stays visible on themes that drop ttk backgrounds."""
        if selected == self.selected:
            return
        self.selected = selected
        suffix = "RowSelected" if selected else "Row"
        try:
            self.configure(style=f"{suffix}.TFrame")
            self.row_body.configure(style=f"{suffix}.TFrame")
            self.actions_frame.configure(style=f"{suffix}.TFrame")
            self.lbl_index.configure(style=f"{suffix}.TLabel")
            self.lbl_cond.configure(style=f"{suffix}.TLabel")
            if selected:
                self.select_bar.place(
                    x=0, y=0, relheight=1.0, width=theme.ROW_MARKER_WIDTH
                )
            else:
                self.select_bar.place_forget()
        except tk.TclError:
            return

    def update_display(self) -> None:
        """이벤트 상태에 따라 UI 갱신"""
        if not self.event:
            runtime_toggle_var = cast(
                tk.BooleanVar | None, getattr(self, "runtime_toggle_var", None)
            )
            if runtime_toggle_var is not None:
                runtime_toggle_var.set(False)
            self.lbl_cond.config(text="")
            self.lbl_grp.config(text="")
            self.lbl_key.config(text="")
            return

        self.use_var.set(self.event.use_event)
        runtime_toggle_var = cast(
            tk.BooleanVar | None, getattr(self, "runtime_toggle_var", None)
        )
        runtime_toggle_tip = cast(
            ToolTip | None, getattr(self, "_tip_runtime_toggle", None)
        )
        if runtime_toggle_var is not None:
            runtime_toggle_var.set(
                bool(getattr(self.event, "runtime_toggle_member", False))
            )
            if runtime_toggle_tip is not None:
                runtime_toggle_tip.update_text(
                    txt(
                        "This event is in the toggle set (starts off until toggled on).",
                        "이 이벤트는 토글 세트에 포함됩니다(시작 시 꺼짐, 토글로 켬).",
                    )
                    if runtime_toggle_var.get()
                    else txt(
                        "Leave unchecked to keep this event always in the base set.",
                        "체크하지 않으면 이 이벤트는 항상 기본 세트로 유지됩니다.",
                    )
                )

        # Name
        event_name = self.event.event_name or ""
        event_rebound = getattr(self, "_bound_event_id", None) != id(self.event)
        if self.entry.get() != event_name:
            self.entry.delete(0, tk.END)
            self.entry.insert(0, event_name)
        if event_rebound:
            self.last_saved_name = event_name
        self._bound_event_id = id(self.event)

        # Condition Only — SOT icon vocabulary (◐ for conditions).
        is_cond = not getattr(self.event, "execute_action", True)
        self.lbl_cond.config(text=txt("◐ Cond", "◐ 조건") if is_cond else "")
        self.entry.config(
            foreground=theme.INK_MUTED if is_cond else theme.INK_PRIMARY
        )
        self._tip_cond.update_text(
            txt(
                "Condition-only mode checks conditions without pressing keys.",
                "조건만 확인하고 키 입력은 하지 않습니다.",
            )
            if is_cond
            else txt(
                "When conditions match, the key input is executed.",
                "조건이 맞으면 키를 눌러 실행됩니다.",
            )
        )

        # Group — SOT icon vocabulary prefixes the group glyph (▣).
        grp = self.event.group_id or ""
        grp_text = grp if grp else txt("None", "없음")
        self.lbl_grp.config(text=f"▣ {grp_text}")
        self._tip_grp.update_text(
            txt(
                f"Current group: {grp}. Click to change it.",
                f"현재 그룹: {grp}. 클릭하면 변경할 수 있습니다.",
            )
            if grp
            else txt(
                "No group assigned. Click to set a group.",
                "현재 그룹이 없습니다. 클릭해서 그룹을 지정하세요.",
            )
        )

        # Key — SOT icon vocabulary (⌨ for key, ◐ for condition-only,
        # ⇄ prefix for inverted match).
        key = self.event.key_to_enter or ""
        invert = bool(getattr(self.event, "invert_match", False)) and not (
            self.event.is_screenless_input()
        )
        if is_cond:
            display = txt("◐ Cond", "◐ 조건")
        else:
            key_text = key if key else txt("None", "없음")
            display = f"⌨ {key_text}"
        if invert:
            display = f"⇄ {display}"
        self.lbl_key.config(text=display)

        # Left color bar reflects the row's overall liveness.
        if hasattr(self, "color_bar"):
            if not getattr(self.event, "use_event", True):
                bar_color = theme.SURFACE_DIVIDER
            elif is_cond:
                bar_color = theme.INK_MUTED
            elif key:
                bar_color = theme.SIGNAL_BASE
            else:
                bar_color = theme.STATUS_WARN_FG
            self.color_bar.config(bg=bar_color)
        if invert:
            self._tip_key.update_text(
                txt(
                    "Invert match is enabled. It runs when the target does not match.",
                    "반전 매칭이 켜져 있습니다. 기준과 불일치할 때 실행됩니다.",
                )
            )
        elif is_cond:
            self._tip_key.update_text(
                txt(
                    "Condition-only event. No input key is needed.",
                    "조건 전용 이벤트입니다. 입력 키가 필요하지 않습니다.",
                )
            )
        elif key:
            if self.event.is_screenless_input():
                self._tip_key.update_text(
                    txt(
                        f"Input key: {key}. No screen target; runs when conditions match.",
                        f"입력 키: {key}. 화면 없이 조건이 맞으면 실행됩니다.",
                    )
                )
            else:
                self._tip_key.update_text(
                    txt(
                        f"Input key: {key}. Click to open the editor.",
                        f"입력 키: {key}. 클릭하면 편집기를 엽니다.",
                    )
                )
        else:
            self._tip_key.update_text(
                txt(
                    "No input key. Click to open the editor.",
                    "입력 키가 없습니다. 클릭하면 편집기를 엽니다.",
                )
            )

    def _on_context_menu(self, event: tk.Event[tk.Misc]) -> object:
        menu_cb = self.cbs.get("menu")
        if menu_cb is None:
            return None
        return menu_cb(event, self.row_num)

    def _on_open_click(self, _event: tk.Event[tk.Misc]) -> None:
        self._on_click("open")

    def _on_toggle_use(self) -> None:
        if self.event:
            self.event.use_event = self.use_var.get()
            save_cb = self.cbs.get("save")
            if save_cb is not None:
                save_cb()

    def _on_group_click(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if self.event:
            group_select_cb = self.cbs.get("group_select")
            if group_select_cb is not None:
                group_select_cb(self.row_num, self.event)

    def _on_toggle_runtime_member(self) -> None:
        if self.event:
            self.event.runtime_toggle_member = self.runtime_toggle_var.get()
            self.update_display()
            save_cb = self.cbs.get("save")
            if save_cb is not None:
                save_cb()

    def _on_select(self, event: tk.Event[tk.Misc] | None = None) -> None:
        select_cb = self.cbs.get("select")
        if self.event is None or select_cb is None:
            return
        state = int(getattr(cast(Any, event), "state", 0) or 0) if event else 0
        select_cb(self.row_num, selection_mode_for_state(state))

    def _on_click(self, key: ClickAction) -> None:
        if key == "open":
            open_cb = self.cbs.get("open")
            if open_cb is not None:
                open_cb(self.row_num, self.event)
        elif key == "copy":
            copy_cb = self.cbs.get("copy")
            if copy_cb is not None:
                copy_cb(self.event)
        elif key == "remove":
            remove_cb = self.cbs.get("remove")
            if remove_cb is not None:
                remove_cb(self, self.row_num)

    def _on_name_changed(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if self.event:
            self.event.event_name = self.entry.get()
            save_cb = self.cbs.get("save")
            if save_cb is not None:
                save_cb()

    def get_name(self) -> str:
        return self.entry.get()


class EventListFrame(ttk.Frame):
    # 특수 키 정렬 순서 (클래스 상수)
    @staticmethod
    def resolve_dialog_parent(
        packing_parent: tk.Misc, host_window: tk.Misc | None
    ) -> tk.Misc:
        """Dialog/grab owner must be the Profile Toplevel, not an inner Frame."""
        return host_window if host_window is not None else packing_parent

    def __init__(
        self,
        win: tk.Misc,
        profile: ProfileModel,
        save_cb: SaveCallback,
        name_getter: Optional[Callable[[], str]] = None,
        status_cb: Optional[StatusCallback] = None,
        select_cb: Optional[Callable[[EventModel | None], None]] = None,
        *,
        profiles_dir: Path,
        host_window: tk.Misc | None = None,
        filter_change_cb: Optional[Callable[[EventFilterState], None]] = None,
    ) -> None:
        # `win` is the packing parent (often an inner workspace Frame).
        # Dialogs and grab handoff must use the Profile Toplevel host instead.
        super().__init__(win)
        self.profile = profile
        self.save_cb = save_cb
        self.win = self.resolve_dialog_parent(win, host_window)
        self.rows: list[EventRow] = []
        self.ctx_row: int | None = None
        self.profile_name_getter = name_getter
        self.status_cb = status_cb
        self.select_cb = select_cb
        self.filter_change_cb = filter_change_cb
        self.profiles_dir = profiles_dir
        self.graph_viewer: ProfileGraphViewer | None = None
        self.empty_state_frame: Optional[ttk.LabelFrame] = None
        self.no_match_frame: Optional[ttk.Frame] = None
        self.add_event_label = txt("➕ Add Event", "➕ 이벤트 추가")
        self.filter_state = EventFilterState()
        self.selected_indices: set[int] = set()
        self.selection_anchor: int | None = None
        self._undo_delete: dict[str, Any] | None = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # --- Search ---
        f_search = ttk.Frame(self)
        f_search.grid(
            row=0,
            column=0,
            columnspan=2,
            padx=UI_PAD_MD,
            pady=(UI_PAD_SM, 0),
            sticky="we",
        )
        ttk.Label(f_search, text=txt("🔎", "🔎")).pack(side=tk.LEFT, padx=(0, UI_PAD_XS))
        self.search_var = tk.StringVar(value="")
        self.search_entry = ttk.Entry(f_search, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.search_entry.bind("<Escape>", self._on_search_escape)
        self.search_var.trace_add("write", self._on_search_changed)
        ToolTip(
            self.search_entry,
            txt(
                "Filter events by name, input key or group.",
                "이벤트 이름, 입력 키, 그룹으로 걸러냅니다.",
            ),
        )
        self.lbl_filter_summary = ttk.Label(
            f_search, text="", foreground=theme.INK_MUTED
        )
        self.lbl_filter_summary.pack(side=tk.LEFT, padx=(UI_PAD_SM, 0))
        self.btn_clear_filter = ttk.Button(
            f_search,
            text=txt("Clear filter", "필터 해제"),
            command=self.clear_filters,
            width=dual_text_width("Clear filter", "필터 해제", padding=1, min_width=11),
        )

        # --- Control Buttons ---
        f_ctrl = ttk.Frame(self)
        f_ctrl.grid(
            row=1,
            column=0,
            columnspan=2,
            padx=UI_PAD_MD,
            pady=(UI_PAD_SM, UI_PAD_MD),
            sticky="we",
        )

        f_primary = ttk.Frame(f_ctrl)
        f_primary.pack(side=tk.LEFT, fill=tk.X, expand=True)
        f_secondary = ttk.Frame(f_ctrl)
        f_secondary.pack(side=tk.RIGHT)

        self.btn_add_event = ttk.Button(
            f_primary,
            text=self.add_event_label,
            command=self._add_event,
            width=dual_text_width(
                "➕ Add Event", "➕ 이벤트 추가", padding=2, min_width=18
            ),
        )
        self.btn_add_event.pack(
            side=tk.LEFT, padx=(0, UI_PAD_SM), fill=tk.X, expand=True
        )
        ToolTip(
            self.btn_add_event,
            txt(
                "Add a new event and open its editor.",
                "새 이벤트를 추가하고 편집기를 엽니다.",
            ),
        )

        self.btn_graph = ttk.Button(
            f_primary,
            text=txt("🗺 View Graph", "🗺 그래프 보기"),
            command=self._open_graph,
            width=dual_text_width(
                "🗺 View Graph", "🗺 그래프 보기", padding=2, min_width=13
            ),
        )
        self.btn_graph.pack(side=tk.LEFT, padx=(0, UI_PAD_SM))
        ToolTip(
            self.btn_graph,
            txt(
                "Open a graph view of the current event flow.",
                "현재 이벤트 흐름을 그래프로 확인합니다.",
            ),
        )

        self.btn_sort = ttk.Menubutton(
            f_secondary,
            text=txt("↕ Sort", "↕ 정렬"),
            width=dual_text_width("↕ Sort", "↕ 정렬", padding=1, min_width=8),
        )
        self.btn_sort.pack(side=tk.LEFT, padx=(0, UI_PAD_SM))
        ToolTip(
            self.btn_sort,
            txt(
                "Sort events by name, key, group/name, or group/key.",
                "이름, 키, 그룹/이름, 그룹/키 순으로 이벤트를 정렬합니다.",
            ),
        )
        self.sort_menu = tk.Menu(self.btn_sort, tearoff=0)
        self.sort_menu.add_command(
            label=txt("Name", "이름"),
            command=self._sort_events_by_name,
        )
        self.sort_menu.add_command(
            label=txt("Key", "키"),
            command=self._sort_events_by_key,
        )
        self.sort_menu.add_command(
            label=txt("Group / Name", "그룹/이름"),
            command=self._sort_events_by_group_name,
        )
        self.sort_menu.add_command(
            label=txt("Group / Key", "그룹/키"),
            command=self._sort_events_by_group_key,
        )
        self.btn_sort.configure(menu=self.sort_menu)

        self.btn_more = ttk.Menubutton(
            f_secondary,
            text=txt("⋯ More", "⋯ 더보기"),
            width=dual_text_width("⋯ More", "⋯ 더보기", padding=1, min_width=8),
        )
        self.btn_more.pack(side=tk.LEFT)
        ToolTip(
            self.btn_more,
            txt(
                "Open additional actions such as import and group management.",
                "가져오기, 그룹 관리 같은 추가 작업을 엽니다.",
            ),
        )
        self.more_menu = tk.Menu(self.btn_more, tearoff=0)
        self.more_menu.add_command(
            label=txt("📥 Import", "📥 가져오기"),
            command=lambda: EventImporter(
                cast(tk.Toplevel, self.win),
                self._import,
                profiles_dir=self.profiles_dir,
            ),
        )
        self.more_menu.add_command(
            label=txt("🧩 Manage Groups", "🧩 그룹 관리"),
            command=self._manage_groups,
        )
        self.btn_more.configure(menu=self.more_menu)

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(
            label=txt(
                "Apply Pixel/Region Info to Similar Areas",
                "유사 영역에 픽셀/영역 정보 적용",
            ),
            command=self._apply_pixel_batch,
        )

        self._create_bulk_bar()
        self._create_header()
        self._create_scroll_area()
        self._load_events()
        self._bind_keyboard_shortcuts()

    # ------------------------------------------------------------------
    # Bulk action bar — appears only while a multi-selection is live.
    # ------------------------------------------------------------------
    def _create_bulk_bar(self) -> None:
        self.bulk_bar = ttk.Frame(self)
        self.lbl_bulk_count = ttk.Label(self.bulk_bar, text="")
        self.lbl_bulk_count.pack(side=tk.LEFT, padx=(0, UI_PAD_MD))
        # Packed before the left-hand buttons so it keeps its width instead of
        # being squeezed off the edge of the bar.
        ttk.Button(
            self.bulk_bar,
            text=txt("Deselect", "선택 해제"),
            command=self.clear_selection,
        ).pack(side=tk.RIGHT)
        for en, ko, command in (
            ("▣ Group", "▣ 그룹", self._bulk_set_group),
            ("Use on", "사용 켜기", lambda: self._bulk_set_use(True)),
            ("Use off", "사용 끄기", lambda: self._bulk_set_use(False)),
            ("Toggle set", "토글 세트", self._bulk_toggle_runtime_member),
        ):
            ttk.Button(
                self.bulk_bar,
                text=txt(en, ko),
                command=command,
            ).pack(side=tk.LEFT, padx=(0, UI_PAD_SM))
        ttk.Button(
            self.bulk_bar,
            text=txt("Delete", "삭제"),
            command=self._bulk_delete,
            style="Danger.TButton",
        ).pack(side=tk.LEFT, padx=(0, UI_PAD_SM))

    def _sync_bulk_bar(self) -> None:
        count = len(self.selected_indices)
        if count >= 2:
            self.lbl_bulk_count.config(
                text=txt(f"{count} selected", f"{count}개 선택됨")
            )
            self.bulk_bar.grid(
                row=2,
                column=0,
                columnspan=2,
                padx=UI_PAD_MD,
                pady=(0, UI_PAD_SM),
                sticky="we",
            )
        else:
            self.bulk_bar.grid_remove()

    def _bind_keyboard_shortcuts(self) -> None:
        """Row navigation on the profile window. Bindings defer to text entry:
        while a name field has focus, editing keys keep their normal meaning."""
        host = self.win
        bindings: tuple[tuple[str, Callable[[tk.Event[tk.Misc]], object]], ...] = (
            ("<Up>", lambda e: self._move_selection(-1)),
            ("<Down>", lambda e: self._move_selection(1)),
            ("<Return>", self._on_shortcut_open),
            ("<Delete>", self._on_shortcut_delete),
            ("<BackSpace>", self._on_shortcut_delete),
            ("<Control-d>", self._on_shortcut_copy),
            ("<Command-d>", self._on_shortcut_copy),
            ("<Control-f>", self._on_shortcut_search),
            ("<Command-f>", self._on_shortcut_search),
        )
        for sequence, handler in bindings:
            try:
                host.bind(sequence, handler, add="+")
            except tk.TclError:
                continue

    def _focus_is_text_entry(self) -> bool:
        try:
            widget = self.win.focus_get()
        except (KeyError, tk.TclError):
            return False
        return isinstance(widget, (ttk.Entry, tk.Entry, tk.Text, ttk.Combobox))

    def _on_shortcut_search(self, _event: tk.Event[tk.Misc]) -> str:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, tk.END)
        return "break"

    def _on_search_escape(self, _event: tk.Event[tk.Misc]) -> str:
        self.search_var.set("")
        return "break"

    def _on_shortcut_open(self, _event: tk.Event[tk.Misc]) -> str | None:
        if self._focus_is_text_entry():
            return None
        index = self._primary_selection()
        if index is None:
            return None
        self._open_editor(index, self.profile.event_list[index])
        return "break"

    def _on_shortcut_delete(self, _event: tk.Event[tk.Misc]) -> str | None:
        if self._focus_is_text_entry():
            return None
        if len(self.selected_indices) >= 2:
            self._bulk_delete()
            return "break"
        index = self._primary_selection()
        if index is None or index >= len(self.rows):
            return None
        self._remove_row(self.rows[index], index)
        return "break"

    def _on_shortcut_copy(self, _event: tk.Event[tk.Misc]) -> str | None:
        if self._focus_is_text_entry():
            return None
        index = self._primary_selection()
        if index is None:
            return None
        self._copy_row(self.profile.event_list[index])
        return "break"

    def _get_existing_groups(self) -> list[str]:
        """프로필 내 모든 고유 그룹 ID 반환"""
        return list(set(e.group_id for e in self.profile.event_list if e.group_id))

    def _get_profile_name(self) -> str:
        if self.profile_name_getter:
            return self.profile_name_getter()
        profile_name = self.profile.name
        if profile_name:
            return profile_name
        return "profile"

    def _get_key_sort_order(self, key: str | None) -> KeySortOrder:
        return key_sort_order(key)

    @staticmethod
    def _get_event_type_sort_order(event: EventModel) -> int:
        return event_type_sort_order(event)

    def _sort_events_with_feedback(
        self, sort_key: SortKey, title_text: str, message_text: str
    ) -> None:
        """Sorting is safe and reversible by re-sorting, so it reports in the
        status line instead of interrupting with a modal."""
        if not self.profile.event_list:
            return
        self.save_names()
        self.profile.event_list.sort(key=sort_key)
        self.clear_selection()
        self.update_events()
        self.save_cb()
        if self.status_cb:
            self.status_cb(title_text)
        else:
            messagebox.showinfo(title_text, message_text, parent=self.win)

    def _sort_events_by_name(self) -> None:
        """이벤트 타입 우선, 같은 타입 내에서는 이름순 정렬."""

        self._sort_events_with_feedback(
            event_name_sort_key,
            txt("Name Sort Complete", "이름순 정렬 완료"),
            txt(
                "Events were sorted by:\nEvent Type (Condition → Action) → Name",
                "이벤트를 다음 순서로 정렬했습니다:\n이벤트 타입(조건 → 실행) → 이름",
            ),
        )

    def _sort_events_by_key(self) -> None:
        """이벤트 타입 우선, 조건은 이름순/실행은 입력 키 순서로 정렬."""

        self._sort_events_with_feedback(
            event_key_sort_key,
            txt("Key Sort Complete", "키 순서 정렬 완료"),
            txt(
                "Events were sorted by:\nCondition → Name\nAction → Input Key",
                "이벤트를 다음 순서로 정렬했습니다:\n조건 → 이름\n실행 → 입력 키",
            ),
        )

    def _sort_events_by_group_name(self) -> None:
        """그룹 우선, 그룹 안에서는 이름 정렬. 그룹 없음은 마지막."""

        self._sort_events_with_feedback(
            event_group_name_sort_key,
            txt("Group / Name Sort Complete", "그룹/이름 정렬 완료"),
            txt(
                "Events were sorted by:\nGroup → Event Type → Name\nEvents without a group are last.",
                "이벤트를 다음 순서로 정렬했습니다:\n그룹 → 이벤트 타입 → 이름\n그룹 없는 이벤트는 맨 뒤입니다.",
            ),
        )

    def _sort_events_by_group_key(self) -> None:
        """그룹 우선, 그룹 안에서는 키 정렬. 그룹 없음은 마지막."""

        self._sort_events_with_feedback(
            event_group_key_sort_key,
            txt("Group / Key Sort Complete", "그룹/키 정렬 완료"),
            txt(
                "Events were sorted by:\nGroup → Condition/Name, Action/Key\nEvents without a group are last.",
                "이벤트를 다음 순서로 정렬했습니다:\n그룹 → 조건/이름, 실행/키\n그룹 없는 이벤트는 맨 뒤입니다.",
            ),
        )

    def _manage_groups(self) -> None:
        """그룹 관리 다이얼로그"""
        if not self._get_existing_groups():
            messagebox.showinfo(
                txt("Groups", "그룹"),
                txt(
                    "No groups yet.\nClick the 'No Group' cell in an event row to assign one.",
                    "아직 그룹이 없습니다.\n이벤트 행의 '그룹 없음' 칸을 클릭해 그룹을 지정하세요.",
                ),
                parent=self.win,
            )
            return
        GroupManagerDialog(
            master=self.win,
            get_group_counts=self._get_group_counts,
            rename_cb=self._rename_group,
            clear_cb=self._clear_group,
        )

    def _get_group_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.profile.event_list:
            if e.group_id:
                counts[e.group_id] = counts.get(e.group_id, 0) + 1
        return counts

    def _rename_group(self, old_name: str, new_name: str) -> tuple[bool, str]:
        target = new_name.strip()
        none_labels = {"(None)", txt("(None)", "(없음)")}
        if not target:
            return False, txt(
                "Group name cannot be empty.", "그룹 이름은 비워둘 수 없습니다."
            )
        if target in none_labels:
            return False, txt(f"'{target}' is reserved.", f"'{target}'은 예약어입니다.")
        if target.lower() != old_name.lower() and target.lower() in {
            g.lower() for g in self._get_existing_groups()
        }:
            return False, txt(
                f"'{target}' already exists.", f"'{target}' 이미 존재합니다."
            )

        changed = 0
        for e in self.profile.event_list:
            if e.group_id == old_name:
                e.group_id = target
                changed += 1
        if changed:
            self.update_events()
            self.save_cb(check_name=False)
        return True, ""

    def _clear_group(self, group_name: str) -> int:
        changed = 0
        for e in self.profile.event_list:
            if e.group_id == group_name:
                e.group_id = None
                changed += 1
        if changed:
            self.update_events()
            self.save_cb(check_name=False)
        return changed

    def _open_graph(self) -> None:
        self.save_names()
        name = self._get_profile_name()
        if self.graph_viewer and self.graph_viewer.is_open():
            self.graph_viewer.set_profile_name(name)
            self.graph_viewer.refresh(force=False)
            self.graph_viewer.lift()
            return
        self.graph_viewer = ProfileGraphViewer(
            parent=self.win,
            profile=self.profile,
            profile_name=name,
            profiles_dir=self.profiles_dir,
            name_getter=self._get_profile_name,
            on_close=lambda: setattr(self, "graph_viewer", None),
        )
        self.graph_viewer.refresh(force=False)

    def _on_group_select(self, row_num: int, event: EventModel) -> None:
        """그룹 선택 팝업 열기"""
        existing = self._get_existing_groups()

        def on_selected(new_group: str | None) -> None:
            event.group_id = new_group
            if 0 <= row_num < len(self.rows):
                self.rows[row_num].update_display()
            self.save_cb(check_name=False)

        GroupSelector(self.win, event.group_id, existing, on_selected)

    def _show_menu(self, event: tk.Event[tk.Misc], row_num: int) -> None:
        self.ctx_row = row_num
        event_obj = cast(Any, event)
        try:
            self.menu.tk_popup(event_obj.x_root, event_obj.y_root)
        finally:
            self.menu.grab_release()

    def _apply_pixel_batch(self) -> None:
        if self.ctx_row is None:
            return
        src = self.profile.event_list[self.ctx_row]
        if not (src.latest_position and src.clicked_position):
            messagebox.showwarning(
                txt("Warning", "경고"),
                txt("Invalid source event.", "유효하지 않은 원본 이벤트입니다."),
                parent=self.win,
            )
            return

        if not messagebox.askyesno(
            txt("Confirm", "확인"),
            txt(
                f"Apply info to all events with area {src.latest_position}?",
                f"영역 {src.latest_position}를 가진 모든 이벤트에 정보를 적용할까요?",
            ),
            parent=self.win,
        ):
            return

        cnt = 0
        for i, evt in enumerate(self.profile.event_list):
            if (
                i != self.ctx_row
                and evt.latest_position == src.latest_position
                and evt.held_screenshot
            ):
                try:
                    evt.clicked_position = src.clicked_position
                    evt.ref_pixel_value = cast(
                        tuple[int, ...],
                        evt.held_screenshot.getpixel(src.clicked_position),
                    )
                    evt.match_mode = getattr(src, "match_mode", "pixel")
                    evt.region_size = getattr(src, "region_size", None)
                    cnt += 1
                except Exception:
                    print(f"Skipped {evt.event_name}")

        if cnt:
            self.save_cb()
            messagebox.showinfo(
                txt("Success", "완료"),
                txt(f"{cnt} events updated.", f"{cnt}개 이벤트를 업데이트했습니다."),
                parent=self.win,
            )
        else:
            messagebox.showinfo(
                txt("Info", "안내"),
                txt("No matching events found.", "일치하는 이벤트가 없습니다."),
                parent=self.win,
            )

    def _create_header(self) -> None:
        """Compact row header aligned to EventRow's fixed grid columns."""
        header = ttk.Frame(self)
        header.grid(
            row=3,
            column=0,
            columnspan=2,
            padx=UI_PAD_MD,
            pady=(UI_PAD_SM, 0),
            sticky="ew",
        )
        tk.Frame(header, width=4).pack(side=tk.LEFT, fill="y", padx=(0, UI_PAD_SM))
        header_body = ttk.Frame(header)
        header_body.pack(side=tk.LEFT, fill="x", expand=True)
        header_body.grid_columnconfigure(2, weight=1)

        ttk.Label(header_body, text="", width=2).grid(row=0, column=0, sticky="ew")
        lbl_use = ttk.Label(
            header_body,
            text=txt("Use", "사용"),
            width=5,
            anchor="center",
        )
        lbl_use.grid(row=0, column=1, sticky="ew")
        ToolTip(
            lbl_use,
            txt("Uncheck to skip this event.", "체크 해제 시 이벤트를 건너뜁니다"),
        )

        lbl_name = ttk.Label(
            header_body,
            text=txt("Event", "이벤트"),
            anchor="w",
            width=EVENT_NAME_COL_WIDTH,
        )
        lbl_name.grid(row=0, column=2, sticky="ew", padx=(0, UI_PAD_SM))
        ToolTip(
            lbl_name,
            txt(
                "Event name, group, input key or condition marker, and toggle set membership.",
                "이벤트 이름, 그룹, 입력 키 또는 조건 표시, 토글 세트 포함 여부입니다.",
            ),
        )
        ttk.Label(
            header_body,
            text=txt("Group", "그룹"),
            width=EVENT_GROUP_COL_WIDTH,
            anchor="center",
        ).grid(row=0, column=3, sticky="ew", padx=(0, theme.SPACE_1))
        ttk.Label(
            header_body,
            text=txt("Key", "키"),
            width=EVENT_KEY_COL_WIDTH,
            anchor="center",
        ).grid(row=0, column=4, sticky="ew", padx=(0, theme.SPACE_1))
        ttk.Label(
            header_body,
            text=txt("Cond", "조건"),
            width=EVENT_COND_COL_WIDTH,
            anchor="center",
        ).grid(row=0, column=5, sticky="ew", padx=(0, theme.SPACE_1))
        ttk.Label(
            header_body,
            text=txt("Toggle", "토글"),
            width=EVENT_EXTRA_COL_WIDTH,
            anchor="center",
        ).grid(row=0, column=6, sticky="ew", padx=(0, theme.SPACE_1))

        lbl_actions = ttk.Label(
            header_body,
            text=txt("Actions", "동작"),
            width=EVENT_ACTIONS_COL_WIDTH,
            anchor="center",
        )
        lbl_actions.grid(row=0, column=7, sticky="ew")
        ToolTip(lbl_actions, txt("Edit / Copy / Delete", "편집 / 복사 / 삭제"))

        # 구분선
        ttk.Separator(self, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(20, 0), padx=UI_PAD_MD
        )

    def _create_scroll_area(self) -> None:
        self.event_canvas = tk.Canvas(
            self,
            borderwidth=0,
            highlightthickness=0,
            background=theme.SURFACE_PAPER,
        )
        self.event_canvas.grid(
            row=4,
            column=0,
            padx=(UI_PAD_MD, 0),
            pady=(UI_PAD_XS, 0),
            sticky="nsew",
        )
        self.event_scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=cast(Any, self.event_canvas).yview,
        )
        self.event_scrollbar.grid(
            row=4,
            column=1,
            padx=(UI_PAD_SM, UI_PAD_MD),
            pady=(UI_PAD_XS, 0),
            sticky="ns",
        )
        self.event_canvas.configure(yscrollcommand=self.event_scrollbar.set)
        self.event_rows_frame = ttk.Frame(self.event_canvas, style="Row.TFrame")
        self.event_rows_window = cast(Any, self.event_canvas).create_window(
            (0, 0), window=self.event_rows_frame, anchor="nw"
        )
        self.event_rows_frame.grid_columnconfigure(0, weight=1)
        self.event_rows_frame.bind("<Configure>", self._on_rows_frame_configure)
        self.event_canvas.bind("<Configure>", self._on_event_canvas_configure)
        self._bind_scroll_events(self.event_canvas)
        self._bind_scroll_events(self.event_rows_frame)

    def _on_rows_frame_configure(self, _event: tk.Event[tk.Misc]) -> None:
        self.event_canvas.configure(
            scrollregion=cast(Any, self.event_canvas).bbox("all")
        )

    def _on_event_canvas_configure(self, event: tk.Event[tk.Misc]) -> None:
        cast(Any, self.event_canvas).itemconfigure(
            self.event_rows_window, width=event.width
        )

    def _bind_scroll_events(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_event_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_event_mousewheel, add="+")
        widget.bind("<Button-5>", self._on_event_mousewheel, add="+")
        for child in widget.winfo_children():
            self._bind_scroll_events(child)

    def _on_event_mousewheel(self, event: tk.Event[tk.Misc]) -> str:
        event_obj = cast(Any, event)
        if getattr(event_obj, "num", None) == 4:
            step = -1
        elif getattr(event_obj, "num", None) == 5:
            step = 1
        else:
            delta = getattr(event_obj, "delta", 0)
            step = -1 if delta > 0 else 1
        self.event_canvas.yview_scroll(step, "units")
        return "break"

    def _load_events(self) -> None:
        for i, evt in enumerate(self.profile.event_list):
            self._add_row(i, evt)
        self._update_delete_buttons()
        self._sync_empty_state()
        self._refresh_row_layout()

    def _sync_empty_state(self) -> None:
        has_events = bool(self.profile.event_list)
        if has_events:
            if self.empty_state_frame and self.empty_state_frame.winfo_exists():
                self.empty_state_frame.grid_remove()
            return

        if not self.empty_state_frame or not self.empty_state_frame.winfo_exists():
            self.empty_state_frame = ttk.LabelFrame(
                self.event_rows_frame, text=txt("Getting Started", "처음 시작 가이드")
            )
            self.empty_state_frame.grid(
                row=0,
                column=0,
                padx=0,
                pady=(UI_PAD_MD, UI_PAD_SM),
                sticky="ew",
            )
            ttk.Label(
                self.empty_state_frame,
                text=txt(
                    "1) Add your first event with the '➕ Add Event' button.",
                    "1) '➕ 이벤트 추가' 버튼으로 첫 이벤트를 추가하세요.",
                ),
            ).pack(anchor="w", padx=10, pady=(8, 2))
            ttk.Label(
                self.empty_state_frame,
                text=txt(
                    "2) Configure capture and input key in the event editor.",
                    "2) 이벤트 편집기에서 캡처와 입력 키를 설정하세요.",
                ),
            ).pack(anchor="w", padx=10, pady=2)
            ttk.Label(
                self.empty_state_frame,
                text=txt(
                    "3) Done when the bottom save status shows '✅ Saved HH:MM:SS'.",
                    "3) 하단 저장 상태가 '✅ 저장됨 HH:MM:SS'로 바뀌면 완료입니다.",
                ),
            ).pack(anchor="w", padx=10, pady=2)
            ttk.Button(
                self.empty_state_frame,
                text=txt("➕ Add First Event", "➕ 첫 이벤트 추가"),
                command=self._add_event,
                style="Accent.TButton",
            ).pack(anchor="e", padx=10, pady=(6, 8))
        else:
            self.empty_state_frame.grid()

    @staticmethod
    def _empty_event_provider() -> EventModel | None:
        return None

    def _add_event(self) -> None:
        row_idx = len(self.profile.event_list)
        KeystrokeEventEditor(
            cast(tk.Tk | tk.Toplevel, self.win),
            row_idx,
            self._on_editor_save,
            self._empty_event_provider,
            existing_events=self.profile.event_list,
        )

    def _add_row(
        self,
        row_num: int | None = None,
        event: EventModel | None = None,
    ) -> None:
        if self.empty_state_frame and self.empty_state_frame.winfo_exists():
            self.empty_state_frame.grid_remove()
        idx = len(self.rows) if row_num is None else row_num
        def save_without_name_check() -> None:
            self.save_cb(check_name=False)

        cbs: EventRowCallbacks = {
            "open": self._open_editor,
            "copy": self._copy_row,
            "remove": self._remove_row,
            "menu": self._show_menu,
            "group_select": self._on_group_select,  # NEW
            "save": save_without_name_check,  # 추가
            "select": self._select_row,
        }
        row = EventRow(self.event_rows_frame, idx, event, cbs)
        row.grid(
            row=idx,
            column=0,
            padx=0,
            pady=(0, UI_PAD_XS),
            sticky="ew",
        )
        self._bind_scroll_events(row)
        self.rows.append(row)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _primary_selection(self) -> int | None:
        """The single row that row-scoped actions (edit, copy, delete) target."""
        if not self.selected_indices:
            return None
        if self.selection_anchor in self.selected_indices:
            return self.selection_anchor
        return min(self.selected_indices)

    def _select_row(self, index: int, mode: SelectMode = "replace") -> None:
        if not (0 <= index < len(self.profile.event_list)):
            return
        self.selected_indices, self.selection_anchor = resolve_selection(
            self.selected_indices, self.selection_anchor, index, mode
        )
        self._sync_row_selection()
        self._notify_selection()

    def clear_selection(self) -> None:
        self.selected_indices = set()
        self.selection_anchor = None
        self._sync_row_selection()
        self._notify_selection()

    def _notify_selection(self) -> None:
        if not self.select_cb:
            return
        index = self._primary_selection()
        single = index if len(self.selected_indices) == 1 else None
        if single is not None and 0 <= single < len(self.profile.event_list):
            self.select_cb(self.profile.event_list[single])
        else:
            self.select_cb(None)

    def _sync_row_selection(self) -> None:
        for i, row in enumerate(self.rows):
            row.set_selected(i in self.selected_indices)
        self._sync_bulk_bar()

    def _move_selection(self, delta: int) -> str:
        """Move the cursor through the *visible* rows so filtering and
        keyboard navigation agree."""
        visible = self.visible_indices()
        if not visible:
            return "break"
        current = self._primary_selection()
        if current is None or current not in visible:
            target = visible[0] if delta > 0 else visible[-1]
        else:
            position = visible.index(current) + delta
            position = max(0, min(len(visible) - 1, position))
            target = visible[position]
        self._select_row(target, "replace")
        self._scroll_row_into_view(target)
        if self._focus_is_text_entry():
            self.event_canvas.focus_set()
        return "break"

    def _scroll_row_into_view(self, index: int) -> None:
        if not (0 <= index < len(self.rows)):
            return
        row = self.rows[index]
        try:
            self.event_canvas.update_idletasks()
            total = self.event_rows_frame.winfo_height()
            if total <= 0:
                return
            top = row.winfo_y() / total
            bottom = (row.winfo_y() + row.winfo_height()) / total
            view_top, view_bottom = cast(Any, self.event_canvas).yview()
            if top < view_top:
                cast(Any, self.event_canvas).yview_moveto(top)
            elif bottom > view_bottom:
                span = view_bottom - view_top
                cast(Any, self.event_canvas).yview_moveto(max(0.0, bottom - span))
        except (tk.TclError, ZeroDivisionError):
            return

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    def visible_indices(self) -> list[int]:
        return filter_event_indices(self.profile.event_list, self.filter_state)

    def _on_search_changed(self, *_args: str) -> None:
        self.set_filter_state(
            dataclass_replace(self.filter_state, query=self.search_var.get()),
            notify=True,
        )

    def set_filter_state(
        self, state: EventFilterState, *, notify: bool = False
    ) -> None:
        self.filter_state = state
        if self.search_var.get() != state.query:
            self.search_var.set(state.query)
        self._refresh_row_layout()
        if notify and self.filter_change_cb:
            self.filter_change_cb(state)

    def clear_filters(self) -> None:
        self.set_filter_state(EventFilterState(), notify=True)

    def reveal_event(self, index: int) -> None:
        """Make sure a just-added or just-edited event is actually on screen.
        Without this a live filter silently swallows it."""
        if not (0 <= index < len(self.profile.event_list)):
            return
        event = self.profile.event_list[index]
        if self.filter_state.is_active() and not event_matches_filter(
            event, self.filter_state
        ):
            self.clear_filters()
            if self.status_cb:
                self.status_cb(
                    txt(
                        "Filter cleared so the event stays visible.",
                        "이벤트가 보이도록 필터를 해제했습니다.",
                    )
                )
        self._select_row(index, "replace")
        self._scroll_row_into_view(index)

    def _sync_filter_chrome(self, visible_count: int) -> None:
        total = len(self.profile.event_list)
        if self.filter_state.is_active():
            self.lbl_filter_summary.config(
                text=txt(
                    f"{visible_count} / {total}",
                    f"{visible_count} / {total}",
                )
            )
            self.btn_clear_filter.pack(side=tk.LEFT, padx=(UI_PAD_SM, 0))
        else:
            self.lbl_filter_summary.config(text="")
            self.btn_clear_filter.pack_forget()

    def open_editor_for(self, index: int) -> None:
        """Open the full editor for a row index (used by the inspector)."""
        if 0 <= index < len(self.profile.event_list):
            self._open_editor(index, self.profile.event_list[index])

    def _open_editor(self, row: int, evt: EventModel | None) -> None:
        def event_provider() -> EventModel:
            return cast(EventModel, evt)

        KeystrokeEventEditor(
            cast(tk.Tk | tk.Toplevel, self.win),
            row,
            self._on_editor_save,
            event_provider,
            existing_events=self.profile.event_list,
        )

    def _is_duplicate_event_name(
        self, name: str, ignore_index: int | None = None
    ) -> bool:
        target = normalized_event_name(name)
        if not target:
            return False
        for idx, evt in enumerate(self.profile.event_list):
            if ignore_index is not None and idx == ignore_index:
                continue
            if normalized_event_name(getattr(evt, "event_name", None)) == target:
                return True
        return False

    def _on_editor_save(self, evt: EventModel, is_edit: bool, row: int = 0) -> None:
        ignore_index = row if is_edit else None
        if self._is_duplicate_event_name(
            evt.event_name or "", ignore_index=ignore_index
        ):
            messagebox.showerror(
                txt("Duplicate Event Name", "중복 이벤트 이름"),
                txt(
                    "Event name '{name}' already exists in this profile.",
                    "이 프로필에 '{name}' 이벤트 이름이 이미 존재합니다.",
                    name=evt.event_name,
                ),
                parent=self.win,
            )
            return
        if is_edit and 0 <= row < len(self.profile.event_list):
            previous_event = self.profile.event_list[row]
            evt.use_event = bool(getattr(previous_event, "use_event", True))
            evt.runtime_toggle_member = bool(
                getattr(previous_event, "runtime_toggle_member", False)
            )
            old_name = previous_event.event_name
            self.profile.event_list[row] = evt
            new_name = evt.event_name
            if old_name and new_name and old_name != new_name:
                self._update_condition_references(old_name, new_name)
        else:
            self.profile.event_list.append(evt)
        self.update_events()
        self.save_cb(check_name=False)
        self.reveal_event(
            row if is_edit else len(self.profile.event_list) - 1
        )

    def _copy_row(self, evt: EventModel | None) -> None:
        if not evt:
            messagebox.showinfo(
                txt("Info", "안내"),
                txt(
                    "Only configured events can be copied.",
                    "설정된 이벤트만 복사할 수 있습니다.",
                ),
            )
            return
        try:
            new = clone_event(
                evt,
                event_name=f"{txt('Copy of', '복사본')} {evt.event_name}",
            )

            self.profile.event_list.append(new)
            self._add_row(event=new)
            self.save_cb()
            self._update_delete_buttons()
            self._refresh_row_layout()
            if self.status_cb:
                self.status_cb(txt("Event copied", "이벤트 복사됨"))
            self.reveal_event(len(self.profile.event_list) - 1)
        except Exception as e:
            messagebox.showerror(
                txt("Error", "오류"),
                txt(f"Copy failed: {e}", f"복사 실패: {e}"),
            )

    def _capture_condition_snapshot(self) -> list[tuple[EventModel, dict[str, bool]]]:
        """Remember every event's conditions so an undo can restore the
        references that deleting an event strips from its dependents."""
        return [(evt, dict(evt.conditions)) for evt in self.profile.event_list]

    def _delete_indices(self, indices: list[int]) -> int:
        """Delete the given positions, keeping at least one event alive.
        Returns how many were actually removed."""
        targets = sorted({i for i in indices if 0 <= i < len(self.profile.event_list)})
        keep_at_least_one = len(self.profile.event_list) - len(targets) < 1
        if keep_at_least_one:
            targets = targets[: max(0, len(self.profile.event_list) - 1)]
        if not targets:
            return 0

        snapshot = self._capture_condition_snapshot()
        removed_pairs = [(i, self.profile.event_list[i]) for i in targets]
        for index in reversed(targets):
            self.profile.event_list.pop(index)
        for _, removed in removed_pairs:
            name = getattr(removed, "event_name", None)
            if name and all(
                getattr(evt, "event_name", None) != name
                for evt in self.profile.event_list
            ):
                self._remove_condition_references(name)

        self._undo_delete = {"removed": removed_pairs, "conditions": snapshot}
        self.clear_selection()
        self.update_events()
        self.save_cb()
        self._announce_delete(len(removed_pairs), keep_at_least_one)
        return len(removed_pairs)

    def _announce_delete(self, count: int, hit_floor: bool) -> None:
        if not self.status_cb:
            return
        message = txt(f"{count} event(s) deleted", f"이벤트 {count}개 삭제됨")
        if hit_floor:
            message = txt(
                f"{count} event(s) deleted. The last event is kept.",
                f"이벤트 {count}개 삭제됨. 마지막 이벤트 1개는 남깁니다.",
            )
        def undo() -> None:
            self.undo_delete()

        self.status_cb(
            message,
            action_label=txt("Undo", "되돌리기"),
            action=undo,
        )

    def undo_delete(self) -> bool:
        """Restore the most recent delete, including condition references."""
        pending = self._undo_delete
        if not pending:
            return False
        self._undo_delete = None
        removed_pairs = cast(
            "list[tuple[int, EventModel]]", pending.get("removed") or []
        )
        for index, event in removed_pairs:
            position = min(index, len(self.profile.event_list))
            self.profile.event_list.insert(position, event)
        snapshot = cast(
            "list[tuple[EventModel, dict[str, bool]]]", pending.get("conditions") or []
        )
        for event, conditions in snapshot:
            event.conditions.clear()
            event.conditions.update(conditions)
        self.clear_selection()
        self.update_events()
        self.save_cb()
        if self.status_cb:
            self.status_cb(txt("Delete undone", "삭제를 되돌렸습니다"))
        return True

    def _remove_row(self, row_widget: EventRow, row_num: int) -> None:
        if len(self.profile.event_list) < 2:
            return
        self._delete_indices([row_num])
        self.win.update_idletasks()

    # ------------------------------------------------------------------
    # Bulk actions — operate on the current multi-selection.
    # ------------------------------------------------------------------
    def _selected_events(self) -> list[EventModel]:
        return [
            self.profile.event_list[i]
            for i in sorted(self.selected_indices)
            if 0 <= i < len(self.profile.event_list)
        ]

    def _bulk_set_group(self) -> None:
        events = self._selected_events()
        if not events:
            return
        current = events[0].group_id if len({e.group_id for e in events}) == 1 else None

        def on_selected(new_group: str | None) -> None:
            for event in events:
                event.group_id = new_group
            self.update_events()
            self.save_cb(check_name=False)
            if self.status_cb:
                label = new_group or txt("No Group", "그룹 없음")
                self.status_cb(
                    txt(
                        f"{len(events)} event(s) moved to {label}",
                        f"이벤트 {len(events)}개를 {label}(으)로 옮겼습니다",
                    )
                )

        GroupSelector(self.win, current, self._get_existing_groups(), on_selected)

    def _bulk_set_use(self, use: bool) -> None:
        events = self._selected_events()
        if not events:
            return
        for event in events:
            event.use_event = use
        self.update_events()
        self.save_cb(check_name=False)
        if self.status_cb:
            state = txt("on", "켜짐") if use else txt("off", "꺼짐")
            self.status_cb(
                txt(
                    f"Use set to {state} for {len(events)} event(s)",
                    f"이벤트 {len(events)}개의 사용을 {state}으로 바꿨습니다",
                )
            )

    def _bulk_toggle_runtime_member(self) -> None:
        """Make the whole selection match: if any row is out of the toggle set,
        add them all; otherwise remove them all."""
        events = self._selected_events()
        if not events:
            return
        target = not all(
            bool(getattr(e, "runtime_toggle_member", False)) for e in events
        )
        for event in events:
            event.runtime_toggle_member = target
        self.update_events()
        self.save_cb(check_name=False)
        if self.status_cb:
            state = txt("added to", "에 추가") if target else txt("removed from", "에서 제외")
            self.status_cb(
                txt(
                    f"{len(events)} event(s) {state} the toggle set",
                    f"이벤트 {len(events)}개를 토글 세트{state}했습니다",
                )
            )

    def _bulk_delete(self) -> None:
        indices = sorted(self.selected_indices)
        if not indices:
            return
        if not messagebox.askyesno(
            txt("Confirm", "확인"),
            txt(
                f"Delete {len(indices)} selected event(s)?",
                f"선택한 이벤트 {len(indices)}개를 삭제할까요?",
            ),
            parent=self.win,
        ):
            return
        self._delete_indices(indices)

    def _import(self, evts: list[EventModel]) -> None:
        self.profile.event_list.extend(evts)
        for e in evts:
            self._add_row(event=e)
        self._sync_empty_state()
        self._refresh_row_layout()
        self.save_cb()
        if evts:
            self.reveal_event(len(self.profile.event_list) - 1)

    def _update_row_indices(self) -> None:
        """행 인덱스 라벨 갱신 + 현재 필터에 맞춰 표시/숨김 재배치."""
        self._refresh_row_layout()

    def _refresh_row_layout(self) -> None:
        """Lay out only the rows that pass the filter. Row numbers stay tied to
        the profile's real positions so callbacks and the label keep matching."""
        visible = set(self.visible_indices())
        slot = 0
        for i, row in enumerate(self.rows):
            row.row_num = i
            row.lbl_index.config(text=str(i + 1))
            if i in visible:
                row.grid(
                    row=slot,
                    column=0,
                    padx=0,
                    pady=(0, UI_PAD_XS),
                    sticky="ew",
                )
                slot += 1
            else:
                row.grid_remove()
        self._sync_filter_chrome(len(visible))
        self._sync_no_match_state(bool(visible))

    def _sync_no_match_state(self, has_visible: bool) -> None:
        """Explain an empty list caused by filtering, and offer a way out."""
        if has_visible or not self.profile.event_list or not self.filter_state.is_active():
            if self.no_match_frame and self.no_match_frame.winfo_exists():
                self.no_match_frame.grid_remove()
            return
        if not self.no_match_frame or not self.no_match_frame.winfo_exists():
            self.no_match_frame = ttk.Frame(self.event_rows_frame)
            ttk.Label(
                self.no_match_frame,
                text=txt(
                    "No events match the current filter.",
                    "현재 필터와 일치하는 이벤트가 없습니다.",
                ),
                foreground=theme.INK_MUTED,
            ).pack(side=tk.LEFT, padx=(UI_PAD_MD, UI_PAD_SM), pady=UI_PAD_MD)
            ttk.Button(
                self.no_match_frame,
                text=txt("Clear filter", "필터 해제"),
                command=self.clear_filters,
            ).pack(side=tk.LEFT, pady=UI_PAD_MD)
        # Grid rows must stay adjacent, so sit right after the (hidden) rows.
        self.no_match_frame.grid(row=len(self.rows), column=0, sticky="ew")

    def _update_delete_buttons(self) -> None:
        can_delete = len(self.profile.event_list) > 1
        state = "normal" if can_delete else "disabled"
        hint = (
            txt("Delete this event.", "이 이벤트를 삭제합니다.")
            if can_delete
            else txt(
                "A profile needs at least one event, so the last one cannot be deleted.",
                "프로필에는 이벤트가 최소 1개 필요해서 마지막 이벤트는 삭제할 수 없습니다.",
            )
        )
        for row in self.rows:
            if row.btn_delete:
                row.btn_delete.config(state=state)
            if row.tip_delete:
                row.tip_delete.update_text(hint)

    def update_events(self) -> None:
        curr, new = len(self.rows), len(self.profile.event_list)

        # Update existing rows
        for i in range(min(curr, new)):
            self.rows[i].event = self.profile.event_list[i]
            self.rows[i].row_num = i
            self.rows[i].update_display()

        # Remove excess rows
        for r in self.rows[new:]:
            r.destroy()
        self.rows = self.rows[:new]

        # Add new rows
        for i in range(curr, new):
            self._add_row(i, self.profile.event_list[i])

        # Drop selection that the new list length no longer has.
        self.selected_indices = {i for i in self.selected_indices if i < new}
        if self.selection_anchor is not None and self.selection_anchor >= new:
            self.selection_anchor = None

        # Re-grid all rows and update indices
        self._update_row_indices()
        self._update_delete_buttons()
        self._sync_empty_state()
        self._sync_row_selection()
        self.win.update_idletasks()

    def save_names(self) -> None:
        for i, r in enumerate(self.rows):
            if i < len(self.profile.event_list):
                old_name = r.last_saved_name
                new_name = r.get_name()
                if old_name and new_name and old_name != new_name:
                    self._update_condition_references(old_name, new_name)
                self.profile.event_list[i].event_name = new_name
                r.last_saved_name = new_name

    def _update_condition_references(self, old_name: str, new_name: str) -> None:
        """이벤트 이름 변경 시 조건 참조 업데이트"""
        rename_condition_references(self.profile.event_list, old_name, new_name)

    def _remove_condition_references(self, removed_name: str) -> None:
        """삭제된 이벤트를 참조하는 조건을 제거"""
        remove_condition_references(self.profile.event_list, removed_name)
