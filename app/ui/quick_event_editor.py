from __future__ import annotations

import tkinter as tk
import tkinter.ttk as ttk
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageTk
from loguru import logger

from app.utils.i18n import dual_text_width, txt
from app.core.models import ColorTuple, EventModel, Position
from app.ui.capture_session import CaptureSession
from app.storage.profile_storage import ensure_quick_profile, load_profile, save_profile
from app.utils.keys import KeyUtils
from app.utils.window_state import StateUtils, WindowUtils
from app.ui import theme


class KeystrokeQuickEventEditor:
    def __init__(
        self,
        settings_window: tk.Tk | tk.Toplevel,
        *,
        profiles_dir: Path,
        on_close: Callable[[], object] | None = None,
    ) -> None:
        self.win = tk.Toplevel(settings_window)
        self.win.title(txt("Quick Event Settings", "빠른 이벤트 설정"))
        self.win.transient(settings_window)
        self.win.grab_set()
        self.win.focus_force()
        cast(Any, self.win).attributes("-topmost", True)
        self.win.bind("<Escape>", self.close)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self.capture_session = CaptureSession()
        self.event_idx = 1
        self.events: list[EventModel] = []
        self.saved_count = 0

        self.capture_w_var = tk.IntVar(value=100)
        self.capture_h_var = tk.IntVar(value=100)

        self.spn_capture_w: ttk.Spinbox | None = None
        self.spn_capture_h: ttk.Spinbox | None = None
        self.lbl_step: ttk.Label | None = None
        self.lbl_session: tk.Label | None = None
        self.lbl_feedback: ttk.Label | None = None
        self.lbl_gauge: ttk.Label | None = None
        self.lbl_img1: tk.Label
        self.lbl_img2: tk.Label
        self.lbl_ref: tk.Label
        self.entries: list[tk.Entry] = []
        self.button_dock: tk.Frame
        self.button_group: tk.Frame

        self.prof_dir = profiles_dir
        self.on_close = on_close
        ensure_quick_profile(self.prof_dir)

        self._create_ui()
        self._load_pos()

        self._is_closing = False
        self._capture_generation = -1
        self._ctrl_was_pressed = False
        self._capture_after_id: str | None = None
        self._modifier_after_id: str | None = None
        self.capture_session.start()
        self._poll_capture()
        self._check_keys()

    @property
    def latest_pos(self) -> Position | None:
        return self.capture_session.latest_position

    @latest_pos.setter
    def latest_pos(self, value: Position | None) -> None:
        self.capture_session.latest_position = value

    @property
    def clicked_pos(self) -> Position | None:
        return self.capture_session.selected_position

    @clicked_pos.setter
    def clicked_pos(self, value: Position | None) -> None:
        self.capture_session.selected_position = value

    @property
    def latest_img(self) -> Image.Image | None:
        return self.capture_session.latest_image

    @latest_img.setter
    def latest_img(self, value: Image.Image | None) -> None:
        self.capture_session.latest_image = value

    @property
    def held_img(self) -> Image.Image | None:
        return self.capture_session.held_image

    @held_img.setter
    def held_img(self, value: Image.Image | None) -> None:
        self.capture_session.held_image = value

    @property
    def ref_pixel(self) -> ColorTuple | None:
        return self.capture_session.reference_color

    @ref_pixel.setter
    def ref_pixel(self, value: ColorTuple | None) -> None:
        self.capture_session.reference_color = value

    def _create_ui(self) -> None:
        try:
            self.win.configure(bg=theme.SURFACE_PAPER)
        except tk.TclError:
            pass
        theme.install_styles(self.win)
        f = theme.fonts()

        # Compact stepper header on top of the editor.
        header = tk.Frame(
            self.win, bg=theme.SURFACE_PANEL, padx=theme.SPACE_3, pady=theme.SPACE_2
        )
        header.pack(fill="x", side="top")
        tk.Label(
            header,
            text=txt("QUICK ADD", "빠른 추가"),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_SECONDARY,
            font=f["body_bold"],
        ).pack(side=tk.LEFT)
        self.lbl_session = tk.Label(
            header,
            text="",
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
        )
        self.lbl_session.pack(side=tk.RIGHT)
        tk.Frame(self.win, bg=theme.SURFACE_DIVIDER, height=1).pack(
            fill="x", side="top"
        )

        f_intro = ttk.LabelFrame(self.win, text=txt("Quick Flow", "빠른 작업 순서"))
        f_intro.pack(fill="x", padx=8, pady=(8, 5))
        ttk.Label(
            f_intro,
            text=txt(
                "① ALT  move pointer   ② CTRL  freeze preview   ③ click target   ④ CTRL  save",
                "① ALT  마우스 이동   ② CTRL  미리보기 고정   ③ 대상 클릭   ④ CTRL  저장",
            ),
            justify="left",
            wraplength=420,
            foreground=theme.INK_SECONDARY,
        ).pack(anchor="w", padx=8, pady=(4, 2))
        # Stepper gauge — dots for steps, dashes for connectors, recolored
        # by _refresh_status_text as the user progresses through the flow.
        self.lbl_gauge = ttk.Label(
            f_intro,
            text="",
            font=theme.fonts()["mono"],
            foreground=theme.INK_MUTED,
            anchor="w",
            justify="left",
        )
        self.lbl_gauge.pack(anchor="w", padx=8, pady=(0, 4))
        self.lbl_step = ttk.Label(f_intro, text="", foreground=theme.SIGNAL_BASE)
        self.lbl_step.pack(anchor="w", padx=8, pady=(0, 6))

        # Images
        f_img = tk.Frame(self.win)
        f_img.pack(pady=5)
        tk.Label(
            f_img,
            text=txt("Live Preview", "실시간 미리보기"),
            fg=theme.INK_SECONDARY,
        ).grid(row=0, column=0, pady=(0, 3))
        tk.Label(
            f_img,
            text=txt("Captured Target", "저장 대상"),
            fg=theme.INK_SECONDARY,
        ).grid(row=0, column=1, pady=(0, 3))
        self.lbl_img1 = self._mk_lbl(f_img, "red", 1, 0)
        self.lbl_img2 = self._mk_lbl(f_img, "gray", 1, 1)
        for seq in ("<Button-1>", "<B1-Motion>"):
            self.lbl_img2.bind(seq, self._on_click_held)

        # Ref Pixel
        f_ref = tk.Frame(self.win)
        f_ref.pack(pady=5)
        self.lbl_ref = tk.Label(f_ref, width=2, height=1, bg="gray")
        self.lbl_ref.grid(row=0, column=1, padx=5)

        # Coords
        entries_frame = tk.Frame(self.win)
        self.entries = self._mk_entries(entries_frame, ["X1:", "Y1:", "X2:", "Y2:"])
        entries_frame.pack()

        # Capture Size
        f_size = tk.Frame(self.win)
        f_size.pack(pady=3)
        tk.Label(f_size, text=txt("Capture Width:", "캡처 너비:")).pack(
            side=tk.LEFT, padx=5
        )
        self.spn_capture_w = ttk.Spinbox(
            f_size,
            textvariable=self.capture_w_var,
            from_=50,
            to=1000,
            width=5,
        )
        self.spn_capture_w.pack(side=tk.LEFT)
        for seq in ("<FocusOut>", "<<Increment>>", "<<Decrement>>", "<KeyRelease>"):
            self.spn_capture_w.bind(seq, self._on_capture_size_change)
        tk.Label(f_size, text=txt("Height:", "높이:")).pack(side=tk.LEFT, padx=5)
        self.spn_capture_h = ttk.Spinbox(
            f_size,
            textvariable=self.capture_h_var,
            from_=50,
            to=1000,
            width=5,
        )
        self.spn_capture_h.pack(side=tk.LEFT)
        for seq in ("<FocusOut>", "<<Increment>>", "<<Decrement>>", "<KeyRelease>"):
            self.spn_capture_h.bind(seq, self._on_capture_size_change)

        # RunDock buttons
        tk.Frame(self.win, bg=theme.SURFACE_DIVIDER, height=1).pack(fill="x")
        f_btn = tk.Frame(self.win, bg=theme.SURFACE_PANEL)
        f_btn.pack(fill="x", ipady=theme.SPACE_2)
        self.button_dock = f_btn
        button_group = tk.Frame(f_btn, bg=theme.SURFACE_PANEL)
        button_group.pack(anchor="center")
        self.button_group = button_group
        ttk.Button(
            button_group,
            text=txt("Grab (Ctrl)", "캡처 (Ctrl)"),
            width=dual_text_width(
                "Grab (Ctrl)", "캡처 (Ctrl)", padding=2, min_width=11
            ),
            command=self.hold_image,
            style="Accent.TButton",
        ).pack(side=tk.LEFT, padx=(0, theme.SPACE_3))
        ttk.Button(
            button_group,
            text=txt("Close (ESC)", "닫기 (ESC)"),
            width=dual_text_width("Close (ESC)", "닫기 (ESC)", padding=2, min_width=11),
            command=self.close,
            style="Outline.TButton",
        ).pack(side=tk.LEFT)

        self.lbl_feedback = ttk.Label(
            self.win,
            text="",
            anchor="center",
            justify="center",
            foreground=theme.INK_SECONDARY,
            wraplength=360,
        )
        self.lbl_feedback.pack(pady=(0, 8), fill="both")
        self._refresh_status_text()

    def _on_capture_size_change(self, *_args: object) -> None:
        """캡처 크기 변경 시 capturer 동기화"""
        try:
            w = max(50, min(1000, self.capture_w_var.get()))
            h = max(50, min(1000, self.capture_h_var.get()))
            if self.capture_w_var.get() != w:
                self.capture_w_var.set(w)
            if self.capture_h_var.get() != h:
                self.capture_h_var.set(h)
            self.capture_session.set_capture_size(w, h)
        except (ValueError, tk.TclError):
            pass

    def _mk_lbl(self, p: tk.Misc, _bg: str, r: int, c: int) -> tk.Label:
        # Larger previews so users can actually verify what was captured.
        label = tk.Label(
            p,
            width=18,
            height=9,
            bg=theme.SURFACE_SUNKEN,
            highlightthickness=1,
            highlightbackground=theme.SURFACE_DIVIDER,
        )
        label.grid(row=r, column=c, padx=5)
        return label

    def _mk_entries(self, p: tk.Frame, labels: Sequence[str]) -> list[tk.Entry]:
        entries: list[tk.Entry] = []
        for i, label_text in enumerate(labels):
            r, c = divmod(i, 2)
            tk.Label(p, text=label_text).grid(row=r, column=c * 2, padx=1, sticky=tk.E)
            e = tk.Entry(p, width=4)
            e.grid(row=r, column=c * 2 + 1, padx=4, sticky=tk.W)
            e.bind("<Up>", lambda _event, en=e: self._adj_val(en, 1))
            e.bind("<Down>", lambda _event, en=e: self._adj_val(en, -1))
            entries.append(e)

        for e in entries[:2]:
            e.bind("<FocusOut>", self._update_pos_from_entry)
        return entries

    def _adj_val(self, e: tk.Entry, d: int) -> str:
        try:
            v = int(e.get()) + d
            e.delete(0, tk.END)
            e.insert(0, str(v))
            if e in self.entries[:2]:
                self._update_pos_from_entry()
        except ValueError:
            pass
        return "break"

    def _update_pos_from_entry(self, event: object | None = None) -> None:
        try:
            self.capture_session.set_position(
                (int(self.entries[0].get()), int(self.entries[1].get()))
            )
        except ValueError:
            pass

    def _check_keys(self) -> None:
        if self._is_closing:
            return
        if KeyUtils.mod_key_pressed("alt"):
            self.capture_session.set_position(self.win.winfo_pointerxy())
        ctrl_pressed = KeyUtils.mod_key_pressed("ctrl")
        if ctrl_pressed and not self._ctrl_was_pressed:
            self.hold_image()
        self._ctrl_was_pressed = ctrl_pressed
        self._modifier_after_id = self.win.after(100, self._check_keys)

    def _poll_capture(self) -> None:
        if self._is_closing:
            return
        snapshot = self.capture_session.snapshot()
        if snapshot.generation != self._capture_generation:
            self._capture_generation = snapshot.generation
            if snapshot.latest_position and snapshot.latest_image:
                self.update_capture(snapshot.latest_position, snapshot.latest_image)
        self._capture_after_id = self.win.after(50, self._poll_capture)

    def update_capture(self, pos: Position, img: Image.Image) -> None:
        if pos and img:
            try:
                if self.lbl_img1.winfo_exists():
                    self._upd_img(self.lbl_img1, self._scale_for_display(img))
                    self._refresh_status_text()
            except (tk.TclError, AttributeError):
                pass

    def hold_image(self) -> None:
        if not (self.latest_pos and self.latest_img):
            self._set_feedback(
                txt(
                    "Move the mouse over the target first so the live preview can update.",
                    "먼저 대상 위로 마우스를 움직여 실시간 미리보기가 보이게 하세요.",
                ),
                color=theme.STATUS_WARN_FG,
            )
            self._refresh_status_text()
            return
        if not self.capture_session.hold() or self.held_img is None:
            return
        held_position = self.capture_session.held_position
        if held_position is None:
            return
        self._set_entries(self.entries[:2], *held_position)
        self._upd_img(self.lbl_img2, self._scale_for_display(self.held_img))
        if self.clicked_pos:
            self._apply_overlay(self.held_img, self.lbl_img2)
            self.save_event()
            return
        self._set_feedback(
            txt(
                "Captured. Now click the right preview to choose the trigger pixel.",
                "캡처했습니다. 이제 오른쪽 미리보기에서 트리거 픽셀을 클릭하세요.",
            )
        )
        self._refresh_status_text()

    def _on_click_held(self, event: tk.Event[tk.Misc]) -> None:
        if not self.held_img:
            self._set_feedback(
                txt(
                    "Capture the live preview first, then choose a pixel on the right image.",
                    "먼저 실시간 미리보기를 캡처한 뒤 오른쪽 이미지에서 픽셀을 고르세요.",
                ),
                color=theme.STATUS_WARN_FG,
            )
            return

        display_w = self.lbl_img2.winfo_width()
        display_h = self.lbl_img2.winfo_height()
        if display_w <= 1 or display_h <= 1:
            return

        if self.capture_session.select((event.x, event.y), (display_w, display_h)):
            if self.clicked_pos is None or self.ref_pixel is None:
                return
            ix, iy = self.clicked_pos
            self._upd_img(self.lbl_ref, Image.new("RGBA", (25, 25), self.ref_pixel))
            self._set_entries(self.entries[2:], ix, iy)
            self._apply_overlay(self.held_img, self.lbl_img2)
            self._set_feedback(
                txt(
                    "Target selected. Press CTRL once more to save the Quick event.",
                    "대상을 선택했습니다. Quick 이벤트를 저장하려면 CTRL을 한 번 더 누르세요.",
                )
            )
            self._refresh_status_text()

    def _apply_overlay(self, img: Image.Image, lbl: tk.Label) -> None:
        """십자선 오버레이"""
        if not self.clicked_pos:
            return
        cx, cy = self.clicked_pos

        res = img.copy()
        pixels = cast(Any, res.load())
        w, h = res.size
        for x in range(w):
            pixels[x, cy] = self._inverted_pixel(pixels[x, cy])
        for y in range(h):
            pixels[cx, y] = self._inverted_pixel(pixels[cx, y])

        self._upd_img(lbl, self._scale_for_display(res))

    @staticmethod
    def _inverted_pixel(pixel: object) -> tuple[int, int, int, int]:
        if isinstance(pixel, int):
            r = g = b = pixel
        else:
            channels = cast(ColorTuple, pixel)
            r, g, b = channels[:3]
        return (255 - int(r), 255 - int(g), 255 - int(b), 255)

    @staticmethod
    def _scale_for_display(img: Image.Image) -> Image.Image:
        """표시용 이미지 스케일 다운 (MAX_DISPLAY=400px 기준, 비율 유지)"""
        MAX_DISPLAY = 400
        scale = min(MAX_DISPLAY / img.width, MAX_DISPLAY / img.height, 1.0)
        if scale < 1.0:
            resize = cast(Any, img).resize
            return cast(
                Image.Image,
                resize(
                    (int(img.width * scale), int(img.height * scale)),
                    Image.Resampling.LANCZOS,
                ),
            )
        return img

    def _upd_img(self, lbl: tk.Label, img: Image.Image) -> None:
        try:
            p = ImageTk.PhotoImage(img.convert("RGB"), master=lbl)
            lbl.configure(image=p, width=img.width, height=img.height)
            cast(Any, lbl).image = p
        except Exception as e:
            logger.error(f"Img update failed: {e}")

    def _set_entries(self, ents: Sequence[tk.Entry], x: int, y: int) -> None:
        for i, v in enumerate((x, y)):
            ents[i].delete(0, tk.END)
            ents[i].insert(0, str(v))

    def _set_feedback(self, text: str, color: str = theme.INK_SECONDARY) -> None:
        if self.lbl_feedback:
            self.lbl_feedback.config(text=text, foreground=color)

    def _refresh_status_text(self) -> None:
        if self.lbl_session:
            self.lbl_session.config(
                text=txt(
                    "{count} Quick event(s) saved in this session.",
                    "이번 세션에서 Quick 이벤트 {count}개를 저장했습니다.",
                    count=self.saved_count,
                )
            )
        self._refresh_gauge()
        if not self.lbl_step:
            return
        if not self.latest_img:
            self.lbl_step.config(
                text=txt(
                    "Current step: move the mouse over the target until the live preview follows it.",
                    "현재 단계: 실시간 미리보기가 따라오도록 대상 위로 마우스를 움직이세요.",
                )
            )
            return
        if not self.held_img:
            self.lbl_step.config(
                text=txt(
                    "Current step: press CTRL to freeze the current area.",
                    "현재 단계: CTRL로 현재 영역을 고정하세요.",
                )
            )
            return
        if not self.clicked_pos:
            self.lbl_step.config(
                text=txt(
                    "Current step: click the right preview to choose the trigger pixel.",
                    "현재 단계: 오른쪽 미리보기를 클릭해 트리거 픽셀을 고르세요.",
                )
            )
            return
        self.lbl_step.config(
            text=txt(
                "Current step: press CTRL again to save this Quick event.",
                "현재 단계: 이 Quick 이벤트를 저장하려면 CTRL을 다시 누르세요.",
            )
        )

    def _current_step_index(self) -> int:
        """0=POINT, 1=CAPTURE, 2=PICK, 3=SAVE."""
        if not self.latest_img:
            return 0
        if not self.held_img:
            return 1
        if not self.clicked_pos:
            return 2
        return 3

    def _refresh_gauge(self) -> None:
        lbl_gauge = getattr(self, "lbl_gauge", None)
        if lbl_gauge is None:
            return
        idx = self._current_step_index()
        labels = [
            txt("POINT", "포인트"),
            txt("CAPTURE", "캡처"),
            txt("PICK", "지정"),
            txt("SAVE", "저장"),
        ]
        # Render in a single line: ● POINT  ━━  ● CAPTURE  ━━  ○ PICK  ━━  ○ SAVE
        parts: list[str] = []
        for i, label in enumerate(labels):
            mark = "●" if i <= idx else "○"
            parts.append(f"{mark} {label}")
        text = "  ━━  ".join(parts)
        lbl_gauge.config(text=text)

    def save_event(self) -> None:
        if (
            self.latest_pos is not None
            and self.clicked_pos is not None
            and self.latest_img is not None
            and self.held_img is not None
            and self.ref_pixel is not None
        ):
            self.events.append(
                EventModel(
                    event_name=str(self.event_idx),
                    capture_size=(self.capture_w_var.get(), self.capture_h_var.get()),
                    latest_position=self.capture_session.held_position,
                    clicked_position=self.clicked_pos,
                    held_screenshot=self.held_img,
                    ref_pixel_value=self.ref_pixel,
                    match_mode="pixel",
                    region_size=None,
                )
            )
            self.event_idx += 1
            p = load_profile(self.prof_dir, "Quick", migrate=True)
            p.event_list = self.events
            save_profile(self.prof_dir, p, name="Quick")
            self.saved_count += 1
            self._set_feedback(
                txt(
                    "Quick event #{count} saved. Move to a new target to capture the next one.",
                    "Quick 이벤트 #{count} 저장 완료. 다음 대상을 캡처하려면 마우스를 옮기세요.",
                    count=self.saved_count,
                ),
                color=theme.STATUS_READY_FG,
            )
            self._refresh_status_text()

    def close(self, event: object | None = None) -> None:
        if self._is_closing:
            return
        self._is_closing = True
        for after_id in (self._capture_after_id, self._modifier_after_id):
            if after_id is not None:
                try:
                    self.win.after_cancel(after_id)
                except tk.TclError:
                    pass
        self.capture_session.stop()

        StateUtils.save_main_app_state(
            quick_pos=f"{self.win.winfo_x()}/{self.win.winfo_y()}",
            quick_ptr=str(self.capture_session.current_position()),
        )
        self.win.grab_release()
        self.win.destroy()
        if self.on_close:
            self.on_close()

    def _load_pos(self) -> None:
        s = StateUtils.load_main_app_state()
        pos = StateUtils.parse_slash_int_pair(s.get("quick_pos")) if s else None
        if pos is not None:
            self.win.geometry(f"+{pos[0]}+{pos[1]}")
        else:
            WindowUtils.center_window(self.win)
        if s and (ptr := s.get("quick_ptr")):
            pt = StateUtils.parse_position_tuple(ptr)
            if pt is not None:
                self._set_entries(self.entries[:2], *pt)
                self.capture_session.set_position(pt)
        self._refresh_status_text()
