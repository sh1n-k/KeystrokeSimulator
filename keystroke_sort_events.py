import pickle
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable

from PIL import Image, ImageTk
from loguru import logger

from keystroke_models import EventModel, ProfileModel
from keystroke_utils import WindowUtils


class KeystrokeSortEvents(tk.Toplevel):
    def __init__(self, master, profile_name: str, save_callback: Callable[[str], None]):
        super().__init__(master)
        self.master = master
        self.profiles_dir = "./profiles"
        self.save_callback = save_callback

        self.title("Event Manager")
        self.configure(bg='#2E2E2E')

        self.profile_name = tk.StringVar(value=profile_name)
        self.profile = self.load_profile(profile_name)
        self.events = self.profile.event_list

        self.create_widgets()

        self.bind("<Escape>", self.close_window)
        self.protocol("WM_DELETE_WINDOW", self.close_window)

        WindowUtils.center_window(self)

    def create_widgets(self):
        # Profile Name frame
        profile_frame = ttk.Frame(self)
        profile_frame.pack(pady=10, padx=10, fill=tk.X)

        ttk.Label(profile_frame, text="Profile Name:").pack(side=tk.LEFT, padx=(0, 5))
        (ttk.Entry(profile_frame, textvariable=self.profile_name, state="readonly")
         .pack(side=tk.LEFT, expand=True, fill=tk.BOTH))

        # Event Frame
        self.event_frame = ttk.Frame(self)
        self.event_frame.pack(pady=10, fill=tk.BOTH, expand=True)

        # Add existing events
        for idx, event in enumerate(self.events):
            self.add_event(idx, event)

        # Save Button
        ttk.Button(self, text="Save", command=self.save_events).pack(pady=10)

    def add_event(self, idx: int, event=None):
        if event is None:
            event = EventModel()
            self.events.append(event)

        frame = ttk.Frame(self.event_frame, style='Event.TFrame')
        frame.pack(pady=5, fill=tk.X, padx=5)
        frame.configure(borderwidth=2, relief="solid")
        style = ttk.Style()
        style.configure('Event.TFrame', background='#2E2E2E', bordercolor='red')

        # Index label
        index_label = ttk.Label(frame, text=f"{idx + 1}")
        index_label.pack(side=tk.LEFT, padx=5)

        # Placeholder for screenshot
        if event.held_screenshot:
            img = ImageTk.PhotoImage(event.held_screenshot.resize((50, 50)))
        else:
            img = ImageTk.PhotoImage(Image.new('RGB', (50, 50), color='gray'))
        img_label = ttk.Label(frame, image=img)
        img_label.image = img  # Keep a reference to prevent garbage collection
        img_label.pack(side=tk.LEFT, padx=5)

        event_name_var = tk.StringVar(value=event.event_name if event.event_name else "")
        entry = ttk.Entry(frame, textvariable=event_name_var)
        entry.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

        event_name_var.trace_add("write", lambda *args: self.update_event_name(event, event_name_var))

        # Start/Stop key display (read-only)
        key_entry = ttk.Label(frame, text=event.key_to_enter or "N/A", width=3, anchor="w",  state="readonly")
        key_entry.pack(side=tk.LEFT, padx=5)

        self.configure_drag_and_drop(frame)
        for idx, child in enumerate(frame.winfo_children()):
            if idx < 2:
                self.configure_drag_and_drop(child)

    def configure_drag_and_drop(self, widget):
        widget.bind("<ButtonPress-1>", self.on_drag_start)
        widget.bind("<B1-Motion>", self.on_drag_motion)
        widget.bind("<ButtonRelease-1>", self.on_drag_release)

    def update_event_name(self, event: EventModel, name_var: tk.StringVar):
        event.event_name = name_var.get()

    def on_drag_start(self, event):
        widget = event.widget
        while not isinstance(widget, ttk.Frame):
            widget = widget.master
        widget._drag_start_y = event.y_root - widget.winfo_rooty()
        widget._drag_start_mouse_y = event.y_root

        # Create a clone of the widget for dragging
        self.drag_image = tk.Toplevel(self)
        self.drag_image.overrideredirect(True)
        self.drag_image.attributes('-alpha', 0.7)  # Make it semi-transparent
        self.drag_image.attributes('-topmost', True)  # Ensure it's always on top
        clone = ttk.Frame(self.drag_image)
        clone.pack(fill=tk.BOTH, expand=True)
        for child in widget.winfo_children():
            child_clone = ttk.Label(clone, image=child.image if hasattr(child, 'image') else None,
                                    text=child['text'] if 'text' in child.keys() else None)
            child_clone.pack(side=tk.LEFT, padx=5)

        # Position the clone at the mouse cursor
        x = self.winfo_pointerx() - self.winfo_rootx()
        y = self.winfo_pointery() - self.winfo_rooty()
        self.drag_image.geometry(f"+{x}+{y}")

    def on_drag_motion(self, event):
        if hasattr(self, 'drag_image'):
            x = self.winfo_pointerx() - self.winfo_rootx()
            y = self.winfo_pointery() - self.winfo_rooty()
            self.drag_image.geometry(f"+{x}+{y}")

        widget = event.widget
        while not isinstance(widget, ttk.Frame):
            widget = widget.master
        y = widget.winfo_y() + (event.y_root - widget._drag_start_mouse_y)
        widget._drag_start_mouse_y = event.y_root
        widget.place(y=y)

    def on_drag_release(self, event):
        if hasattr(self, 'drag_image'):
            self.drag_image.destroy()
            del self.drag_image

        widget = event.widget
        while not isinstance(widget, ttk.Frame):
            widget = widget.master
        y = widget.winfo_y() + (event.y_root - widget._drag_start_mouse_y)
        widget.place(y=y)

        # Reorder events based on new positions
        sorted_frames = sorted(self.event_frame.winfo_children(), key=lambda w: w.winfo_y())
        self.events = [self.events[int(f.winfo_children()[0]['text']) - 1] for f in sorted_frames]

        # Update event order and redraw
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
        # if messagebox.askokcancel("Warning", f"Any changes made will be canceled.\n변경된 내용이 취소됩니다."):
        #     self.destroy()
        #     return
        self.master.load_settings()
        self.master.bind_events()
        self.destroy()
