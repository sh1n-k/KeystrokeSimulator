import copy
import pickle
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Callable, Optional, List

from keystroke_event_editor import KeystrokeEventEditor
from keystroke_event_importer import EventImporter
from keystroke_models import ProfileModel, EventModel
from keystroke_utils import WindowUtils, StateUtils


class ProfileFrame(ttk.Frame):
    def __init__(self, master, name: str, fav: bool):
        super().__init__(master)
        self.fav_var = tk.BooleanVar(value=fav)

        ttk.Label(self, text="Profile Name: ").pack(side=tk.LEFT)
        self.entry = ttk.Entry(self)
        self.entry.pack(side=tk.LEFT, padx=1)
        self.entry.insert(0, name)
        ttk.Checkbutton(self, text="Favorite", variable=self.fav_var).pack(
            side=tk.LEFT, padx=5
        )

    def get_data(self):
        return self.entry.get(), self.fav_var.get()


class EventRow(ttk.Frame):
    def __init__(self, master, row_num: int, event: Optional[EventModel], cbs: dict):
        super().__init__(master)
        self.row_num, self.event, self.cbs = row_num, event, cbs
        self.use_var = tk.BooleanVar(value=event.use_event if event else True)

        # 1. Index
        ttk.Label(self, text=str(row_num + 1), width=2, anchor="center").pack(
            side=tk.LEFT
        )

        # 2. Checkbox
        ttk.Checkbutton(self, variable=self.use_var, command=self._on_toggle_use).pack(
            side=tk.LEFT
        )

        # 3. Independent Thread Indicator (고정 너비, 항상 존재)
        self.lbl_indep = ttk.Label(self, text="", width=2, anchor="center")
        self.lbl_indep.pack(side=tk.LEFT)

        # 4. Condition Indicator (고정 너비, 항상 존재)
        self.lbl_cond = ttk.Label(self, text="", width=6, anchor="center")
        self.lbl_cond.pack(side=tk.LEFT)

        # 5. Group ID Label
        self.lbl_grp = ttk.Label(
            self, text="", width=10, anchor="center", relief="sunken"
        )
        self.lbl_grp.pack(side=tk.LEFT, padx=2)

        # 6. Event Name Entry
        self.entry = ttk.Entry(self)
        self.entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        if event:
            self.entry.insert(0, event.event_name or "")

        # 7. Action Buttons
        for text, key in [("⚙️", "open"), ("📝", "copy"), ("🗑️", "remove")]:
            btn = ttk.Button(
                self, text=text, width=3, command=lambda k=key: self._on_click(k)
            )
            btn.pack(side=tk.LEFT, padx=1)
            btn.bind("<Button-3>", lambda e: self.cbs["menu"](e, self.row_num))

        # Context Menu Binding
        self.entry.bind("<Button-3>", lambda e: self.cbs["menu"](e, self.row_num))

        # Initial Display
        self.update_display()

    def update_display(self):
        """이벤트 상태에 따라 UI 갱신"""
        if not self.event:
            self.lbl_indep.config(text="")
            self.lbl_cond.config(text="")
            self.lbl_grp.config(text="")
            return

        self.use_var.set(self.event.use_event)

        # Name
        if self.entry.get() != (self.event.event_name or ""):
            self.entry.delete(0, tk.END)
            self.entry.insert(0, self.event.event_name or "")

        # Independent Thread
        is_indep = getattr(self.event, "independent_thread", False)
        self.lbl_indep.config(text="⚡" if is_indep else "")

        # Condition Only
        is_cond = not getattr(self.event, "execute_action", True)
        self.lbl_cond.config(text="[COND]" if is_cond else "")
        self.entry.config(foreground="gray" if is_cond else "black")

        # Group
        grp = self.event.group_id or ""
        self.lbl_grp.config(text=grp)

    def _on_toggle_use(self):
        if self.event:
            self.event.use_event = self.use_var.get()

    def _on_click(self, key):
        if key == "open":
            self.cbs["open"](self.row_num, self.event)
        elif key == "copy":
            self.cbs["copy"](self.event)
        elif key == "remove":
            self.cbs["remove"](self, self.row_num)

    def get_name(self) -> str:
        return self.entry.get()


class EventListFrame(ttk.Frame):
    def __init__(self, win, profile: ProfileModel, save_cb: Callable):
        super().__init__(win)
        self.win, self.profile, self.save_cb = win, profile, save_cb
        self.rows: List[EventRow] = []
        self.ctx_row = None

        # --- Control Buttons ---
        f_ctrl = ttk.Frame(self)
        f_ctrl.grid(row=1, column=0, columnspan=2, pady=5, sticky="we")

        ttk.Button(f_ctrl, text="Add Event", command=self._add_row).pack(
            side=tk.LEFT, padx=2, fill=tk.X, expand=True
        )
        ttk.Button(
            f_ctrl,
            text="Import From",
            command=lambda: EventImporter(self.win, self._import),
        ).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)

        # Auto Sort Button
        ttk.Button(f_ctrl, text="Auto Sort", command=self._sort_events).pack(
            side=tk.LEFT, padx=2, fill=tk.X, expand=True
        )

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(
            label="Apply Pixel/Region Info to Similar Areas",
            command=self._apply_pixel_batch,
        )
        self._load_events()

    def _sort_events(self):
        """
        이벤트 목록 자동 정렬 로직
        1. Independent Thread (True -> False)
        2. Group ID (String, Empty last)
        3. Priority (Ascending)
        4. Name (Ascending)
        """
        if not self.profile.event_list:
            return

        def sort_key(e: EventModel):
            is_indep = 0 if getattr(e, "independent_thread", False) else 1
            grp = getattr(e, "group_id", "") or ""
            grp_order = 0 if grp else 1
            prio = getattr(e, "priority", 0)
            name = e.event_name or ""
            return (is_indep, grp_order, grp, prio, name)

        self.save_names()
        self.profile.event_list.sort(key=sort_key)
        self.update_events()
        self.save_cb()
        messagebox.showinfo(
            "Sorted",
            "Events sorted by:\nIndependent -> Group -> Priority -> Name",
            parent=self.win,
        )

    def _show_menu(self, event, row_num):
        self.ctx_row = row_num
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _apply_pixel_batch(self):
        if self.ctx_row is None:
            return
        src = self.profile.event_list[self.ctx_row]
        if not (src.latest_position and src.clicked_position):
            return messagebox.showwarning(
                "Warning", "Invalid source event.", parent=self.win
            )

        if not messagebox.askyesno(
            "Confirm",
            f"Apply Info to all events with Area {src.latest_position}?",
            parent=self.win,
        ):
            return

        cnt = 0
        for i, evt in enumerate(self.profile.event_list):
            if (
                i != self.ctx_row
                and evt.latest_position == src.latest_position
                and evt.held_screenshot
            ):
                try:
                    evt.clicked_position = src.clicked_position
                    evt.ref_pixel_value = evt.held_screenshot.getpixel(
                        src.clicked_position
                    )
                    evt.match_mode = getattr(src, "match_mode", "pixel")
                    evt.region_size = getattr(src, "region_size", None)
                    cnt += 1
                except Exception:
                    print(f"Skipped {evt.event_name}")

        if cnt:
            self.save_cb()
            messagebox.showinfo("Success", f"{cnt} events updated.", parent=self.win)
        else:
            messagebox.showinfo("Info", "No matching events found.", parent=self.win)

    def _load_events(self):
        for i, evt in enumerate(self.profile.event_list):
            self._add_row(i, evt, resize=False)

    def _add_row(self, row_num=None, event=None, resize=True):
        idx = len(self.rows) if row_num is None else row_num
        cbs = {
            "open": self._open_editor,
            "copy": self._copy_row,
            "remove": self._remove_row,
            "menu": self._show_menu,
        }
        row = EventRow(self, idx, event, cbs)
        row.grid(row=idx + 3, column=0, columnspan=2, padx=5, pady=2, sticky="ew")
        self.rows.append(row)

    def _open_editor(self, row, evt):
        KeystrokeEventEditor(
            self.win,
            row,
            self._on_editor_save,
            lambda: evt,
            existing_events=self.profile.event_list,
        )

    def _on_editor_save(self, evt, is_edit, row=0):
        if is_edit and 0 <= row < len(self.profile.event_list):
            self.profile.event_list[row] = evt
        else:
            self.profile.event_list.append(evt)
        self.save_cb(check_name=False)

    def _copy_row(self, evt):
        if not evt:
            return messagebox.showinfo("Info", "Only set events can be copied")
        try:
            new = copy.deepcopy(evt)
            new.event_name = f"Copy of {evt.event_name}"
            self.profile.event_list.append(new)
            self._add_row(event=new)
            self.save_cb()
        except Exception as e:
            messagebox.showerror("Error", f"Copy failed: {e}")

    def _remove_row(self, row_widget, row_num):
        if len(self.profile.event_list) < 2:
            return messagebox.showinfo("Info", "Keep at least one event")
        row_widget.destroy()
        self.rows.remove(row_widget)
        if 0 <= row_num < len(self.profile.event_list):
            self.profile.event_list.pop(row_num)
        self.save_cb()
        self.win.update_idletasks()

    def _import(self, evts):
        self.profile.event_list.extend(evts)
        for e in evts:
            self._add_row(event=e)
        self.save_cb()

    def update_events(self):
        curr, new = len(self.rows), len(self.profile.event_list)

        # Update existing rows
        for i in range(min(curr, new)):
            self.rows[i].event = self.profile.event_list[i]
            self.rows[i].update_display()

        # Remove excess rows
        for r in self.rows[new:]:
            r.destroy()
        self.rows = self.rows[:new]

        # Add new rows
        for i in range(curr, new):
            self._add_row(i, self.profile.event_list[i], resize=False)

        self.win.update_idletasks()

    def save_names(self):
        for i, r in enumerate(self.rows):
            if i < len(self.profile.event_list):
                self.profile.event_list[i].event_name = r.get_name()


class KeystrokeProfiles:
    def __init__(self, main_win, prof_name, save_cb=None):
        self.main_win, self.prof_name, self.ext_save_cb = main_win, prof_name, save_cb
        self.prof_dir = Path("profiles")

        self.win = tk.Toplevel(main_win)
        self.win.title("Profile Manager")
        self.win.transient(main_win)
        self.win.grab_set()
        self.win.bind("<Escape>", self._close)
        self.win.protocol("WM_DELETE_WINDOW", self._close)

        self.profile = self._load()
        self.p_frame = ProfileFrame(self.win, prof_name, self.profile.favorite)
        self.p_frame.pack(pady=5)
        self.e_frame = EventListFrame(self.win, self.profile, self._save)
        self.e_frame.pack(fill="both", expand=True)

        f_btn = ttk.Frame(self.win, style="success.TFrame")
        f_btn.pack(side="bottom", anchor="e", pady=10, fill="both")
        ttk.Button(f_btn, text="Save Names", command=self._on_ok).pack(
            side=tk.LEFT, anchor="center", padx=5
        )

        self._load_pos()

    def _load(self):
        try:
            with open(self.prof_dir / f"{self.prof_name}.pkl", "rb") as f:
                p = pickle.load(f)
                # Backward compatibility defaults
                for e in p.event_list:
                    if not hasattr(e, "match_mode"):
                        e.match_mode = "pixel"
                    if not hasattr(e, "execute_action"):
                        e.execute_action = True
                    if not hasattr(e, "group_id"):
                        e.group_id = None
                    if not hasattr(e, "priority"):
                        e.priority = 0
                    if not hasattr(e, "conditions"):
                        e.conditions = {}
                    if not hasattr(e, "independent_thread"):
                        e.independent_thread = False
                p.favorite = getattr(p, "favorite", False)
                return p
        except Exception:
            return ProfileModel(name=self.prof_name, event_list=[], favorite=False)

    def _save(self, check_name=True, reload=True):
        if not self.profile.event_list:
            raise ValueError("At least one event must be set")
        new_name, is_fav = self.p_frame.get_data()

        if check_name and not new_name:
            raise ValueError("Enter profile name")
        self.profile.favorite = is_fav

        if new_name != self.prof_name:
            if (self.prof_dir / f"{new_name}.pkl").exists():
                raise ValueError(f"'{new_name}' exists.")
            (self.prof_dir / f"{self.prof_name}.pkl").unlink(missing_ok=True)
            self.prof_name = new_name

        if reload:
            self.e_frame.save_names()
        with open(self.prof_dir / f"{self.prof_name}.pkl", "wb") as f:
            pickle.dump(self.profile, f)
        if reload:
            self.e_frame.update_events()

    def _on_ok(self):
        try:
            self.e_frame.save_names()
            self._save(reload=False)
            self._close()
            if self.ext_save_cb:
                self.ext_save_cb(self.prof_name)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _close(self, event=None):
        StateUtils.save_main_app_state(
            prof_pos=f"{self.win.winfo_x()}/{self.win.winfo_y()}"
        )
        self.win.destroy()

    def _load_pos(self):
        if pos := StateUtils.load_main_app_state().get("prof_pos"):
            self.win.geometry(f"+{pos.split('/')[0]}+{pos.split('/')[1]}")
        else:
            WindowUtils.center_window(self.win)
