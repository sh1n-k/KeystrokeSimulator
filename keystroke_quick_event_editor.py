import copy
import os
import pickle
import platform
import tkinter as tk
from typing import List, Tuple

from PIL import Image, ImageTk
from loguru import logger

from keystroke_capturer import ScreenshotCapturer
from keystroke_models import EventModel, ProfileModel
from keystroke_utils import StateUtils, WindowUtils, KeyUtils

if platform.system() == "Darwin":
    import keyboard


else:
    import pynput


class KeystrokeQuickEventEditor:
    def __init__(self, settings_window: tk.Tk | tk.Toplevel):
        self.settings_window = settings_window
        self.event_window = None
        self.setup_window()
        self.initialize_variables()
        self.create_ui()
        self.bind_events()
        self.load_latest_position()
        self.screenshot_capturer.start_capture()

    def setup_window(self):
        self.event_window = tk.Toplevel(self.settings_window)
        self.event_window.title("Quick Event Settings")
        self.event_window.transient(self.settings_window)
        self.event_window.grab_set()
        self.event_window.focus_force()
        self.event_window.attributes("-topmost", True)

    def initialize_variables(self):
        self.event_idx = 1
        self.event_list: List[EventModel] = []
        self.latest_position: Tuple[int, int] | None = None
        self.clicked_position: Tuple[int, int] | None = None
        self.latest_screenshot: Image.Image | None = None
        self.held_screenshot: Image.Image | None = None
        self.ref_pixel_value: Tuple[int, int, int, int] | None = None
        self.key_to_enter = None
        self.keyboard_input_listener = None
        self.screenshot_capturer = ScreenshotCapturer()
        self.screenshot_capturer.screenshot_callback = self.update_capture_image
        self.file_path = "profiles/Quick.pkl"
        self.ensure_file_exists()

    def ensure_file_exists(self):
        if not os.path.isfile(self.file_path):
            with open(self.file_path, "wb") as f:
                pass

    def create_ui(self):
        self.create_image_frame()
        self.create_ref_pixel_frame()
        self.create_coordinate_frame()
        self.create_buttons_frame()
        self.create_info_label()

    def create_image_frame(self):
        image_frame = tk.Frame(self.event_window)
        image_frame.pack(pady=5)

        self.image1_placeholder = self.create_image_placeholder(
            image_frame, "red", 0, 0
        )
        self.image2_placeholder = self.create_image_placeholder(
            image_frame, "gray", 0, 1
        )
        self.image2_placeholder.bind("<Button-1>", self.get_coordinates_of_held_image)
        self.image2_placeholder.bind("<B1-Motion>", self.get_coordinates_of_held_image)

    def create_image_placeholder(
            self, parent: tk.Frame, bg_color: str, row: int, column: int
    ) -> tk.Label:
        placeholder = tk.Label(parent, width=10, height=5, bg=bg_color)
        placeholder.grid(row=row, column=column, padx=5)
        return placeholder

    def create_ref_pixel_frame(self):
        ref_pixel_frame = tk.Frame(self.event_window)
        ref_pixel_frame.pack(pady=5)
        self.ref_pixel_placeholder = tk.Label(
            ref_pixel_frame, width=2, height=1, bg="gray"
        )
        self.ref_pixel_placeholder.grid(row=0, column=1, padx=5)

    def create_coordinate_frame(self):
        coord_frame = tk.Frame(self.event_window)
        coord_frame.pack()

        coord_labels = ["X1:", "Y1:", "X2:", "Y2:"]
        self.coord_entries = self.create_coord_entries(coord_frame, coord_labels)

    def create_buttons_frame(self):  # 함수 이름 변경
        button_frame = tk.Frame(self.event_window)  # 버튼들을 담을 Frame 생성
        button_frame.pack(pady=5)  # button_frame 을 pack

        grab_button = tk.Button(  # Grab 버튼 생성
            button_frame, text="Grab(Ctrl)", command=self.handle_grab_button_click  # command 지정
        )
        grab_button.pack(side=tk.LEFT, padx=5)  # Grab 버튼을 왼쪽에 pack

        close_button = tk.Button(  # Close 버튼 생성 (기존 코드 유지)
            button_frame, text="Close(ESC)", command=self.close_window
        )
        close_button.pack(side=tk.LEFT, padx=5)  # Close 버튼을 오른쪽에 pack

    def create_info_label(self):
        self.info_label = tk.Label(
            self.event_window,
            text="ALT: Area selection\nCTRL: Grab current image\n"
                 + "Left-click on the collected image to set a Crossline and press CTRL to save it to a Quick Event."
                 + "\n\n"
                 + "ALT: 영역 선택\nCTRL: 현재 이미지 가져오기\n"
                 + "수집된 이미지에 왼쪽 클릭으로 교차선을 설정한 뒤\nCTRL 키를 누르면 Quick 이벤트에 저장됩니다.",
            anchor="center",
            fg="black",
            wraplength=200,
        )
        self.info_label.pack(pady=5, fill="both")

    def bind_events(self):
        self.event_window.bind("<Escape>", self.close_window)
        self.event_window.protocol("WM_DELETE_WINDOW", self.close_window)
        self.bind_hotkey()

    def bind_hotkey(self):
        if platform.system() == "Darwin":

            def on_cmd_press(e):
                logger.info(f'Command pressed: {e.name}')
                if e.event_type == "down":
                    self.screenshot_capturer.set_current_mouse_position(
                        self.event_window.winfo_pointerxy()
                    )

            def on_control_press(e):
                logger.info(f'Control pressed: {e.name}')
                if e.event_type == "down":
                    self.hold_image()

            keyboard.hook_key(KeyUtils.get_keycode("command"), on_cmd_press)
            keyboard.hook_key(KeyUtils.get_keycode("control"), on_control_press)

        elif platform.system() == "Windows":
            pass

            def on_press(key):
                logger.debug(f"windows on_press()")
                if key == pynput.keyboard.Key.alt_l:
                    self.screenshot_capturer.set_current_mouse_position(
                        self.event_window.winfo_pointerxy()
                    )
                elif key == pynput.keyboard.Key.ctrl_l:
                    self.hold_image()

            def on_release(key):
                logger.debug(f"windows on_release()")
                return key != pynput.keyboard.Key.esc

            self.keyboard_input_listener = pynput.keyboard.Listener(
                on_press=on_press, on_release=on_release
            )
            self.keyboard_input_listener.start()

    def update_capture_image(self, position: Tuple[int, int], image: Image.Image):
        if position and image:
            self.latest_position = position
            self.latest_screenshot = image
            if self.image1_placeholder and self.image1_placeholder.winfo_exists():
                self.update_image_placeholder(self.image1_placeholder, image)

    def hold_image(self):
        if self.latest_position and self.latest_screenshot:
            self.update_coordinate_entries(
                self.coord_entries[:2], *self.latest_position
            )
            self.held_screenshot = self.latest_screenshot
            self.update_image_placeholder(
                self.image2_placeholder, self.latest_screenshot
            )

            if self.clicked_position:
                self.apply_crosshair_to_placeholder(
                    self.held_screenshot, self.image2_placeholder
                )
                self.save_event()

    def get_coordinates_of_held_image(self, event):
        if not self.held_screenshot:
            return

        image = copy.deepcopy(self.held_screenshot)
        image_x, image_y = self.get_scaled_coordinates(event, image)

        if not self.is_valid_coordinate(image, image_x, image_y):
            return

        self.update_ref_pixel_placeholder(image, (image_x, image_y))
        self.clicked_position = (image_x, image_y)
        self.update_coordinate_entries(self.coord_entries[2:], image_x, image_y)
        self.apply_crosshair_to_placeholder(image, self.image2_placeholder)

    def get_scaled_coordinates(self, event, image):
        return (
            int(event.x * image.width / self.image2_placeholder.winfo_width()),
            int(event.y * image.height / self.image2_placeholder.winfo_height()),
        )

    @staticmethod
    def is_valid_coordinate(image, x, y):
        return 0 <= x < image.width and 0 <= y < image.height

    def update_ref_pixel_placeholder(self, image, coordinates):
        self.ref_pixel_value = image.getpixel(coordinates)
        color_square = Image.new("RGBA", (25, 25), color=self.ref_pixel_value)
        self.update_image_placeholder(self.ref_pixel_placeholder, color_square)

    def apply_crosshair_to_placeholder(self, image: Image.Image, placeholder: tk.Label):
        image_to_apply = copy.deepcopy(image)
        image_x, image_y = self.clicked_position
        self.invert_pixels_by_coordinate(image_to_apply, image_x, image_y, "x")
        self.invert_pixels_by_coordinate(image_to_apply, image_x, image_y, "y")
        self.update_image_placeholder(placeholder, image_to_apply)

    @staticmethod
    def invert_pixels_by_coordinate(image, x, y, axis):
        width, height = image.width, image.height
        for coord in range(width if axis == "x" else height):
            current_pixel = image.getpixel((x, coord) if axis == "y" else (coord, y))
            inverted_pixel = tuple(255 - v for v in current_pixel[:3]) + (255,)
            image.putpixel((x, coord) if axis == "y" else (coord, y), inverted_pixel)

    @staticmethod
    def update_image_placeholder(placeholder: tk.Label, image: Image.Image):
        try:
            image = image.convert("RGB")
            photo = ImageTk.PhotoImage(image, master=placeholder)
            placeholder.configure(image=photo, width=image.width, height=image.height)
            placeholder.image = photo
        except tk.TclError as e:
            logger.error(f"Failed to update image placeholder: {e}")

    @staticmethod
    def update_coordinate_entries(entries: List[tk.Entry], x, y):
        for idx, entry in enumerate(entries):
            # entry.configure(state="normal")
            entry.delete(0, tk.END)
            entry.insert(0, str((x, y)[idx]))
            # entry.configure(state="readonly")

    def handle_grab_button_click(self):  # 새로운 함수 추가
        self.hold_image()  # Ctrl 키 입력과 동일한 hold_image 함수 호출

    def close_window(self, event=None):
        if platform.system() == "Darwin":
            keyboard.unhook_all()
            # keyboard.unhook_key(KeyUtils.get_keycode("command"))
            # keyboard.unhook_key(KeyUtils.get_keycode("control"))
        self.stop_listeners()
        self.save_latest_position()
        self.event_window.grab_release()
        self.event_window.destroy()

    def stop_listeners(self):
        if self.keyboard_input_listener:
            self.keyboard_input_listener.stop()
            self.keyboard_input_listener.join()

        if (
                self.screenshot_capturer.capture_thread
                and self.screenshot_capturer.capture_thread.is_alive()
        ):
            self.screenshot_capturer.stop_capture()
            self.screenshot_capturer.capture_thread.join(timeout=0.1)

    def save_latest_position(self):
        StateUtils.save_main_app_state(
            quick_position=f"{self.event_window.winfo_x()}/{self.event_window.winfo_y()}",
            quick_pointer=str(self.screenshot_capturer.get_current_mouse_position()),
        )

    def load_latest_position(self):
        state = StateUtils.load_main_app_state()
        if not state or "quick_position" not in state:
            WindowUtils.center_window(self.event_window)
            return
        else:
            x, y = state["quick_position"].split("/")
            self.event_window.geometry(f"+{x}+{y}")

        if state and "quick_pointer" in state:
            pointer_position = eval(state["quick_pointer"])
            self.coord_entries[0].insert(0, pointer_position[0])
            self.coord_entries[1].insert(0, pointer_position[1])
            self.screenshot_capturer.set_current_mouse_position(pointer_position)

    def create_coord_entries(self, parent: tk.Frame, labels: List[str]) -> List[tk.Entry]:
        entries = []
        for i, label_text in enumerate(labels):
            label = tk.Label(parent, text=label_text)
            row, column = divmod(i, 2)
            label.grid(row=row, column=column * 2, padx=1, sticky=tk.E)

            entry = tk.Entry(parent, width=4)
            entry.grid(row=row, column=column * 2 + 1, padx=4, sticky=tk.W)
            entries.append(entry)

        entries[0].bind("<FocusOut>", self.update_position_from_entries)  # X1 Entry
        entries[1].bind("<FocusOut>", self.update_position_from_entries)  # Y1 Entry

        return entries

    def update_position_from_entries(self, event=None):
        try:
            x1 = int(self.coord_entries[0].get())
            y1 = int(self.coord_entries[1].get())
            self.screenshot_capturer.set_current_mouse_position((x1, y1))
        except ValueError:
            # Entry 에 숫자가 아닌 값이 입력된 경우 에러 처리 (옵션)
            print("X1, Y1 좌표에 유효한 숫자를 입력하세요.")
            pass

    def save_event(self):
        if all(
                [
                    self.latest_position,
                    self.clicked_position,
                    self.latest_screenshot,
                    self.held_screenshot,
                    self.ref_pixel_value,
                ]
        ):
            event = EventModel(
                event_name=str(self.event_idx),
                latest_position=self.latest_position,
                clicked_position=self.clicked_position,
                latest_screenshot=self.latest_screenshot,
                held_screenshot=self.held_screenshot,
                ref_pixel_value=self.ref_pixel_value,
            )
            self.event_list.append(event)
            self.event_idx += 1
            self.save_to_quick_profile()

    def save_to_quick_profile(self):
        profile = ProfileModel()
        profile.event_list = self.event_list
        with open(self.file_path, "wb") as f:
            pickle.dump(profile, f)
