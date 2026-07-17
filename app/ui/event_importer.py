from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from collections.abc import Callable
from typing import Any, cast

from loguru import logger
from app.utils.i18n import dual_text_width, txt

from app.core.models import EventModel, ProfileModel
from app.core.profile_events import clone_event
from app.storage.profile_storage import list_profile_names, load_profile
from app.utils.window_state import StateUtils
from app.ui import theme


class EventImporter:
    def __init__(
        self,
        profiles_window: tk.Toplevel,
        confirm_callback: Callable[[list[EventModel]], None] | None = None,
        *,
        profiles_dir: Path,
    ) -> None:
        self.win = tk.Toplevel(profiles_window)
        self.win.title(txt("Import Events", "이벤트 가져오기"))
        self.win.transient(profiles_window)  # 부모창 위에 뜨도록 설정
        self.win.focus_force()
        cast(Any, self.win).attributes("-topmost", True)
        self.win.grab_set()

        self.profile_dir = profiles_dir
        self.confirm_cb = confirm_callback
        self.checkboxes: list[tk.IntVar] = []
        self.current_profile_data: ProfileModel | None = None
        self.cb_prof: ttk.Combobox
        self.canvas: tk.Canvas
        self.f_events: ttk.Frame
        self.canvas_window: int
        self.btn_ok: ttk.Button
        self.lbl_selection_count: ttk.Label

        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", self.close)
        try:
            self.win.configure(bg=theme.SURFACE_PAPER)
        except tk.TclError:
            pass
        theme.install_styles(self.win)

        self.create_ui()
        self.load_profiles()
        self.load_pos()

    def create_ui(self) -> None:
        f = theme.fonts()
        # ContextBar — dialog title + role description to match the rest of
        # the workstation surface.
        bar = tk.Frame(
            self.win,
            bg=theme.SURFACE_PANEL,
            padx=theme.SPACE_3,
            pady=theme.SPACE_2,
        )
        bar.pack(fill="x", side="top")
        tk.Label(
            bar,
            text=txt("Import Events", "이벤트 가져오기"),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_PRIMARY,
            font=f["heading"],
        ).pack(side="left")
        tk.Label(
            bar,
            text=txt("Copy events from another profile", "다른 프로필에서 이벤트 복사"),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
        ).pack(side="left", padx=(theme.SPACE_3, 0))
        tk.Frame(self.win, bg=theme.SURFACE_DIVIDER, height=1).pack(fill="x")

        # 1. 프로필 선택 영역
        f_prof = ttk.Frame(self.win)
        f_prof.pack(pady=10, fill="x", padx=10)
        ttk.Label(f_prof, text=txt("Source Profile:", "원본 프로필:")).pack(side="left", padx=5)
        self.cb_prof = ttk.Combobox(f_prof, state="readonly")
        self.cb_prof.bind("<<ComboboxSelected>>", self.load_events)
        self.cb_prof.pack(side="left", padx=5, fill="x", expand=True)

        # 2. 이벤트 목록 영역 (스크롤바 추가)
        container = ttk.LabelFrame(
            self.win, text=txt("Select Events to Import", "가져올 이벤트 선택")
        )
        container.pack(pady=5, padx=10, fill="both", expand=True)

        self.canvas = tk.Canvas(container, highlightthickness=0)
        canvas_yview = cast(Any, self.canvas).yview
        scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=canvas_yview
        )

        # 캔버스 내부 프레임
        self.f_events = ttk.Frame(self.canvas)

        # 캔버스 윈도우 생성
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.f_events, anchor="nw"
        )

        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 스크롤 이벤트 바인딩
        self.f_events.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.win.bind_all("<MouseWheel>", self._on_mousewheel)

        # 3. 하단 RunDock — 분리선 + 패널 톤으로 메인 창과 동일 표면.
        tk.Frame(self.win, bg=theme.SURFACE_DIVIDER, height=1).pack(
            side="bottom", fill="x"
        )
        f_btn = tk.Frame(self.win, bg=theme.SURFACE_PANEL)
        f_btn.pack(side="bottom", fill="x", padx=0, pady=0, ipady=theme.SPACE_2)
        self.btn_ok = ttk.Button(
            f_btn,
            text=txt("Import", "가져오기"),
            width=dual_text_width("Import", "가져오기", padding=2, min_width=12),
            command=self.on_ok,
            style="Accent.TButton",
        )
        self.btn_ok.pack(side="left", padx=5)
        ttk.Button(
            f_btn,
            text=txt("Cancel", "취소"),
            width=dual_text_width("Cancel", "취소", padding=2, min_width=7),
            command=self.close,
            style="Outline.TButton",
        ).pack(side="left", padx=5)
        # All/None toggle rendered as a text link to keep the run-dock light.
        f = theme.fonts()
        link_all = tk.Label(
            f_btn,
            text=txt("Select / Deselect All", "전체 선택 / 해제"),
            bg=theme.SURFACE_PANEL,
            fg=theme.SIGNAL_BASE,
            cursor="hand2",
            font=(
                f["caption"].cget("family"),
                f["caption"].cget("size"),
                "underline",
            ),
        )
        link_all.pack(side="right", padx=theme.SPACE_2)
        link_all.bind("<Button-1>", lambda _e: self.toggle_all())
        self.lbl_selection_count = ttk.Label(
            f_btn,
            text="",
            foreground=theme.INK_MUTED,
        )
        self.lbl_selection_count.pack(side="right", padx=theme.SPACE_2)

    # --- 스크롤 관련 핸들러 ---
    def _on_frame_configure(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfig(self.canvas_window, width=cast(Any, event).width)

    def _on_mousewheel(self, event: tk.Event[tk.Misc]) -> None:
        if self.canvas.bbox("all")[3] > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-1 * (cast(Any, event).delta / 120)), "units")

    # -----------------------

    def load_profiles(self) -> None:
        self.profile_dir.mkdir(exist_ok=True)
        names = list_profile_names(self.profile_dir)
        self.cb_prof["values"] = names
        if names:
            self.cb_prof.current(0)
            self.load_events()
        else:
            self._refresh_selection_summary()

    def load_events(self, event: tk.Event[tk.Misc] | None = None) -> None:
        prof_name = self.cb_prof.get()
        if not prof_name:
            return

        # UI 초기화
        for w in self.f_events.winfo_children():
            w.destroy()
        self.checkboxes.clear()
        self.canvas.yview_moveto(0)  # 스크롤 초기화

        try:
            self.current_profile_data = load_profile(
                self.profile_dir, prof_name, migrate=True
            )
        except Exception as e:
            logger.error(f"Failed to load profile {prof_name}: {e}")
            self.current_profile_data = None

        if self.current_profile_data and self.current_profile_data.event_list:
            for i, evt in enumerate(self.current_profile_data.event_list):
                self._add_event_row(i, evt)
        self._refresh_selection_summary()

    def _add_event_row(self, idx: int, evt: EventModel) -> None:
        var = tk.IntVar()

        def _refresh_from_trace(*_args: str) -> None:
            self._refresh_selection_summary()

        var.trace_add("write", _refresh_from_trace)

        # Left color bar reflects the checked state of this row.
        bar = tk.Frame(self.f_events, bg=theme.SURFACE_DIVIDER, width=4)
        bar.grid(row=idx, column=0, sticky="ns", padx=(2, theme.SPACE_1))
        bar.grid_propagate(False)

        def _sync_bar(*_args: str) -> None:
            bar.configure(
                bg=theme.SIGNAL_BASE if var.get() else theme.SURFACE_DIVIDER
            )

        var.trace_add("write", _sync_bar)

        chk = ttk.Checkbutton(self.f_events, text=f"{idx + 1}", variable=var)
        chk.grid(row=idx, column=1, sticky="w", padx=(0, theme.SPACE_2), pady=2)

        e_name = ttk.Entry(self.f_events)
        e_name.insert(0, evt.event_name or "")
        e_name.config(state="readonly")
        e_name.grid(row=idx, column=2, padx=5, pady=2, sticky="ew")

        e_key = ttk.Entry(self.f_events, width=8, justify="center")
        e_key.insert(0, evt.key_to_enter or "")
        e_key.config(state="readonly")
        e_key.grid(row=idx, column=3, padx=5, pady=2)

        # Hover background transition: the bar widens visually by darkening
        # SURFACE_DIVIDER while the row is hovered (without affecting state).
        idle_bg = theme.SURFACE_DIVIDER
        hover_bg = theme.SURFACE_SUNKEN

        def _on_enter(_event: tk.Event[tk.Misc] | None = None) -> None:
            if not var.get():
                bar.configure(bg=hover_bg)

        def _on_leave(_event: tk.Event[tk.Misc] | None = None) -> None:
            if not var.get():
                bar.configure(bg=idle_bg)

        for w in (bar, chk, e_name, e_key):
            w.bind("<Enter>", _on_enter)
            w.bind("<Leave>", _on_leave)

        # 이름 컬럼이 늘어나도록 설정
        self.f_events.columnconfigure(2, weight=1)

        self.checkboxes.append(var)
        self._refresh_selection_summary()

    def _refresh_selection_summary(self) -> None:
        count = sum(1 for v in self.checkboxes if v.get())
        self.lbl_selection_count.config(
            text=txt(
                f"{count} selected",
                f"{count}개 선택됨",
            )
        )
        label = txt("Import", "가져오기")
        self.btn_ok.config(text=f"{label}{f' ({count})' if count else ''}")
        self.btn_ok.config(state="normal" if count else "disabled")

    def toggle_all(self) -> None:
        target = 1 if any(v.get() == 0 for v in self.checkboxes) else 0
        for v in self.checkboxes:
            v.set(target)
        self._refresh_selection_summary()

    def _copy_event(self, evt: EventModel) -> EventModel:
        return clone_event(evt)

    def on_ok(self) -> None:
        if not self.current_profile_data:
            return

        selected = [
            self._copy_event(self.current_profile_data.event_list[i])
            for i, var in enumerate(self.checkboxes)
            if var.get()
        ]

        if selected and self.confirm_cb:
            self.confirm_cb(selected)
            logger.info(f"Imported {len(selected)} events from '{self.cb_prof.get()}'")

        self.close()

    def close(self, event: tk.Event[tk.Misc] | None = None) -> None:
        self.win.unbind_all("<MouseWheel>")  # 마우스 휠 바인딩 해제
        StateUtils.save_main_app_state(
            importer_pos=f"{self.win.winfo_x()}/{self.win.winfo_y()}"
        )
        self.win.grab_release()
        self.win.destroy()

    def load_pos(self) -> None:
        pos = StateUtils.parse_slash_int_pair(
            StateUtils.load_main_app_state().get("importer_pos")
        )
        if pos is not None:
            self.win.geometry(f"500x600+{pos[0]}+{pos[1]}")  # 기본 크기 적용
        else:
            self.win.geometry("500x600")
