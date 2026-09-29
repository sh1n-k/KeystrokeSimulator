"""작업 공간: 프로필·실행 세트 관리와 이벤트 편집을 한 창에서 한다.

모달이 아니어서 게임 창과 번갈아 쓸 수 있다. 실행은 시작 시점에 불러온
프로필을 쓰므로, 실행 중 편집은 다음 시작부터 반영된다.
"""

from __future__ import annotations

import time
import tkinter as tk
import tkinter.ttk as ttk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, simpledialog
from typing import Any, cast

from loguru import logger
from PIL import Image, ImageTk

from app.core.models import EventModel, ProfileModel
from app.core.profile_events import (
    EventSection,
    apply_target_to_same_area,
    clone_event,
    copy_event_name,
    event_needs_attention,
    next_available_event_name,
    profile_fingerprint,
    remove_condition_references,
    rename_colliding_events,
    snapshot_events,
    sort_sections_by_name,
    write_section_order,
)
from app.core.validation import event_name_taken, find_duplicate_event_names
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
from app.ui import theme
from app.ui.capture_hud import CaptureHud, CaptureResult
from app.ui.event_graph import ensure_profile_graph_image
from app.ui.profile_settings import ProfileFrame, RuntimeToggleSettingsFrame
from app.ui.workspace_detail import EventDetailPanel, apply_capture
from app.ui.workspace_list import EventTree
from app.ui.workspace_sidebar import ItemKind, WorkspaceSidebar
from app.utils.i18n import txt
from app.utils.runtime_toggle import collect_runtime_toggle_validation_errors
from app.utils.window_state import StateUtils, WindowUtils

WORKSPACE_DEFAULT_GEOMETRY = "1180x720"
WORKSPACE_MIN_SIZE = (980, 600)
AUTOSAVE_DELAY_MS = 250
UNDO_LIMIT = 30

CatalogCallback = Callable[[str | None], None]


class GraphView(ttk.Frame):
    """목록 자리의 그래프 탭. 기존 PNG 렌더링을 그대로 쓴다."""

    def __init__(self, master: tk.Misc, cache_dir: Path) -> None:
        super().__init__(master)
        self.cache_dir = cache_dir
        self.photo: ImageTk.PhotoImage | None = None
        self.canvas = tk.Canvas(self, bg=theme.SURFACE_PAPER, highlightthickness=0)
        ys = ttk.Scrollbar(self, orient="vertical", command=cast(Any, self.canvas).yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=cast(Any, self.canvas).xview)
        self.canvas.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="we")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

    def show(self, profile: ProfileModel, name: str) -> None:
        try:
            path = ensure_profile_graph_image(profile, name or "profile", self.cache_dir)
            with Image.open(path) as img:
                img.load()
                view = img.copy()
        except Exception as exc:
            logger.error(f"Graph render failed: {exc}")
            self.canvas.delete("all")
            self.canvas.create_text(
                20, 20, anchor="nw", text=txt("Graph failed: {e}", "그래프 오류: {e}", e=exc)
            )
            return
        self.photo = ImageTk.PhotoImage(view, master=self.canvas)
        self.canvas.delete("all")
        cast(Any, self.canvas).create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.config(scrollregion=(0, 0, view.width, view.height))


class RunSetEditor(ttk.Frame):
    """실행 세트 구성 편집. 체크를 바꾸면 바로 저장한다."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_members_changed: Callable[[list[str]], bool],
        on_rename: Callable[[str], None],
    ) -> None:
        super().__init__(master)
        self.on_members_changed = on_members_changed
        self.on_rename = on_rename
        self.name = ""
        self.available: list[str] = []
        self.vars: dict[str, tk.BooleanVar] = {}
        header = ttk.Frame(self)
        header.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_3)
        ttk.Label(header, text=txt("Run set", "실행 세트")).pack(side="left")
        self.name_var = tk.StringVar(master=self)
        self.entry_name = ttk.Entry(header, textvariable=self.name_var, width=28)
        self.entry_name.pack(side="left", padx=(theme.SPACE_2, 0))
        self.entry_name.bind("<Return>", self._commit_name)
        self.entry_name.bind("<FocusOut>", self._commit_name)
        ttk.Label(
            self,
            text=txt(
                "Profiles checked here run together when this set is started.",
                "여기서 체크한 프로필이 이 세트를 시작할 때 함께 실행됩니다.",
            ),
            foreground=theme.INK_MUTED,
        ).pack(anchor="w", padx=theme.SPACE_3)
        self.list_frame = ttk.Frame(self)
        self.list_frame.pack(fill="both", expand=True, padx=theme.SPACE_3, pady=theme.SPACE_2)
        self.lbl_error = ttk.Label(self, text="", foreground=theme.STATUS_ERROR_FG)
        self.lbl_error.pack(anchor="w", padx=theme.SPACE_3, pady=(0, theme.SPACE_3))

    def load(self, name: str, members: list[str], available: list[str]) -> None:
        self.name = name
        self.available = available
        self.name_var.set(name)
        self.lbl_error.config(text="")
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.vars = {}
        chosen = set(members)
        for profile in available:
            var = tk.BooleanVar(master=self, value=profile in chosen)
            self.vars[profile] = var
            ttk.Checkbutton(
                self.list_frame,
                text=profile,
                variable=var,
                command=self._on_toggle,
            ).pack(anchor="w")

    def members(self) -> list[str]:
        return [name for name in self.available if self.vars[name].get()]

    def _on_toggle(self) -> None:
        if self.on_members_changed(self.members()):
            self.lbl_error.config(text="")
            return
        self.lbl_error.config(
            text=txt("Keep at least one profile.", "프로필을 하나 이상 남겨 두세요.")
        )

    def _commit_name(self, _event: object | None = None) -> None:
        new = self.name_var.get().strip()
        if new and new != self.name:
            self.on_rename(new)


class Workspace:
    def __init__(
        self,
        master: tk.Misc,
        *,
        profiles_dir: Path,
        run_sets_path: Path,
        running_getter: Callable[[], bool],
        settings_getter: Callable[[], object | None] = lambda: None,
        on_catalog_changed: CatalogCallback | None = None,
        on_close: Callable[[], object] | None = None,
        profile: str | None = None,
        run_set: str | None = None,
    ) -> None:
        self.master = master
        self.profiles_dir = profiles_dir
        self.run_sets_path = run_sets_path
        self.running_getter = running_getter
        self.settings_getter = settings_getter
        self.on_catalog_changed = on_catalog_changed
        self.on_close = on_close
        self.mode: ItemKind = "profile"
        self.prof_name = ""
        self.profile = ProfileModel(name="", event_list=[])
        self.run_set_name = ""
        self._last_saved_fingerprint: tuple[object, ...] | None = None
        self._autosave_after_id: str | None = None
        self._status_after_id: str | None = None
        self._undo: list[tuple[str, list[EventModel]]] = []
        self._options_open = False
        self._closed = False
        self.header_frame: ProfileFrame | None = None
        self.runtime_toggle_frame: RuntimeToggleSettingsFrame | None = None
        self.new_signal_hud: CaptureHud | None = None

        self.win = tk.Toplevel(master)
        self.win.geometry(WORKSPACE_DEFAULT_GEOMETRY)
        self.win.minsize(*WORKSPACE_MIN_SIZE)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        try:
            self.win.configure(bg=theme.SURFACE_PAPER)
        except tk.TclError:
            pass
        theme.install_styles(self.win)
        self._build()
        for seq in ("<Command-z>", "<Control-z>"):
            self.win.bind(seq, self._on_undo_key)
        for seq in ("<Command-f>", "<Control-f>"):
            self.win.bind(seq, lambda _e: (self.entry_search.focus_set(), "break")[1])
        self._restore_geometry()
        self.reload_catalog()
        if run_set and run_set in list_run_set_names(self.run_sets_path):
            self.open_run_set(run_set)
        else:
            self.open_profile(profile or QUICK_PROFILE_NAME)
        self.set_running(self.running_getter())

    # -- layout ---------------------------------------------------------------

    def _build(self) -> None:
        f = theme.fonts()
        top = tk.Frame(self.win, bg=theme.SURFACE_PANEL, padx=theme.SPACE_3, pady=theme.SPACE_2)
        top.pack(fill="x")
        self.header_host = tk.Frame(top, bg=theme.SURFACE_PANEL)
        self.header_host.pack(side="left", fill="x", expand=True)
        self.lbl_running = tk.Label(
            top,
            text=txt(
                "{icon} Running — edits apply from the next start",
                "{icon} 실행 중 — 편집 내용은 다음 시작부터 반영됩니다",
                icon=theme.STATUS_RUNNING_ICON,
            ),
            bg=theme.STATUS_RUNNING_BG,
            fg=theme.STATUS_RUNNING_FG,
            font=f["caption"],
            padx=theme.SPACE_2,
            pady=theme.SPACE_1,
        )
        self.options_bar = tk.Frame(self.win, bg=theme.SURFACE_PANEL)
        self.options_bar.pack(fill="x")
        self.lbl_options = tk.Label(
            self.options_bar,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.SIGNAL_BASE,
            font=f["caption"],
            cursor="hand2",
            anchor="w",
        )
        self.lbl_options.pack(fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_1))
        self.lbl_options.bind("<Button-1>", lambda _e: self._toggle_options())
        self.options_host = tk.Frame(self.options_bar, bg=theme.SURFACE_PANEL)
        tk.Frame(self.win, bg=theme.SURFACE_DIVIDER, height=1).pack(fill="x")

        # Status bar packs first so the body cannot squeeze it out.
        status = tk.Frame(self.win, bg=theme.SURFACE_PANEL, padx=theme.SPACE_3, pady=theme.SPACE_1)
        status.pack(side="bottom", fill="x")
        tk.Frame(self.win, bg=theme.SURFACE_DIVIDER, height=1).pack(side="bottom", fill="x")
        self.lbl_save = tk.Label(status, text="", bg=theme.SURFACE_PANEL, font=f["caption"], padx=theme.SPACE_2)
        self.lbl_save.pack(side="left")
        self.lbl_status = tk.Label(status, text="", bg=theme.SURFACE_PANEL, fg=theme.INK_MUTED, font=f["caption"])
        self.lbl_status.pack(side="left", padx=(theme.SPACE_2, 0))
        self.btn_undo = ttk.Button(status, text=txt("Undo", "되돌리기"), command=self.undo)
        self.btn_undo.pack(side="left", padx=(theme.SPACE_2, 0))
        self.lbl_counts = tk.Label(status, text="", bg=theme.SURFACE_PANEL, fg=theme.INK_SECONDARY, font=f["caption"])
        self.lbl_counts.pack(side="right")

        body = tk.Frame(self.win, bg=theme.SURFACE_PAPER)
        body.pack(fill="both", expand=True)
        self.sidebar = WorkspaceSidebar(
            body,
            on_select=self._on_sidebar_select,
            on_action=self._on_sidebar_action,
            on_new=self._on_sidebar_new,
        )
        self.sidebar.configure(width=210)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Frame(body, bg=theme.SURFACE_DIVIDER, width=1).pack(side="left", fill="y")

        self.detail_host = tk.Frame(body, bg=theme.SURFACE_PANEL, width=340)
        self.detail_host.pack(side="right", fill="y")
        self.detail_host.pack_propagate(False)
        self.detail_divider = tk.Frame(body, bg=theme.SURFACE_DIVIDER, width=1)
        self.detail_divider.pack(side="right", fill="y")
        self.detail = EventDetailPanel(
            self.detail_host,
            events_getter=lambda: self.profile.event_list,
            toggle_enabled_getter=lambda: bool(self.profile.runtime_toggle_enabled),
            running_getter=self.running_getter,
            on_change=self._on_event_changed,
            on_bulk=self._on_bulk,
        )
        self.detail.pack(fill="both", expand=True)

        self.center = tk.Frame(body, bg=theme.SURFACE_PAPER)
        self.center.pack(side="left", fill="both", expand=True)
        self.profile_view = tk.Frame(self.center, bg=theme.SURFACE_PAPER)
        toolbar = tk.Frame(self.profile_view, bg=theme.SURFACE_PAPER)
        toolbar.pack(fill="x", padx=theme.SPACE_2, pady=(theme.SPACE_2, 0))
        ttk.Label(toolbar, text=theme.ICON_SEARCH).pack(side="left")
        self.search_var = tk.StringVar(master=self.win)
        self.entry_search = ttk.Entry(toolbar, textvariable=self.search_var, width=18)
        self.entry_search.pack(side="left", padx=(theme.SPACE_1, theme.SPACE_2))
        self.search_var.trace_add("write", self._on_search_changed)
        self.entry_search.bind("<Escape>", lambda _e: self.search_var.set(""))
        ttk.Button(toolbar, text=txt("＋ Rule", "＋ 규칙"), command=self.add_rule).pack(side="right")
        ttk.Button(toolbar, text=txt("＋ Signal", "＋ 신호"), command=self.add_signal).pack(
            side="right", padx=(0, theme.SPACE_1)
        )
        ttk.Button(
            toolbar, text=txt("Sort by name", "이름순 정렬"), command=self.sort_by_name
        ).pack(side="right", padx=(0, theme.SPACE_2))

        self.tabs = ttk.Notebook(self.profile_view)
        self.tabs.pack(fill="both", expand=True, padx=theme.SPACE_2, pady=theme.SPACE_2)
        self.tree = EventTree(
            self.tabs,
            on_select=self.detail.show,
            on_reorder=self._on_reorder,
            on_context=self._on_list_context,
            on_delete=self.delete_selected,
            on_copy=self.copy_selected,
            on_activate=lambda: self.detail.entry_name.focus_set(),
            on_drop_rejected=lambda: self.show_status(
                txt(
                    "Drag within the same section (and clear the search first).",
                    "같은 묶음 안에서만 옮길 수 있습니다(검색 중에는 옮길 수 없습니다).",
                )
            ),
        )
        self.graph = GraphView(self.tabs, profiles_dir_cache(self.profiles_dir))
        self.tabs.add(self.tree, text=txt("List", "목록"))
        self.tabs.add(self.graph, text=txt("Graph", "그래프"))
        self.tabs.bind("<<NotebookTabChanged>>", lambda _e: self._refresh_graph_if_visible())
        self.menu = tk.Menu(self.win, tearoff=0)

        self.run_set_view = RunSetEditor(
            self.center,
            on_members_changed=self._on_run_set_members,
            on_rename=self._rename_current_run_set,
        )

    def _on_search_changed(self, *_args: str) -> None:
        self.tree.set_query(self.search_var.get())

    # -- catalog / sidebar ------------------------------------------------------

    def reload_catalog(self) -> None:
        profiles, favorites = ordered_profile_names(self.profiles_dir)
        current: tuple[ItemKind, str] | None = (
            ("profile", self.prof_name)
            if self.mode == "profile"
            else ("run_set", self.run_set_name)
        )
        self.sidebar.set_items(
            profiles, favorites, list_run_set_names(self.run_sets_path), current
        )

    def _notify_catalog(self, selected: str | None = None) -> None:
        self.reload_catalog()
        if self.on_catalog_changed is not None:
            self.on_catalog_changed(selected)

    def _on_sidebar_select(self, kind: ItemKind, name: str) -> None:
        if kind == "profile":
            self.open_profile(name)
        else:
            self.open_run_set(name)

    def _on_sidebar_new(self, kind: ItemKind) -> None:
        if kind == "profile":
            existing = set(list_profile_names(self.profiles_dir))
            name = self._ask_name(
                txt("New profile", "새 프로필"),
                next_available_event_name(txt("New profile", "새 프로필"), existing),
            )
            if name is None:
                return
            if name in existing:
                self._error(txt("'{n}' already exists.", "'{n}' 이미 있습니다.", n=name))
                return
            save_profile(self.profiles_dir, ProfileModel(name=name, event_list=[]), name=name)
            self._notify_catalog()
            self.open_profile(name)
            return
        existing = set(list_run_set_names(self.run_sets_path))
        members = [self.prof_name] if self.mode == "profile" and self.prof_name else [QUICK_PROFILE_NAME]
        name = self._ask_name(
            txt("New run set", "새 실행 세트"),
            next_available_event_name(txt("Run set", "실행 세트"), existing),
        )
        if name is None:
            return
        if name in existing:
            self._error(txt("'{n}' already exists.", "'{n}' 이미 있습니다.", n=name))
            return
        upsert_run_set(name, members, self.run_sets_path)
        self._notify_catalog()
        self.open_run_set(name)

    def _on_sidebar_action(self, kind: ItemKind, action: str, name: str) -> None:
        if action in ("rename", "delete") and self.running_getter():
            self._error(
                txt(
                    "Stop the run before renaming or deleting.",
                    "실행 중에는 이름을 바꾸거나 삭제할 수 없습니다.",
                )
            )
            return
        try:
            if kind == "profile":
                self._profile_action(action, name)
            else:
                self._run_set_action(action, name)
        except Exception as exc:
            self._error(str(exc))

    def _profile_action(self, action: str, name: str) -> None:
        if name == self.prof_name and self.mode == "profile" and not self.flush():
            return
        existing = set(list_profile_names(self.profiles_dir))
        if action == "copy":
            dst = next_available_event_name(f"{name} - {txt('Copy', '복사본')}", existing)
            copy_profile(self.profiles_dir, name, dst)
            self._notify_catalog()
            self.show_status(txt("Copied to '{n}'", "'{n}'(으)로 복사했습니다", n=dst))
        elif action == "favorite":
            if name == self.prof_name and self.mode == "profile" and self.header_frame is not None:
                self.header_frame.fav_var.set(not self.header_frame.fav_var.get())
                return
            profile = load_profile(self.profiles_dir, name, migrate=False)
            profile.favorite = not profile.favorite
            save_profile(self.profiles_dir, profile, name=name)
            self._notify_catalog()
        elif action == "rename":
            new = self._ask_name(txt("Rename profile", "프로필 이름 바꾸기"), name)
            if new is None or new == name:
                return
            if new in existing:
                raise ValueError(txt("'{n}' already exists.", "'{n}' 이미 있습니다.", n=new))
            if name == self.prof_name and self.mode == "profile" and self.header_frame is not None:
                self.header_frame.entry.delete(0, tk.END)
                self.header_frame.entry.insert(0, new)
                self._run_autosave(check_name=True)
                return
            rename_profile_files(self.profiles_dir, name, new)
            rename_profile_in_run_sets(name, new, self.run_sets_path)
            self._notify_catalog(new)
        elif action == "delete":
            if not messagebox.askokcancel(
                txt("Delete profile", "프로필 삭제"),
                txt("Delete profile '{n}'?", "프로필 '{n}'을(를) 삭제할까요?", n=name),
                parent=self.win,
            ):
                return
            if name == self.prof_name and self.mode == "profile":
                self.open_profile(QUICK_PROFILE_NAME)
            delete_profile_files(self.profiles_dir, name)
            self._notify_catalog()

    def _run_set_action(self, action: str, name: str) -> None:
        existing = set(list_run_set_names(self.run_sets_path))
        if action == "copy":
            dst = next_available_event_name(f"{name} - {txt('Copy', '복사본')}", existing)
            copy_run_set(name, dst, self.run_sets_path)
            self._notify_catalog()
        elif action == "rename":
            new = self._ask_name(txt("Rename run set", "실행 세트 이름 바꾸기"), name)
            if new is None or new == name:
                return
            rename_run_set(name, new, self.run_sets_path)
            if self.mode == "run_set" and self.run_set_name == name:
                self.run_set_name = new
                self.run_set_view.load(new, get_run_set(new, self.run_sets_path), self._all_profiles())
            self._notify_catalog()
        elif action == "delete":
            if not messagebox.askokcancel(
                txt("Delete run set", "실행 세트 삭제"),
                txt("Delete run set '{n}'?", "실행 세트 '{n}'을(를) 삭제할까요?", n=name),
                parent=self.win,
            ):
                return
            delete_run_set(name, self.run_sets_path)
            if self.mode == "run_set" and self.run_set_name == name:
                self.open_profile(self.prof_name or QUICK_PROFILE_NAME)
            self._notify_catalog()

    def _ask_name(self, title: str, initial: str) -> str | None:
        value = simpledialog.askstring(
            title, txt("Name:", "이름:"), initialvalue=initial, parent=self.win
        )
        if value is None:
            return None
        value = value.strip()
        return value or None

    def _all_profiles(self) -> list[str]:
        return ordered_profile_names(self.profiles_dir)[0]

    # -- opening --------------------------------------------------------------

    def open_profile(self, name: str) -> None:
        if self.mode == "profile" and name == self.prof_name and self.header_frame is not None:
            return
        if self.mode == "profile" and self.header_frame is not None and not self.flush():
            self.reload_catalog()
            return
        if name not in list_profile_names(self.profiles_dir):
            name = QUICK_PROFILE_NAME
        self.mode = "profile"
        self.prof_name = name
        try:
            self.profile = load_profile(self.profiles_dir, name, migrate=True)
        except Exception as exc:
            logger.error(f"Workspace load failed for {name}: {exc}")
            self.profile = ProfileModel(name=name, event_list=[])
        self._undo.clear()
        self._build_profile_header()
        self.run_set_view.pack_forget()
        self.profile_view.pack(fill="both", expand=True)
        self.detail_divider.pack(side="right", fill="y")
        self.detail_host.pack(side="right", fill="y", before=self.detail_divider)
        self.options_bar.pack(fill="x", after=self.header_host.master)
        self.search_var.set("")
        self.tree.set_events(
            self.profile.event_list,
            toggle_enabled=bool(self.profile.runtime_toggle_enabled),
            keep_selection=False,
        )
        self.detail.show([])
        self._last_saved_fingerprint = profile_fingerprint(
            self.profile, self.prof_name, self.profile.favorite
        )
        self._refresh_chrome()
        self._set_save_state("saved")
        self.sidebar.mark_current(("profile", name))
        self._refresh_graph_if_visible()

    def open_run_set(self, name: str) -> None:
        if self.mode == "run_set" and name == self.run_set_name:
            return
        if self.mode == "profile" and self.header_frame is not None and not self.flush():
            self.reload_catalog()
            return
        self.mode = "run_set"
        self.run_set_name = name
        for child in self.header_host.winfo_children():
            child.destroy()
        self.header_frame = None
        tk.Label(
            self.header_host,
            text=txt("Run set · {n}", "실행 세트 · {n}", n=name),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_PRIMARY,
            font=theme.fonts()["heading"],
        ).pack(side="left")
        self.options_bar.pack_forget()
        self.profile_view.pack_forget()
        self.detail_host.pack_forget()
        self.detail_divider.pack_forget()
        self.run_set_view.load(name, get_run_set(name, self.run_sets_path), self._all_profiles())
        self.run_set_view.pack(fill="both", expand=True)
        self.win.title(f"{txt('Workspace', '작업 공간')} - {name}")
        self.lbl_counts.config(text="")
        self._set_save_state("saved")
        self.sidebar.mark_current(("run_set", name))

    def _build_profile_header(self) -> None:
        for child in self.header_host.winfo_children():
            child.destroy()
        self.header_frame = ProfileFrame(
            self.header_host,
            self.prof_name,
            self.profile.favorite,
            on_change=self._on_header_changed,
            profiles_dir=self.profiles_dir,
        )
        self.header_frame.pack(side="left")
        if self.prof_name == QUICK_PROFILE_NAME:
            self.header_frame.entry.state(["disabled"])
        for child in self.options_host.winfo_children():
            child.destroy()
        self.runtime_toggle_frame = RuntimeToggleSettingsFrame(
            self.options_host, self.profile, on_change=self._on_options_changed
        )
        self.runtime_toggle_frame.pack(fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_2))
        self._sync_options_label()

    def _toggle_options(self) -> None:
        self._options_open = not self._options_open
        if self._options_open:
            self.options_host.pack(fill="x")
        else:
            self.options_host.pack_forget()
        self._sync_options_label()

    def _sync_options_label(self) -> None:
        mark = theme.ICON_EXPANDED if self._options_open else theme.ICON_COLLAPSED
        state = (
            txt("hotkey on/off: on", "단축키로 켜고 끄기: 사용")
            if self.profile.runtime_toggle_enabled
            else txt("hotkey on/off: off", "단축키로 켜고 끄기: 안 씀")
        )
        self.lbl_options.config(text=f"{mark} {txt('Run options', '실행 옵션')} · {state}")

    def _on_options_changed(self) -> None:
        if self.runtime_toggle_frame is not None:
            self.runtime_toggle_frame.apply_to_profile(self.profile)
        self._sync_options_label()
        self._refresh_list()
        self._on_changed()

    def _on_header_changed(self) -> None:
        self._on_changed(check_name=False)

    # -- running policy -------------------------------------------------------

    def set_running(self, running: bool) -> None:
        if self._closed:
            return
        if running:
            self.lbl_running.pack(side="right")
        else:
            self.lbl_running.pack_forget()
        if self.header_frame is not None:
            locked = running or self.prof_name == QUICK_PROFILE_NAME
            self.header_frame.entry.state(["disabled"] if locked else ["!disabled"])

    # -- list plumbing --------------------------------------------------------

    def _refresh_list(self) -> None:
        self.tree.set_events(
            self.profile.event_list,
            toggle_enabled=bool(self.profile.runtime_toggle_enabled),
        )
        self._refresh_chrome()

    def _refresh_chrome(self) -> None:
        events = self.profile.event_list
        rules = sum(1 for e in events if e.execute_action)
        signals = len(events) - rules
        missing = sum(1 for e in events if event_needs_attention(e))
        parts = [
            txt("Rules {n}", "규칙 {n}", n=rules),
            txt("Signals {n}", "신호 {n}", n=signals),
        ]
        if missing:
            parts.append(txt("No key {n}", "키 없음 {n}", n=missing))
        self.lbl_counts.config(text=" · ".join(parts))
        self.btn_undo.state(["!disabled"] if self._undo else ["disabled"])
        if self._undo:
            self.btn_undo.config(text=txt("Undo: {l}", "되돌리기: {l}", l=self._undo[-1][0]))
        else:
            self.btn_undo.config(text=txt("Undo", "되돌리기"))
        name = self.prof_name
        self.win.title(f"{txt('Workspace', '작업 공간')} - {name}")

    def _on_event_changed(self, event: EventModel, field: str) -> None:
        self._refresh_list()
        self._on_changed()

    def push_undo(self, label: str) -> None:
        self._undo.append((label, snapshot_events(self.profile.event_list)))
        del self._undo[:-UNDO_LIMIT]

    def undo(self) -> bool:
        if not self._undo:
            return False
        label, snapshot = self._undo.pop()
        self.profile.event_list[:] = snapshot
        self.tree.set_events(
            self.profile.event_list,
            toggle_enabled=bool(self.profile.runtime_toggle_enabled),
            keep_selection=False,
        )
        self.detail.show([])
        self._refresh_chrome()
        self._on_changed()
        self.show_status(txt("Undone: {l}", "되돌렸습니다: {l}", l=label))
        return True

    def _on_undo_key(self, _event: object | None = None) -> str | None:
        focus = self.win.focus_get()
        if focus is not None and focus.winfo_class() in ("Entry", "TEntry", "TSpinbox", "TCombobox"):
            return None
        self.undo()
        return "break"

    def _on_reorder(self, ordered: list[EventModel]) -> None:
        before = [e.priority for e in ordered]
        self.push_undo(txt("reorder", "순서 변경"))
        if not write_section_order(ordered):
            self._undo.pop()
            return
        logger.debug(f"Reordered priorities {before} -> {[e.priority for e in ordered]}")
        self._refresh_list()
        self.tree.select([ordered[0]] if not self.tree.selected_events() else self.tree.selected_events())
        self._on_changed()

    def sort_by_name(self) -> None:
        self.push_undo(txt("sort by name", "이름순 정렬"))
        if not sort_sections_by_name(self.profile.event_list):
            self._undo.pop()
            self.show_status(txt("Already in name order.", "이미 이름순입니다."))
            return
        self._refresh_list()
        self._on_changed()
        self.show_status(txt("Sorted each section by name.", "묶음마다 이름순으로 정렬했습니다."))

    # -- add / copy / delete --------------------------------------------------

    def _names(self) -> set[str]:
        return {e.event_name or "" for e in self.profile.event_list}

    def add_rule(self) -> None:
        name = next_available_event_name(txt("Rule", "규칙"), self._names())
        event = EventModel(event_name=name, execute_action=True)
        self._append([event], txt("add rule", "규칙 추가"))
        self.detail.entry_name.focus_set()
        self.detail.entry_name.select_range(0, tk.END)

    def add_signal(self) -> None:
        hud = self.new_signal_hud
        if hud is not None and hud.is_open():
            cast(Any, hud.win).lift()
            return
        name = next_available_event_name(txt("Signal", "신호"), self._names())
        state = {"name": name}

        def on_name(new: str) -> None:
            state["name"] = new

        def on_apply(result: CaptureResult) -> None:
            final = state["name"].strip() or name
            if event_name_taken(self.profile.event_list, final):
                final = next_available_event_name(final, self._names())
            event = EventModel(event_name=final, execute_action=False)
            apply_capture(event, result)
            self._append([event], txt("add signal", "신호 추가"))

        def on_close() -> None:
            self.new_signal_hud = None

        self.new_signal_hud = CaptureHud(
            self.win,
            mode="single",
            name=name,
            on_name_change=on_name,
            on_apply=on_apply,
            grab=True,
            border=not self.running_getter(),
            on_close=on_close,
        )

    def _append(self, events: list[EventModel], label: str) -> None:
        self.push_undo(label)
        self.profile.event_list.extend(events)
        self.search_var.set("")
        self._refresh_list()
        self.tree.select(events)
        self.detail.show(events)
        self._on_changed()

    def copy_selected(self) -> None:
        selected = self.tree.selected_events()
        if not selected:
            return
        copies: list[EventModel] = []
        for event in selected:
            name = copy_event_name(event.event_name or "", [*self.profile.event_list, *copies])
            copies.append(clone_event(event, event_name=name))
        self._append(copies, txt("copy", "복사"))
        self.show_status(txt("Copied {n} event(s)", "이벤트 {n}개를 복사했습니다", n=len(copies)))

    def delete_selected(self) -> None:
        selected = self.tree.selected_events()
        if not selected:
            return
        self.delete_events(selected)

    def delete_events(self, events: list[EventModel]) -> None:
        self.push_undo(txt("delete", "삭제"))
        doomed = {id(e) for e in events}
        self.profile.event_list[:] = [e for e in self.profile.event_list if id(e) not in doomed]
        for event in events:
            name = event.event_name or ""
            if name and not event_name_taken(self.profile.event_list, name):
                remove_condition_references(self.profile.event_list, name)
        self.detail.show([])
        self._refresh_list()
        self._on_changed()
        self.show_status(
            txt("Deleted {n} event(s). Undo with ⌘Z.", "이벤트 {n}개를 삭제했습니다. ⌘Z로 되돌립니다.", n=len(events))
        )

    def _on_bulk(self, action: str, value: object) -> None:
        events = self.tree.selected_events()
        if not events:
            return
        if action == "delete":
            self.delete_events(events)
            return
        self.push_undo(txt("bulk change", "일괄 변경"))
        for event in events:
            if action == "use":
                event.use_event = bool(value)
            elif action == "toggle":
                event.runtime_toggle_member = bool(value)
            elif action == "group" and event.execute_action:
                event.group_id = cast(str | None, value)
        self._refresh_list()
        self.detail.show(self.tree.selected_events())
        self._on_changed()

    # -- context menu ---------------------------------------------------------

    def _on_list_context(
        self, event: tk.Event[tk.Misc], selected: list[EventModel], section: EventSection | None
    ) -> None:
        menu = self.menu
        menu.delete(0, "end")
        if section is not None:
            if section.kind != "group":
                return
            menu.add_command(
                label=txt("Rename group…", "그룹 이름 바꾸기…"),
                command=lambda: self.rename_group(section.group),
            )
            menu.add_command(
                label=txt("Ungroup", "그룹 해제"),
                command=lambda: self.clear_group(section.group),
            )
        elif selected:
            menu.add_command(label=txt("Duplicate", "복사"), command=self.copy_selected)
            copy_menu = tk.Menu(menu, tearoff=0)
            for name in self._all_profiles():
                if name != self.prof_name:
                    copy_menu.add_command(
                        label=name, command=lambda n=name: self.copy_to_profile(n)
                    )
            menu.add_cascade(label=txt("Copy to profile", "다른 프로필로 복사"), menu=copy_menu)
            if len(selected) == 1 and selected[0].clicked_position is not None:
                menu.add_command(
                    label=txt("Apply target to same-area events", "같은 위치 이벤트에 대상 적용"),
                    command=lambda: self.apply_target(selected[0]),
                )
            menu.add_separator()
            menu.add_command(label=txt("Delete", "삭제"), command=self.delete_selected)
        else:
            return
        menu.tk_popup(event.x_root, event.y_root)

    def rename_group(self, old: str) -> None:
        new = self._ask_name(txt("Rename group", "그룹 이름 바꾸기"), old)
        if new is None or new == old:
            return
        existing = {(e.group_id or "").strip().casefold() for e in self.profile.event_list}
        if new.casefold() != old.casefold() and new.casefold() in existing:
            self._error(txt("'{n}' already exists.", "'{n}' 이미 있습니다.", n=new))
            return
        self.push_undo(txt("rename group", "그룹 이름 변경"))
        for event in self.profile.event_list:
            if (event.group_id or "").strip() == old:
                event.group_id = new
        self._refresh_list()
        self._on_changed()

    def clear_group(self, group: str) -> None:
        self.push_undo(txt("ungroup", "그룹 해제"))
        for event in self.profile.event_list:
            if (event.group_id or "").strip() == group:
                event.group_id = None
        self._refresh_list()
        self._on_changed()

    def copy_to_profile(self, target: str) -> None:
        events = self.tree.selected_events()
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
            self._error(txt("Copy failed: {e}", "복사 실패: {e}", e=exc))
            return
        message = txt(
            "Copied {n} event(s) to '{p}'", "'{p}'에 이벤트 {n}개를 복사했습니다", n=len(copies), p=target
        )
        if renamed:
            message += txt(
                " ({n} renamed)", " (이름 {n}개 변경)", n=len(renamed)
            )
        self.show_status(message)

    def apply_target(self, source: EventModel) -> None:
        self.push_undo(txt("apply target", "대상 적용"))
        count = apply_target_to_same_area(self.profile.event_list, source)
        if not count:
            self._undo.pop()
            self.show_status(txt("No other events at that area.", "같은 위치의 다른 이벤트가 없습니다."))
            return
        self._refresh_list()
        self._on_changed()
        self.show_status(txt("Updated {n} event(s)", "이벤트 {n}개를 바꿨습니다", n=count))

    # -- run set --------------------------------------------------------------

    def _on_run_set_members(self, members: list[str]) -> bool:
        if not members:
            return False
        upsert_run_set(self.run_set_name, members, self.run_sets_path)
        self._set_save_state("saved")
        if self.on_catalog_changed is not None:
            self.on_catalog_changed(None)
        return True

    def _rename_current_run_set(self, new: str) -> None:
        old = self.run_set_name
        try:
            rename_run_set(old, new, self.run_sets_path)
        except Exception as exc:
            self._error(str(exc))
            self.run_set_view.name_var.set(old)
            return
        self.run_set_name = new
        self.run_set_view.name = new
        self._notify_catalog()
        self.open_run_set(new)

    # -- saving ---------------------------------------------------------------

    def _on_changed(self, check_name: bool = False) -> None:
        if self.mode != "profile":
            return
        self._set_save_state("saving")
        if self._autosave_after_id is not None:
            self.win.after_cancel(self._autosave_after_id)
        self._autosave_after_id = self.win.after(
            AUTOSAVE_DELAY_MS, lambda: self._run_autosave(check_name=check_name)
        )

    def _run_autosave(self, check_name: bool = False) -> bool:
        self._autosave_after_id = None
        try:
            self._save(check_name=check_name)
        except Exception as exc:
            self._set_save_state("error", str(exc))
            return False
        self._set_save_state("saved")
        self._refresh_graph_if_visible()
        return True

    def flush(self) -> bool:
        """예약된 저장을 지금 한다. 실패하면 이유를 보이고 False."""
        if self.mode != "profile" or self.header_frame is None:
            return True
        if self._autosave_after_id is not None:
            self.win.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
        self.detail.show(self.tree.selected_events())  # commits a half-typed name
        if self._run_autosave(check_name=True):
            return True
        messagebox.showerror(txt("Save failed", "저장 실패"), self.lbl_status.cget("text"), parent=self.win)
        return False

    def _save(self, check_name: bool = False) -> None:
        header = self.header_frame
        if header is None:
            return
        new_name, favorite = header.get_data()
        new_name = new_name.strip()
        if check_name and not new_name:
            raise ValueError(txt("Enter profile name", "프로필 이름을 입력하세요"))
        if not new_name:
            new_name = self.prof_name
        duplicates = find_duplicate_event_names(self.profile.event_list)
        if duplicates:
            raise ValueError(
                txt(
                    "Duplicate event names are not allowed: {names}",
                    "중복 이벤트 이름은 허용되지 않습니다: {names}",
                    names=", ".join(duplicates),
                )
            )
        errors = collect_runtime_toggle_validation_errors(
            self.profile,
            list(self.profile.event_list),
            settings=cast(Any, self.settings_getter()),
        )
        if errors:
            raise ValueError(errors[0])
        renamed = new_name != self.prof_name
        if renamed:
            if self.running_getter():
                raise ValueError(
                    txt("Stop the run before renaming.", "실행 중에는 이름을 바꿀 수 없습니다.")
                )
            if (self.profiles_dir / f"{new_name}.json").exists():
                raise ValueError(txt("'{n}' already exists.", "'{n}' 이미 있습니다.", n=new_name))
            rename_profile_files(self.profiles_dir, self.prof_name, new_name)
            rename_profile_in_run_sets(self.prof_name, new_name, self.run_sets_path)
            self.prof_name = new_name
        favorite_changed = bool(favorite) != bool(self.profile.favorite)
        self.profile.favorite = bool(favorite)
        self.profile.name = self.prof_name
        fingerprint = profile_fingerprint(self.profile, self.prof_name, self.profile.favorite)
        if renamed or fingerprint != self._last_saved_fingerprint:
            save_profile(self.profiles_dir, self.profile, name=self.prof_name)
            self._last_saved_fingerprint = fingerprint
            if renamed or favorite_changed:
                self._notify_catalog(self.prof_name)
            elif self.on_catalog_changed is not None:
                self.on_catalog_changed(None)
        self._refresh_chrome()

    def _set_save_state(self, state: str, detail: str = "") -> None:
        if state == "saving":
            self.lbl_save.config(text=txt("Saving…", "저장 중…"), bg=theme.STATUS_WARN_BG, fg=theme.STATUS_WARN_FG)
        elif state == "saved":
            self.lbl_save.config(
                text=txt("Saved {t}", "저장됨 {t}", t=time.strftime("%H:%M:%S")),
                bg=theme.STATUS_READY_BG,
                fg=theme.STATUS_READY_FG,
            )
        else:
            self.lbl_save.config(text=txt("Save failed", "저장 실패"), bg=theme.STATUS_ERROR_BG, fg=theme.STATUS_ERROR_FG)
            self.lbl_status.config(text=detail, fg=theme.STATUS_ERROR_FG)

    def show_status(self, text: str, duration_ms: int = 6000) -> None:
        self.lbl_status.config(text=text, fg=theme.INK_SECONDARY)
        if self._status_after_id is not None:
            self.win.after_cancel(self._status_after_id)
        self._status_after_id = self.win.after(duration_ms, self._clear_status)

    def _clear_status(self) -> None:
        self._status_after_id = None
        try:
            self.lbl_status.config(text="")
        except tk.TclError:
            pass

    def _error(self, message: str) -> None:
        messagebox.showerror(txt("Error", "오류"), message, parent=self.win)

    def _refresh_graph_if_visible(self) -> None:
        if self.mode != "profile" or self._closed:
            return
        try:
            visible = str(cast(Any, self.tabs).select()) == str(self.graph)
        except tk.TclError:
            return
        if visible:
            self.graph.show(self.profile, self.prof_name)

    # -- lifecycle ------------------------------------------------------------

    def select_item(self, kind: ItemKind, name: str) -> None:
        cast(Any, self.win).lift()
        if kind == "profile":
            self.open_profile(name)
        else:
            self.open_run_set(name)

    def is_open(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _restore_geometry(self) -> None:
        state = StateUtils.load_main_app_state() or {}
        pos = StateUtils.parse_slash_int_pair(state.get("workspace_pos"))
        size = StateUtils.parse_slash_int_pair(state.get("workspace_size"))
        if pos is not None and size is not None:
            self.win.geometry(f"{size[0]}x{size[1]}+{pos[0]}+{pos[1]}")
        else:
            WindowUtils.center_window(self.win)

    def close(self) -> None:
        if self._closed:
            return
        if not self.flush():
            return
        self._closed = True
        for hud in (self.detail.capture_hud, self.new_signal_hud):
            if hud is not None:
                hud.close()
        try:
            StateUtils.save_main_app_state(
                workspace_pos=f"{self.win.winfo_x()}/{self.win.winfo_y()}",
                workspace_size=f"{self.win.winfo_width()}/{self.win.winfo_height()}",
            )
        except tk.TclError:
            pass
        self.win.destroy()
        if self.on_close is not None:
            self.on_close()


def profiles_dir_cache(profiles_dir: Path) -> Path:
    return profiles_dir / "_graphs"
