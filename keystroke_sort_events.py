import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Callable

from PIL import Image, ImageTk
from loguru import logger

from keystroke_models import EventModel
from keystroke_profile_storage import load_profile, save_profile
from keystroke_utils import StateUtils, WindowUtils


class KeystrokeSortEvents(tk.Toplevel):
    def __init__(self, master, profile_name: str, save_callback: Callable[[str], None]):
        super().__init__(master)
        self.master, self.save_cb = master, save_callback
        self.prof_dir = Path("profiles")
        self.title("Event Organizer")
        self.configure(bg="#2E2E2E")

        style = ttk.Style(self)
        style.configure(
            "Event.TFrame", background="#2E2E2E", relief="solid", borderwidth=1
        )
        style.configure("TLabel", background="#2E2E2E", foreground="white")
        style.configure("TCheckbutton", background="#2E2E2E")
        style.configure("Group.TLabel", background="#3E3E3E", foreground="#AAAAAA", relief="groove")

        self.prof_name = tk.StringVar(value=profile_name)
        self.profile = self._load_profile(profile_name)
        self.events = self.profile.event_list

        self._create_ui()
        self._load_state()

        self.bind("<Escape>", self.close)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.focus_force()

    def _create_ui(self):
        # 1. Top Frame (Profile Name)
        f_top = tk.Frame(self, bg="#2E2E2E")
        f_top.pack(pady=10, padx=10, fill=tk.X)
        tk.Label(f_top, text="Profile Name:", bg="#2E2E2E", fg="white").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Entry(f_top, textvariable=self.prof_name, state="readonly").pack(
            side=tk.LEFT, expand=True, fill=tk.BOTH
        )

        # 2. Save Button
        ttk.Button(self, text="Save", command=self.save).pack(pady=5)

        # 3. [New] Column Headers
        self._create_header()

        # 4. Scrollable Area
        self.canvas = tk.Canvas(self, bg="#2E2E2E", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=sb.set)

        self.f_events = tk.Frame(self.canvas, bg="#2E2E2E")
        self.win_id = self.canvas.create_window(
            (0, 0), window=self.f_events, anchor="nw"
        )

        self.f_events.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

        self._refresh_list()

    def _create_header(self):
        """컬럼 타이틀 헤더 생성"""
        f_h = tk.Frame(self, bg="#2E2E2E")
        # padx=(5, 20): 왼쪽은 행과 맞추고, 오른쪽은 스크롤바 너비만큼 여백을 줌
        f_h.pack(fill=tk.X, padx=(5, 20), pady=(10, 0))

        # _add_row의 위젯 구성과 너비를 맞춰서 라벨 배치
        # 1. No
        tk.Label(f_h, text="No", width=3, bg="#2E2E2E", fg="gray").pack(side=tk.LEFT, padx=5)
        # 2. Use (Checkbox)
        tk.Label(f_h, text="Use", width=3, bg="#2E2E2E", fg="gray").pack(side=tk.LEFT, padx=5)
        # 3. Img
        tk.Label(f_h, text="Img", width=6, bg="#2E2E2E", fg="gray").pack(side=tk.LEFT, padx=5)
        # 4. Group
        tk.Label(f_h, text="Group (Prio)", width=12, bg="#2E2E2E", fg="gray").pack(side=tk.LEFT, padx=5)
        # 5. Name (Expandable)
        tk.Label(f_h, text="Event Name", bg="#2E2E2E", fg="gray", anchor="w").pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        # 6. Key/Type
        tk.Label(f_h, text="Key", width=6, bg="#2E2E2E", fg="gray").pack(side=tk.LEFT, padx=5)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.win_id, width=event.width)

    def _refresh_list(self):
        for w in self.f_events.winfo_children():
            w.destroy()
        for i, evt in enumerate(self.events):
            self._add_row(i, evt)

    def _add_row(self, idx, evt):
        f = ttk.Frame(self.f_events, style="Event.TFrame")
        f.pack(pady=2, fill=tk.X, padx=5)

        widgets = []
        
        # 1. Index
        widgets.append(ttk.Label(f, text=f"{idx + 1}", width=3, anchor="center"))

        # 2. Use Checkbox
        var = tk.BooleanVar(value=evt.use_event)
        var.trace_add("write", lambda *a: setattr(evt, "use_event", var.get()))
        widgets.append(ttk.Checkbutton(f, variable=var))

        # 3. Image
        img = (
            evt.held_screenshot.resize((40, 40))
            if evt.held_screenshot
            else Image.new("RGB", (40, 40), "gray")
        )
        photo = ImageTk.PhotoImage(img)
        lbl_img = ttk.Label(f, image=photo)
        lbl_img.image = photo
        widgets.append(lbl_img)

        # 4. Group Info
        grp_text = ""
        if evt.group_id:
            grp_text = f"{evt.group_id} ({evt.priority})"
        
        lbl_grp = ttk.Label(f, text=grp_text, width=12, anchor="center", style="Group.TLabel")
        widgets.append(lbl_grp)

        # 5. Event Name
        name_var = tk.StringVar(value=evt.event_name or "")
        name_var.trace_add(
            "write", lambda *a: setattr(evt, "event_name", name_var.get())
        )
        widgets.append(ttk.Entry(f, textvariable=name_var))

        # 6. Key or Type
        if getattr(evt, "execute_action", True):
            key_text = evt.key_to_enter or "N/A"
            fg_color = "white"
        else:
            key_text = "Cond"
            fg_color = "#888888"
            
        lbl_key = ttk.Label(f, text=key_text, width=6, anchor="center")
        if fg_color != "white":
            lbl_key.configure(foreground=fg_color)
        widgets.append(lbl_key)

        # Pack & Bind
        for w in widgets:
            is_interactive = isinstance(w, (ttk.Entry, ttk.Checkbutton))
            
            w.pack(
                side=tk.LEFT, padx=5, fill=tk.Y if isinstance(w, ttk.Entry) else None, expand=isinstance(w, ttk.Entry)
            )

            if not is_interactive:
                self._bind_drag_events(w, f)

        self._bind_drag_events(f, f)

    # ... (이하 기존 메서드 동일: _bind_drag_events, _drag_start, _drag_motion, _drag_end, _load_profile, save, close, _load_state) ...
    def _bind_drag_events(self, widget, parent_frame):
        widget.bind("<ButtonPress-1>", lambda e: self._drag_start(e, parent_frame))
        widget.bind("<B1-Motion>", lambda e: self._drag_motion(e, parent_frame))
        widget.bind("<ButtonRelease-1>", lambda e: self._drag_end(e, parent_frame))

    def _drag_start(self, event, frame):
        self._drag_data = {
            "y": event.y_root,
            "frame": frame,
            "start_y": frame.winfo_y(),
        }
        frame.lift()
        frame.configure(cursor="hand2")

    def _drag_motion(self, event, frame):
        if not hasattr(self, "_drag_data"):
            return
        dy = event.y_root - self._drag_data["y"]
        frame.place(y=self._drag_data["start_y"] + dy, x=5, relwidth=0.95)

    def _drag_end(self, event, frame):
        if not hasattr(self, "_drag_data"):
            return
        frame.configure(cursor="")

        rows = sorted(
            [w for w in self.f_events.winfo_children() if w != frame],
            key=lambda w: w.winfo_y(),
        )

        current_y = frame.winfo_y()
        insert_idx = len(rows)
        for i, r in enumerate(rows):
            if current_y < r.winfo_y() + (r.winfo_height() / 2):
                insert_idx = i
                break

        old_idx = int(frame.winfo_children()[0].cget("text")) - 1
        moved_event = self.events.pop(old_idx)
        self.events.insert(insert_idx, moved_event)

        del self._drag_data
        self._refresh_list()

    def _load_profile(self, name):
        try:
            return load_profile(self.prof_dir, name, migrate=True)
        except Exception:
            messagebox.showerror("Error", f"Load failed: {name}")
            self.close()

    def save(self):
        self.profile.event_list = self.events
        try:
            save_profile(self.prof_dir, self.profile, name=self.prof_name.get())
            self.save_cb(self.prof_name.get())
            self.close()
        except Exception as e:
            logger.error(f"Save failed: {e}")

    def close(self, event=None):
        StateUtils.save_main_app_state(
            org_pos=f"{self.winfo_x()}/{self.winfo_y()}",
            org_size=f"{self.winfo_width()}/{self.winfo_height()}",
        )
        self.master.load_settings()
        self.master.setup_event_handlers()
        self.destroy()

    def _load_state(self):
        s = StateUtils.load_main_app_state()
        if s and (p := s.get("org_pos")) and (sz := s.get("org_size")):
            self.geometry(
                f"{sz.split('/')[0]}x{sz.split('/')[1]}+{p.split('/')[0]}+{p.split('/')[1]}"
            )
        else:
            WindowUtils.center_window(self)
