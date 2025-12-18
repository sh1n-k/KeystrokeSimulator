import copy
import time
import tkinter as tk
import tkinter.ttk as ttk
from threading import Thread
from tkinter import messagebox
from typing import Callable, Optional, List, Dict, Set

from PIL import ImageTk, Image, ImageDraw
from loguru import logger

from keystroke_capturer import ScreenshotCapturer
from keystroke_models import EventModel
from keystroke_utils import KeyUtils, StateUtils


class KeystrokeEventEditor:
    def __init__(
        self,
        profiles_window: tk.Tk | tk.Toplevel,
        row_num: int,
        save_callback: Optional[Callable[[EventModel, bool, int], None]],
        event_function: Optional[Callable[[], EventModel]],
        existing_events: Optional[List[EventModel]] = None,
    ):
        self.win = tk.Toplevel(profiles_window)
        self.win.title(f"Event Settings - Row {row_num + 1}")
        self.win.transient(profiles_window)
        self.win.grab_set()
        self.win.focus_force()
        self.win.attributes("-topmost", True)

        self.match_mode_var = tk.StringVar(value="pixel")
        self.region_w_var = tk.IntVar(value=20)
        self.region_h_var = tk.IntVar(value=20)
        self.invert_match_var = tk.BooleanVar(value=False)
        self.execute_action_var = tk.BooleanVar(value=True)
        self.group_id_var = tk.StringVar()
        self.priority_var = tk.IntVar(value=0)
        self.independent_thread = tk.BooleanVar(value=False)

        self.save_cb = save_callback
        self.capturer = ScreenshotCapturer()
        self.capturer.screenshot_callback = self.update_capture_image

        self.event_name = ""
        self.latest_pos = None
        self.clicked_pos = None
        self.latest_img = None
        self.held_img = None
        self.ref_pixel = None
        self.key_to_enter = None

        self.existing_events = existing_events or []
        self.temp_conditions: Dict[str, bool] = {}

        self._create_layout()
        self.bind_events()

        self.row_num = row_num
        self.is_edit = bool(event_function())
        self.load_stored_event(event_function)
        self.capturer.start_capture()

        self.key_check_active = True
        self.key_check_thread = Thread(target=self.check_key_states, daemon=True)
        self.key_check_thread.start()

        self.load_latest_position()

        # Traces
        self.match_mode_var.trace_add("write", lambda *a: self._redraw_overlay())
        self.region_w_var.trace_add("write", lambda *a: self._redraw_overlay())
        self.region_h_var.trace_add("write", lambda *a: self._redraw_overlay())
        self.independent_thread.trace_add("write", self._on_indep_toggle)

    def _create_layout(self):
        self.notebook = ttk.Notebook(self.win)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        self.tab_basic = ttk.Frame(self.notebook)
        self.tab_detail = ttk.Frame(self.notebook)
        self.tab_logic = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_basic, text="Basic (기본)")
        self.notebook.add(self.tab_detail, text="Detail/Region (상세/지역)")
        self.notebook.add(self.tab_logic, text="Logic/Group (논리/그룹)")

        self._setup_basic_tab()
        self._setup_detail_tab()
        self._setup_logic_tab()
        self._setup_bottom_buttons()

    def _setup_basic_tab(self):
        f_name = tk.Frame(self.tab_basic)
        f_name.pack(pady=5, fill="x", padx=10)
        tk.Label(f_name, text="Event Name:").pack(side="left")
        self.entry_name = tk.Entry(f_name)
        self.entry_name.pack(side="left", fill="x", expand=True, padx=5)

        f_img = tk.Frame(self.tab_basic)
        f_img.pack(pady=5)
        self.lbl_img1 = tk.Label(f_img, width=10, height=5, bg="red")
        self.lbl_img1.grid(row=0, column=0, padx=5)
        self.lbl_img2 = tk.Label(f_img, width=10, height=5, bg="gray")
        self.lbl_img2.grid(row=0, column=1, padx=5)
        for seq in ("<Button-1>", "<B1-Motion>"):
            self.lbl_img2.bind(seq, self.get_coordinates_of_held_image)

        f_ref = tk.Frame(self.tab_basic)
        f_ref.pack(pady=5)
        self.lbl_ref = tk.Label(f_ref, width=2, height=1, bg="gray")
        self.lbl_ref.grid(row=0, column=1, padx=5)

        self.coord_entries = self.create_coord_entries(
            tk.Frame(self.tab_basic), ["Area X:", "Area Y:", "Pixel X:", "Pixel Y:"]
        )
        self.coord_entries[0].master.pack()

        f_key = tk.Frame(self.tab_basic)
        f_key.pack(pady=5)
        tk.Label(f_key, text="Key:", anchor="w").grid(row=0, column=0)
        self.key_combobox = ttk.Combobox(
            f_key, state="readonly", values=KeyUtils.get_key_name_list()
        )
        self.key_combobox.grid(row=0, column=1)

        tk.Label(
            self.tab_basic,
            text="ALT: Area selection | CTRL: Grab image\nClick right image to set target.",
            fg="gray",
        ).pack(pady=5)

    def _create_numeric_validator(self):
        """숫자 입력 검증 함수 생성 (재사용)"""
        return (self.win.register(lambda P: P == "" or P.isdigit()), "%P")

    def _setup_detail_tab(self):
        f_main = ttk.Frame(self.tab_detail)
        f_main.pack(fill="both", expand=True, padx=10, pady=10)

        vcmd = self._create_numeric_validator()

        gb_mode = ttk.LabelFrame(f_main, text="Matching Mode")
        gb_mode.pack(fill="x", pady=5)
        ttk.Radiobutton(
            gb_mode, text="Pixel (1px)", variable=self.match_mode_var, value="pixel"
        ).pack(side="left", padx=10)
        ttk.Radiobutton(
            gb_mode, text="Region (Area)", variable=self.match_mode_var, value="region"
        ).pack(side="left", padx=10)
        ttk.Checkbutton(
            gb_mode,
            text="Trigger when NOT matching (반전 매칭)",
            variable=self.invert_match_var,
        ).pack(side="left", padx=10)

        gb_size = ttk.LabelFrame(f_main, text="Region Size (Only for Region Mode)")
        gb_size.pack(fill="x", pady=5)

        ttk.Label(gb_size, text="Width:").pack(side="left", padx=5)
        ttk.Entry(
            gb_size,
            textvariable=self.region_w_var,
            width=5,
            validate="key",
            validatecommand=vcmd,
        ).pack(side="left", padx=5)

        ttk.Label(gb_size, text="Height:").pack(side="left", padx=5)
        ttk.Entry(
            gb_size,
            textvariable=self.region_h_var,
            width=5,
            validate="key",
            validatecommand=vcmd,
        ).pack(side="left", padx=5)

        gb_time = ttk.LabelFrame(f_main, text="Timing (Overrides Global)")
        gb_time.pack(fill="x", pady=5)

        ttk.Label(gb_time, text="Duration (ms):").grid(
            row=0, column=0, padx=5, pady=2, sticky="e"
        )
        self.entry_dur = ttk.Entry(
            gb_time, width=8, validate="key", validatecommand=vcmd
        )
        self.entry_dur.grid(row=0, column=1, padx=5, pady=2)

        ttk.Label(gb_time, text="Random (ms):").grid(
            row=1, column=0, padx=5, pady=2, sticky="e"
        )
        self.entry_rand = ttk.Entry(
            gb_time, width=8, validate="key", validatecommand=vcmd
        )
        self.entry_rand.grid(row=1, column=1, padx=5, pady=2)

        ttk.Checkbutton(
            f_main,
            text="Independent Thread (Ignores Group/Condition)",
            variable=self.independent_thread,
        ).pack(pady=10, anchor="w")

    def _get_existing_groups(self) -> List[str]:
        """기존 이벤트에서 그룹 ID 목록 추출"""
        return sorted(
            {
                e.group_id
                for e in self.existing_events
                if e.group_id and e.group_id.strip()
            }
        )

    def _setup_logic_tab(self):
        f_main = ttk.Frame(self.tab_logic)
        f_main.pack(fill="both", expand=True, padx=10, pady=10)

        vcmd = self._create_numeric_validator()

        gb_exec = ttk.LabelFrame(f_main, text="Execution Type")
        gb_exec.pack(fill="x", pady=5)
        ttk.Checkbutton(
            gb_exec,
            text="Execute Key Action (Uncheck for Condition-only)",
            variable=self.execute_action_var,
        ).pack(padx=10, pady=5, anchor="w")

        gb_grp = ttk.LabelFrame(f_main, text="Grouping & Priority")
        gb_grp.pack(fill="x", pady=5)

        ttk.Label(gb_grp, text="Group ID:").grid(row=0, column=0, padx=5, pady=5)

        self.cmb_group = ttk.Combobox(gb_grp, textvariable=self.group_id_var, width=15)
        self.cmb_group.grid(row=0, column=1, padx=5, pady=5)
        self.cmb_group["values"] = self._get_existing_groups()

        ttk.Label(gb_grp, text="Priority (Lower=High):").grid(
            row=0, column=2, padx=5, pady=5
        )
        ttk.Entry(
            gb_grp,
            textvariable=self.priority_var,
            width=5,
            validate="key",
            validatecommand=vcmd,
        ).grid(row=0, column=3, padx=5, pady=5)

        gb_cond = ttk.LabelFrame(
            f_main, text="Conditions (Click: Ignore -> Active -> Inactive)"
        )
        gb_cond.pack(fill="both", expand=True, pady=5)

        cols = ("event", "state")
        self.tree_cond = ttk.Treeview(gb_cond, columns=cols, show="headings", height=5)
        self.tree_cond.heading("event", text="Event Name")
        self.tree_cond.heading("state", text="Required State")
        self.tree_cond.column("event", width=150)
        self.tree_cond.column("state", width=100)

        sb = ttk.Scrollbar(gb_cond, orient="vertical", command=self.tree_cond.yview)
        self.tree_cond.configure(yscrollcommand=sb.set)

        self.tree_cond.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.tree_cond.bind("<Button-1>", self._on_tree_click)

    def _setup_bottom_buttons(self):
        f_btn = tk.Frame(self.win)
        f_btn.pack(pady=10, fill="x")

        tk.Button(f_btn, text="Grab(Ctrl)", command=self.hold_image).pack(
            side="left", padx=20
        )
        tk.Button(f_btn, text="Cancel(ESC)", command=self.close_window).pack(
            side="right", padx=20
        )
        tk.Button(f_btn, text="OK(Enter)", command=self.save_event, bg="#dddddd").pack(
            side="right", padx=5
        )

    def _on_indep_toggle(self, *args):
        # 독립 스레드 활성화 시 그룹 ID 입력 비활성화
        if self.independent_thread.get():
            self.cmb_group.set("")
            self.cmb_group.config(state="disabled")
            self.group_id_var.set("")
        else:
            self.cmb_group.config(state="normal")

    def create_coord_entries(self, parent, labels):
        entries = []
        for i, txt in enumerate(labels):
            r, c = i // 2, (i % 2) * 2
            tk.Label(parent, text=txt).grid(row=r, column=c, padx=1, sticky=tk.E)
            e = tk.Entry(parent, width=4)
            e.grid(row=r, column=c + 1, padx=4, sticky=tk.W)
            e.bind("<Up>", lambda ev, en=e: self._adj_entry(en, 1))
            e.bind("<Down>", lambda ev, en=e: self._adj_entry(en, -1))
            entries.append(e)

        for e in entries[:2]:
            e.bind("<FocusOut>", self.update_position_from_entries)
        return entries

    def _adj_entry(self, entry, delta):
        try:
            val = int(entry.get()) + delta
            entry.delete(0, tk.END)
            entry.insert(0, str(val))
            if entry in self.coord_entries[:2]:
                self.update_position_from_entries()
        except ValueError:
            pass
        return "break"

    def check_key_states(self):
        """
        Thread Safety:
        백그라운드 스레드에서 UI 업데이트 호출 시 self.win.after 사용
        """
        while self.key_check_active:
            if KeyUtils.mod_key_pressed("alt"):
                cur_pos = self.win.winfo_pointerxy()
                self.capturer.set_current_mouse_position(cur_pos)

                valid_pos = self.capturer.get_current_mouse_position()
                if valid_pos:
                    # Safe UI update
                    self.win.after(
                        0,
                        lambda p=valid_pos: self._set_entries(
                            self.coord_entries[:2], *p
                        ),
                    )

            if KeyUtils.mod_key_pressed("ctrl"):
                # Safe UI update
                self.win.after(0, self.hold_image)
                time.sleep(0.2)
            time.sleep(0.1)

    def bind_events(self):
        self.win.bind("<Escape>", self.close_window)
        self.win.bind("<Return>", self.save_event)
        self.win.protocol("WM_DELETE_WINDOW", self.close_window)
        self.key_combobox.bind(
            "<<ComboboxSelected>>",
            lambda e: setattr(self, "key_to_enter", self.key_combobox.get()),
        )
        self.key_combobox.bind("<KeyPress>", self.filter_key_combobox)

    def filter_key_combobox(self, event):
        key = (event.keysym or event.char).upper()
        if key.startswith("F") and key[1:].isdigit():
            self.key_combobox.set(key)
            self.key_to_enter = key
        elif val := event.char.upper():
            if match := [k for k in self.key_combobox["values"] if k.startswith(val)]:
                self.key_combobox.set(match[0])
                self.key_to_enter = match[0]

    def update_capture_image(self, pos, img):
        """
        스레드 안전한 이미지 업데이트
        - 윈도우가 닫힌 후 호출될 수 있으므로 위젯 존재 여부 확인
        """
        if not pos or not img:
            return

        self.latest_pos, self.latest_img = pos, img

        # 윈도우와 위젯이 모두 존재하는지 확인
        try:
            if (
                hasattr(self, "win")
                and self.win.winfo_exists()
                and hasattr(self, "lbl_img1")
                and self.lbl_img1.winfo_exists()
            ):
                self.win.after(0, lambda: self._safe_update_img_lbl(self.lbl_img1, img))
        except (tk.TclError, AttributeError, RuntimeError):
            # 윈도우가 이미 파괴된 경우 무시
            pass

    def hold_image(self):
        if self.latest_pos and self.latest_img:
            self._set_entries(self.coord_entries[:2], *self.latest_pos)
            self.held_img = self.latest_img.copy()
            self._update_img_lbl(self.lbl_img2, self.latest_img)
            if self.clicked_pos:
                self._draw_overlay(self.held_img, self.lbl_img2)
                self._update_ref_pixel(self.held_img, self.clicked_pos)

    def get_coordinates_of_held_image(self, event):
        if (
            not self.held_img
            or event.x >= self.lbl_img2.winfo_width()  # 라벨 크기 기준으로 체크
            or event.y >= self.lbl_img2.winfo_height()
        ):
            return

        w_ratio = self.held_img.width / self.lbl_img2.winfo_width()
        h_ratio = self.held_img.height / self.lbl_img2.winfo_height()

        ix, iy = int(event.x * w_ratio), int(event.y * h_ratio)

        # 이미지 범위 내인지 최종 확인
        if ix >= self.held_img.width or iy >= self.held_img.height:
            return

        self.clicked_pos = (ix, iy)
        self._update_ref_pixel(self.held_img, (ix, iy))  # deepcopy 제거 (불필요)
        self._set_entries(self.coord_entries[2:], ix, iy)
        self._draw_overlay(self.held_img, self.lbl_img2)

    def _draw_overlay(self, img, lbl):
        if not self.clicked_pos:
            return

        res_img = img.copy()  # copy.deepcopy → copy()
        draw = ImageDraw.Draw(res_img)
        cx, cy = self.clicked_pos
        w, h = res_img.size

        if self.match_mode_var.get() == "region":
            try:
                rw = self.region_w_var.get() // 2
                rh = self.region_h_var.get() // 2
                x1, y1 = max(0, cx - rw), max(0, cy - rh)
                x2, y2 = min(w, cx + rw), min(h, cy + rh)
                draw.rectangle([x1, y1, x2, y2], outline="yellow", width=2)
            except Exception:
                pass
        else:
            # 이미지 모드에 관계없이 안전하게 처리
            pixels = res_img.load()
            num_channels = len(res_img.getbands())

            for x in range(w):
                orig = pixels[x, cy]
                inverted = tuple(255 - c for c in orig[:3])
                pixels[x, cy] = (
                    inverted
                    if num_channels == 3
                    else inverted + (orig[3] if num_channels == 4 else 255,)
                )

            for y in range(h):
                orig = pixels[cx, y]
                inverted = tuple(255 - c for c in orig[:3])
                pixels[cx, y] = (
                    inverted
                    if num_channels == 3
                    else inverted + (orig[3] if num_channels == 4 else 255,)
                )

        self._update_img_lbl(lbl, res_img)

    def _redraw_overlay(self):
        if self.held_img and self.clicked_pos:
            self._draw_overlay(self.held_img, self.lbl_img2)

    def _update_ref_pixel(self, img, coords):
        self.ref_pixel = img.getpixel(coords)
        if len(self.ref_pixel) == 3:
            color = self.ref_pixel + (255,)  # 알파 채널 추가
        else:
            color = self.ref_pixel
        self._update_img_lbl(self.lbl_ref, Image.new("RGBA", (25, 25), color=color))

    def _get_condition_display(self, state_val: Optional[bool]) -> str:
        """조건 상태 값을 표시 문자열로 변환"""
        if state_val is True:
            return "Active (True)"
        elif state_val is False:
            return "Inactive (False)"
        return "Ignore"

    def _populate_condition_tree(self):
        for item in self.tree_cond.get_children():
            self.tree_cond.delete(item)

        for evt in self.existing_events:
            if self.event_name and evt.event_name == self.event_name:
                continue

            # 이미 나를 조건으로 참조하고 있는 이벤트는 제외 (1차 방어)
            if evt.conditions and self.event_name in evt.conditions:
                continue

            state_val = self.temp_conditions.get(evt.event_name, None)
            display = self._get_condition_display(state_val)
            self.tree_cond.insert("", "end", values=(evt.event_name, display))

    def _cycle_condition_state(self, current_state: str) -> tuple[str, Optional[bool]]:
        """조건 상태 순환: Ignore -> Active -> Inactive -> Ignore"""
        if "Ignore" in current_state:
            return "Active (True)", True
        elif "Active" in current_state:
            return "Inactive (False)", False
        else:
            return "Ignore", None

    def _on_tree_click(self, event):
        region = self.tree_cond.identify("region", event.x, event.y)
        if region != "cell":
            return

        item_id = self.tree_cond.identify_row(event.y)
        if not item_id:
            return

        vals = self.tree_cond.item(item_id, "values")
        evt_name, curr_state = vals[0], vals[1]

        new_state_disp, new_val = self._cycle_condition_state(curr_state)
        self.tree_cond.item(item_id, values=(evt_name, new_state_disp))

        if new_val is None:
            self.temp_conditions.pop(evt_name, None)
        else:
            self.temp_conditions[evt_name] = new_val

    def _validate_cycles(
        self, new_event_name: str, new_conditions: Dict[str, bool]
    ) -> bool:
        """
        조건 순환 참조 검사 (DFS)
        True: Cycle Detected, False: Safe
        """
        # 1. 가상의 그래프 생성 (Existing events + Current editing event)
        graph = {e.event_name: list(e.conditions.keys()) for e in self.existing_events}
        # 현재 편집 중인 이벤트 정보 업데이트
        graph[new_event_name] = list(new_conditions.keys())

        visited = set()
        rec_stack = set()

        def dfs(node):
            visited.add(node)
            rec_stack.add(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True  # Cycle found

            rec_stack.remove(node)
            return False

        # 모든 노드에 대해 검사
        for node in graph:
            if node not in visited:
                if dfs(node):
                    return True
        return False

    def _validate_required_fields(self) -> bool:
        """필수 필드 검증"""
        required = [
            self.latest_pos,
            self.clicked_pos,
            self.latest_img,
            self.held_img,
            self.ref_pixel,
        ]
        need_key = self.execute_action_var.get()
        if need_key:
            required.append(self.key_to_enter)

        if not all(required):
            msg = (
                "You must set the image, coordinates, key\n이미지와 좌표 및 키를 설정하세요."
                if need_key
                else "You must set the image and coordinates\n이미지와 좌표를 설정하세요."
            )
            messagebox.showerror("Error", msg)
            return False
        return True

    def _parse_numeric_inputs(
        self,
    ) -> tuple[Optional[int], Optional[int], int, int, int]:
        """숫자 입력값 파싱 및 검증"""
        try:
            dur_str, rand_str = self.entry_dur.get(), self.entry_rand.get()
            dur = int(dur_str) if dur_str else None
            rand = int(rand_str) if rand_str else None

            rw = self.region_w_var.get()
            rh = self.region_h_var.get()

            if self.match_mode_var.get() == "region" and (rw <= 0 or rh <= 0):
                messagebox.showerror("Error", "Region Width/Height must be > 0")
                return None, None, 0, 0, 0

            try:
                prio = self.priority_var.get()
            except tk.TclError:
                prio = 0

            return dur, rand, rw, rh, prio
        except ValueError:
            messagebox.showerror("Error", "Invalid numeric input.")
            return None, None, 0, 0, 0

    def _validate_timing_values(self, dur: Optional[int], rand: Optional[int]) -> bool:
        """타이밍 값 검증"""
        if dur and dur < 50:
            messagebox.showerror("Error", "Press Duration must be at least 50 ms.")
            return False
        if dur and rand and rand < 30:
            messagebox.showerror("Error", "Randomization must be at least 30 ms.")
            return False
        return True

    def save_event(self, event=None):
        if not self._validate_required_fields():
            return

        final_name = self.entry_name.get().strip()
        if not final_name:
            messagebox.showerror("Error", "Event Name is required.")
            return

        parsed = self._parse_numeric_inputs()
        if parsed == (None, None, 0, 0, 0):
            return

        dur, rand, rw, rh, prio = parsed

        if not self._validate_timing_values(dur, rand):
            return

        if self._validate_cycles(final_name, self.temp_conditions):
            return messagebox.showerror(
                "Error", "Circular dependency detected in conditions!"
            )

        # 독립 스레드일 경우 그룹 제거
        grp_id = self.group_id_var.get()
        if self.independent_thread.get():
            grp_id = None

        evt = EventModel(
            final_name,
            self.latest_pos,
            self.clicked_pos,
            self.latest_img.copy() if self.latest_img else None,  # 복사본
            self.held_img.copy() if self.held_img else None,  # 복사본
            self.ref_pixel,
            self.key_to_enter,
            press_duration_ms=dur,
            randomization_ms=rand,
            independent_thread=self.independent_thread.get(),
            match_mode=self.match_mode_var.get(),
            invert_match=self.invert_match_var.get(),
            region_size=(rw, rh),
            execute_action=self.execute_action_var.get(),
            group_id=grp_id,
            priority=prio,
            conditions=copy.deepcopy(self.temp_conditions),
        )
        self.save_cb(evt, self.is_edit, self.row_num)
        self._update_img_lbl(self.lbl_img2, self.held_img)
        self.close_window()

    def close_window(self, event=None):
        # 콜백 비활성화를 위해 capturer 콜백을 None으로 설정
        self.capturer.stop_capture()
        self.capturer.screenshot_callback = None
        self.key_check_active = False

        if self.key_check_thread.is_alive():
            self.key_check_thread.join(0.5)
        if self.capturer.capture_thread and self.capturer.capture_thread.is_alive():
            self.capturer.capture_thread.join(0.1)

        StateUtils.save_main_app_state(
            event_position=f"{self.win.winfo_x()}/{self.win.winfo_y()}",
            event_pointer=str(self.capturer.get_current_mouse_position()),
            clicked_position=str(self.clicked_pos),
        )
        self.win.grab_release()
        self.win.destroy()

    def load_latest_position(self):
        state = StateUtils.load_main_app_state() or {}
        if pos := state.get("event_position"):
            self.win.geometry(f"+{pos.split('/')[0]}+{pos.split('/')[1]}")
        if not self.is_edit and (ptr := state.get("event_pointer")):
            self.capturer.set_current_mouse_position(eval(ptr))

    def update_position_from_entries(self, event=None):
        try:
            self.capturer.set_current_mouse_position(
                (int(self.coord_entries[0].get()), int(self.coord_entries[1].get()))
            )
        except ValueError:
            pass

    def load_stored_event(self, func):
        if not (evt := func()):
            default_name = f"Event_{len(self.existing_events) + 1}"
            self.entry_name.insert(0, default_name)
            self._populate_condition_tree()
            return

        self.event_name, self.latest_pos, self.clicked_pos = (
            evt.event_name,
            evt.latest_position,
            evt.clicked_position,
        )
        self.latest_img, self.held_img, self.key_to_enter = (
            evt.latest_screenshot,
            evt.held_screenshot,
            evt.key_to_enter,
        )

        self.entry_name.delete(0, tk.END)
        self.entry_name.insert(0, self.event_name or "")

        self.capturer.set_mouse_position(self.latest_pos)
        self._set_entries(self.coord_entries[:2], *self.latest_pos)
        self._set_entries(self.coord_entries[2:], *self.clicked_pos)

        # 원본 ref_pixel 값이 있으면 사용
        if hasattr(evt, "ref_pixel_value") and evt.ref_pixel_value:
            self.ref_pixel = evt.ref_pixel_value
            self._update_img_lbl(
                self.lbl_ref,
                Image.new(
                    "RGBA",
                    (25, 25),
                    color=(
                        self.ref_pixel[:4]
                        if len(self.ref_pixel) >= 4
                        else self.ref_pixel + (255,)
                    ),
                ),
            )
        else:
            self._update_ref_pixel(self.held_img, self.clicked_pos)

        if self.key_to_enter in self.key_combobox["values"]:
            self.key_combobox.set(self.key_to_enter)

        is_indep = getattr(evt, "independent_thread", False)
        self.independent_thread.set(is_indep)

        if d := getattr(evt, "press_duration_ms", None):
            self.entry_dur.insert(0, str(int(d)))
        if r := getattr(evt, "randomization_ms", None):
            self.entry_rand.insert(0, str(int(r)))

        self.match_mode_var.set(getattr(evt, "match_mode", "pixel"))
        self.invert_match_var.set(getattr(evt, "invert_match", False))
        if r_size := getattr(evt, "region_size", None):
            self.region_w_var.set(r_size[0])
            self.region_h_var.set(r_size[1])
        self.execute_action_var.set(getattr(evt, "execute_action", True))

        gid = getattr(evt, "group_id", "") or ""
        self.group_id_var.set(gid)
        if is_indep:  # 독립 스레드면 UI 비활성화 동기화
            self.cmb_group.config(state="disabled")

        self.priority_var.set(getattr(evt, "priority", 0))

        self.temp_conditions = copy.deepcopy(getattr(evt, "conditions", {}))
        self._populate_condition_tree()

        self._draw_overlay(self.held_img, self.lbl_img2)

    @staticmethod
    def _set_entries(entries, x, y):
        for i, val in enumerate((x, y)):
            entries[i].delete(0, tk.END)
            entries[i].insert(0, str(val))

    def _safe_update_img_lbl(self, lbl, img):
        """위젯 존재 확인 후 안전하게 이미지 업데이트"""
        try:
            if lbl.winfo_exists():
                self._update_img_lbl(lbl, img)
        except (tk.TclError, AttributeError):
            # 위젯이 파괴된 경우 무시
            pass

    @staticmethod
    def _update_img_lbl(lbl, img):
        photo = ImageTk.PhotoImage(img)
        lbl.configure(image=photo, width=img.width, height=img.height)
        lbl.image = photo
