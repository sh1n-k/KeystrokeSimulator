import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Callable, Optional

from PIL import Image, ImageTk
from loguru import logger

from keystroke_models import EventModel
from keystroke_profile_storage import load_profile, save_profile
from keystroke_utils import StateUtils, WindowUtils

SW_PAD_XS = 2
SW_PAD_SM = 4
SW_PAD_MD = 8
SW_PAD_LG = 12
SW_ROW_IMAGE_SIZE = 40

SW_BG_BASE = "#f3f2ee"
SW_BG_PANEL = "#f7f6f2"
SW_BG_ROW = "#efeee9"
SW_BG_CHIP = "#e8e6de"
SW_BG_THUMBNAIL = "#d9d6cd"
SW_BG_ROW_ACTIVE = "#e7e5dc"

SW_FG_PRIMARY = "#2f2f2a"
SW_FG_MUTED = "#6f6d64"
SW_FG_WARN = "#8a6f2d"
SW_BORDER_SOFT = "#d6d3c9"


class KeystrokeSortEvents(tk.Toplevel):
    HEADER_COLUMNS = [
        ("#", 3, "center", False),
        ("사용", 3, "center", False),
        ("이미지", 6, "center", False),
        ("그룹(우선순위)", 14, "center", False),
        ("이벤트 이름", 0, "w", True),
        ("입력 키", 8, "center", False),
    ]

    def __init__(self, master, profile_name: str, save_callback: Callable[[str], None]):
        super().__init__(master)
        self.master, self.save_cb = master, save_callback
        self.prof_dir = Path("profiles")
        self.title("이벤트 정렬")
        self.configure(bg=SW_BG_BASE)

        style = ttk.Style(self)
        style.configure("SortReadonly.TEntry", fieldbackground="#fbfaf7")

        self.prof_name = tk.StringVar(value=profile_name)
        self.profile: Optional[object] = self._load_profile(profile_name)
        if not self.profile:
            self.after(0, self.destroy)
            return
        self.events = self.profile.event_list
        self._preview_win = None
        self._preview_photo = None

        self._create_ui()
        self._load_state()

        self.bind("<Escape>", self.close)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.focus_force()

    def _create_ui(self):
        # 1. Top Toolbar
        f_top = tk.Frame(
            self,
            bg=SW_BG_PANEL,
            highlightbackground=SW_BORDER_SOFT,
            highlightthickness=1,
            bd=0,
        )
        f_top.pack(pady=(SW_PAD_MD, SW_PAD_SM), padx=SW_PAD_MD, fill=tk.X)
        tk.Label(
            f_top,
            text="프로필:",
            bg=SW_BG_PANEL,
            fg=SW_FG_MUTED,
        ).pack(side=tk.LEFT, padx=(SW_PAD_MD, SW_PAD_SM), pady=SW_PAD_SM)
        ttk.Entry(
            f_top,
            textvariable=self.prof_name,
            state="readonly",
            style="SortReadonly.TEntry",
        ).pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=(0, SW_PAD_MD), pady=SW_PAD_SM)
        ttk.Button(
            f_top,
            text="저장 후 닫기",
            command=self.save,
        ).pack(side=tk.RIGHT, padx=(0, SW_PAD_MD), pady=SW_PAD_SM)

        # 3. [New] Column Headers
        self._create_header()

        # 4. Scrollable Area
        body = tk.Frame(self, bg=SW_BG_BASE)
        body.pack(fill=tk.BOTH, expand=True, padx=SW_PAD_MD, pady=(0, SW_PAD_MD))

        self.canvas = tk.Canvas(
            body,
            bg=SW_BG_BASE,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=sb.set)

        self.f_events = tk.Frame(self.canvas, bg=SW_BG_BASE)
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
        f_h = tk.Frame(
            self,
            bg=SW_BG_PANEL,
            highlightbackground=SW_BORDER_SOFT,
            highlightthickness=1,
            bd=0,
        )
        f_h.pack(fill=tk.X, padx=SW_PAD_MD, pady=(SW_PAD_SM, SW_PAD_SM))

        for text, width, anchor, expand in self.HEADER_COLUMNS:
            kw = {
                "text": text,
                "bg": SW_BG_PANEL,
                "fg": SW_FG_MUTED,
                "anchor": anchor,
            }
            if width:
                kw["width"] = width
            tk.Label(f_h, **kw).pack(
                side=tk.LEFT,
                padx=SW_PAD_SM,
                pady=SW_PAD_SM,
                fill=tk.X if expand else None,
                expand=expand,
            )

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.win_id, width=event.width)

    def _refresh_list(self):
        for w in self.f_events.winfo_children():
            w.destroy()
        for i, evt in enumerate(self.events):
            self._add_row(i, evt)

    @staticmethod
    def _format_group_text(evt: EventModel) -> str:
        if evt.group_id:
            return f"{evt.group_id} ({evt.priority})"
        return "그룹 없음"

    @staticmethod
    def _format_key_text(evt: EventModel) -> tuple[str, str]:
        if not getattr(evt, "execute_action", True):
            return "조건", SW_FG_MUTED
        key = (evt.key_to_enter or "").strip()
        if key:
            return key, SW_FG_PRIMARY
        return "키 없음", SW_FG_WARN

    def _add_row(self, idx, evt):
        f = tk.Frame(
            self.f_events,
            bg=SW_BG_ROW,
            highlightbackground=SW_BORDER_SOFT,
            highlightthickness=1,
            bd=0,
        )
        f.pack(pady=(0, SW_PAD_XS), fill=tk.X)

        widgets = []

        # 1. Index
        widgets.append(
            tk.Label(
                f,
                text=f"{idx + 1}",
                width=3,
                anchor="center",
                bg=SW_BG_ROW,
                fg=SW_FG_PRIMARY,
            )
        )

        # 2. Use Checkbox
        var = tk.BooleanVar(value=evt.use_event)
        var.trace_add("write", lambda *a: setattr(evt, "use_event", var.get()))
        widgets.append(ttk.Checkbutton(f, variable=var))

        # 3. Image
        img = (
            evt.held_screenshot.resize((SW_ROW_IMAGE_SIZE, SW_ROW_IMAGE_SIZE))
            if evt.held_screenshot
            else Image.new("RGB", (SW_ROW_IMAGE_SIZE, SW_ROW_IMAGE_SIZE), SW_BG_THUMBNAIL)
        )
        photo = ImageTk.PhotoImage(img)
        lbl_img = tk.Label(f, image=photo, bg=SW_BG_ROW)
        lbl_img.image = photo
        self._bind_image_preview(lbl_img, evt)
        widgets.append(lbl_img)

        # 4. Group Info
        grp_text = self._format_group_text(evt)
        grp_fg = SW_FG_PRIMARY if evt.group_id else SW_FG_MUTED
        lbl_grp = tk.Label(
            f,
            text=grp_text,
            width=14,
            anchor="center",
            bg=SW_BG_CHIP,
            fg=grp_fg,
            relief="groove",
            bd=1,
        )
        widgets.append(lbl_grp)

        # 5. Event Name
        name_var = tk.StringVar(value=evt.event_name or "")
        name_var.trace_add(
            "write", lambda *a: setattr(evt, "event_name", name_var.get())
        )
        widgets.append(ttk.Entry(f, textvariable=name_var))

        # 6. Key or Type
        key_text, key_fg = self._format_key_text(evt)
        lbl_key = tk.Label(
            f,
            text=key_text,
            width=8,
            anchor="center",
            bg=SW_BG_ROW,
            fg=key_fg,
        )
        widgets.append(lbl_key)

        # Pack & Bind
        for w in widgets:
            is_interactive = isinstance(w, (ttk.Entry, ttk.Checkbutton))
            is_image_widget = w is lbl_img

            w.pack(
                side=tk.LEFT,
                padx=SW_PAD_SM,
                pady=SW_PAD_SM,
                fill=tk.Y if isinstance(w, ttk.Entry) else None,
                expand=isinstance(w, ttk.Entry),
            )

            if not is_interactive and not is_image_widget:
                self._bind_drag_events(w, f)

        self._bind_drag_events(f, f)

    # ... (이하 기존 메서드 동일: _bind_drag_events, _drag_start, _drag_motion, _drag_end, _load_profile, save, close, _load_state) ...
    def _bind_drag_events(self, widget, parent_frame):
        widget.bind("<ButtonPress-1>", lambda e: self._drag_start(e, parent_frame))
        widget.bind("<B1-Motion>", lambda e: self._drag_motion(e, parent_frame))
        widget.bind("<ButtonRelease-1>", lambda e: self._drag_end(e, parent_frame))

    def _bind_image_preview(self, widget, evt):
        widget.bind("<ButtonPress-1>", lambda e: self._open_image_preview(evt, e))

    def _open_image_preview(self, evt, click_event=None):
        if not evt.held_screenshot:
            return

        self._close_image_preview()

        preview = tk.Toplevel(self)
        preview.title("Event Image Preview")
        preview.transient(self)
        preview.protocol("WM_DELETE_WINDOW", self._close_image_preview)
        preview.bind("<Escape>", self._close_image_preview)

        img = evt.held_screenshot
        self._preview_photo = ImageTk.PhotoImage(img)
        lbl = ttk.Label(preview, image=self._preview_photo)
        lbl.image = self._preview_photo
        lbl.pack()

        x = click_event.x_root if click_event else self.winfo_rootx()
        y = click_event.y_root if click_event else self.winfo_rooty()
        offset_x, offset_y = 12, 12
        x += offset_x
        y += offset_y
        max_x = max(0, self.winfo_screenwidth() - img.width)
        max_y = max(0, self.winfo_screenheight() - img.height)
        x = min(max(0, x), max_x)
        y = min(max(0, y), max_y)

        preview.geometry(f"{img.width}x{img.height}+{x}+{y}")
        preview.focus_force()

        self._preview_win = preview

    def _close_image_preview(self, event=None):
        if self._preview_win and self._preview_win.winfo_exists():
            self._preview_win.destroy()
        self._preview_win = None
        self._preview_photo = None

    def _drag_start(self, event, frame):
        self._drag_data = {
            "y": event.y_root,
            "frame": frame,
            "start_y": frame.winfo_y(),
        }
        frame.lift()
        frame.configure(cursor="hand2", bg=SW_BG_ROW_ACTIVE)

    def _drag_motion(self, event, frame):
        if not hasattr(self, "_drag_data"):
            return
        dy = event.y_root - self._drag_data["y"]
        frame.place(y=self._drag_data["start_y"] + dy, x=0, relwidth=1.0)

    def _drag_end(self, event, frame):
        if not hasattr(self, "_drag_data"):
            return
        frame.configure(cursor="", bg=SW_BG_ROW)

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
            messagebox.showerror(
                "오류",
                f"프로필을 불러오지 못했습니다: {name}",
                parent=self,
            )
            self.close()

    def save(self):
        self.profile.event_list = self.events
        try:
            save_profile(self.prof_dir, self.profile, name=self.prof_name.get())
            self.save_cb(self.prof_name.get())
            self.close()
        except Exception as e:
            logger.error(f"Save failed: {e}")
            messagebox.showerror(
                "저장 실패",
                f"프로필 저장 중 오류가 발생했습니다:\n{e}",
                parent=self,
            )

    def close(self, event=None):
        self._close_image_preview()
        self.unbind_all("<MouseWheel>")
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
