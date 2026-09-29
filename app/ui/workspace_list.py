"""작업 공간 가운데 목록: 신호/규칙 묶음, 드래그로 순서(=우선순위) 바꾸기."""

from __future__ import annotations

import tkinter as tk
import tkinter.ttk as ttk
from collections.abc import Callable, Sequence
from typing import Any, cast

from app.core.models import EventModel
from app.core.profile_events import (
    EventSection,
    build_event_sections,
    event_has_screen,
    event_matches_query,
    event_needs_attention,
    move_in_section,
    referenced_event_names,
)
from app.ui import theme
from app.utils.i18n import txt

DRAG_HANDLE = "⋮⋮"
_COND_SUMMARY_CHARS = 40

SelectCallback = Callable[[list[EventModel]], None]
ReorderCallback = Callable[[list[EventModel]], None]
ContextCallback = Callable[[tk.Event[tk.Misc], list[EventModel], EventSection | None], None]


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
    return txt(
        "Rules · no group — all run ({count})",
        "규칙 · 그룹 없음 — 모두 실행 ({count})",
        count=count,
    )


def condition_summary(event: EventModel, limit: int = _COND_SUMMARY_CHARS) -> str:
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
        badges.append("⏻")
    return badges


class EventTree(ttk.Frame):
    """묶음(부모 행) 아래 이벤트(자식 행)를 보여주는 Treeview."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_select: SelectCallback,
        on_reorder: ReorderCallback,
        on_context: ContextCallback,
        on_delete: Callable[[], object],
        on_copy: Callable[[], object],
        on_activate: Callable[[], object],
        on_drop_rejected: Callable[[], object],
    ) -> None:
        super().__init__(master)
        self.on_select = on_select
        self.on_reorder = on_reorder
        self.on_context = on_context
        self.on_drop_rejected = on_drop_rejected
        self.events: list[EventModel] = []
        self.sections: list[EventSection] = []
        self.query = ""
        self._event_by_iid: dict[str, EventModel] = {}
        self._iid_by_event: dict[int, str] = {}
        self._section_by_iid: dict[str, EventSection] = {}
        self._drag_iid: str | None = None
        self._drop_iid: str | None = None
        self._toggle_enabled = False

        style = ttk.Style(self)
        style.configure("Workspace.Treeview", rowheight=24)
        self.tree = ttk.Treeview(
            self,
            columns=("key", "detail", "badges"),
            selectmode="extended",
            style="Workspace.Treeview",
        )
        self.tree.heading("#0", text=txt("Name", "이름"), anchor="w")
        self.tree.heading("key", text=txt("Key", "키"), anchor="w")
        self.tree.heading("detail", text=txt("Conditions / screen", "조건 / 화면"), anchor="w")
        self.tree.heading("badges", text="", anchor="w")
        self.tree.column("#0", width=220, minwidth=140, stretch=True)
        self.tree.column("key", width=60, minwidth=40, stretch=False)
        self.tree.column("detail", width=220, minwidth=100, stretch=True)
        self.tree.column("badges", width=150, minwidth=80, stretch=False)
        f = theme.fonts()
        self.tree.tag_configure(
            "section", background=theme.SURFACE_PANEL, font=f["body_bold"]
        )
        self.tree.tag_configure("unused", foreground=theme.INK_MUTED)
        self.tree.tag_configure("attention", foreground=theme.STATUS_WARN_FG)
        self.tree.tag_configure("drop", background=theme.SIGNAL_TINT)
        scroll = ttk.Scrollbar(self, orient="vertical", command=cast(Any, self.tree).yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.lbl_empty = ttk.Label(self, text="", foreground=theme.INK_MUTED)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<ButtonPress-1>", self._on_press, add="+")
        self.tree.bind("<B1-Motion>", self._on_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_release, add="+")
        for seq in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.tree.bind(seq, self._on_context_click)
        for seq in ("<Delete>", "<BackSpace>"):
            self.tree.bind(seq, lambda _e: (on_delete(), "break")[1])
        for seq in ("<Command-d>", "<Control-d>"):
            self.tree.bind(seq, lambda _e: (on_copy(), "break")[1])
        self.tree.bind("<Return>", lambda _e: (on_activate(), "break")[1])
        self.tree.bind("<Double-Button-1>", lambda _e: on_activate())

    # -- data -----------------------------------------------------------------

    def set_events(
        self,
        events: Sequence[EventModel],
        *,
        toggle_enabled: bool,
        keep_selection: bool = True,
    ) -> None:
        selected = self.selected_events() if keep_selection else []
        self.events = list(events)
        self._toggle_enabled = toggle_enabled
        self._rebuild()
        if selected:
            self.select(selected, see=False)

    def set_query(self, query: str) -> None:
        self.query = query
        selected = self.selected_events()
        self._rebuild()
        self.select(selected, see=False)

    def _rebuild(self) -> None:
        tree = self.tree
        for iid in tree.get_children():
            tree.delete(iid)
        self._event_by_iid.clear()
        self._iid_by_event.clear()
        self._section_by_iid.clear()
        referenced = referenced_event_names(self.events)
        self.sections = build_event_sections(self.events)
        shown = 0
        for index, section in enumerate(self.sections):
            visible = [
                e for e in section.events if event_matches_query(e, self.query)
            ]
            if not visible:
                continue
            section_iid = f"section{index}"
            self._section_by_iid[section_iid] = section
            tree.insert(
                "",
                "end",
                iid=section_iid,
                text=section_title(section),
                open=True,
                tags=("section",),
            )
            for event in visible:
                iid = f"event{id(event)}"
                self._event_by_iid[iid] = event
                self._iid_by_event[id(event)] = iid
                tags: list[str] = []
                if not event.use_event:
                    tags.append("unused")
                elif event_needs_attention(event):
                    tags.append("attention")
                tree.insert(
                    section_iid,
                    "end",
                    iid=iid,
                    text=f"{DRAG_HANDLE} {event.event_name or ''}",
                    values=(
                        (event.key_to_enter or "") if event.execute_action else "",
                        row_detail(event),
                        " · ".join(
                            row_badges(
                                event,
                                referenced=(event.event_name or "") in referenced,
                                toggle_enabled=self._toggle_enabled,
                            )
                        ),
                    ),
                    tags=tuple(tags),
                )
                shown += 1
        self._sync_empty(shown)

    def _sync_empty(self, shown: int) -> None:
        if shown:
            self.lbl_empty.place_forget()
            return
        text = (
            txt("No events match the search.", "검색과 일치하는 이벤트가 없습니다.")
            if self.events
            else txt(
                "No events yet. Add a signal (screen watch) or a rule (key input).",
                "이벤트가 없습니다. 신호(화면 감시)나 규칙(키 입력)을 추가하세요.",
            )
        )
        self.lbl_empty.config(text=text)
        self.lbl_empty.place(relx=0.5, rely=0.3, anchor="center")

    # -- selection ------------------------------------------------------------

    def selected_events(self) -> list[EventModel]:
        return [
            self._event_by_iid[iid]
            for iid in self.tree.selection()
            if iid in self._event_by_iid
        ]

    def select(self, events: Sequence[EventModel], *, see: bool = True) -> None:
        iids = [
            self._iid_by_event[id(e)] for e in events if id(e) in self._iid_by_event
        ]
        self.tree.selection_set(iids)
        if iids:
            self.tree.focus(iids[0])
            if see:
                self.tree.see(iids[0])

    def section_of(self, event: EventModel) -> EventSection | None:
        for section in self.sections:
            if any(e is event for e in section.events):
                return section
        return None

    def _on_tree_select(self, _event: object | None = None) -> None:
        selection = self.tree.selection()
        headers = [iid for iid in selection if iid in self._section_by_iid]
        if headers:
            # 묶음 행은 선택 대상이 아니다.
            self.tree.selection_remove(headers)
            return
        self.on_select(self.selected_events())

    # -- drag -----------------------------------------------------------------

    def _on_press(self, event: tk.Event[tk.Misc]) -> None:
        iid = self.tree.identify_row(event.y)
        self._drag_iid = iid if iid in self._event_by_iid else None

    def _set_drop_target(self, iid: str | None) -> None:
        if self._drop_iid == iid:
            return
        if self._drop_iid is not None and self.tree.exists(self._drop_iid):
            tags = [t for t in self.tree.item(self._drop_iid, "tags") if t != "drop"]
            self.tree.item(self._drop_iid, tags=tags)
        self._drop_iid = iid
        if iid is not None:
            tags = [*self.tree.item(iid, "tags"), "drop"]
            self.tree.item(iid, tags=tags)

    def _on_motion(self, event: tk.Event[tk.Misc]) -> None:
        if self._drag_iid is None:
            return
        target = self.tree.identify_row(event.y)
        same_section = (
            target in self._event_by_iid
            and target != self._drag_iid
            and self.tree.parent(target) == self.tree.parent(self._drag_iid)
        )
        self._set_drop_target(target if same_section else None)

    def _on_release(self, event: tk.Event[tk.Misc]) -> None:
        drag = self._drag_iid
        self._drag_iid = None
        self._set_drop_target(None)
        if drag is None:
            return
        target = self.tree.identify_row(event.y)
        if not target or target == drag:
            return
        if target not in self._event_by_iid:
            return
        self.drop(drag, target)

    def drop(self, drag_iid: str, target_iid: str) -> None:
        """`drag_iid`를 `target_iid` 자리로 옮긴다. 같은 묶음 안에서만 된다."""
        if self.tree.parent(target_iid) != self.tree.parent(drag_iid):
            self.on_drop_rejected()
            return
        if self.query.strip():
            # 검색 중에는 보이는 행만으로 순서를 알 수 없다.
            self.on_drop_rejected()
            return
        section = self._section_by_iid.get(self.tree.parent(drag_iid))
        if section is None:
            return
        moved = self._event_by_iid[drag_iid]
        target = self._event_by_iid[target_iid]
        target_index = next(
            i for i, e in enumerate(section.events) if e is target
        )
        self.on_reorder(move_in_section(section.events, moved, target_index))

    # -- context menu ---------------------------------------------------------

    def _on_context_click(self, event: tk.Event[tk.Misc]) -> str:
        iid = self.tree.identify_row(event.y)
        section = self._section_by_iid.get(iid)
        if section is not None:
            self.on_context(event, [], section)
            return "break"
        if iid in self._event_by_iid and iid not in self.tree.selection():
            self.tree.selection_set([iid])
            self.tree.focus(iid)
        self.on_context(event, self.selected_events(), None)
        return "break"
