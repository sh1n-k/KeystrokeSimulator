"""작업 공간 오른쪽 상세 패널: 선택한 이벤트를 바로 편집한다."""

from __future__ import annotations

import tkinter as tk
import tkinter.ttk as ttk
from collections.abc import Callable
from typing import Any, cast

from PIL import Image, ImageTk

from app.core.models import EventModel, Position
from app.core.profile_events import event_has_screen, rename_condition_references
from app.core.validation import (
    MIN_REGION_SIZE,
    condition_cycle_if_added,
    event_name_taken,
    normalized_event_name,
    region_limits,
    timing_is_valid,
)
from app.ui import theme
from app.ui.capture_hud import CaptureHud, CaptureResult, render_overlay
from app.utils.i18n import txt
from app.utils.keys import KeyUtils

ChangeCallback = Callable[[EventModel, str], None]
BulkCallback = Callable[[str, object], None]

THUMB_MAX = 160
PANEL_WRAP = 280


def event_issues(event: EventModel) -> list[str]:
    """실행되지 않는 이유. 비어 있으면 실행할 수 있다."""
    issues: list[str] = []
    if event.execute_action:
        if not (event.key_to_enter or "").strip():
            issues.append(txt("No input key: this rule cannot run.", "키 없음: 이 규칙은 실행되지 않습니다."))
        if not event_has_screen(event) and not event.conditions:
            issues.append(
                txt(
                    "Add a condition or capture a screen trigger.",
                    "조건을 추가하거나 화면 트리거를 캡처하세요.",
                )
            )
    elif not event_has_screen(event):
        issues.append(
            txt("A signal needs a screen. Capture one.", "신호에는 화면이 필요합니다. 캡처하세요.")
        )
    if event.match_mode == "region" and event.held_screenshot is None:
        issues.append(txt("Region mode needs a capture.", "영역 모드에는 캡처본이 필요합니다."))
    return issues


def capture_from_event(event: EventModel) -> CaptureResult | None:
    if (
        event.latest_position is None
        or event.clicked_position is None
        or event.held_screenshot is None
        or event.ref_pixel_value is None
    ):
        return None
    return CaptureResult(
        position=event.latest_position,
        capture_size=event.capture_size or event.held_screenshot.size,
        image=event.held_screenshot,
        pixel=event.clicked_position,
        color=event.ref_pixel_value,
    )


def apply_capture(event: EventModel, result: CaptureResult) -> None:
    event.latest_position = result.position
    event.clicked_position = result.pixel
    event.held_screenshot = result.image
    event.ref_pixel_value = result.color
    event.capture_size = result.capture_size
    clamp_region(event)


def clear_capture(event: EventModel) -> None:
    event.latest_position = None
    event.clicked_position = None
    event.held_screenshot = None
    event.ref_pixel_value = None
    event.match_mode = "pixel"
    event.invert_match = False
    event.region_size = None


def clamp_region(event: EventModel) -> None:
    """영역 크기를 캡처본 안으로 줄인다. 캡처가 없으면 그대로 둔다."""
    if event.match_mode != "region" or event.held_screenshot is None:
        return
    if event.clicked_position is None:
        return
    max_w, max_h = region_limits(event.held_screenshot.size, event.clicked_position)
    w, h = event.region_size or (100, 100)
    event.region_size = (
        max(min(MIN_REGION_SIZE, max_w), min(w, max_w)),
        max(min(MIN_REGION_SIZE, max_h), min(h, max_h)),
    )


def _is_digits(value: str) -> bool:
    return value == "" or value.isdigit()


class ScrollFrame(ttk.Frame):
    """세로 스크롤 되는 내용 프레임."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.canvas = tk.Canvas(
            self, borderwidth=0, highlightthickness=0, bg=theme.SURFACE_PANEL
        )
        bar = ttk.Scrollbar(self, orient="vertical", command=cast(Any, self.canvas).yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=theme.SURFACE_PANEL)
        window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width)
        )
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(seq, self._on_wheel, add="+")

    def _on_wheel(self, event: tk.Event[tk.Misc]) -> None:
        widget = cast(Any, event).widget
        try:
            inside = str(widget).startswith(str(self.canvas))
        except (tk.TclError, AttributeError):
            return
        if not inside or self.body.winfo_height() <= self.canvas.winfo_height():
            return
        num = getattr(event, "num", None)
        step = (-1 if num == 4 else 1) if num in (4, 5) else (-1 if event.delta > 0 else 1)
        self.canvas.yview_scroll(step, "units")


class EventDetailPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        events_getter: Callable[[], list[EventModel]],
        toggle_enabled_getter: Callable[[], bool],
        running_getter: Callable[[], bool],
        on_change: ChangeCallback,
        on_bulk: BulkCallback,
    ) -> None:
        super().__init__(master)
        self.events_getter = events_getter
        self.toggle_enabled_getter = toggle_enabled_getter
        self.running_getter = running_getter
        self.on_change = on_change
        self.on_bulk = on_bulk
        self.event: EventModel | None = None
        self.selection: list[EventModel] = []
        self.capture_hud: CaptureHud | None = None
        self._syncing = False
        self._thumb: ImageTk.PhotoImage | None = None
        self._advanced_open = False

        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True)
        body = self.scroll.body
        f = theme.fonts()

        self.lbl_title = tk.Label(
            body,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_PRIMARY,
            font=f["heading"],
            anchor="w",
            justify="left",
            wraplength=PANEL_WRAP,
        )
        self.lbl_title.pack(fill="x", pady=(theme.SPACE_3, theme.SPACE_2), padx=theme.SPACE_3)

        # --- single-event editor ---------------------------------------------
        self.editor = tk.Frame(body, bg=theme.SURFACE_PANEL)
        self._build_editor(self.editor)

        # --- multi-selection actions -----------------------------------------
        self.bulk = tk.Frame(body, bg=theme.SURFACE_PANEL)
        self._build_bulk(self.bulk)

        self.lbl_placeholder = tk.Label(
            body,
            text=txt(
                "Select an event to edit it here. ↑/↓ moves between events.",
                "이벤트를 선택하면 여기에서 바로 편집합니다. ↑/↓로 이동합니다.",
            ),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            anchor="w",
            justify="left",
            wraplength=PANEL_WRAP,
        )
        self.show([])

    # -- layout ---------------------------------------------------------------

    def _label(self, parent: tk.Misc, text: str, *, muted: bool = True) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED if muted else theme.INK_PRIMARY,
            font=theme.fonts()["caption"],
            anchor="w",
        )

    def _build_editor(self, parent: tk.Frame) -> None:
        grid = tk.Frame(parent, bg=theme.SURFACE_PANEL)
        grid.pack(fill="x", padx=theme.SPACE_3)
        grid.grid_columnconfigure(1, weight=1)

        self._label(grid, txt("Name", "이름")).grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(master=self)
        self.entry_name = ttk.Entry(grid, textvariable=self.name_var)
        self.entry_name.grid(row=0, column=1, sticky="we", pady=2)
        self.entry_name.bind("<FocusOut>", self._commit_name)
        self.entry_name.bind("<Return>", self._commit_name)
        self.lbl_name_error = tk.Label(
            grid,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.STATUS_ERROR_FG,
            font=theme.fonts()["caption"],
            anchor="w",
            wraplength=PANEL_WRAP,
            justify="left",
        )
        self.lbl_name_error.grid(row=1, column=1, sticky="w")

        self._label(grid, txt("Type", "종류")).grid(row=2, column=0, sticky="w")
        self.kind_var = tk.StringVar(master=self, value="rule")
        f_kind = tk.Frame(grid, bg=theme.SURFACE_PANEL)
        f_kind.grid(row=2, column=1, sticky="w", pady=2)
        for value, label in (
            ("signal", txt("Signal", "신호")),
            ("rule", txt("Rule", "규칙")),
        ):
            ttk.Radiobutton(
                f_kind,
                text=label,
                value=value,
                variable=self.kind_var,
                command=self._on_kind_changed,
            ).pack(side="left", padx=(0, theme.SPACE_2))

        self.lbl_key = self._label(grid, txt("Key", "키"))
        self.lbl_key.grid(row=3, column=0, sticky="w")
        self.key_var = tk.StringVar(master=self)
        self.combo_key = ttk.Combobox(
            grid,
            textvariable=self.key_var,
            state="readonly",
            values=KeyUtils.get_key_name_list(),
            width=12,
        )
        self.combo_key.grid(row=3, column=1, sticky="w", pady=2)
        self.combo_key.bind("<<ComboboxSelected>>", self._on_key_changed)
        self.combo_key.bind("<KeyPress>", self._on_key_typed)

        self.lbl_group = self._label(grid, txt("Group", "그룹"))
        self.lbl_group.grid(row=4, column=0, sticky="w")
        self.group_var = tk.StringVar(master=self)
        self.combo_group = ttk.Combobox(grid, textvariable=self.group_var, width=16)
        self.combo_group.grid(row=4, column=1, sticky="w", pady=2)
        for seq in ("<<ComboboxSelected>>", "<FocusOut>", "<Return>"):
            self.combo_group.bind(seq, self._on_group_changed)
        self.lbl_group_hint = tk.Label(
            grid,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=theme.fonts()["caption"],
            anchor="w",
            justify="left",
            wraplength=PANEL_WRAP,
        )
        self.lbl_group_hint.grid(row=5, column=1, sticky="w")

        f_flags = tk.Frame(parent, bg=theme.SURFACE_PANEL)
        f_flags.pack(fill="x", pady=(theme.SPACE_1, 0), padx=theme.SPACE_3)
        self.use_var = tk.BooleanVar(master=self, value=True)
        ttk.Checkbutton(
            f_flags,
            text=txt("In use", "사용"),
            variable=self.use_var,
            command=self._on_use_changed,
        ).pack(side="left", padx=(0, theme.SPACE_3))
        self.toggle_var = tk.BooleanVar(master=self, value=False)
        self.chk_toggle = ttk.Checkbutton(
            f_flags,
            text=txt("Hotkey on/off set", "단축키로 켜고 끄기"),
            variable=self.toggle_var,
            command=self._on_toggle_changed,
        )

        # --- conditions ---
        self._section_header(parent, txt("Conditions", "조건"))
        self.cond_list = tk.Frame(parent, bg=theme.SURFACE_PANEL)
        self.cond_list.pack(fill="x", padx=theme.SPACE_3)
        self.btn_add_cond = ttk.Menubutton(parent, text=txt("＋ Add condition", "＋ 조건 추가"))
        self.btn_add_cond.pack(anchor="w", pady=(theme.SPACE_1, 0), padx=theme.SPACE_3)
        self.cond_menu = tk.Menu(self.btn_add_cond, tearoff=0, postcommand=self._fill_condition_menu)
        self.btn_add_cond.configure(menu=self.cond_menu)

        # --- screen ---
        self._section_header(parent, txt("Screen", "화면"))
        f_screen = tk.Frame(parent, bg=theme.SURFACE_PANEL)
        f_screen.pack(fill="x", padx=theme.SPACE_3)
        thumb_border = tk.Frame(f_screen, bg=theme.SURFACE_DIVIDER, padx=1, pady=1)
        thumb_border.pack(anchor="w")
        self.lbl_thumb = tk.Label(
            thumb_border, bg=theme.SURFACE_SUNKEN, highlightthickness=0, bd=0
        )
        self.lbl_thumb.pack()
        f_info = tk.Frame(f_screen, bg=theme.SURFACE_PANEL)
        f_info.pack(fill="x", pady=(theme.SPACE_1, 0))
        self.lbl_swatch = tk.Label(
            f_info,
            width=2,
            bg=theme.SURFACE_SUNKEN,
            highlightthickness=1,
            highlightbackground=theme.SURFACE_DIVIDER,
        )
        self.lbl_swatch.pack(side="left")
        self.lbl_screen = tk.Label(
            f_info,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_SECONDARY,
            font=theme.fonts()["caption"],
            anchor="w",
            justify="left",
        )
        self.lbl_screen.pack(side="left", padx=(theme.SPACE_1, 0))
        f_screen_btns = tk.Frame(f_screen, bg=theme.SURFACE_PANEL)
        f_screen_btns.pack(anchor="w", pady=(theme.SPACE_1, 0))
        ttk.Button(
            f_screen_btns,
            text=txt("Capture…", "캡처…"),
            command=self.open_capture,
            style="Accent.TButton",
        ).pack(side="left", padx=(0, theme.SPACE_1))
        self.btn_clear_screen = ttk.Button(
            f_screen_btns,
            text=txt("Clear", "지우기"),
            command=self._on_clear_screen,
            style="Outline.TButton",
        )
        self.btn_clear_screen.pack(side="left")

        # --- advanced ---
        self.lbl_advanced = tk.Label(
            parent,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.SIGNAL_BASE,
            font=theme.fonts()["caption"],
            anchor="w",
            cursor="hand2",
        )
        self.lbl_advanced.pack(fill="x", pady=(theme.SPACE_3, 0), padx=theme.SPACE_3)
        self.lbl_advanced.bind("<Button-1>", lambda _e: self._toggle_advanced())
        self.advanced = tk.Frame(parent, bg=theme.SURFACE_PANEL)
        self._build_advanced(self.advanced)

        self.lbl_issues = tk.Label(
            parent,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.STATUS_WARN_FG,
            font=theme.fonts()["caption"],
            anchor="w",
            justify="left",
            wraplength=PANEL_WRAP,
        )
        self.lbl_issues.pack(fill="x", pady=(theme.SPACE_3, theme.SPACE_3), padx=theme.SPACE_3)

    def _build_advanced(self, parent: tk.Frame) -> None:
        grid = tk.Frame(parent, bg=theme.SURFACE_PANEL)
        grid.pack(fill="x", padx=theme.SPACE_3)
        vcmd = (self.register(_is_digits), "%P")
        self.dur_var = tk.StringVar(master=self)
        self.rand_var = tk.StringVar(master=self)
        for row, (label, var) in enumerate(
            (
                (txt("Press time (ms, min 50)", "누름 시간 (ms, 최소 50)"), self.dur_var),
                (txt("Random (ms, min 30)", "랜덤 (ms, 최소 30)"), self.rand_var),
            )
        ):
            self._label(grid, label).grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(
                grid, textvariable=var, width=6, validate="key", validatecommand=vcmd
            )
            entry.grid(row=row, column=1, sticky="w", pady=1, padx=(theme.SPACE_1, 0))
            entry.bind("<FocusOut>", self._commit_timing)
            entry.bind("<Return>", self._commit_timing)
        self._label(
            grid,
            txt("Blank uses the global timing.", "비워 두면 전역 타이밍을 씁니다."),
        ).grid(row=2, column=0, columnspan=2, sticky="w")
        self.lbl_timing_error = tk.Label(
            grid,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.STATUS_ERROR_FG,
            font=theme.fonts()["caption"],
            anchor="w",
        )
        self.lbl_timing_error.grid(row=3, column=0, columnspan=2, sticky="w")

        self.invert_var = tk.BooleanVar(master=self)
        self.chk_invert = ttk.Checkbutton(
            parent,
            text=txt("Trigger when the color differs", "색이 다를 때"),
            variable=self.invert_var,
            command=self._on_invert_changed,
        )
        self.chk_invert.pack(anchor="w", padx=theme.SPACE_3, pady=(theme.SPACE_1, 0))

        f_mode = tk.Frame(parent, bg=theme.SURFACE_PANEL)
        f_mode.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_1, 0))
        self._label(f_mode, txt("Match", "매칭")).pack(side="left", padx=(0, theme.SPACE_1))
        self.mode_var = tk.StringVar(master=self, value="pixel")
        self.mode_buttons: list[ttk.Radiobutton] = []
        for value, label in (
            ("pixel", txt("Pixel", "픽셀")),
            ("region", txt("Region", "영역")),
        ):
            button = ttk.Radiobutton(
                f_mode,
                text=label,
                value=value,
                variable=self.mode_var,
                command=self._on_mode_changed,
            )
            button.pack(side="left", padx=(0, theme.SPACE_2))
            self.mode_buttons.append(button)
        f_region = tk.Frame(parent, bg=theme.SURFACE_PANEL)
        f_region.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_1, 0))
        self._label(f_region, txt("Region W×H", "영역 가로×세로")).pack(side="left")
        self.region_w_var = tk.StringVar(master=self)
        self.region_h_var = tk.StringVar(master=self)
        self.region_spins: list[ttk.Spinbox] = []
        for var in (self.region_w_var, self.region_h_var):
            spin = ttk.Spinbox(
                f_region, textvariable=var, from_=MIN_REGION_SIZE, to=1000, width=5
            )
            spin.pack(side="left", padx=(theme.SPACE_1, 0))
            for seq in ("<FocusOut>", "<Return>", "<<Increment>>", "<<Decrement>>"):
                spin.bind(seq, self._on_region_size_changed)
            self.region_spins.append(spin)

    def _build_bulk(self, parent: tk.Frame) -> None:
        for text, action, value in (
            (txt("Turn on", "사용 켜기"), "use", True),
            (txt("Turn off", "사용 끄기"), "use", False),
            (txt("Add to hotkey set", "단축키 묶음에 넣기"), "toggle", True),
            (txt("Remove from hotkey set", "단축키 묶음에서 빼기"), "toggle", False),
            (txt("Delete", "삭제"), "delete", None),
        ):
            ttk.Button(
                parent,
                text=text,
                command=lambda a=action, v=value: self.on_bulk(a, v),
                style="Outline.TButton",
            ).pack(anchor="w", padx=theme.SPACE_3)
        f_group = tk.Frame(parent, bg=theme.SURFACE_PANEL)
        f_group.pack(anchor="w", padx=theme.SPACE_3, pady=(theme.SPACE_2, 0))
        self._label(f_group, txt("Group", "그룹")).pack(side="left")
        self.bulk_group_var = tk.StringVar(master=self)
        self.combo_bulk_group = ttk.Combobox(
            f_group, textvariable=self.bulk_group_var, width=14
        )
        self.combo_bulk_group.pack(side="left", padx=(theme.SPACE_1, 0))
        ttk.Button(
            f_group,
            text=txt("Set", "지정"),
            command=lambda: self.on_bulk("group", self.bulk_group_var.get().strip() or None),
        ).pack(side="left", padx=(theme.SPACE_1, 0))

    def _section_header(self, parent: tk.Misc, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_SECONDARY,
            font=theme.fonts()["body_bold"],
            anchor="w",
        ).pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_3, theme.SPACE_1))

    # -- showing --------------------------------------------------------------

    def show(self, selection: list[EventModel]) -> None:
        """선택이 바뀔 때. 편집 중인 이름은 먼저 확정한다."""
        if self.event is not None and not self._syncing:
            self._commit_name()
        self.selection = list(selection)
        self.event = selection[0] if len(selection) == 1 else None
        for frame in (self.editor, self.bulk, self.lbl_placeholder):
            frame.pack_forget()
        if self.event is not None:
            self.editor.pack(fill="x")
            self.refresh()
        elif selection:
            self.lbl_title.config(
                text=txt("{count} selected", "{count}개 선택됨", count=len(selection))
            )
            groups = sorted({(e.group_id or "").strip() for e in self._events()} - {""})
            self.combo_bulk_group.config(values=groups)
            self.bulk.pack(fill="x")
        else:
            self.lbl_title.config(text=txt("Details", "상세"))
            self.lbl_placeholder.pack(fill="x", padx=theme.SPACE_3)

    def _events(self) -> list[EventModel]:
        return self.events_getter()

    def refresh(self) -> None:
        event = self.event
        if event is None:
            return
        self._syncing = True
        try:
            is_rule = bool(event.execute_action)
            self.lbl_title.config(text=event.event_name or txt("(unnamed)", "(이름 없음)"))
            if self.focus_get() is not self.entry_name:
                self.name_var.set(event.event_name or "")
                self.lbl_name_error.config(text="")
            self.kind_var.set("rule" if is_rule else "signal")
            self.key_var.set(event.key_to_enter or "")
            self.combo_key.config(state="readonly" if is_rule else "disabled")
            groups = sorted({(e.group_id or "").strip() for e in self._events()} - {""})
            self.combo_group.config(values=groups, state="normal" if is_rule else "disabled")
            if self.focus_get() is not self.combo_group:
                self.group_var.set((event.group_id or "").strip())
            self.lbl_group_hint.config(text=self._group_hint(event))
            self.use_var.set(bool(event.use_event))
            self.toggle_var.set(bool(event.runtime_toggle_member))
            if self.toggle_enabled_getter():
                self.chk_toggle.pack(side="left")
            else:
                self.chk_toggle.pack_forget()
            self._refresh_conditions()
            self._refresh_screen()
            self._refresh_advanced()
            issues = event_issues(event)
            self.lbl_issues.config(
            text="\n".join(f"{theme.STATUS_WARN_ICON} {i}" for i in issues)
        )
        finally:
            self._syncing = False

    @staticmethod
    def _group_hint(event: EventModel) -> str:
        if not event.execute_action:
            return txt(
                "Signals only feed conditions; groups apply to rules.",
                "신호는 조건으로만 쓰입니다. 그룹은 규칙에만 적용됩니다.",
            )
        if (event.group_id or "").strip():
            return txt(
                "Only one rule per group runs: the highest in the list.",
                "그룹에서는 목록 위쪽 규칙 하나만 실행됩니다.",
            )
        return txt(
            "No group: every matching rule runs, so order does not matter.",
            "그룹 없음: 조건이 맞는 규칙이 모두 실행되어 순서가 상관없습니다.",
        )

    def _refresh_conditions(self) -> None:
        event = self.event
        for child in self.cond_list.winfo_children():
            child.destroy()
        if event is None:
            return
        if not event.conditions:
            self._label(self.cond_list, txt("None", "없음")).pack(anchor="w")
            return
        for name, state in list(event.conditions.items()):
            row = tk.Frame(self.cond_list, bg=theme.SURFACE_PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(
                row,
                text=name,
                bg=theme.SURFACE_PANEL,
                fg=theme.INK_PRIMARY,
                anchor="w",
            ).pack(side="left", fill="x", expand=True)
            state_var = tk.StringVar(
                master=row, value=self._state_label(state)
            )
            combo = ttk.Combobox(
                row,
                textvariable=state_var,
                state="readonly",
                width=6,
                values=[self._state_label(True), self._state_label(False)],
            )
            combo.pack(side="left", padx=(theme.SPACE_1, 0))
            combo.bind(
                "<<ComboboxSelected>>",
                lambda _e, n=name, v=state_var: self._set_condition(
                    n, v.get() == self._state_label(True)
                ),
            )
            ttk.Button(
                row,
                text=theme.ICON_REMOVE,
                width=2,
                command=lambda n=name: self._remove_condition(n),
            ).pack(side="left", padx=(theme.SPACE_1, 0))

    @staticmethod
    def _state_label(state: bool) -> str:
        return txt("on", "켜짐") if state else txt("off", "꺼짐")

    def _refresh_screen(self) -> None:
        event = self.event
        if event is None:
            return
        image = event.held_screenshot
        if image is None:
            size = THUMB_MAX * 3 // 4
            shown = Image.new("RGB", (size, size // 2), theme.SURFACE_SUNKEN)
        else:
            region = event.region_size if event.match_mode == "region" else None
            shown = render_overlay(image, event.clicked_position, region)
            shown.thumbnail((THUMB_MAX, THUMB_MAX))
        self._thumb = ImageTk.PhotoImage(shown, master=self.lbl_thumb)
        self.lbl_thumb.configure(image=cast(Any, self._thumb), width=shown.width, height=shown.height)
        color = event.ref_pixel_value
        self.lbl_swatch.config(
            bg="#{:02x}{:02x}{:02x}".format(*(int(c) for c in color[:3]))
            if color
            else theme.SURFACE_SUNKEN
        )
        if event_has_screen(event):
            pos = cast(Position, event.latest_position)
            pixel = cast(Position, event.clicked_position)
            rgb = ",".join(str(int(c)) for c in color[:3]) if color else "—"
            self.lbl_screen.config(text=f"{rgb}  ({pos[0] + pixel[0]}, {pos[1] + pixel[1]})")
            self.btn_clear_screen.state(["!disabled"])
        else:
            self.lbl_screen.config(
                text=txt("No screen trigger", "화면 트리거 없음")
                if event.execute_action
                else txt("No screen yet", "화면 없음")
            )
            self.btn_clear_screen.state(["disabled"])

    def _refresh_advanced(self) -> None:
        event = self.event
        if event is None:
            return
        self.dur_var.set("" if event.press_duration_ms is None else str(int(event.press_duration_ms)))
        self.rand_var.set("" if event.randomization_ms is None else str(int(event.randomization_ms)))
        self.lbl_timing_error.config(text="")
        self.invert_var.set(bool(event.invert_match))
        self.mode_var.set(event.match_mode or "pixel")
        has_image = event.held_screenshot is not None and event.clicked_position is not None
        for button in self.mode_buttons:
            button.state(["!disabled"] if has_image else ["disabled"])
        self.chk_invert.state(["!disabled"] if event_has_screen(event) else ["disabled"])
        region = event.region_size or (100, 100)
        self.region_w_var.set(str(region[0]))
        self.region_h_var.set(str(region[1]))
        region_state = ["!disabled"] if event.match_mode == "region" and has_image else ["disabled"]
        for spin in self.region_spins:
            spin.state(region_state)
        customized = bool(
            event.press_duration_ms
            or event.randomization_ms
            or event.invert_match
            or event.match_mode == "region"
        )
        mark = theme.ICON_EXPANDED if self._advanced_open else theme.ICON_COLLAPSED
        dot = " ·" if customized else ""
        self.lbl_advanced.config(text=f"{mark} {txt('Advanced', '고급')}{dot}")

    def _toggle_advanced(self) -> None:
        self._advanced_open = not self._advanced_open
        if self._advanced_open:
            self.advanced.pack(fill="x", after=self.lbl_advanced)
        else:
            self.advanced.pack_forget()
        self._refresh_advanced()

    # -- commits --------------------------------------------------------------

    def _changed(self, field: str) -> None:
        if self.event is None:
            return
        self.on_change(self.event, field)
        self.refresh()

    def _commit_name(self, _event: object | None = None) -> str | None:
        event = self.event
        if event is None or self._syncing:
            return None
        new_name = normalized_event_name(self.name_var.get())
        old_name = event.event_name or ""
        if new_name == old_name:
            self.lbl_name_error.config(text="")
            return None
        if not new_name:
            self.lbl_name_error.config(text=txt("Enter a name.", "이름을 입력하세요."))
            return "break"
        if event_name_taken(self._events(), new_name, ignore=event):
            self.lbl_name_error.config(
                text=txt(
                    "'{name}' already exists.", "'{name}' 이름이 이미 있습니다.", name=new_name
                )
            )
            return "break"
        self.lbl_name_error.config(text="")
        event.event_name = new_name
        if old_name:
            rename_condition_references(self._events(), old_name, new_name)
        self._changed("name")
        return None

    def _on_kind_changed(self) -> None:
        if self.event is None or self._syncing:
            return
        self.event.execute_action = self.kind_var.get() == "rule"
        self._changed("kind")

    def _on_key_changed(self, _event: object | None = None) -> None:
        if self.event is None or self._syncing:
            return
        self.event.key_to_enter = self.key_var.get() or None
        self._changed("key")

    def _on_key_typed(self, event: tk.Event[tk.Misc]) -> None:
        """키 이름을 타이핑해 고른다(F1~F12 포함)."""
        key = (event.keysym or event.char).upper()
        values = [str(v) for v in cast(Any, self.combo_key).cget("values")]
        if key.startswith("F") and key[1:].isdigit() and key in values:
            self.key_var.set(key)
        elif char := event.char.upper():
            match = next((v for v in values if v.startswith(char)), None)
            if match is None:
                return
            self.key_var.set(match)
        else:
            return
        self._on_key_changed()

    def _on_group_changed(self, _event: object | None = None) -> None:
        event = self.event
        if event is None or self._syncing:
            return
        group = self.group_var.get().strip() or None
        if group == ((event.group_id or "").strip() or None):
            return
        event.group_id = group
        self._changed("group")

    def _on_use_changed(self) -> None:
        if self.event is None or self._syncing:
            return
        self.event.use_event = bool(self.use_var.get())
        self._changed("use")

    def _on_toggle_changed(self) -> None:
        if self.event is None or self._syncing:
            return
        self.event.runtime_toggle_member = bool(self.toggle_var.get())
        self._changed("toggle")

    def _set_condition(self, name: str, state: bool) -> None:
        if self.event is None:
            return
        self.event.conditions[name] = state
        self._changed("conditions")

    def _remove_condition(self, name: str) -> None:
        if self.event is None:
            return
        self.event.conditions.pop(name, None)
        self._changed("conditions")

    def condition_candidates(self) -> list[tuple[EventModel, list[str] | None]]:
        """추가할 수 있는 조건 후보와, 순환이 생기면 그 경로. 신호가 먼저다."""
        target = self.event
        if target is None:
            return []
        events = self._events()
        candidates = [
            e
            for e in events
            if e is not target
            and e.event_name
            and e.event_name not in target.conditions
        ]
        candidates.sort(key=lambda e: (bool(e.execute_action), (e.event_name or "").casefold()))
        return [
            (e, condition_cycle_if_added(events, target, e.event_name or ""))
            for e in candidates
        ]

    def _fill_condition_menu(self) -> None:
        menu = self.cond_menu
        menu.delete(0, "end")
        candidates = self.condition_candidates()
        if not candidates:
            menu.add_command(
                label=txt("No other events", "다른 이벤트가 없습니다"), state="disabled"
            )
            return
        last_kind: bool | None = None
        for event, cycle in candidates:
            kind = bool(event.execute_action)
            if last_kind is not None and kind != last_kind:
                menu.add_separator()
            last_kind = kind
            name = event.event_name or ""
            if cycle:
                menu.add_command(
                    label=txt(
                        "{name} — circular: {path}",
                        "{name} — 순환: {path}",
                        name=name,
                        path=" → ".join(cycle),
                    ),
                    state="disabled",
                )
            else:
                menu.add_command(
                    label=name, command=lambda n=name: self._set_condition(n, True)
                )

    def _commit_timing(self, _event: object | None = None) -> None:
        event = self.event
        if event is None or self._syncing:
            return
        dur = int(self.dur_var.get()) if self.dur_var.get() else None
        rand = int(self.rand_var.get()) if self.rand_var.get() else None
        if not timing_is_valid(dur, rand):
            self.lbl_timing_error.config(
                text=txt(
                    "Press time must be at least 50 ms and random at least 30 ms.",
                    "누름 시간은 50ms, 랜덤은 30ms 이상이어야 합니다.",
                )
            )
            return
        self.lbl_timing_error.config(text="")
        if (dur, rand) == (event.press_duration_ms, event.randomization_ms):
            return
        event.press_duration_ms = dur
        event.randomization_ms = rand
        self._changed("timing")

    def _on_invert_changed(self) -> None:
        if self.event is None or self._syncing:
            return
        self.event.invert_match = bool(self.invert_var.get())
        self._changed("invert")

    def _on_mode_changed(self) -> None:
        event = self.event
        if event is None or self._syncing:
            return
        event.match_mode = self.mode_var.get()
        if event.match_mode == "region":
            clamp_region(event)
        self._changed("mode")

    def _on_region_size_changed(self, _event: object | None = None) -> None:
        event = self.event
        if event is None or self._syncing or event.match_mode != "region":
            return
        try:
            size = (int(self.region_w_var.get()), int(self.region_h_var.get()))
        except ValueError:
            self._refresh_advanced()
            return
        before = event.region_size
        event.region_size = size
        clamp_region(event)
        if event.region_size != before:
            self._changed("region")
        else:
            self._refresh_advanced()

    def _on_clear_screen(self) -> None:
        if self.event is None:
            return
        clear_capture(self.event)
        self._changed("screen")

    # -- capture HUD ----------------------------------------------------------

    def open_capture(self) -> None:
        event = self.event
        if event is None:
            return
        hud = self.capture_hud
        if hud is not None and hud.is_open():
            cast(Any, hud.win).lift()
            return
        region = event.region_size if event.match_mode == "region" else None

        def on_apply(result: CaptureResult) -> None:
            apply_capture(event, result)
            if self.event is event:
                self._changed("screen")
            else:
                self.on_change(event, "screen")

        def on_name_change(name: str) -> None:
            if self.event is event:
                self.name_var.set(name)

        def on_close() -> None:
            self.capture_hud = None
            if self.event is event:
                self._commit_name()

        self.capture_hud = CaptureHud(
            self.winfo_toplevel(),
            mode="single",
            name=event.event_name or "",
            on_name_change=on_name_change,
            on_apply=on_apply,
            initial=capture_from_event(event),
            capture_size=event.capture_size or (100, 100),
            region_size=region,
            grab=True,
            border=not self.running_getter(),
            on_close=on_close,
        )
