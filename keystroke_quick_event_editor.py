import tkinter as tk
import tkinter.ttk as ttk
import time
from pathlib import Path
from threading import Thread
from typing import List, Tuple

from PIL import Image, ImageTk
from loguru import logger

from i18n import dual_text_width, txt
from keystroke_capturer import ScreenshotCapturer
from keystroke_models import EventModel
from keystroke_profile_storage import ensure_quick_profile, load_profile, save_profile
from keystroke_utils import StateUtils, WindowUtils, KeyUtils


class KeystrokeQuickEventEditor:
    def __init__(self, settings_window: tk.Tk | tk.Toplevel):
        self.win = tk.Toplevel(settings_window)
        self.win.title(txt("Quick Event Settings", "빠른 이벤트 설정"))
        self.win.transient(settings_window)
        self.win.grab_set()
        self.win.focus_force()
        self.win.attributes("-topmost", True)
        self.win.bind("<Escape>", self.close)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self.event_idx = 1
        self.events: List[EventModel] = []
        self.latest_pos = None
        self.clicked_pos = None
        self.latest_img = None
        self.held_img = None
        self.ref_pixel = None
        self.saved_count = 0

        self.capture_w_var = tk.IntVar(value=100)
        self.capture_h_var = tk.IntVar(value=100)

        self.spn_capture_w = None
        self.spn_capture_h = None
        self.lbl_step = None
        self.lbl_session = None
        self.lbl_feedback = None

        self.capturer = ScreenshotCapturer()
        self.capturer.screenshot_callback = self.update_capture
        self.prof_dir = Path("profiles")
        ensure_quick_profile(self.prof_dir)

        self._create_ui()
        self._load_pos()

        self.capturer.start_capture()
        self.chk_active = True
        self.chk_thread = Thread(target=self._check_keys, daemon=True)
        self.chk_thread.start()

    def _create_ui(self):
        f_intro = ttk.LabelFrame(self.win, text=txt("Quick Flow", "빠른 작업 순서"))
        f_intro.pack(fill="x", padx=8, pady=(8, 5))
        ttk.Label(
            f_intro,
            text=txt(
                "1. Move the mouse with ALT.\n2. Press CTRL to freeze the left preview.\n3. Click the right preview to choose the pixel.\n4. Press CTRL again to save the Quick event.",
                "1. ALT로 마우스를 이동합니다.\n2. CTRL로 왼쪽 미리보기를 고정합니다.\n3. 오른쪽 미리보기에서 픽셀을 클릭합니다.\n4. CTRL을 다시 눌러 Quick 이벤트를 저장합니다.",
            ),
            justify="left",
            wraplength=360,
        ).pack(anchor="w", padx=8, pady=(4, 2))
        self.lbl_step = ttk.Label(f_intro, text="", foreground="#1e3a8a")
        self.lbl_step.pack(anchor="w", padx=8, pady=(0, 2))
        self.lbl_session = ttk.Label(f_intro, text="", foreground="#555555")
        self.lbl_session.pack(anchor="w", padx=8, pady=(0, 6))

        # Images
        f_img = tk.Frame(self.win)
        f_img.pack(pady=5)
        tk.Label(
            f_img,
            text=txt("Live Preview", "실시간 미리보기"),
            fg="#555555",
        ).grid(row=0, column=0, pady=(0, 3))
        tk.Label(
            f_img,
            text=txt("Captured Target", "저장 대상"),
            fg="#555555",
        ).grid(row=0, column=1, pady=(0, 3))
        self.lbl_img1 = self._mk_lbl(f_img, "red", 1, 0)
        self.lbl_img2 = self._mk_lbl(f_img, "gray", 1, 1)
        for seq in ("<Button-1>", "<B1-Motion>"):
            self.lbl_img2.bind(seq, self._on_click_held)

        # Ref Pixel
        f_ref = tk.Frame(self.win)
        f_ref.pack(pady=5)
        self.lbl_ref = tk.Label(f_ref, width=2, height=1, bg="gray")
        self.lbl_ref.grid(row=0, column=1, padx=5)

        # Coords
        self.entries = self._mk_entries(
            tk.Frame(self.win), ["X1:", "Y1:", "X2:", "Y2:"]
        )
        self.entries[0].master.pack()

        # Capture Size
        f_size = tk.Frame(self.win)
        f_size.pack(pady=3)
        tk.Label(f_size, text=txt("Capture Width:", "캡처 너비:")).pack(
            side=tk.LEFT, padx=5
        )
        self.spn_capture_w = ttk.Spinbox(
            f_size,
            textvariable=self.capture_w_var,
            from_=50,
            to=1000,
            width=5,
        )
        self.spn_capture_w.pack(side=tk.LEFT)
        for seq in ("<FocusOut>", "<<Increment>>", "<<Decrement>>", "<KeyRelease>"):
            self.spn_capture_w.bind(seq, self._on_capture_size_change)
        tk.Label(f_size, text=txt("Height:", "높이:")).pack(side=tk.LEFT, padx=5)
        self.spn_capture_h = ttk.Spinbox(
            f_size,
            textvariable=self.capture_h_var,
            from_=50,
            to=1000,
            width=5,
        )
        self.spn_capture_h.pack(side=tk.LEFT)
        for seq in ("<FocusOut>", "<<Increment>>", "<<Decrement>>", "<KeyRelease>"):
            self.spn_capture_h.bind(seq, self._on_capture_size_change)

        # Buttons
        f_btn = tk.Frame(self.win)
        f_btn.pack(pady=5)
        tk.Button(
            f_btn,
            text=txt("Grab (Ctrl)", "캡처 (Ctrl)"),
            width=dual_text_width(
                "Grab (Ctrl)", "캡처 (Ctrl)", padding=2, min_width=11
            ),
            command=self.hold_image,
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            f_btn,
            text=txt("Close (ESC)", "닫기 (ESC)"),
            width=dual_text_width("Close (ESC)", "닫기 (ESC)", padding=2, min_width=11),
            command=self.close,
        ).pack(side=tk.LEFT, padx=5)

        self.lbl_feedback = ttk.Label(
            self.win,
            text="",
            anchor="center",
            justify="center",
            foreground="#555555",
            wraplength=360,
        )
        self.lbl_feedback.pack(pady=(0, 8), fill="both")
        self._refresh_status_text()

    def _on_capture_size_change(self, *args):
        """캡처 크기 변경 시 capturer 동기화"""
        try:
            w = max(50, min(1000, self.capture_w_var.get()))
            h = max(50, min(1000, self.capture_h_var.get()))
            if self.capture_w_var.get() != w:
                self.capture_w_var.set(w)
            if self.capture_h_var.get() != h:
                self.capture_h_var.set(h)
            self.capturer.set_capture_size(w, h)
        except (ValueError, tk.TclError):
            pass

    def _mk_lbl(self, p, bg, r, c):
        l = tk.Label(p, width=10, height=5, bg=bg)
        l.grid(row=r, column=c, padx=5)
        return l

    def _mk_entries(self, p, labels):
        entries = []
        for i, txt in enumerate(labels):
            r, c = divmod(i, 2)
            tk.Label(p, text=txt).grid(row=r, column=c * 2, padx=1, sticky=tk.E)
            e = tk.Entry(p, width=4)
            e.grid(row=r, column=c * 2 + 1, padx=4, sticky=tk.W)
            e.bind("<Up>", lambda ev, en=e: self._adj_val(en, 1))
            e.bind("<Down>", lambda ev, en=e: self._adj_val(en, -1))
            entries.append(e)

        for e in entries[:2]:
            e.bind("<FocusOut>", self._update_pos_from_entry)
        return entries

    def _adj_val(self, e, d):
        try:
            v = int(e.get()) + d
            e.delete(0, tk.END)
            e.insert(0, str(v))
            if e in self.entries[:2]:
                self._update_pos_from_entry()
        except ValueError:
            pass
        return "break"

    def _update_pos_from_entry(self, event=None):
        try:
            self.capturer.set_current_mouse_position(
                (int(self.entries[0].get()), int(self.entries[1].get()))
            )
        except ValueError:
            pass

    def _check_keys(self):
        while self.chk_active:
            if KeyUtils.mod_key_pressed("alt"):
                self.capturer.set_current_mouse_position(self.win.winfo_pointerxy())
            if KeyUtils.mod_key_pressed("ctrl"):
                self.win.after(0, self.hold_image)
                time.sleep(0.2)
            time.sleep(0.1)

    def update_capture(self, pos, img):
        if pos and img:
            self.latest_pos, self.latest_img = pos, img
            try:
                if self.lbl_img1.winfo_exists():
                    scaled = self._scale_for_display(img)
                    self.win.after(0, lambda s=scaled: self._upd_img(self.lbl_img1, s))
                    self.win.after(0, self._refresh_status_text)
            except (tk.TclError, AttributeError):
                pass

    def hold_image(self):
        if not (self.latest_pos and self.latest_img):
            self._set_feedback(
                txt(
                    "Move the mouse over the target first so the live preview can update.",
                    "먼저 대상 위로 마우스를 움직여 실시간 미리보기가 보이게 하세요.",
                ),
                color="#7a5b00",
            )
            self._refresh_status_text()
            return
        self._set_entries(self.entries[:2], *self.latest_pos)
        self.held_img = self.latest_img.copy()
        self._upd_img(self.lbl_img2, self._scale_for_display(self.latest_img))
        if self.clicked_pos:
            self._apply_overlay(self.held_img, self.lbl_img2)
            self.save_event()
            return
        self._set_feedback(
            txt(
                "Captured. Now click the right preview to choose the trigger pixel.",
                "캡처했습니다. 이제 오른쪽 미리보기에서 트리거 픽셀을 클릭하세요.",
            )
        )
        self._refresh_status_text()

    def _on_click_held(self, event):
        if not self.held_img:
            self._set_feedback(
                txt(
                    "Capture the live preview first, then choose a pixel on the right image.",
                    "먼저 실시간 미리보기를 캡처한 뒤 오른쪽 이미지에서 픽셀을 고르세요.",
                ),
                color="#7a5b00",
            )
            return

        display_w = self.lbl_img2.winfo_width()
        display_h = self.lbl_img2.winfo_height()
        if display_w <= 1 or display_h <= 1:
            return

        w_r = self.held_img.width / display_w
        h_r = self.held_img.height / display_h
        ix, iy = int(event.x * w_r), int(event.y * h_r)

        if 0 <= ix < self.held_img.width and 0 <= iy < self.held_img.height:
            self.clicked_pos = (ix, iy)
            self.ref_pixel = self.held_img.getpixel((ix, iy))
            self._upd_img(self.lbl_ref, Image.new("RGBA", (25, 25), self.ref_pixel))
            self._set_entries(self.entries[2:], ix, iy)
            self._apply_overlay(self.held_img, self.lbl_img2)
            self._set_feedback(
                txt(
                    "Target selected. Press CTRL once more to save the Quick event.",
                    "대상을 선택했습니다. Quick 이벤트를 저장하려면 CTRL을 한 번 더 누르세요.",
                )
            )
            self._refresh_status_text()

    def _apply_overlay(self, img, lbl):
        """십자선 오버레이"""
        if not self.clicked_pos:
            return
        cx, cy = self.clicked_pos

        res = img.copy()
        px = res.load()
        w, h = res.size
        for x in range(w):
            px[x, cy] = tuple(255 - c for c in px[x, cy][:3]) + (255,)
        for y in range(h):
            px[cx, y] = tuple(255 - c for c in px[cx, y][:3]) + (255,)

        self._upd_img(lbl, self._scale_for_display(res))

    @staticmethod
    def _scale_for_display(img: Image.Image) -> Image.Image:
        """표시용 이미지 스케일 다운 (MAX_DISPLAY=400px 기준, 비율 유지)"""
        MAX_DISPLAY = 400
        scale = min(MAX_DISPLAY / img.width, MAX_DISPLAY / img.height, 1.0)
        if scale < 1.0:
            return img.resize(
                (int(img.width * scale), int(img.height * scale)), Image.LANCZOS
            )
        return img

    def _upd_img(self, lbl, img):
        try:
            p = ImageTk.PhotoImage(img.convert("RGB"), master=lbl)
            lbl.configure(image=p, width=img.width, height=img.height)
            lbl.image = p
        except Exception as e:
            logger.error(f"Img update failed: {e}")

    def _set_entries(self, ents, x, y):
        for i, v in enumerate((x, y)):
            ents[i].delete(0, tk.END)
            ents[i].insert(0, str(v))

    def _set_feedback(self, text: str, color: str = "#555555"):
        if self.lbl_feedback:
            self.lbl_feedback.config(text=text, foreground=color)

    def _refresh_status_text(self):
        if self.lbl_session:
            self.lbl_session.config(
                text=txt(
                    "{count} Quick event(s) saved in this session.",
                    "이번 세션에서 Quick 이벤트 {count}개를 저장했습니다.",
                    count=self.saved_count,
                )
            )
        if not self.lbl_step:
            return
        if not self.latest_img:
            self.lbl_step.config(
                text=txt(
                    "Current step: move the mouse over the target until the live preview follows it.",
                    "현재 단계: 실시간 미리보기가 따라오도록 대상 위로 마우스를 움직이세요.",
                )
            )
            return
        if not self.held_img:
            self.lbl_step.config(
                text=txt(
                    "Current step: press CTRL to freeze the current area.",
                    "현재 단계: CTRL로 현재 영역을 고정하세요.",
                )
            )
            return
        if not self.clicked_pos:
            self.lbl_step.config(
                text=txt(
                    "Current step: click the right preview to choose the trigger pixel.",
                    "현재 단계: 오른쪽 미리보기를 클릭해 트리거 픽셀을 고르세요.",
                )
            )
            return
        self.lbl_step.config(
            text=txt(
                "Current step: press CTRL again to save this Quick event.",
                "현재 단계: 이 Quick 이벤트를 저장하려면 CTRL을 다시 누르세요.",
            )
        )

    def save_event(self):
        if all(
            [
                self.latest_pos,
                self.clicked_pos,
                self.latest_img,
                self.held_img,
                self.ref_pixel,
            ]
        ):
            self.events.append(
                EventModel(
                    event_name=str(self.event_idx),
                    capture_size=(self.capture_w_var.get(), self.capture_h_var.get()),
                    latest_position=self.latest_pos,
                    clicked_position=self.clicked_pos,
                    latest_screenshot=None,  # latest_screenshot is not persisted
                    held_screenshot=self.held_img,
                    ref_pixel_value=self.ref_pixel,
                    match_mode="pixel",
                    region_size=None,
                )
            )
            self.event_idx += 1
            p = load_profile(self.prof_dir, "Quick", migrate=True)
            p.event_list = self.events
            save_profile(self.prof_dir, p, name="Quick")
            self.saved_count += 1
            self._set_feedback(
                txt(
                    "Quick event #{count} saved. Move to a new target to capture the next one.",
                    "Quick 이벤트 #{count} 저장 완료. 다음 대상을 캡처하려면 마우스를 옮기세요.",
                    count=self.saved_count,
                ),
                color="#1e5f3a",
            )
            self._refresh_status_text()

    def close(self, event=None):
        self.chk_active = False
        if self.chk_thread.is_alive():
            self.chk_thread.join(0.5)
        self.capturer.stop_capture()
        if self.capturer.capture_thread and self.capturer.capture_thread.is_alive():
            self.capturer.capture_thread.join(0.1)

        StateUtils.save_main_app_state(
            quick_pos=f"{self.win.winfo_x()}/{self.win.winfo_y()}",
            quick_ptr=str(self.capturer.get_current_mouse_position()),
        )
        self.win.grab_release()
        self.win.destroy()

    def _load_pos(self):
        s = StateUtils.load_main_app_state()
        if s and (p := s.get("quick_pos")):
            self.win.geometry(f"+{p.split('/')[0]}+{p.split('/')[1]}")
        else:
            WindowUtils.center_window(self.win)
        if s and (ptr := s.get("quick_ptr")):
            pt = eval(ptr)
            self._set_entries(self.entries[:2], *pt)
            self.capturer.set_current_mouse_position(pt)
        self._refresh_status_text()
