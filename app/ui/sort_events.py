from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Any, ClassVar, Literal, Protocol, TypedDict, cast

from PIL import Image, ImageTk
from loguru import logger
from app.utils.i18n import dual_text_width, txt

from app.core.models import EventModel, ProfileModel
from app.storage.profile_storage import load_profile, save_profile
from app.utils.window_state import StateUtils, WindowUtils
from app.ui import theme

SW_PAD_XS = theme.SPACE_1
SW_PAD_SM = theme.SPACE_1
SW_PAD_MD = theme.SPACE_2
SW_ROW_IMAGE_SIZE = 40

# Workstation tones — these legacy names now alias the canonical
# design tokens defined in app/ui/theme.py.
SW_BG_BASE = theme.SURFACE_PAPER
SW_BG_PANEL = theme.SURFACE_PANEL
SW_BG_ROW = theme.SURFACE_CANVAS
SW_BG_CHIP = theme.SURFACE_SUNKEN
SW_BG_THUMBNAIL = theme.SURFACE_SUNKEN
SW_BG_ROW_ACTIVE = theme.SIGNAL_TINT

SW_FG_PRIMARY = theme.INK_PRIMARY
SW_FG_MUTED = theme.INK_MUTED
SW_FG_WARN = theme.STATUS_WARN_FG
SW_BORDER_SOFT = theme.SURFACE_DIVIDER

HeaderAnchor = Literal["center", "w"]


class SortHost(Protocol):
    def load_settings(self) -> None: ...

    def setup_event_handlers(self) -> None: ...


class DragData(TypedDict):
    y: int
    frame: tk.Frame
    start_y: int


class KeystrokeSortEvents(tk.Toplevel):
    HEADER_COLUMNS: ClassVar[list[tuple[str, int, HeaderAnchor, bool, str]]] = [
        ("", 2, "center", False, ""),
        ("#", 3, "center", False, "#"),
        ("Enabled", 5, "center", False, "사용"),
        ("Image", 6, "center", False, "이미지"),
        ("Group (Priority)", 16, "center", False, "그룹(우선순위)"),
        ("Event Name", 0, "w", True, "이벤트 이름"),
        ("Input Key", 10, "center", False, "입력 키"),
    ]

    _drag_data: DragData

    def __init__(
        self,
        master: tk.Misc,
        profile_name: str,
        save_callback: Callable[[str], None],
        *,
        profiles_dir: Path,
    ) -> None:
        super().__init__(master)
        self.master, self.save_cb = master, save_callback
        self.app_master = cast(SortHost, master)
        self.prof_dir = profiles_dir
        self.title(txt("Sort Events", "이벤트 정렬"))
        self.configure(bg=SW_BG_BASE)

        style = ttk.Style(self)
        style.configure("SortReadonly.TEntry", fieldbackground=theme.SURFACE_PAPER)

        self.prof_name = tk.StringVar(value=profile_name)
        self.profile: ProfileModel | None = self._load_profile(profile_name)
        if not self.profile:
            self.after(0, self.destroy)
            return
        self.events = self.profile.event_list
        self._preview_win: tk.Toplevel | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self.lbl_summary: tk.Label | None = None
        self.canvas: tk.Canvas
        self.f_events: tk.Frame
        self.win_id: int

        self._create_ui()
        self._load_state()

        self.bind("<Escape>", self.close)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.focus_force()

    def _create_ui(self) -> None:
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
            text=txt("Profile:", "프로필:"),
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
            text=txt("Save and Close", "저장 후 닫기"),
            width=dual_text_width("Save and Close", "저장 후 닫기", padding=2, min_width=14),
            command=self.save,
        ).pack(side=tk.RIGHT, padx=(0, SW_PAD_MD), pady=SW_PAD_SM)

        self.lbl_summary = tk.Label(
            self,
            bg=SW_BG_BASE,
            fg=SW_FG_MUTED,
            justify="left",
            anchor="w",
            wraplength=760,
        )
        self.lbl_summary.pack(fill=tk.X, padx=SW_PAD_MD, pady=(0, SW_PAD_SM))

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

        sb = ttk.Scrollbar(
            body,
            orient="vertical",
            command=cast(
                Callable[..., tuple[float, float] | None],
                cast(Any, self.canvas).yview,
            ),
        )
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=sb.set)

        self.f_events = tk.Frame(self.canvas, bg=SW_BG_BASE)
        self.win_id = self.canvas.create_window(
            (0, 0), window=self.f_events, anchor="nw"
        )

        self.f_events.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mouse_wheel)

        self._refresh_list()

    def _build_summary_text(self) -> str:
        return txt(
            "{count} event(s). Drag the handle to reorder. Click an image to open a full preview.",
            "이벤트 {count}개. 핸들을 드래그해서 순서를 바꾸고, 이미지를 클릭하면 크게 볼 수 있습니다.",
            count=len(self.events),
        )

    def _create_header(self) -> None:
        """컬럼 타이틀 헤더 생성"""
        f_h = tk.Frame(
            self,
            bg=SW_BG_PANEL,
            highlightbackground=SW_BORDER_SOFT,
            highlightthickness=1,
            bd=0,
        )
        f_h.pack(fill=tk.X, padx=SW_PAD_MD, pady=(SW_PAD_SM, SW_PAD_SM))

        for en_text, width, anchor, expand, ko_text in self.HEADER_COLUMNS:
            if width:
                label = tk.Label(
                    f_h,
                    text=txt(en_text, ko_text),
                    bg=SW_BG_PANEL,
                    fg=SW_FG_MUTED,
                    anchor=anchor,
                    width=width,
                )
            else:
                label = tk.Label(
                    f_h,
                    text=txt(en_text, ko_text),
                    bg=SW_BG_PANEL,
                    fg=SW_FG_MUTED,
                    anchor=anchor,
                )
            if expand:
                label.pack(
                    side=tk.LEFT,
                    padx=SW_PAD_SM,
                    pady=SW_PAD_SM,
                    fill=tk.X,
                    expand=True,
                )
            else:
                label.pack(
                    side=tk.LEFT,
                    padx=SW_PAD_SM,
                    pady=SW_PAD_SM,
                    expand=False,
                )

    def _on_frame_configure(self, event: object) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfig(self.win_id, width=event.width)

    def _on_mouse_wheel(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _refresh_list(self) -> None:
        for w in self.f_events.winfo_children():
            w.destroy()
        for i, evt in enumerate(self.events):
            self._add_row(i, evt)
        if self.lbl_summary:
            self.lbl_summary.config(text=self._build_summary_text())

    @staticmethod
    def _format_group_text(evt: EventModel) -> str:
        if evt.group_id:
            return f"{evt.group_id} ({evt.priority})"
        return txt("No Group", "그룹 없음")

    @staticmethod
    def _format_key_text(evt: EventModel) -> tuple[str, str]:
        if not getattr(evt, "execute_action", True):
            return txt("Condition", "조건"), SW_FG_MUTED
        key = (evt.key_to_enter or "").strip()
        if key:
            return key, SW_FG_PRIMARY
        return txt("No Key", "키 없음"), SW_FG_WARN

    def _add_row(self, idx: int, evt: EventModel) -> None:
        f = tk.Frame(
            self.f_events,
            bg=SW_BG_ROW,
            highlightbackground=SW_BORDER_SOFT,
            highlightthickness=1,
            bd=0,
        )
        f.pack(pady=(0, SW_PAD_XS), fill=tk.X)
        cast(Any, f)._event_model = evt

        widgets: list[tk.Widget] = []

        # 0. Drag handle (visual affordance; cursor switches to hand2)
        lbl_handle = tk.Label(
            f,
            text="⋮⋮",
            width=2,
            anchor="center",
            bg=SW_BG_ROW,
            fg=SW_FG_MUTED,
            cursor="hand2",
        )
        widgets.append(lbl_handle)

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

        def update_use_event(*_args: object) -> None:
            evt.use_event = var.get()

        var.trace_add("write", update_use_event)
        widgets.append(ttk.Checkbutton(f, variable=var))

        # 3. Image
        img = (
            cast(
                Image.Image,
                cast(Any, evt.held_screenshot).resize(
                    (SW_ROW_IMAGE_SIZE, SW_ROW_IMAGE_SIZE)
                ),
            )
            if evt.held_screenshot
            else Image.new("RGB", (SW_ROW_IMAGE_SIZE, SW_ROW_IMAGE_SIZE), SW_BG_THUMBNAIL)
        )
        photo = ImageTk.PhotoImage(img)
        lbl_img = tk.Label(f, image=photo, bg=SW_BG_ROW)
        cast(Any, lbl_img).image = photo
        self._bind_image_preview(lbl_img, evt)
        widgets.append(lbl_img)

        # 4. Group Info
        grp_text = self._format_group_text(evt)
        grp_fg = SW_FG_PRIMARY if evt.group_id else SW_FG_MUTED
        lbl_grp = tk.Label(
            f,
            text=grp_text,
            width=16,
            anchor="center",
            bg=SW_BG_CHIP,
            fg=grp_fg,
            relief="groove",
            bd=1,
        )
        widgets.append(lbl_grp)

        # 5. Event Name
        name_var = tk.StringVar(value=evt.event_name or "")

        def update_event_name(*_args: object) -> None:
            evt.event_name = name_var.get()

        name_var.trace_add("write", update_event_name)
        widgets.append(ttk.Entry(f, textvariable=name_var))

        # 6. Key or Type
        key_text, key_fg = self._format_key_text(evt)
        lbl_key = tk.Label(
            f,
            text=key_text,
            width=10,
            anchor="center",
            bg=SW_BG_ROW,
            fg=key_fg,
        )
        widgets.append(lbl_key)

        # Pack & Bind. Only the explicit handle starts a drag; other text
        # areas stay passive so accidental row movement is less likely.
        for widget in widgets:
            if isinstance(widget, ttk.Entry):
                widget.pack(
                    side=tk.LEFT,
                    padx=SW_PAD_SM,
                    pady=SW_PAD_SM,
                    fill=tk.Y,
                    expand=True,
                )
            else:
                widget.pack(
                    side=tk.LEFT,
                    padx=SW_PAD_SM,
                    pady=SW_PAD_SM,
                    expand=False,
                )

        self._bind_drag_events(lbl_handle, f)

    def _bind_drag_events(self, widget: tk.Widget, parent_frame: tk.Frame) -> None:
        def on_drag_start(event: tk.Event[tk.Misc]) -> None:
            self._drag_start(event, parent_frame)

        def on_drag_motion(event: tk.Event[tk.Misc]) -> None:
            self._drag_motion(event, parent_frame)

        def on_drag_end(event: tk.Event[tk.Misc]) -> None:
            self._drag_end(event, parent_frame)

        widget.bind("<ButtonPress-1>", on_drag_start)
        widget.bind("<B1-Motion>", on_drag_motion)
        widget.bind("<ButtonRelease-1>", on_drag_end)

    def _bind_image_preview(self, widget: tk.Widget, evt: EventModel) -> None:
        def on_open(_event: tk.Event[tk.Misc]) -> None:
            self._open_image_preview(evt)

        widget.bind("<ButtonPress-1>", on_open)

    def _open_image_preview(self, evt: EventModel) -> None:
        if not evt.held_screenshot:
            return

        self._close_image_preview()

        preview = tk.Toplevel(self)
        preview.title(txt("Event Image Preview", "이벤트 이미지 미리보기"))
        preview.transient(self)
        preview.configure(bg=SW_BG_BASE)
        preview.protocol("WM_DELETE_WINDOW", self._close_image_preview)
        preview.bind("<Escape>", self._close_image_preview)

        img = evt.held_screenshot
        self._preview_photo = ImageTk.PhotoImage(img)
        lbl = ttk.Label(preview, image=self._preview_photo)
        cast(Any, lbl).image = self._preview_photo
        lbl.pack(padx=SW_PAD_MD, pady=SW_PAD_MD)
        # Clicking the preview itself dismisses it — modal toast behavior.
        lbl.bind("<Button-1>", self._close_image_preview)

        # Centered modal: locate the preview on the sort window so the
        # interaction reads as a focused overlay rather than a tooltip.
        self.update_idletasks()
        win_w = self.winfo_width() or img.width
        win_h = self.winfo_height() or img.height
        x = self.winfo_rootx() + max(0, (win_w - img.width) // 2)
        y = self.winfo_rooty() + max(0, (win_h - img.height) // 2)
        max_x = max(0, self.winfo_screenwidth() - img.width)
        max_y = max(0, self.winfo_screenheight() - img.height)
        x = min(max(0, x), max_x)
        y = min(max(0, y), max_y)

        preview.geometry(f"{img.width + 2 * SW_PAD_MD}x{img.height + 2 * SW_PAD_MD}+{x}+{y}")
        preview.grab_set()
        preview.focus_force()

        self._preview_win = preview

    def _close_image_preview(self, event: object | None = None) -> None:
        if self._preview_win and self._preview_win.winfo_exists():
            try:
                self._preview_win.grab_release()
            except tk.TclError:
                pass
            self._preview_win.destroy()
        self._preview_win = None
        self._preview_photo = None

    def _drag_start(self, event: tk.Event[tk.Misc], frame: tk.Frame) -> None:
        self._drag_data = {
            "y": event.y_root,
            "frame": frame,
            "start_y": frame.winfo_y(),
        }
        cast(Any, frame).lift()
        frame.configure(cursor="hand2", bg=SW_BG_ROW_ACTIVE)

    def _drag_motion(self, event: tk.Event[tk.Misc], frame: tk.Frame) -> None:
        drag_data = getattr(self, "_drag_data", None)
        if drag_data is None:
            return
        dy = event.y_root - drag_data["y"]
        frame.place(y=drag_data["start_y"] + dy, x=0, relwidth=1.0)

    def _drag_end(self, event: object | None, frame: tk.Frame) -> None:
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

        moved_event = cast(EventModel | None, getattr(frame, "_event_model", None))
        old_idx = None
        if moved_event is not None:
            old_idx = next(
                (i for i, evt in enumerate(self.events) if evt is moved_event),
                None,
            )
        if old_idx is None:
            del self._drag_data
            self._refresh_list()
            return

        moved_event = self.events.pop(old_idx)
        self.events.insert(insert_idx, moved_event)

        del self._drag_data
        self._refresh_list()

    def _load_profile(self, name: str) -> ProfileModel | None:
        try:
            return load_profile(self.prof_dir, name, migrate=True)
        except Exception:
            messagebox.showerror(
                txt("Error", "오류"),
                txt("Failed to load profile: {name}", "프로필을 불러오지 못했습니다: {name}", name=name),
                parent=self,
            )
            self.close()

    def save(self) -> None:
        if self.profile is None:
            return
        self.profile.event_list = self.events
        try:
            save_profile(self.prof_dir, self.profile, name=self.prof_name.get())
            self.save_cb(self.prof_name.get())
            self.close()
        except Exception as e:
            logger.error(f"Save failed: {e}")
            messagebox.showerror(
                txt("Save Failed", "저장 실패"),
                txt(
                    "An error occurred while saving profile:\n{error}",
                    "프로필 저장 중 오류가 발생했습니다:\n{error}",
                    error=e,
                ),
                parent=self,
            )

    def close(self, event: object | None = None) -> None:
        self._close_image_preview()
        self.unbind_all("<MouseWheel>")
        StateUtils.save_main_app_state(
            org_pos=f"{self.winfo_x()}/{self.winfo_y()}",
            org_size=f"{self.winfo_width()}/{self.winfo_height()}",
        )
        self.app_master.load_settings()
        self.app_master.setup_event_handlers()
        self.destroy()

    def _load_state(self) -> None:
        s = StateUtils.load_main_app_state()
        pos = StateUtils.parse_slash_int_pair(s.get("org_pos")) if s else None
        size = StateUtils.parse_slash_int_pair(s.get("org_size")) if s else None
        if pos is not None and size is not None:
            self.geometry(f"{size[0]}x{size[1]}+{pos[0]}+{pos[1]}")
        else:
            WindowUtils.center_window(self)
