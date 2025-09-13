import copy
import os
import pickle
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Optional, List

from keystroke_event_editor import KeystrokeEventEditor
from keystroke_event_importer import EventImporter
from keystroke_models import ProfileModel, EventModel
from keystroke_utils import WindowUtils, StateUtils


class ProfileFrame(ttk.Frame):
    def __init__(self, master, profile_name: str, favorite_status: bool):
        super().__init__(master)
        self.profile_name = profile_name
        self.favorite_status = tk.BooleanVar(value=favorite_status)
        self._create_widgets()

    def _create_widgets(self):
        self.profile_label = ttk.Label(self, text="Profile Name: ")
        self.profile_entry = ttk.Entry(self)
        self.profile_label.grid(row=0, column=0, sticky=tk.E)
        self.profile_entry.grid(row=0, column=1, padx=1)
        self.profile_entry.insert(0, self.profile_name)

        self.favorite_checkbox = ttk.Checkbutton(
            self, text="Favorite", variable=self.favorite_status
        )
        self.favorite_checkbox.grid(row=0, column=2, padx=5)

    def get_profile_name(self) -> str:
        return self.profile_entry.get()

    def get_favorite_status(self) -> bool:
        return self.favorite_status.get()


class EventRow(ttk.Frame):
    def __init__(self, master, row_num: int, event: Optional[EventModel], callbacks):
        super().__init__(master)
        self.row_num = row_num
        self.event = event
        self.callbacks = callbacks
        self.widgets = []  # [추가됨] 위젯 리스트
        self._create_widgets()
        self._bind_events()  # [추가됨] 이벤트 바인딩 호출

    def _create_widgets(self):
        label = ttk.Label(self, text=str(self.row_num + 1), width=2, anchor="center")
        label.pack(side=tk.LEFT)
        self.entry = ttk.Entry(self)
        self.entry.pack(side=tk.LEFT, padx=5)
        if self.event and hasattr(self.event, "event_name"):
            self.entry.insert(0, self.event.event_name)

        # [수정됨] 버튼들을 리스트에 추가
        self.widgets = [self, label, self.entry]
        for text, command in [
            ("⚙️", self._open_event_settings),
            ("📝", self._copy_event),
            ("🗑️", self._remove_event),
        ]:
            button = ttk.Button(self, text=text, command=command)
            button.pack(side=tk.LEFT)
            self.widgets.append(button)

    # [추가됨] 우클릭 이벤트를 모든 위젯에 바인딩하는 함수
    def _bind_events(self):
        for widget in self.widgets:
            widget.bind("<Button-3>", self._show_context_menu)

    def _open_event_settings(self):
        self.callbacks["open_event_settings"](self.row_num, self.event)

    def _copy_event(self):
        self.callbacks["copy_event"](self.event)

    def _remove_event(self):
        self.callbacks["remove_event"](self, self.row_num)

    # [추가됨] 컨텍스트 메뉴를 표시하는 콜백 호출
    def _show_context_menu(self, event):
        self.callbacks["show_context_menu"](event, self.row_num)

    def get_event_name(self) -> str:
        return self.entry.get()


class EventListFrame(ttk.Frame):
    def __init__(self, settings_window, profile: ProfileModel, save_callback: Callable):
        super().__init__(settings_window)
        self.settings_window = settings_window
        self.profile = profile
        self.save_callback = save_callback
        self.event_rows: List[EventRow] = []
        self.context_menu_source_row = None  # [추가됨] 우클릭된 행의 인덱스 저장
        self._create_widgets()

    def _create_widgets(self):
        self._create_buttons()
        self._create_context_menu()  # [추가됨] 컨텍스트 메뉴 생성
        self._load_events()

    def _create_buttons(self):
        ttk.Button(self, text="Add Event", command=self._add_event_row).grid(
            row=1, column=0, columnspan=1, pady=5, sticky="we"
        )
        ttk.Button(self, text="Import From", command=self._open_importer).grid(
            row=1, column=1, columnspan=1, pady=5, sticky="we"
        )

    # [추가됨] 우클릭 컨텍스트 메뉴 생성
    def _create_context_menu(self):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="Apply Pixel Info to Similar Areas",
            command=self._apply_pixel_info_to_similar,
        )

    # [추가됨] 컨텍스트 메뉴를 표시하는 함수
    def _show_context_menu(self, event, row_num):
        self.context_menu_source_row = row_num
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    # [수정됨] 일괄 적용 시 각 이벤트의 스크린샷에서 직접 컬러 값을 다시 읽도록 수정
    def _apply_pixel_info_to_similar(self):
        if self.context_menu_source_row is None:
            return

        source_event = self.profile.event_list[self.context_menu_source_row]
        source_area = source_event.latest_position
        new_pixel_pos = source_event.clicked_position

        if not all([source_area, new_pixel_pos]):
            messagebox.showwarning(
                "Warning",
                "Source event is not configured correctly.",
                parent=self.settings_window,
            )
            return

        if not messagebox.askyesno(
            "Confirm Batch Update",
            f"Apply Pixel Info from this event to all others with Area ({source_area[0]}, {source_area[1]})?\n\n"
            f"이 이벤트의 Pixel 정보를 동일한 Area({source_area[0]}, {source_area[1]}) 좌표를 가진\n"
            "다른 모든 이벤트에 일괄 적용하시겠습니까?",
            parent=self.settings_window,
        ):
            return

        update_count = 0
        for i, target_event in enumerate(self.profile.event_list):
            if i == self.context_menu_source_row:
                continue

            # Area 좌표가 일치하고, 대상 이벤트에 스크린샷이 있는지 확인
            if (
                target_event.latest_position == source_area
                and target_event.held_screenshot
            ):
                try:
                    # 1. Pixel 좌표를 새로운 좌표로 갱신
                    target_event.clicked_position = new_pixel_pos

                    # 2. 대상 이벤트의 스크린샷에서, 새로운 Pixel 좌표의 컬러 값을 직접 가져와 갱신
                    new_color = target_event.held_screenshot.getpixel(new_pixel_pos)
                    target_event.ref_pixel_value = new_color

                    update_count += 1
                except IndexError:
                    # new_pixel_pos가 이미지 범위를 벗어나는 경우 등 예외 처리
                    print(
                        f"Warning: Could not update event '{target_event.event_name}' due to an invalid pixel coordinate."
                    )
                    continue

        if update_count > 0:
            self.save_callback()  # 변경사항 저장
            messagebox.showinfo(
                "Batch Update Complete",
                f"{update_count} event(s) have been updated successfully.",
                parent=self.settings_window,
            )
        else:
            messagebox.showinfo(
                "Info",
                "No other events with the same Area coordinates were found.",
                parent=self.settings_window,
            )

    def _load_events(self):
        if self.profile.event_list:
            for idx, event in enumerate(self.profile.event_list):
                self._add_event_row(row_num=idx, event=event, resize=False)

    def _add_event_row(self, row_num=None, event=None, resize=True):
        if row_num is None:
            row_num = len(self.event_rows)

        callbacks = {
            "open_event_settings": self._open_event_settings,
            "copy_event": self._copy_event_row,
            "remove_event": self._remove_event_row,
            "show_context_menu": self._show_context_menu,  # [추가됨] 콜백 전달
        }

        event_row = EventRow(self, row_num, event, callbacks)
        event_row.grid(row=row_num + 3, column=0, columnspan=2, padx=5, pady=2)
        self.event_rows.append(event_row)

    def _open_event_settings(self, row_num, event):
        KeystrokeEventEditor(
            self.settings_window,
            row_num=row_num,
            save_callback=self._save_event_callback,
            event_function=lambda: event,
        )

    def _save_event_callback(self, event: EventModel, is_edit: bool, row_num: int = 0):
        if is_edit and 0 <= row_num < len(self.profile.event_list):
            self.profile.event_list[row_num] = event
        else:
            self.profile.event_list.append(event)
        self.save_callback(check_profile_name=False)

    def _copy_event_row(self, event: Optional[EventModel]):
        if event:
            try:
                new_event = copy.deepcopy(event)
                new_event.event_name = f"Copy of {event.event_name}"
                self.profile.event_list.append(new_event)
                self._add_event_row(event=new_event)
                self.save_callback()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to copy event: {str(e)}")
        else:
            messagebox.showinfo("Info", "Only set events can be copied")

    def _remove_event_row(self, row_frame, row_num):
        if len(self.profile.event_list) < 2:
            messagebox.showinfo("Info", "There must be at least one event")
            return

        row_frame.destroy()
        self.event_rows.remove(row_frame)
        if 0 <= row_num < len(self.profile.event_list):
            self.profile.event_list.pop(row_num)
        self.save_callback()
        self.settings_window.update_idletasks()

    def _open_importer(self):
        EventImporter(self.settings_window, self._import_events)

    def _import_events(self, event_list: List[EventModel]):
        self.profile.event_list.extend(event_list)
        for event in event_list:
            self._add_event_row(event=event)
        self.save_callback()

    def update_events(self):
        current_row_count = len(self.event_rows)
        new_row_count = len(self.profile.event_list)

        for idx in range(min(current_row_count, new_row_count)):
            event = self.profile.event_list[idx]
            self.event_rows[idx].event = event
            self.event_rows[idx].entry.delete(0, tk.END)
            self.event_rows[idx].entry.insert(0, event.event_name)

        if current_row_count > new_row_count:
            for row in self.event_rows[new_row_count:]:
                row.destroy()
            self.event_rows = self.event_rows[:new_row_count]

        for idx in range(current_row_count, new_row_count):
            self._add_event_row(
                row_num=idx, event=self.profile.event_list[idx], resize=False
            )

        self.settings_window.update_idletasks()

    def save_event_names(self):
        for idx, event_row in enumerate(self.event_rows):
            if idx < len(self.profile.event_list):
                self.profile.event_list[idx].event_name = event_row.get_event_name()


class KeystrokeProfiles:
    # ... (KeystrokeProfiles 클래스의 나머지 코드는 변경 없음)
    def __init__(
        self,
        main_window: tk.Tk,
        profile_name: str,
        save_callback: Optional[Callable[[str], None]] = None,
    ):
        self.main_window = main_window
        self.profile_name = profile_name
        self.external_save_callback = save_callback
        self.profiles_dir = "profiles"

        self.settings_window = self._create_settings_window()
        self.profile = self._load_profile()

        self.profile_frame = ProfileFrame(
            self.settings_window, profile_name, self.profile.favorite
        )
        self.event_list_frame = EventListFrame(
            self.settings_window, self.profile, self._save_profile
        )

        self._pack_frames()
        self._create_buttons()
        self._load_latest_position()

        self.settings_window.protocol("WM_DELETE_WINDOW", self._close_settings)

    def _create_settings_window(self) -> tk.Toplevel:
        window = tk.Toplevel(self.main_window)
        window.title("Profile Manager")
        window.transient(self.main_window)
        window.grab_set()
        window.focus_force()
        window.bind("<Escape>", self._close_settings)
        return window

    def _load_profile(self) -> ProfileModel:
        try:
            with open(f"{self.profiles_dir}/{self.profile_name}.pkl", "rb") as f:
                profile = pickle.load(f)
                if profile.event_list:
                    for event in profile.event_list:
                        if not hasattr(event, "press_duration_ms"):
                            event.press_duration_ms = None
                        if not hasattr(event, "randomization_ms"):
                            event.randomization_ms = None
                if not hasattr(profile, "favorite"):
                    profile.favorite = False
                return profile
        except FileNotFoundError:
            return ProfileModel(name=self.profile_name, event_list=[], favorite=False)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load profile: {e}")
            return ProfileModel(name=self.profile_name, event_list=[], favorite=False)

    def _pack_frames(self):
        self.profile_frame.pack()
        self.event_list_frame.pack()

    def _create_buttons(self):
        button_frame = ttk.Frame(self.settings_window, style="success.TFrame")
        button_frame.pack(side="bottom", anchor="e", pady=10, fill="both")

        ttk.Button(
            button_frame, text="Save Names", command=self._handle_ok_button
        ).pack(side=tk.LEFT, anchor="center", padx=5)

    def _save_profile(
        self, check_profile_name: bool = True, reload_event_frame: bool = True
    ):
        if not self.profile.event_list:
            raise ValueError("At least one event must be set")

        new_profile_name = self.profile_frame.get_profile_name()
        if check_profile_name and not new_profile_name:
            raise ValueError("Enter the profile name to save")

        self.profile.favorite = self.profile_frame.get_favorite_status()

        if new_profile_name != self.profile_name:
            new_file_path = f"{self.profiles_dir}/{new_profile_name}.pkl"
            if os.path.exists(new_file_path):
                raise ValueError(
                    f"A profile with the name '{new_profile_name}' already exists."
                )
            self._remove_old_profile()
            self.profile_name = new_profile_name

        if reload_event_frame:
            self.event_list_frame.save_event_names()

        with open(f"{self.profiles_dir}/{self.profile_name}.pkl", "wb") as f:
            pickle.dump(self.profile, f)

        if reload_event_frame:
            self.event_list_frame.update_events()

    def _remove_old_profile(self):
        old_file = f"{self.profiles_dir}/{self.profile_name}.pkl"
        if os.path.exists(old_file):
            os.remove(old_file)

    def _handle_ok_button(self):
        try:
            self.event_list_frame.save_event_names()
            self._save_profile(reload_event_frame=False)
            self._close_settings()
            if self.external_save_callback:
                self.external_save_callback(self.profile_name)
        except ValueError as e:
            messagebox.showerror("Error", str(e))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save profile: {e}")

    def _save_latest_position(self):
        StateUtils.save_main_app_state(
            profile_position=f"{self.settings_window.winfo_x()}/{self.settings_window.winfo_y()}",
        )

    def _load_latest_position(self):
        state = StateUtils.load_main_app_state()
        if not state or "profile_position" not in state:
            WindowUtils.center_window(self.settings_window)
            return
        else:
            x, y = state["profile_position"].split("/")
            self.settings_window.geometry(f"+{x}+{y}")

    def _close_settings(self, event=None):
        self._save_latest_position()
        self.settings_window.grab_release()
        self.settings_window.destroy()
