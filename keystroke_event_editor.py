import copy
import time
import tkinter as tk
import tkinter.ttk as ttk
from threading import Thread
from tkinter import messagebox
from typing import Callable, Optional

from PIL import ImageTk, Image
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
    ):
        self.win = tk.Toplevel(profiles_window)
        self.win.title(f"Event Settings - Row {row_num + 1}")
        self.win.transient(profiles_window)
        self.win.grab_set()
        self.win.focus_force()
        self.win.attributes("-topmost", True)
        self.win.grid_rowconfigure(0, weight=1)
        self.win.grid_columnconfigure(0, weight=1)

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
        self.independent_thread = tk.BooleanVar(value=False)

        self.create_ui()
        self.bind_events()

        self.row_num = row_num
        self.is_edit = bool(event_function())
        self.load_stored_event(event_function)
        self.capturer.start_capture()

        self.key_check_active = True
        self.key_check_thread = Thread(target=self.check_key_states, daemon=True)
        self.key_check_thread.start()

        self.load_latest_position()
        self.key_combobox.focus_set()

    def create_ui(self):
        # Image Placeholders
        f_img = tk.Frame(self.win)
        f_img.pack(pady=5)
        self.lbl_img1 = tk.Label(f_img, width=10, height=5, bg="red")
        self.lbl_img1.grid(row=0, column=0, padx=5)
        self.lbl_img2 = tk.Label(f_img, width=10, height=5, bg="gray")
        self.lbl_img2.grid(row=0, column=1, padx=5)
        for seq in ("<Button-1>", "<B1-Motion>"):
            self.lbl_img2.bind(seq, self.get_coordinates_of_held_image)

        # Ref Pixel
        f_ref = tk.Frame(self.win)
        f_ref.pack(pady=5)
        self.lbl_ref = tk.Label(f_ref, width=2, height=1, bg="gray")
        self.lbl_ref.grid(row=0, column=1, padx=5)

        # Coordinates
        self.coord_entries = self.create_coord_entries(
            tk.Frame(self.win), ["Area X:", "Area Y:", "Pixel X:", "Pixel Y:"]
        )
        self.coord_entries[0].master.pack()

        # Key Entry
        f_key = tk.Frame(self.win)
        f_key.pack(pady=5)
        tk.Label(f_key, text="Key:", anchor="w").grid(row=0, column=0)
        self.key_combobox = ttk.Combobox(
            f_key, state="readonly", values=KeyUtils.get_key_name_list()
        )
        self.key_combobox.grid(row=0, column=1)

        # Duration
        f_dur = tk.Frame(self.win)
        f_dur.pack(pady=5)
        vcmd = (self.win.register(lambda P: P == "" or P.isdigit()), "%P")
        self.entry_dur = self._create_labeled_entry(
            f_dur, "Press Duration (ms):", 0, vcmd
        )
        self.entry_rand = self._create_labeled_entry(
            f_dur, "Randomization (ms):", 1, vcmd
        )

        # Checkbox & Buttons & Info
        tk.Checkbutton(
            self.win, text="Independent Thread", variable=self.independent_thread
        ).pack(pady=5)

        f_btn = tk.Frame(self.win)
        f_btn.pack(pady=10)
        tk.Button(f_btn, text="Grab(Ctrl)", command=self.hold_image).grid(
            row=0, column=0, columnspan=2, padx=5
        )
        tk.Button(f_btn, text="OK(↩️)", command=self.save_event).grid(
            row=1, column=0, padx=5
        )
        tk.Button(f_btn, text="Cancel(ESC)", command=self.close_window).grid(
            row=1, column=1, padx=5
        )

        tk.Label(
            self.win,
            text="ALT: Area selection\nCTRL: Grab current image\n\n1. Click right image to select ref pixel.\n2. Select key.",
            anchor="center",
            fg="black",
            wraplength=250,
        ).pack(pady=5, fill="both")

    def _create_labeled_entry(self, parent, text, row, vcmd):
        tk.Label(parent, text=text).grid(row=row, column=0, padx=5)
        e = tk.Entry(parent, width=10, validate="key", validatecommand=vcmd)
        e.grid(row=row, column=1, padx=5)
        return e

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
        while self.key_check_active:
            if KeyUtils.mod_key_pressed("alt"):
                self.capturer.set_current_mouse_position(self.win.winfo_pointerxy())
            if KeyUtils.mod_key_pressed("ctrl"):
                self.hold_image()
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
        if pos and img:
            self.latest_pos, self.latest_img = pos, img
            if self.lbl_img1.winfo_exists():
                self._update_img_lbl(self.lbl_img1, img)

    def hold_image(self):
        if self.latest_pos and self.latest_img:
            self._set_entries(self.coord_entries[:2], *self.latest_pos)
            self.held_img = self.latest_img
            self._update_img_lbl(self.lbl_img2, self.latest_img)
            if self.clicked_pos:
                self._apply_crosshair(self.held_img, self.lbl_img2)
                self._update_ref_pixel(self.held_img, self.clicked_pos)

    def get_coordinates_of_held_image(self, event):
        if (
            not self.held_img
            or event.x >= self.held_img.width
            or event.y >= self.held_img.height
        ):
            return
        w_ratio = self.held_img.width / self.lbl_img2.winfo_width()
        h_ratio = self.held_img.height / self.lbl_img2.winfo_height()

        ix, iy = int(event.x * w_ratio), int(event.y * h_ratio)
        self.clicked_pos = (ix, iy)
        self._update_ref_pixel(copy.deepcopy(self.held_img), (ix, iy))
        self._set_entries(self.coord_entries[2:], ix, iy)
        self._apply_crosshair(self.held_img, self.lbl_img2)

    def _apply_crosshair(self, img, lbl):
        if not self.clicked_pos:
            return
        res_img = copy.deepcopy(img)
        pixels = res_img.load()
        cx, cy = self.clicked_pos
        w, h = res_img.size

        for x in range(w):
            pixels[x, cy] = tuple(255 - c for c in pixels[x, cy][:3]) + (255,)
        for y in range(h):
            pixels[cx, y] = tuple(255 - c for c in pixels[cx, y][:3]) + (255,)
        self._update_img_lbl(lbl, res_img)

    def _update_ref_pixel(self, img, coords):
        self.ref_pixel = img.getpixel(coords)
        self._update_img_lbl(
            self.lbl_ref, Image.new("RGBA", (25, 25), color=self.ref_pixel)
        )

    def save_event(self, event=None):
        if not all(
            [
                self.latest_pos,
                self.clicked_pos,
                self.latest_img,
                self.held_img,
                self.ref_pixel,
                self.key_to_enter,
            ]
        ):
            return messagebox.showerror(
                "Error",
                "You must set the image, coordinates, key\n이미지와 좌표 및 키를 설정하세요.",
            )

        dur_str, rand_str = self.entry_dur.get(), self.entry_rand.get()
        dur = int(dur_str) if dur_str else None
        rand = int(rand_str) if rand_str else None

        if dur and dur < 50:
            return messagebox.showerror(
                "Error", "Press Duration must be at least 50 ms."
            )
        if dur and rand and rand < 30:
            return messagebox.showerror(
                "Error", "Randomization must be at least 30 ms."
            )

        evt = EventModel(
            self.event_name,
            self.latest_pos,
            self.clicked_pos,
            self.latest_img,
            self.held_img,
            self.ref_pixel,
            self.key_to_enter,
            press_duration_ms=dur,
            randomization_ms=rand,
            independent_thread=self.independent_thread.get(),
        )
        self.save_cb(evt, self.is_edit, self.row_num)
        self._update_img_lbl(self.lbl_img2, self.held_img)
        self.close_window()

    def close_window(self, event=None):
        self.key_check_active = False
        if self.key_check_thread.is_alive():
            self.key_check_thread.join(0.5)
        self.capturer.stop_capture()
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

        self.capturer.set_mouse_position(self.latest_pos)
        self._apply_crosshair(self.held_img, self.lbl_img2)
        self._set_entries(self.coord_entries[:2], *self.latest_pos)
        self._set_entries(self.coord_entries[2:], *self.clicked_pos)
        self._update_ref_pixel(self.held_img, self.clicked_pos)

        if self.key_to_enter in self.key_combobox["values"]:
            self.key_combobox.set(self.key_to_enter)
        self.independent_thread.set(getattr(evt, "independent_thread", False))
        if d := getattr(evt, "press_duration_ms", None):
            self.entry_dur.insert(0, str(int(d)))
        if r := getattr(evt, "randomization_ms", None):
            self.entry_rand.insert(0, str(int(r)))

    @staticmethod
    def _set_entries(entries, x, y):
        for i, val in enumerate((x, y)):
            entries[i].delete(0, tk.END)
            entries[i].insert(0, str(val))

    @staticmethod
    def _update_img_lbl(lbl, img):
        photo = ImageTk.PhotoImage(img)
        lbl.configure(image=photo, width=img.width, height=img.height)
        lbl.image = photo
