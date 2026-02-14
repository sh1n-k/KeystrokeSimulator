import copy
import time
import tkinter as tk
from pathlib import Path
from threading import Thread
from typing import List, Tuple

from PIL import Image, ImageTk
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
                self.hold_image()
                time.sleep(0.2)
            time.sleep(0.1)

    def update_capture(self, pos, img):
        if pos and img:
            self.latest_pos, self.latest_img = pos, img
            if self.lbl_img1.winfo_exists():
                self._upd_img(self.lbl_img1, img)

    def hold_image(self):
        if self.latest_pos and self.latest_img:
            self._set_entries(self.entries[:2], *self.latest_pos)
            self.held_img = self.latest_img
            self._upd_img(self.lbl_img2, self.latest_img)
            if self.clicked_pos:
                self._apply_crosshair(self.held_img, self.lbl_img2)
                self.save_event()

    def _on_click_held(self, event):
        if not self.held_img:
            return
        w_r, h_r = (
            self.held_img.width / self.lbl_img2.winfo_width(),
            self.held_img.height / self.lbl_img2.winfo_height(),
        )
        ix, iy = int(event.x * w_r), int(event.y * h_r)

        if 0 <= ix < self.held_img.width and 0 <= iy < self.held_img.height:
            self.clicked_pos = (ix, iy)
            self.ref_pixel = self.held_img.getpixel((ix, iy))
            self._upd_img(self.lbl_ref, Image.new("RGBA", (25, 25), self.ref_pixel))
            self._set_entries(self.entries[2:], ix, iy)
            self._apply_crosshair(self.held_img, self.lbl_img2)

    def _apply_crosshair(self, img, lbl):
        res = copy.deepcopy(img)
        px = res.load()
        cx, cy = self.clicked_pos
        w, h = res.size
        for x in range(w):
            px[x, cy] = tuple(255 - c for c in px[x, cy][:3]) + (255,)
        for y in range(h):
            px[cx, y] = tuple(255 - c for c in px[cx, y][:3]) + (255,)
        self._upd_img(lbl, res)

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
            self.events.append(
                EventModel(
                    str(self.event_idx),
                    self.latest_pos,
                    self.clicked_pos,
                    None,  # latest_screenshot is not persisted
                    self.held_img,
                    self.ref_pixel,
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
