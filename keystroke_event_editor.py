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


def invert_pixels_by_coordinate(image: Image.Image, x: int, y: int, axis: str):
    width, height = image.width, image.height
    for coord in range(width) if axis == "x" else range(height):
        current_pixel = image.getpixel((x, coord) if axis == "y" else (coord, y))
        inverted_pixel = (
            255 - current_pixel[0],
            255 - current_pixel[1],
            255 - current_pixel[2],
            255,
        )
        image.putpixel((x, coord) if axis == "y" else (coord, y), inverted_pixel)


class KeystrokeEventEditor:
    def __init__(
        self,
        profiles_window: tk.Tk | tk.Toplevel,
        row_num: int,
        save_callback: Optional[Callable[[EventModel, bool, int], None]],
        event_function: Optional[Callable[[], EventModel]],
    ):
        self.profiles_window = profiles_window
        self.event_window = tk.Toplevel(profiles_window)
        self.event_window.title(f"Event Settings - Row {row_num + 1}")
        self.event_window.transient(profiles_window)
        self.event_window.grab_set()
        self.event_window.focus_force()
        self.event_window.attributes("-topmost", True)
        self.event_window.update_idletasks()
        self.event_window.grid_rowconfigure(0, weight=1)
        self.event_window.grid_columnconfigure(0, weight=1)

        self.save_callback = save_callback
        self.screenshot_capturer = ScreenshotCapturer()
        self.screenshot_capturer.screenshot_callback = self.update_capture_image
        self.event_name: Optional[str] = ""
        self.latest_position: Optional[tuple] = None
        self.clicked_position: Optional[tuple] = None
        self.latest_screenshot: Optional[Image.Image] = None
        self.held_screenshot: Optional[Image.Image] = None
        self.ref_pixel_value = None
        self.key_to_enter = None
        self.independent_thread = tk.BooleanVar(value=False)

        self.create_ui()
        self.bind_events()

        self.event_window.update_idletasks()
        self.row_num = row_num
        self.is_edit = bool(event_function())
        self.load_stored_event(event_function)
        self.screenshot_capturer.start_capture()

        self.key_check_active = True
        self.key_check_thread = Thread(target=self.check_key_states)
        self.key_check_thread.daemon = True
        self.key_check_thread.start()

        self.load_latest_position()
        self.key_combobox.focus_set()

    def create_ui(self):
        self.create_image_placeholders()
        self.create_ref_pixel_placeholder()
        self.create_coordinate_entries()
        self.create_key_entry()
        self.create_duration_entries()
        self.create_independent_thread_checkbox()
        self.create_buttons_frame()
        self.create_info_label()

    def create_image_placeholders(self):
        image_frame = tk.Frame(self.event_window)
        image_frame.pack(pady=5)

        self.image1_placeholder = tk.Label(image_frame, width=10, height=5, bg="red")
        self.image1_placeholder.grid(row=0, column=0, padx=5)

        self.image2_placeholder = tk.Label(image_frame, width=10, height=5, bg="gray")
        self.image2_placeholder.grid(row=0, column=1, padx=5)
        self.image2_placeholder.bind("<Button-1>", self.get_coordinates_of_held_image)
        self.image2_placeholder.bind("<B1-Motion>", self.get_coordinates_of_held_image)

    def create_ref_pixel_placeholder(self):
        ref_pixel_frame = tk.Frame(self.event_window)
        ref_pixel_frame.pack(pady=5)
        self.ref_pixel_placeholder = tk.Label(
            ref_pixel_frame, width=2, height=1, bg="gray"
        )
        self.ref_pixel_placeholder.grid(row=0, column=1, padx=5)

    def create_coordinate_entries(self):
        coord_frame = tk.Frame(self.event_window)
        coord_frame.pack()

        coord_labels = ["Area X:", "Area Y:", "Pixel X:", "Pixel Y:"]
        self.coord_entries = self.create_coord_entries(coord_frame, coord_labels)

    def create_key_entry(self):
        key_frame = tk.Frame(self.event_window)
        key_frame.pack(pady=5)

        tk.Label(key_frame, text="Key:", anchor="w").grid(row=0, column=0)
        self.key_combobox = ttk.Combobox(
            key_frame, state="readonly", values=KeyUtils.get_key_name_list()
        )
        self.key_combobox.grid(row=0, column=1)

    # [추가됨] 숫자만 입력되도록 하는 유효성 검사 함수
    def _validate_numeric_input(self, P):
        """Allow only digits or an empty string."""
        if P == "" or P.isdigit():
            return True
        return False

    # [수정됨] 유효성 검사 적용
    def create_duration_entries(self):
        duration_frame = tk.Frame(self.event_window)
        duration_frame.pack(pady=5)

        # Register the validation command
        vcmd = (self.event_window.register(self._validate_numeric_input), "%P")

        tk.Label(duration_frame, text="Press Duration (ms):").grid(
            row=0, column=0, padx=5
        )
        self.press_duration_entry = tk.Entry(
            duration_frame, width=10, validate="key", validatecommand=vcmd
        )
        self.press_duration_entry.grid(row=0, column=1, padx=5)

        tk.Label(duration_frame, text="Randomization (ms):").grid(
            row=1, column=0, padx=5
        )
        self.randomization_entry = tk.Entry(
            duration_frame, width=10, validate="key", validatecommand=vcmd
        )
        self.randomization_entry.grid(row=1, column=1, padx=5)

    def create_independent_thread_checkbox(self):
        checkbox_frame = tk.Frame(self.event_window)
        checkbox_frame.pack(pady=5)

        self.independent_thread_checkbox = tk.Checkbutton(
            checkbox_frame, text="Independent Thread", variable=self.independent_thread
        )
        self.independent_thread_checkbox.pack()

    def create_buttons_frame(self):
        button_frame = tk.Frame(self.event_window)
        button_frame.pack(pady=10)

        grab_button = tk.Button(
            button_frame, text="Grab(Ctrl)", command=self.handle_grab_button_click
        )
        grab_button.grid(row=0, column=0, padx=5, columnspan=2)

        ok_button = tk.Button(button_frame, text="OK(↩️)", command=self.save_event)
        ok_button.grid(row=1, column=0, padx=5)

        cancel_button = tk.Button(
            button_frame, text="Cancel(ESC)", command=self.close_window
        )
        cancel_button.grid(row=1, column=1, padx=5)

    def create_info_label(self):
        info_label = tk.Label(
            self.event_window,
            text="ALT: Area selection\nCTRL: Grab current image\n\n"
            + "1. Left-click the right image (grabbed image)\n   to select the reference pixel.\n"
            + "2. Select the key you want to set.\n\n"
            + "ALT: 캡처 영역 선택\nCTRL: 현재 이미지 가져오기\n\n"
            + "1. 오른쪽 이미지(가져온 이미지)를 클릭하여\n   기준이 될 픽셀을 선택하세요.\n"
            + "2. 설정할 키를 선택하세요.",
            anchor="center",
            fg="black",
            wraplength=250,
        )
        info_label.pack(pady=5, fill="both")

    def check_key_states(self):
        """Thread function to check key states periodically."""
        while self.key_check_active:
            if KeyUtils.mod_key_pressed("alt"):
                self.screenshot_capturer.set_current_mouse_position(
                    self.event_window.winfo_pointerxy()
                )

            if KeyUtils.mod_key_pressed("ctrl"):
                self.hold_image()
                time.sleep(0.2)

            time.sleep(0.1)

    def bind_events(self):
        self.event_window.bind("<Escape>", self.close_window)
        self.event_window.bind("<Return>", self.save_event)
        self.event_window.protocol("WM_DELETE_WINDOW", self.close_window)
        self.key_combobox.bind("<<ComboboxSelected>>", self.update_key_to_enter)
        self.key_combobox.bind("<KeyPress>", self.filter_key_combobox)

    def filter_key_combobox(self, event):
        key_name = (event.keysym or event.char).upper()
        if key_name.startswith("F") and key_name[1:].isdigit():
            self.key_combobox.set(key_name)
            self.update_key_to_enter(event)
        else:
            value = event.char.upper()
            if value:
                filtered_values = [
                    k for k in self.key_combobox["values"] if k.startswith(value)
                ]
                if filtered_values:
                    self.key_combobox.set(filtered_values[0])
                    self.update_key_to_enter(event)

    def update_capture_image(self, position: tuple, image: Image.Image):
        if position and image:
            self.latest_position = position
            self.latest_screenshot = image
            if self.image1_placeholder.winfo_exists():
                self.update_image_placeholder(self.image1_placeholder, image)

    def update_ref_pixel_placeholder(self, image, coordinates):
        self.ref_pixel_value = image.getpixel(coordinates)
        color_square = Image.new("RGBA", (25, 25), color=self.ref_pixel_value)
        self.update_image_placeholder(self.ref_pixel_placeholder, color_square)

    def hold_image(self):
        if self.latest_position and self.latest_screenshot:
            x, y = self.latest_position
            self.update_coordinate_entries(self.coord_entries[:2], x, y)

            self.held_screenshot = self.latest_screenshot
            self.update_image_placeholder(
                self.image2_placeholder, self.latest_screenshot
            )

            if self.clicked_position:
                self.apply_crosshair_to_placeholder(
                    self.held_screenshot, self.image2_placeholder
                )
                self.update_ref_pixel_placeholder(
                    self.held_screenshot, self.clicked_position
                )

    def get_coordinates_of_held_image(self, event):
        image = copy.deepcopy(self.held_screenshot)

        if not self.held_screenshot:
            return
        if event.x >= image.width or event.y >= image.height:
            return

        image_x = int(event.x * image.width / self.image2_placeholder.winfo_width())
        image_y = int(event.y * image.height / self.image2_placeholder.winfo_height())

        self.update_ref_pixel_placeholder(image, (image_x, image_y))

        self.clicked_position = (image_x, image_y)
        self.update_coordinate_entries(self.coord_entries[2:], image_x, image_y)

        self.apply_crosshair_to_placeholder(image, self.image2_placeholder)

    def apply_crosshair_to_placeholder(self, image: Image.Image, placeholder: tk.Label):
        image_to_apply = copy.deepcopy(image)
        image_x, image_y = self.clicked_position

        invert_pixels_by_coordinate(image_to_apply, image_x, image_y, "x")
        invert_pixels_by_coordinate(image_to_apply, image_x, image_y, "y")

        self.update_image_placeholder(placeholder, image_to_apply)

    def handle_grab_button_click(self):
        self.hold_image()

    # [수정됨] 저장 시 유효성 검사 로직 추가
    def save_event(self, event=None):
        try:
            if not all(
                [
                    self.latest_position,
                    self.clicked_position,
                    self.latest_screenshot,
                    self.held_screenshot,
                    self.ref_pixel_value,
                    self.key_to_enter,
                ]
            ):
                messagebox.showerror(
                    "Error",
                    "You must set the image, coordinates, key\n이미지와 좌표 및 키를 설정하세요.",
                )
                return

            # --- 유효성 검사 로직 시작 ---
            press_duration_str = self.press_duration_entry.get()
            randomization_str = self.randomization_entry.get()

            if press_duration_str:
                press_duration_val = int(press_duration_str)
                if press_duration_val < 50:
                    messagebox.showerror(
                        "Validation Error", "Press Duration must be at least 50 ms."
                    )
                    return

                if randomization_str:
                    randomization_val = int(randomization_str)
                    if randomization_val < 30:
                        messagebox.showerror(
                            "Validation Error",
                            "Randomization must be at least 30 ms when Press Duration is set.",
                        )
                        return
            # --- 유효성 검사 로직 끝 ---

            press_duration_ms = (
                float(press_duration_str) if press_duration_str else None
            )
            randomization_ms = float(randomization_str) if randomization_str else None

            event = EventModel(
                self.event_name,
                self.latest_position,
                self.clicked_position,
                self.latest_screenshot,
                self.held_screenshot,
                self.ref_pixel_value,
                self.key_to_enter,
                press_duration_ms=press_duration_ms,
                randomization_ms=randomization_ms,
                independent_thread=self.independent_thread.get(),
            )
            self.save_callback(event, self.is_edit, self.row_num)
            self.update_image_placeholder(self.image2_placeholder, self.held_screenshot)
            self.close_window()

        except Exception as e:
            logger.debug(f"Failed to save event: {e}")
            messagebox.showerror("Error", f"Failed to save event: {str(e)}")

    def close_window(self, event=None):
        self.key_combobox.unbind("<<ComboboxSelected>>")
        self.key_combobox.unbind("<KeyPress>")

        self.key_check_active = False
        if hasattr(self, "key_check_thread") and self.key_check_thread.is_alive():
            self.key_check_thread.join(timeout=0.5)

        if self.screenshot_capturer:
            self.screenshot_capturer.stop_capture()
            if (
                self.screenshot_capturer.capture_thread
                and self.screenshot_capturer.capture_thread.is_alive()
            ):
                self.screenshot_capturer.capture_thread.join(timeout=0.1)

        self.save_latest_position()
        self.event_window.grab_release()
        self.event_window.destroy()

    def save_latest_position(self):
        StateUtils.save_main_app_state(
            event_position=f"{self.event_window.winfo_x()}/{self.event_window.winfo_y()}",
            event_pointer=str(self.screenshot_capturer.get_current_mouse_position()),
            clicked_position=str(self.clicked_position),
        )

    def load_latest_position(self):
        state = StateUtils.load_main_app_state()
        if state and "event_position" in state:
            x, y = state["event_position"].split("/")
            self.event_window.geometry(f"+{x}+{y}")
            self.event_window.update_idletasks()

        if not self.is_edit and state and "event_pointer" in state:
            pointer_position = eval(state["event_pointer"])
            self.screenshot_capturer.set_current_mouse_position(pointer_position)

    def create_coord_entries(
        self, parent: tk.Frame, labels: list[str]
    ) -> list[tk.Entry]:
        entries = []
        for i, label_text in enumerate(labels):
            label = tk.Label(parent, text=label_text)
            row = 0 if i < 2 else 1
            column = (i % 2) * 2
            label.grid(row=row, column=column, padx=1, sticky=tk.E)

            entry = tk.Entry(parent, width=4)
            entry.grid(row=row, column=column + 1, padx=4, sticky=tk.W)
            entries.append(entry)

        entries[0].bind("<FocusOut>", self.update_position_from_entries)
        entries[1].bind("<FocusOut>", self.update_position_from_entries)

        for entry in entries:
            entry.bind("<Up>", lambda event, e=entry: self.increment_entry_value(e))
            entry.bind("<Down>", lambda event, e=entry: self.decrement_entry_value(e))

        return entries

    def update_position_from_entries(self, event=None):
        try:
            x1 = int(self.coord_entries[0].get())
            y1 = int(self.coord_entries[1].get())
            self.screenshot_capturer.set_current_mouse_position((x1, y1))
        except ValueError:
            print("Please enter valid numbers for Area X and Area Y coordinates.")
            pass

    def increment_entry_value(self, entry):
        try:
            current_value = int(entry.get())
            entry.delete(0, tk.END)
            entry.insert(0, str(current_value + 1))
            if entry in self.coord_entries[:2]:
                self.update_position_from_entries()
        except ValueError:
            pass
        return "break"

    def decrement_entry_value(self, entry):
        try:
            current_value = int(entry.get())
            entry.delete(0, tk.END)
            entry.insert(0, str(current_value - 1))
            if entry in self.coord_entries[:2]:
                self.update_position_from_entries()
        except ValueError:
            pass
        return "break"

    def update_key_to_enter(self, event):
        self.key_to_enter = self.key_combobox.get()

    def load_stored_event(self, event_function):
        event: EventModel = event_function()
        if not event:
            return

        self.event_name = event.event_name
        self.latest_position = event.latest_position
        self.clicked_position = event.clicked_position
        self.latest_screenshot = event.latest_screenshot
        self.held_screenshot = event.held_screenshot
        self.key_to_enter = event.key_to_enter

        self.screenshot_capturer.set_mouse_position(event.latest_position)

        self.apply_crosshair_to_placeholder(
            self.held_screenshot, self.image2_placeholder
        )

        self.update_coordinate_entries(
            self.coord_entries[:2], self.latest_position[0], self.latest_position[1]
        )
        self.update_coordinate_entries(
            self.coord_entries[2:], self.clicked_position[0], self.clicked_position[1]
        )

        self.update_ref_pixel_placeholder(self.held_screenshot, self.clicked_position)

        if self.key_to_enter:
            self.event_window.update_idletasks()
            if self.key_to_enter in self.key_combobox["values"]:
                self.key_combobox.set(self.key_to_enter)
            else:
                logger.debug(f"Key {self.key_to_enter} not found in combobox values")

        if hasattr(event, "independent_thread"):
            self.independent_thread.set(event.independent_thread)

        if hasattr(event, "press_duration_ms") and event.press_duration_ms is not None:
            self.press_duration_entry.insert(0, str(int(event.press_duration_ms)))

        if hasattr(event, "randomization_ms") and event.randomization_ms is not None:
            self.randomization_entry.insert(0, str(int(event.randomization_ms)))

    @staticmethod
    def update_coordinate_entries(entries: list[tk.Entry], x, y):
        for idx, entry in enumerate(entries):
            entry.delete(0, tk.END)
            entry.insert(0, str((x, y)[idx]))

    @staticmethod
    def update_image_placeholder(placeholder: tk.Label, image: Image.Image):
        photo = ImageTk.PhotoImage(image)
        placeholder.configure(
            image=photo,
            width=image.width,
            height=image.height,
        )
        placeholder.image = photo
