import copy
import tkinter as tk
import tkinter.ttk as ttk
import time
from pathlib import Path
from threading import Thread
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageTk
from loguru import logger

from keystroke_capturer import ScreenshotCapturer
from keystroke_models import EventModel
from keystroke_profile_storage import ensure_quick_profile, load_profile, save_profile
from keystroke_utils import StateUtils, WindowUtils, KeyUtils


class KeystrokeQuickEventEditor:
    def __init__(self, settings_window: tk.Tk | tk.Toplevel):
        self.win = tk.Toplevel(settings_window)
        self.win.title("Quick Event Settings")
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

        self.match_mode_var = tk.StringVar(value="pixel")
        self.region_w_var = tk.IntVar(value=100)
        self.region_h_var = tk.IntVar(value=100)

        self.spn_region_w = None
        self.spn_region_h = None

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
        # Images
        f_img = tk.Frame(self.win)
        f_img.pack(pady=5)
        self.lbl_img1 = self._mk_lbl(f_img, "red", 0, 0)
        self.lbl_img2 = self._mk_lbl(f_img, "gray", 0, 1)
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

        # Match Mode
        f_mode = tk.Frame(self.win)
        f_mode.pack(pady=3)
        tk.Label(f_mode, text="모드:").pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(
            f_mode, text="Pixel", variable=self.match_mode_var, value="pixel",
            command=self._on_match_mode_change,
        ).pack(side=tk.LEFT)
        tk.Radiobutton(
            f_mode, text="Region", variable=self.match_mode_var, value="region",
            command=self._on_match_mode_change,
        ).pack(side=tk.LEFT)

        # Region Size
        f_size = tk.Frame(self.win)
        f_size.pack(pady=3)
        tk.Label(f_size, text="너비:").pack(side=tk.LEFT, padx=5)
        self.spn_region_w = ttk.Spinbox(
            f_size, textvariable=self.region_w_var, from_=50, to=1000, width=5,
        )
        self.spn_region_w.pack(side=tk.LEFT)
        for seq in ("<FocusOut>", "<<Increment>>", "<<Decrement>>"):
            self.spn_region_w.bind(seq, self._on_capture_size_change)
        tk.Label(f_size, text="높이:").pack(side=tk.LEFT, padx=5)
        self.spn_region_h = ttk.Spinbox(
            f_size, textvariable=self.region_h_var, from_=50, to=1000, width=5,
        )
        self.spn_region_h.pack(side=tk.LEFT)
        for seq in ("<FocusOut>", "<<Increment>>", "<<Decrement>>"):
            self.spn_region_h.bind(seq, self._on_capture_size_change)

        # Buttons
        f_btn = tk.Frame(self.win)
        f_btn.pack(pady=5)
        tk.Button(f_btn, text="Grab(Ctrl)", command=self.hold_image).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(f_btn, text="Close(ESC)", command=self.close).pack(
            side=tk.LEFT, padx=5
        )

        # Info
        tk.Label(
            self.win,
            text="ALT: Area selection\nCTRL: Grab current image\nLeft-click to set Crossline & CTRL to save.\n\nALT: 영역 선택\nCTRL: 이미지 가져오기\n클릭으로 교차선 설정 후 CTRL로 저장.",
            anchor="center",
            fg="black",
            wraplength=200,
        ).pack(pady=5, fill="both")

    def _on_match_mode_change(self):
        """매칭 모드 변경 시 캡처 크기 동기화"""
        try:
            w = max(50, min(1000, self.region_w_var.get()))
            h = max(50, min(1000, self.region_h_var.get()))
            self.capturer.set_capture_size(w, h)
        except (ValueError, tk.TclError):
            pass

    def _on_capture_size_change(self, *args):
        """캡처 크기 변경 시 capturer 동기화"""
        try:
            w = max(50, min(1000, self.region_w_var.get()))
            h = max(50, min(1000, self.region_h_var.get()))
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
            except (tk.TclError, AttributeError):
                pass

    def hold_image(self):
        if self.latest_pos and self.latest_img:
            self._set_entries(self.entries[:2], *self.latest_pos)
            self.held_img = self.latest_img.copy()
            self._upd_img(self.lbl_img2, self._scale_for_display(self.latest_img))
            if self.clicked_pos:
                self._apply_overlay(self.held_img, self.lbl_img2)
                self.save_event()

    def _on_click_held(self, event):
        if not self.held_img:
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

    def _apply_overlay(self, img, lbl):
        """pixel 모드: 십자선, region 모드: 직사각형 오버레이"""
        if not self.clicked_pos:
            return
        cx, cy = self.clicked_pos

        if self.match_mode_var.get() == "region":
            res = img.copy()
            draw = ImageDraw.Draw(res)
            try:
                rw = max(50, min(1000, self.region_w_var.get())) // 2
                rh = max(50, min(1000, self.region_h_var.get())) // 2
            except (ValueError, tk.TclError):
                rw, rh = 50, 50
            x1, y1 = max(0, cx - rw), max(0, cy - rh)
            x2, y2 = min(img.width, cx + rw), min(img.height, cy + rh)
            draw.rectangle([x1, y1, x2, y2], outline="yellow", width=2)
        else:
            res = copy.deepcopy(img)
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
            mode = self.match_mode_var.get()
            region_size = None
            if mode == "region":
                try:
                    region_size = (
                        max(50, min(1000, self.region_w_var.get())),
                        max(50, min(1000, self.region_h_var.get())),
                    )
                except (ValueError, tk.TclError):
                    region_size = (100, 100)

            self.events.append(
                EventModel(
                    str(self.event_idx),
                    self.latest_pos,
                    self.clicked_pos,
                    None,  # latest_screenshot is not persisted
                    self.held_img,
                    self.ref_pixel,
                    match_mode=mode,
                    region_size=region_size,
                )
            )
            self.event_idx += 1
            p = load_profile(self.prof_dir, "Quick", migrate=True)
            p.event_list = self.events
            save_profile(self.prof_dir, p, name="Quick")

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
