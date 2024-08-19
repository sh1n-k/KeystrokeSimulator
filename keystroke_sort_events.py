import pickle
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable

from PIL import Image, ImageTk
from loguru import logger

from keystroke_models import EventModel, ProfileModel
from keystroke_utils import StateUtils, WindowUtils


class KeystrokeSortEvents(tk.Toplevel):
    def __init__(self, master, profile_name: str, save_callback: Callable[[str], None]):
        super().__init__(master)
        self.master = master
        self.profiles_dir = "./profiles"
        self.save_callback = save_callback

        self.title("Event Organizer")
        self.configure(bg="#2E2E2E")

        self.profile_name = tk.StringVar(value=profile_name)
        self.profile = self.load_profile(profile_name)
        self.events = self.profile.event_list

        self.create_widgets()

        self.bind("<Escape>", self.close_window)
        self.protocol("WM_DELETE_WINDOW", self.close_window)

        self.load_window_state()

    def load_window_state(self):
        try:
            state = StateUtils.load_main_app_state()
            if state:
                geometry = self.build_geometry_string(state)
                if geometry:
                    self.geometry(geometry)
            else:
                WindowUtils.center_window(self)
        except Exception as e:
            logger.error(f"Error loading window state: {e}")
            WindowUtils.center_window(self)

    @staticmethod
    def build_geometry_string(state):
        geometry = ""
        if "organizer_size" in state:
            width, height = state["organizer_size"].split("/")
            geometry = f"{width}x{height}"
        if "organizer_postition" in state:
            x, y = state["organizer_postition"].split("/")
            geometry += f"+{x}+{y}"
        logger.debug(f"Organizer geometry: {geometry}")
        return geometry

    def create_widgets(self):
        self.create_profile_frame()
        self.create_save_button()
        self.create_scrollable_event_frame()

    def create_profile_frame(self):
        profile_frame = ttk.Frame(self)
        profile_frame.pack(pady=10, padx=10, fill=tk.X)

        ttk.Label(profile_frame, text="Profile Name:").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Entry(profile_frame, textvariable=self.profile_name, state="readonly").pack(
            side=tk.LEFT, expand=True, fill=tk.BOTH
        )

    def create_save_button(self):
        ttk.Button(self, text="Save", command=self.save_events).pack(pady=5)

    def create_scrollable_event_frame(self):
        canvas = tk.Canvas(self)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.event_frame = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=self.event_frame, anchor="nw")

        self.event_frame.bind(
            "<Configure>", lambda e: self.update_canvas(canvas, self.event_frame)
        )

        canvas.configure(yscrollcommand=scrollbar.set)

        self.bind_mouse_wheel(canvas)

        for idx, event in enumerate(self.events):
            self.add_event(idx, event)

    def update_canvas(self, canvas, frame):
        canvas.configure(scrollregion=canvas.bbox("all"))
        if frame.winfo_width() > canvas.winfo_width():
            canvas.config(width=frame.winfo_width())

    def bind_mouse_wheel(self, canvas):
        def on_mouse_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", on_mouse_wheel)

        for widget in self.event_frame.winfo_children():
            widget.bind(
                "<Enter>", lambda e: canvas.bind_all("<MouseWheel>", on_mouse_wheel)
            )
            widget.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    def add_event(self, idx: int, event=None):
        if event is None:
            event = EventModel()
            self.events.append(event)

        frame = self.create_event_frame(idx)
        self.add_event_widgets(frame, idx, event)
        self.configure_drag_and_drop(frame)

    def create_event_frame(self, idx):
        frame = ttk.Frame(self.event_frame, style="Event.TFrame")
        frame.pack(pady=5, fill=tk.X, padx=5)
        frame.configure(borderwidth=2, relief="solid")
        style = ttk.Style()
        style.configure("Event.TFrame", background="#2E2E2E", bordercolor="red")
        return frame

    def add_event_widgets(self, frame, idx, event):
        self.add_index_label(frame, idx)
        self.add_use_event_checkbox(frame, event)
        self.add_screenshot_placeholder(frame, event)
        self.add_event_name_entry(frame, event)
        self.add_key_display(frame, event)

    def add_index_label(self, frame, idx):
        index_label = ttk.Label(frame, text=f"{idx + 1}")
        index_label.pack(side=tk.LEFT, padx=5)

    def add_use_event_checkbox(self, frame, event):
        use_event_var = tk.BooleanVar(value=event.use_event)
        use_event_check = ttk.Checkbutton(frame, variable=use_event_var)
        use_event_check.pack(side=tk.LEFT, padx=5)
        use_event_var.trace_add(
            "write", lambda *args: self.update_use_event(event, use_event_var)
        )

    def add_screenshot_placeholder(self, frame, event):
        if event.held_screenshot:
            img = ImageTk.PhotoImage(event.held_screenshot.resize((50, 50)))
        else:
            img = ImageTk.PhotoImage(Image.new("RGB", (50, 50), color="gray"))
        img_label = ttk.Label(frame, image=img)
        img_label.image = img  # Keep a reference to prevent garbage collection
        img_label.pack(side=tk.LEFT, padx=5)

    def add_event_name_entry(self, frame, event):
        event_name_var = tk.StringVar(
            value=event.event_name if event.event_name else ""
        )
        entry = ttk.Entry(frame, textvariable=event_name_var)
        entry.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

        event_name_var.trace_add(
            "write", lambda *args: self.update_event_name(event, event_name_var)
        )

    def add_key_display(self, frame, event):
        key_entry = ttk.Label(
            frame,
            text=event.key_to_enter or "N/A",
            width=3,
            anchor="w",
            state="readonly",
        )
        key_entry.pack(side=tk.LEFT, padx=5)

    def update_use_event(self, event: EventModel, use_event_var: tk.BooleanVar):
        event.use_event = use_event_var.get()

    def configure_drag_and_drop(self, widget):
        widget.bind("<ButtonPress-1>", self.on_drag_start)
        widget.bind("<B1-Motion>", self.on_drag_motion)
        widget.bind("<ButtonRelease-1>", self.on_drag_release)

    def update_event_name(self, event: EventModel, name_var: tk.StringVar):
        event.event_name = name_var.get()

    def on_drag_start(self, event):
        widget = self.get_parent_frame(event.widget)
        widget._drag_start_y = event.y_root - widget.winfo_rooty()
        widget._drag_start_mouse_y = event.y_root

        self.create_drag_image(widget)

    def get_parent_frame(self, widget):
        while not isinstance(widget, ttk.Frame):
            widget = widget.master
        return widget

    def create_drag_image(self, widget):
        self.drag_image = tk.Toplevel(self)
        self.drag_image.overrideredirect(True)
        self.drag_image.attributes("-alpha", 0.7)
        self.drag_image.attributes("-topmost", True)
        clone = ttk.Frame(self.drag_image)
        clone.pack(fill=tk.BOTH, expand=True)
        for child in widget.winfo_children():
            child_clone = ttk.Label(
                clone,
                image=child.image if hasattr(child, "image") else None,
                text=child["text"] if "text" in child.keys() else None,
            )
            child_clone.pack(side=tk.LEFT, padx=5)

        x = self.winfo_pointerx() - 100
        y = self.winfo_pointery()

        self.drag_image.geometry(f"+{x}+{y}")

    def on_drag_motion(self, event):
        if hasattr(self, "drag_image"):
            x = self.winfo_pointerx() - 100
            y = self.winfo_pointery()
            self.drag_image.geometry(f"+{x}+{y}")

        widget = self.get_parent_frame(event.widget)
        y = widget.winfo_y() + (event.y_root - widget._drag_start_mouse_y)
        widget._drag_start_mouse_y = event.y_root
        widget.place(y=y)

    def on_drag_release(self, event):
        if hasattr(self, "drag_image"):
            self.drag_image.destroy()
            del self.drag_image

        widget = self.get_parent_frame(event.widget)
        y = widget.winfo_y() + (event.y_root - widget._drag_start_mouse_y)
        widget.place(y=y)

        self.reorder_events()

    def reorder_events(self):
        sorted_frames = sorted(
            self.event_frame.winfo_children(), key=lambda w: w.winfo_y()
        )
        self.events = [
            self.events[int(f.winfo_children()[0]["text"]) - 1] for f in sorted_frames
        ]

        for widget in self.event_frame.winfo_children():
            widget.destroy()
        for idx, event in enumerate(self.events):
            self.add_event(idx, event)

    def load_profile(self, profile_name: str) -> ProfileModel:
        try:
            with open(f"{self.profiles_dir}/{profile_name}.pkl", "rb") as f:
                return pickle.load(f)
        except FileNotFoundError:
            messagebox.showerror("Error", f"File not found: {profile_name}")
            self.close_window()

    def save_events(self):
        self.profile.event_list = self.events

        try:
            with open(f"{self.profiles_dir}/{self.profile_name.get()}.pkl", "wb") as f:
                pickle.dump(self.profile, f)
        except Exception as e:
            logger.error(f"Failed to save events: {type(e)}, {str(e)}")
            return

        self.save_callback(self.profile_name.get())
        self.close_window()

    def close_window(self, event=None):
        self.save_window_state()
        self.master.load_settings()
        self.master.bind_events()
        self.destroy()

    def save_window_state(self):
        x = self.winfo_x()
        y = self.winfo_y()
        height = self.winfo_height()
        width = self.winfo_width()
        StateUtils.save_main_app_state(
            organizer_postition=f"{x}/{y}", organizer_size=f"{width}/{height}"
        )
