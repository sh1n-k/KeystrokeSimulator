import copy
import platform
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox
from typing import Callable, Optional

import keyboard
import pynput
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
        self.event_window.transient(profiles_window)  # Set parent window
        self.event_window.grab_set()  # Make the window modal
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
        self.keyboard_input_listener = None

        self.create_ui()
        self.bind_events()

        self.event_window.update_idletasks()
        self.row_num = row_num
        self.is_edit = bool(event_function())
        self.load_stored_event(event_function)
        self.screenshot_capturer.start_capture()

        self.load_latest_position()
        self.key_combobox.focus_set()

    def create_ui(self):
        self.create_image_placeholders()
        self.create_ref_pixel_placeholder()
        self.create_coordinate_entries()
        self.create_refresh_button()
        self.create_key_entry()
        self.create_ok_cancel_buttons()
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

        coord_labels = ["X1:", "Y1:", "X2:", "Y2:"]
        self.coord_entries = self.create_coord_entries(coord_frame, coord_labels)

    def create_refresh_button(self):
        refresh_button = tk.Button(
            self.event_window, text="Refresh", command=self.handle_refresh_btn
        )
        refresh_button.pack(pady=5)

    def create_key_entry(self):
        key_frame = tk.Frame(self.event_window)
        key_frame.pack(pady=5)

        tk.Label(key_frame, text="Key:", anchor="w").grid(row=0, column=0)
        self.key_combobox = ttk.Combobox(
            key_frame, state="readonly", values=KeyUtils.get_key_name_list()
        )
        self.key_combobox.grid(row=0, column=1)

    def create_ok_cancel_buttons(self):
        button_frame = tk.Frame(self.event_window)
        button_frame.pack(pady=10)

        ok_button = tk.Button(button_frame, text="OK", command=self.save_event)
        ok_button.grid(row=0, column=0, padx=5)

        cancel_button = tk.Button(
            button_frame, text="Cancel", command=self.close_window
        )
        cancel_button.grid(row=0, column=1, padx=5)

    def create_info_label(self):
        info_label = tk.Label(
            self.event_window,
            text="ALT: Area selection\nCTRL: Grab current image\n"
            + "1. Set a crossline by left-clicking on the collected image.\n"
            + "2. select the key you want to set."
            + "\n\n"
            + "ALT: 영역 선택\nCTRL: 현재 이미지 가져오기\n"
            + "1. 수집된 이미지에 왼쪽 클릭으로 교차선을 설정하세요.\n"
            + "2. 설정할 키를 선택하세요.\n",
            anchor="center",
            fg="black",
            wraplength=200,
        )
        info_label.pack(pady=5, fill="both")

    def bind_events(self):
        self.bind_hotkey()
        self.event_window.bind("<Escape>", self.close_window)
        self.event_window.protocol("WM_DELETE_WINDOW", self.close_window)
        self.key_combobox.bind("<<ComboboxSelected>>", self.update_key_to_enter)
        self.key_combobox.bind("<KeyPress>", self.filter_key_combobox)

    def filter_key_combobox(self, event):
        key_name = event.keysym.upper()
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

    def bind_hotkey(self):
        if platform.system() == "Darwin":

            def on_cmd_press(e):
                if e.event_type == "down":
                    self.screenshot_capturer.set_current_mouse_position(
                        self.event_window.winfo_pointerxy()
                    )

            def on_control_press(e):
                if e.event_type == "down":
                    self.hold_image()

            keyboard.hook_key(KeyUtils.get_keycode("command"), on_cmd_press)
            keyboard.hook_key(KeyUtils.get_keycode("control"), on_control_press)

        elif platform.system() == "Windows":
            position_trigger_key = (
                pynput.keyboard.Key.cmd_l
                if platform.system() == "Darwin"
                else pynput.keyboard.Key.alt_l
            )

            def on_press(key):
                if key == position_trigger_key:
                    logger.debug(f"reset position")
                    self.screenshot_capturer.set_current_mouse_position(
                        self.event_window.winfo_pointerxy()
                    )
                elif key == pynput.keyboard.Key.ctrl_l:
                    logger.debug(f"hold current image")
                    self.hold_image()

            def on_release(key):
                pass

            self.keyboard_input_listener = pynput.keyboard.Listener(
                on_press=on_press, on_release=on_release
            )
            self.keyboard_input_listener.start()

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
                self.handle_refresh_btn()

    def get_coordinates_of_held_image(self, event):
        image = copy.deepcopy(self.held_screenshot)

        if not self.held_screenshot:
            return
        if event.x >= image.width or event.y >= image.height:
            return

        image_x = int(event.x * image.width / self.image2_placeholder.winfo_width())
        image_y = int(event.y * image.height / self.image2_placeholder.winfo_height())
        logger.debug(f"Image coordinates: ({image_x}, {image_y})")

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

    def save_event(self):
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

            event = EventModel(
                self.event_name,
                self.latest_position,
                self.clicked_position,
                self.latest_screenshot,
                self.held_screenshot,
                self.ref_pixel_value,
                self.key_to_enter,
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

        if self.keyboard_input_listener:
            self.keyboard_input_listener.stop()
            self.keyboard_input_listener.join()
        keyboard.unhook_all()

        if (
            self.screenshot_capturer.capture_thread
            and self.screenshot_capturer.capture_thread.is_alive()
        ):
            self.screenshot_capturer.stop_capture()
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

        if state and "event_pointer" in state:
            pointer_position = eval(state["event_pointer"])
            self.screenshot_capturer.set_current_mouse_position(pointer_position)

    @staticmethod
    def create_coord_entries(parent: tk.Frame, labels: list[str]) -> list[tk.Entry]:
        entries = []
        for i, label_text in enumerate(labels):
            label = tk.Label(parent, text=label_text)
            row = 0 if i < 2 else 1
            column = (i % 2) * 2
            label.grid(row=row, column=column, padx=1, sticky=tk.E)

            entry = tk.Entry(parent, width=4)
            entry.grid(row=row, column=column + 1, padx=4, sticky=tk.W)
            entries.append(entry)
        return entries

    def update_key_to_enter(self, event):
        self.key_to_enter = self.key_combobox.get()

    def handle_refresh_btn(self):
        self.update_ref_pixel_placeholder(self.held_screenshot, self.clicked_position)

    def load_stored_event(self, event_function):
        event = event_function()
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
            self.key_combobox.set(self.key_to_enter)

    @staticmethod
    def update_coordinate_entries(entries: list[tk.Entry], x, y):
        for idx, entry in enumerate(entries):
            entry.configure(state="normal")
            entry.delete(0, tk.END)
            entry.insert(0, str((x, y)[idx]))
            entry.configure(state="readonly")

    @staticmethod
    def update_image_placeholder(placeholder: tk.Label, image: Image.Image):
        photo = ImageTk.PhotoImage(image)
        placeholder.configure(
            image=photo,
            width=image.width,
            height=image.height,
        )
        placeholder.image = photo
