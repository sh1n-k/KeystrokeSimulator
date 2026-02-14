import copy
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Optional

from loguru import logger

from keystroke_models import EventModel
from keystroke_profile_storage import list_profile_names, load_profile
from keystroke_utils import StateUtils


class EventImporter:
    def __init__(
        self,
        profiles_window: tk.Toplevel,
        confirm_callback: Optional[Callable[[list[EventModel]], None]] = None,
    ):
        self.win = tk.Toplevel(profiles_window)
        self.win.title("Import events")
        self.win.transient(profiles_window)  # 부모창 위에 뜨도록 설정
        self.win.focus_force()
        self.win.attributes("-topmost", True)
        self.win.grab_set()

        self.profile_dir = Path("profiles")
        self.confirm_cb = confirm_callback
        self.checkboxes = []
        self.current_profile_data = None

        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", self.close)

        self.create_ui()
        self.load_profiles()
        self.load_pos()

    def create_ui(self):
        # 1. 프로필 선택 영역
        f_prof = ttk.Frame(self.win)
        f_prof.pack(pady=10, fill="x", padx=10)
        ttk.Label(f_prof, text="Source Profile:").pack(side="left", padx=5)
        self.cb_prof = ttk.Combobox(f_prof, state="readonly")
        self.cb_prof.bind("<<ComboboxSelected>>", self.load_events)
        self.cb_prof.pack(side="left", padx=5, fill="x", expand=True)

        # 2. 이벤트 목록 영역 (스크롤바 추가)
        container = ttk.LabelFrame(self.win, text="Select Events to Import")
        container.pack(pady=5, padx=10, fill="both", expand=True)

        self.canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=self.canvas.yview
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

        # 3. 하단 버튼 영역
        f_btn = ttk.Frame(self.win)
        f_btn.pack(side="bottom", pady=10, fill="x", padx=10)
        ttk.Button(f_btn, text="OK", command=self.on_ok).pack(side="left", padx=5)
        ttk.Button(f_btn, text="Cancel", command=self.close).pack(side="left", padx=5)
        ttk.Button(f_btn, text="Select/Deselect All", command=self.toggle_all).pack(
            side="right", padx=5
        )

    # --- 스크롤 관련 핸들러 ---
    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        if self.canvas.bbox("all")[3] > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # -----------------------

    def load_profiles(self):
        self.profile_dir.mkdir(exist_ok=True)
        names = list_profile_names(self.profile_dir)
        self.cb_prof["values"] = names
        if names:
            self.cb_prof.current(0)
            self.load_events()

    def _ensure_event_defaults(self, event_list):
        """이벤트 목록의 하위 호환성 보장"""
        for e in event_list:
            if not hasattr(e, "match_mode"):
                e.match_mode = "pixel"
            if not hasattr(e, "invert_match"):
                e.invert_match = False
            if not hasattr(e, "execute_action"):
                e.execute_action = True
            if not hasattr(e, "group_id"):
                e.group_id = None
            if not hasattr(e, "priority"):
                e.priority = 0
            if not hasattr(e, "conditions"):
                e.conditions = {}
            if not hasattr(e, "independent_thread"):
                e.independent_thread = False

    def load_events(self, event=None):
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
            if self.current_profile_data and self.current_profile_data.event_list:
                self._ensure_event_defaults(self.current_profile_data.event_list)
        except Exception as e:
            logger.error(f"Failed to load profile {prof_name}: {e}")
            self.current_profile_data = None

        if self.current_profile_data and self.current_profile_data.event_list:
            for i, evt in enumerate(self.current_profile_data.event_list):
                self._add_event_row(i, evt)

    def _add_event_row(self, idx, evt):
        var = tk.IntVar()

        # Grid 사용 및 패딩 조정
        ttk.Checkbutton(self.f_events, text=f"{idx + 1}", variable=var).grid(
            row=idx, column=0, sticky="w", padx=(5, 10), pady=2
        )

        e_name = ttk.Entry(self.f_events)
        e_name.insert(0, evt.event_name or "")
        e_name.config(state="readonly")
        e_name.grid(row=idx, column=1, padx=5, pady=2, sticky="ew")

        e_key = ttk.Entry(self.f_events, width=8, justify="center")
        e_key.insert(0, evt.key_to_enter or "")
        e_key.config(state="readonly")
        e_key.grid(row=idx, column=2, padx=5, pady=2)

        # 이름 컬럼이 늘어나도록 설정
        self.f_events.columnconfigure(1, weight=1)

        self.checkboxes.append(var)

    def toggle_all(self):
        target = 1 if any(v.get() == 0 for v in self.checkboxes) else 0
        for v in self.checkboxes:
            v.set(target)

    def _copy_event(self, evt: EventModel) -> EventModel:
        """이벤트 깊은 복사 (PIL Image 포함) - 매우 중요"""
        new_evt = EventModel(
            event_name=evt.event_name,
            latest_position=evt.latest_position,
            clicked_position=evt.clicked_position,
            latest_screenshot=None,  # not persisted; left preview is always live capture
            held_screenshot=evt.held_screenshot.copy() if evt.held_screenshot else None,
            ref_pixel_value=evt.ref_pixel_value,
            key_to_enter=evt.key_to_enter,
            press_duration_ms=getattr(evt, "press_duration_ms", None),
            randomization_ms=getattr(evt, "randomization_ms", None),
            independent_thread=getattr(evt, "independent_thread", False),
            match_mode=getattr(evt, "match_mode", "pixel"),
            invert_match=getattr(evt, "invert_match", False),
            region_size=getattr(evt, "region_size", None),
            execute_action=getattr(evt, "execute_action", True),
            group_id=getattr(evt, "group_id", None),
            priority=getattr(evt, "priority", 0),
            conditions=copy.deepcopy(getattr(evt, "conditions", {})),
        )
        new_evt.use_event = getattr(evt, "use_event", True)
        return new_evt

    def on_ok(self):
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

    def close(self, event=None):
        self.win.unbind_all("<MouseWheel>")  # 마우스 휠 바인딩 해제
        StateUtils.save_main_app_state(
            importer_pos=f"{self.win.winfo_x()}/{self.win.winfo_y()}"
        )
        self.win.grab_release()
        self.win.destroy()

    def load_pos(self):
        if pos := StateUtils.load_main_app_state().get("importer_pos"):
            try:
                x, y = pos.split("/")
                self.win.geometry(f"500x600+{x}+{y}")  # 기본 크기 적용
            except:
                self.win.geometry("500x600")
        else:
            self.win.geometry("500x600")
