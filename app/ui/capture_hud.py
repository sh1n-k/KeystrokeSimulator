"""캡처 HUD — 편집기와 빠른 이벤트가 함께 쓰는 작은 항상 위 캡처 창.

게임 화면과 캡처 영역을 비교하려고 topmost를 유지하고, 대신 창을 작게
두고 캡처 박스와 겹치면 스스로 비켜난다.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.ttk as ttk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from PIL import Image, ImageDraw, ImageTk

from app.core.models import ColorTuple, EventModel, Position
from app.core.profile_events import next_numbered_event_name
from app.storage.profile_storage import ensure_quick_profile, load_profile, save_profile
from app.ui import theme
from app.ui.capture_session import (
    MAX_CAPTURE_SIZE,
    MIN_CAPTURE_SIZE,
    CaptureBackend,
    CaptureSession,
    Rect,
    capture_rect,
    rects_overlap,
)
from app.utils.i18n import txt
from app.utils.keys import KeyUtils
from app.utils.system import PermissionUtils
from app.utils.window_state import StateUtils, WindowUtils

HudMode = Literal["single", "continuous"]

PREVIEW_MAX = 200
MAGNIFIER_ZOOM = 8
MAGNIFIER_SPAN = 11  # 원본 픽셀 수(홀수라 가운데 픽셀이 있다)
HUD_MARGIN = 16
HUD_WRAP = 250
_TEXT_INPUT_CLASSES = frozenset(
    {"Entry", "TEntry", "Spinbox", "TSpinbox", "TCombobox", "Text"}
)
# 100ms 폴링 기준 3초. 권한 조회는 호출당 10ms 이상이다.
_PERMISSION_POLL_TICKS = 30


@dataclass(frozen=True)
class CaptureResult:
    """적용한 캡처. position은 캡처 박스의 왼쪽 위(화면 좌표)다."""

    position: Position
    capture_size: Position
    image: Image.Image
    pixel: Position
    color: ColorTuple


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def preview_size(image_size: Position) -> Position:
    """1:1로 보여주되 긴 변을 PREVIEW_MAX로 제한한다."""
    w, h = image_size
    scale = min(1.0, PREVIEW_MAX / max(1, w), PREVIEW_MAX / max(1, h))
    return (max(1, int(w * scale)), max(1, int(h * scale)))


def display_to_image(
    point: Position, display_size: Position, image_size: Position
) -> Position | None:
    dw, dh = display_size
    if dw <= 0 or dh <= 0:
        return None
    x = int(point[0] * image_size[0] / dw)
    y = int(point[1] * image_size[1] / dh)
    if not (0 <= x < image_size[0] and 0 <= y < image_size[1]):
        return None
    return (x, y)


def magnifier_to_image(
    point: Position, center: Position, image_size: Position
) -> Position | None:
    """돋보기 좌표를 원본 픽셀 좌표로 바꾼다. 원본 밖이면 None."""
    half = MAGNIFIER_SPAN // 2
    x = center[0] - half + point[0] // MAGNIFIER_ZOOM
    y = center[1] - half + point[1] // MAGNIFIER_ZOOM
    if not (0 <= x < image_size[0] and 0 <= y < image_size[1]):
        return None
    return (x, y)


def render_magnifier(
    image: Image.Image, center: Position, selected: Position | None
) -> Image.Image:
    """center 주변 MAGNIFIER_SPAN 픽셀을 확대한다. 원본 밖은 회색으로 채운다."""
    half = MAGNIFIER_SPAN // 2
    left, top = center[0] - half, center[1] - half
    src = Image.new("RGB", (MAGNIFIER_SPAN, MAGNIFIER_SPAN), theme.SURFACE_SUNKEN)
    clip = (
        max(0, left),
        max(0, top),
        min(image.width, left + MAGNIFIER_SPAN),
        min(image.height, top + MAGNIFIER_SPAN),
    )
    if clip[0] < clip[2] and clip[1] < clip[3]:
        src.paste(image.convert("RGB").crop(clip), (clip[0] - left, clip[1] - top))
    size = MAGNIFIER_SPAN * MAGNIFIER_ZOOM
    zoomed = cast(
        Image.Image, cast(Any, src).resize((size, size), Image.Resampling.NEAREST)
    )
    draw = ImageDraw.Draw(zoomed)
    if selected is not None:
        sx, sy = selected[0] - left, selected[1] - top
        if 0 <= sx < MAGNIFIER_SPAN and 0 <= sy < MAGNIFIER_SPAN:
            x0, y0 = sx * MAGNIFIER_ZOOM, sy * MAGNIFIER_ZOOM
            x1, y1 = x0 + MAGNIFIER_ZOOM - 1, y0 + MAGNIFIER_ZOOM - 1
            draw.rectangle([x0 - 1, y0 - 1, x1 + 1, y1 + 1], outline="white")
            draw.rectangle([x0, y0, x1, y1], outline="black")
    return zoomed


def render_overlay(
    image: Image.Image, pixel: Position | None, region_size: Position | None = None
) -> Image.Image:
    """대상 픽셀 표시. 픽셀 모드는 반전 십자선, 영역 모드는 영역 사각형."""
    res = image.convert("RGB")  # always a copy
    if pixel is None:
        return res
    cx, cy = pixel
    w, h = res.size
    if not (0 <= cx < w and 0 <= cy < h):
        return res
    if region_size is not None:
        rw, rh = region_size[0] // 2, region_size[1] // 2
        draw = ImageDraw.Draw(res)
        draw.rectangle(
            [max(0, cx - rw), max(0, cy - rh), min(w, cx + rw), min(h, cy + rh)],
            outline="yellow",
            width=2,
        )
        return res
    pixels = cast(Any, res.load())
    for x in range(w):
        r, g, b = pixels[x, cy]
        pixels[x, cy] = (255 - r, 255 - g, 255 - b)
    for y in range(h):
        if y == cy:
            continue
        r, g, b = pixels[cx, y]
        pixels[cx, y] = (255 - r, 255 - g, 255 - b)
    return res


def hud_position(
    hud: Rect, box: Rect, screen: Position, margin: int = HUD_MARGIN
) -> Position | None:
    """HUD가 캡처 박스와 겹치면 박스 반대편 화면 모서리 위치. 안 겹치면 None."""
    if not rects_overlap(hud, box):
        return None
    _, _, w, h = hud
    sw, sh = screen
    near_x, far_x = margin, sw - w - margin
    near_y, far_y = margin, sh - h - margin
    box_cx, box_cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    xs = (near_x, far_x) if box_cx > sw / 2 else (far_x, near_x)
    ys = (near_y, far_y) if box_cy > sh / 2 else (far_y, near_y)
    candidates = [(xs[0], ys[0]), (xs[0], ys[1]), (xs[1], ys[0]), (xs[1], ys[1])]
    clamped = [
        (max(0, min(x, sw - w)), max(0, min(y, sh - h))) for x, y in candidates
    ]
    for x, y in clamped:
        if not rects_overlap((x, y, w, h), box):
            return (x, y)
    return clamped[0]


def border_rects(box: Rect, thickness: int) -> list[Rect]:
    """캡처 박스 바깥쪽 테두리 4개(위, 아래, 왼쪽, 오른쪽). 박스 안은 덮지 않는다."""
    x, y, w, h = box
    t = thickness
    return [
        (x - t, y - t, w + 2 * t, t),
        (x - t, y + h, w + 2 * t, t),
        (x - t, y, t, h),
        (x + w, y, t, h),
    ]


class CaptureBorder:
    """캡처 박스를 게임 화면 위에 표시하는 얇은 창 4개."""

    def __init__(self, master: tk.Misc) -> None:
        self._box: Rect | None = None
        self.windows: list[tk.Toplevel] = []
        for _ in range(4):
            win = tk.Toplevel(master, bg=theme.CAPTURE_BORDER)
            win.overrideredirect(True)
            win.withdraw()
            self.windows.append(win)

    def show(self, box: Rect) -> None:
        if box == self._box:
            return
        self._box = box
        rects = border_rects(box, theme.CAPTURE_BORDER_WIDTH)
        for win, (x, y, w, h) in zip(self.windows, rects, strict=True):
            try:
                win.geometry(f"{max(1, w)}x{max(1, h)}+{x}+{y}")
                if win.state() == "withdrawn":
                    win.deiconify()
                    win.update_idletasks()
                    cast(Any, win).attributes("-topmost", True)
            except tk.TclError:
                continue
        # macOS는 메뉴바 영역 등에 놓인 창을 스스로 옮긴다. 옮겨진 조각은
        # 캡처 박스 안으로 들어올 수 있으므로 숨긴다.
        for win, (x, y, _w, _h) in zip(self.windows, rects, strict=True):
            try:
                win.update_idletasks()
                if (win.winfo_x(), win.winfo_y()) != (x, y):
                    win.withdraw()
            except tk.TclError:
                continue

    def destroy(self) -> None:
        for win in self.windows:
            try:
                win.destroy()
            except tk.TclError:
                pass
        self.windows = []


def ctrl_capture_allowed(focus: tk.Misc | None) -> bool:
    """텍스트 입력 중에는 CTRL을 캡처로 받지 않는다."""
    if focus is None:
        return True
    try:
        return focus.winfo_class() not in _TEXT_INPUT_CLASSES
    except tk.TclError:
        return True


def append_quick_event(profiles_dir: Path, result: CaptureResult) -> str:
    """Quick 프로필을 다시 읽어 뒤에 추가한다. 붙인 이름을 돌려준다."""
    profile = load_profile(profiles_dir, "Quick", migrate=True)
    name = next_numbered_event_name(e.event_name or "" for e in profile.event_list)
    profile.event_list.append(
        EventModel(
            event_name=name,
            capture_size=result.capture_size,
            latest_position=result.position,
            clicked_position=result.pixel,
            held_screenshot=result.image,
            ref_pixel_value=result.color,
            match_mode="pixel",
            region_size=None,
        )
    )
    save_profile(profiles_dir, profile, name="Quick")
    return name


def _color_hex(color: ColorTuple) -> str:
    r, g, b = (int(c) for c in color[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


class CaptureHud:
    """단일 모드는 이벤트 하나의 화면을 고르고, 연속 모드는 Quick에 계속 추가한다."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        mode: HudMode,
        name: str = "",
        on_name_change: Callable[[str], None] | None = None,
        on_apply: Callable[[CaptureResult], None] | None = None,
        profiles_dir: Path | None = None,
        initial: CaptureResult | None = None,
        capture_size: Position = (100, 100),
        region_size: Position | None = None,
        grab: bool = False,
        border: bool = True,
        on_close: Callable[[], object] | None = None,
        capturer: CaptureBackend | None = None,
    ) -> None:
        self.mode: HudMode = mode
        self.master = master
        self.on_name_change = on_name_change
        self.on_apply = on_apply
        self.profiles_dir = profiles_dir
        self.region_size = region_size
        self.on_close = on_close
        self._grab = grab
        self.saved_count = 0
        self._is_closing = False
        self._alt_down = False
        self._ctrl_was_pressed = False
        self._capture_generation = -1
        self._held_size: Position | None = None
        self._mag_center: Position | None = None
        self._preview_display: Position = (1, 1)
        self._feedback: tuple[str, str] | None = None
        self._permission_message = self._compute_permission_message()
        self._permission_ticks = _PERMISSION_POLL_TICKS
        self._capture_after_id: str | None = None
        self._modifier_after_id: str | None = None
        self._pointer_state_key = "event_pointer" if mode == "single" else "quick_ptr"

        if mode == "continuous" and profiles_dir is not None:
            ensure_quick_profile(profiles_dir)

        self.capture_session = CaptureSession(capturer)
        self.win = tk.Toplevel(master)
        # 실행 중에는 테두리를 만들지 않는다(호출부가 border=False로 연다).
        self.border: CaptureBorder | None = CaptureBorder(self.win) if border else None
        self.win.title(
            txt("Capture", "캡처")
            if mode == "single"
            else txt("Quick Capture", "빠른 캡처")
        )
        if isinstance(master, tk.Tk | tk.Toplevel):
            self.win.transient(master)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", self.close)
        self.win.bind("<Return>", self._on_return)

        self.name_var = tk.StringVar(master=self.win, value=name)
        self.capture_w_var = tk.IntVar(master=self.win, value=capture_size[0])
        self.capture_h_var = tk.IntVar(master=self.win, value=capture_size[1])
        self._create_ui()

        self.capture_session.set_capture_size(*capture_size)
        if initial is not None:
            self.capture_w_var.set(initial.capture_size[0])
            self.capture_h_var.set(initial.capture_size[1])
            self.capture_session.set_capture_size(*initial.capture_size)
            self.capture_session.set_position(initial.position, force=True)
            self.capture_session.restore(
                latest_position=initial.position,
                held_image=initial.image.copy(),
                selected_position=initial.pixel,
                reference_color=initial.color,
            )
            self._held_size = initial.capture_size
            self._mag_center = initial.pixel
        self._restore_state(restore_pointer=initial is None)
        self._render()
        # macOS Tk drops -topmost set on a transient window before it is
        # mapped, so apply it after the pending geometry work.
        self.win.update_idletasks()
        cast(Any, self.win).attributes("-topmost", True)

        if grab:
            try:
                self.win.grab_set()
            except tk.TclError:
                pass
        self.win.focus_force()
        self.capture_session.start()
        self._poll_capture()
        self._check_keys()

    # -- layout ---------------------------------------------------------------

    def _create_ui(self) -> None:
        try:
            self.win.configure(bg=theme.SURFACE_PAPER)
        except tk.TclError:
            pass
        theme.install_styles(self.win)
        f = theme.fonts()

        header = tk.Frame(
            self.win, bg=theme.SURFACE_PANEL, padx=theme.SPACE_2, pady=theme.SPACE_1
        )
        header.pack(fill="x")
        self.entry_name: ttk.Entry | None = None
        self.lbl_title: tk.Label | None = None
        if self.mode == "single":
            entry = ttk.Entry(header, textvariable=self.name_var, width=24)
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<KeyRelease>", self._on_name_edit)
            entry.bind("<Return>", self._commit_name)
            entry.bind("<KP_Enter>", self._commit_name)
            self.entry_name = entry
        else:
            self.lbl_title = tk.Label(
                header,
                text="",
                bg=theme.SURFACE_PANEL,
                fg=theme.INK_PRIMARY,
                font=f["body_bold"],
                anchor="w",
            )
            self.lbl_title.pack(side="left", fill="x", expand=True)
        tk.Frame(self.win, bg=theme.SURFACE_DIVIDER, height=1).pack(fill="x")

        body = tk.Frame(
            self.win, bg=theme.SURFACE_PAPER, padx=theme.SPACE_2, pady=theme.SPACE_2
        )
        body.pack(fill="both")

        images = tk.Frame(body, bg=theme.SURFACE_PAPER)
        images.pack(anchor="w")
        self.lbl_preview = self._make_image_label(images)
        cast(tk.Frame, self.lbl_preview.master).pack(side="left", anchor="n")
        self.lbl_magnifier = self._make_image_label(images)
        cast(tk.Frame, self.lbl_magnifier.master).pack(
            side="left", anchor="n", padx=(theme.SPACE_2, 0)
        )
        for seq in ("<Button-1>", "<B1-Motion>"):
            self.lbl_preview.bind(seq, self._on_preview_click)
            self.lbl_magnifier.bind(seq, self._on_magnifier_click)
        self.lbl_preview.bind("<Motion>", self._on_preview_motion)
        self.lbl_preview.bind("<Leave>", self._on_preview_leave)

        info = tk.Frame(body, bg=theme.SURFACE_PAPER)
        info.pack(fill="x", pady=(theme.SPACE_2, 0))
        self.lbl_swatch = tk.Label(
            info,
            width=2,
            bg=theme.SURFACE_SUNKEN,
            highlightthickness=1,
            highlightbackground=theme.SURFACE_DIVIDER,
        )
        self.lbl_swatch.pack(side="left")
        self.lbl_info = tk.Label(
            info,
            text="",
            bg=theme.SURFACE_PAPER,
            fg=theme.INK_PRIMARY,
            font=f["mono"],
            anchor="w",
        )
        self.lbl_info.pack(side="left", padx=(theme.SPACE_1, 0))

        tk.Label(
            body,
            text=txt(
                "ALT move · CTRL freeze · click to pick",
                "ALT 이동 · CTRL 고정 · 클릭 지정",
            ),
            bg=theme.SURFACE_PAPER,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
        ).pack(fill="x", pady=(theme.SPACE_1, 0))
        self.lbl_status = tk.Label(
            body,
            text="",
            bg=theme.SURFACE_PAPER,
            fg=theme.INK_SECONDARY,
            font=f["caption"],
            anchor="w",
            justify="left",
            wraplength=HUD_WRAP,
        )
        self.lbl_status.pack(fill="x")

        self.lbl_advanced = tk.Label(
            body,
            text="",
            bg=theme.SURFACE_PAPER,
            fg=theme.SIGNAL_BASE,
            font=f["caption"],
            anchor="w",
            cursor="hand2",
        )
        self.lbl_advanced.pack(fill="x", pady=(theme.SPACE_1, 0))
        self.lbl_advanced.bind("<Button-1>", lambda _e: self._toggle_advanced())
        self.advanced = tk.Frame(body, bg=theme.SURFACE_PAPER)
        self._build_advanced(self.advanced)
        self._advanced_open = False
        self._sync_advanced_label()

        tk.Frame(self.win, bg=theme.SURFACE_DIVIDER, height=1).pack(fill="x")
        dock = tk.Frame(
            self.win, bg=theme.SURFACE_PANEL, padx=theme.SPACE_2, pady=theme.SPACE_2
        )
        dock.pack(fill="x")
        ttk.Button(
            dock,
            text=txt("Recapture", "다시 캡처"),
            command=self.recapture,
            style="Outline.TButton",
        ).pack(side="left")
        self.btn_apply = ttk.Button(
            dock,
            text=txt("Apply ↵", "적용 ↵"),
            command=self.apply,
            style="Accent.TButton",
        )
        self.btn_apply.pack(side="right")

    def _build_advanced(self, parent: tk.Frame) -> None:
        rows = (
            (txt("Box", "위치"), "pos"),
            (txt("Pixel", "픽셀"), "pixel"),
        )
        self.pos_entries: list[ttk.Entry] = []
        self.pixel_entries: list[ttk.Entry] = []
        for row, (label, kind) in enumerate(rows):
            tk.Label(
                parent, text=label, bg=theme.SURFACE_PAPER, fg=theme.INK_SECONDARY
            ).grid(row=row, column=0, sticky="w", pady=1)
            for col, axis in enumerate(("X", "Y")):
                tk.Label(
                    parent, text=axis, bg=theme.SURFACE_PAPER, fg=theme.INK_MUTED
                ).grid(row=row, column=1 + col * 2, sticky="e", padx=(theme.SPACE_2, 2))
                entry = ttk.Entry(parent, width=5)
                entry.grid(row=row, column=2 + col * 2, sticky="w", pady=1)
                entry.bind(
                    "<Up>", lambda _e, en=entry, k=kind: self._nudge_entry(en, k, 1)
                )
                entry.bind(
                    "<Down>", lambda _e, en=entry, k=kind: self._nudge_entry(en, k, -1)
                )
                if kind == "pos":
                    entry.bind("<FocusOut>", self._on_pos_entry)
                    self._bind_commit(entry, self._on_pos_entry)
                    self.pos_entries.append(entry)
                else:
                    entry.bind("<KeyRelease>", self._on_pixel_entry)
                    self._bind_commit(entry, self._on_pixel_entry)
                    self.pixel_entries.append(entry)
        tk.Label(
            parent,
            text=txt("Size", "크기"),
            bg=theme.SURFACE_PAPER,
            fg=theme.INK_SECONDARY,
        ).grid(row=2, column=0, sticky="w", pady=1)
        for col, (axis, var) in enumerate(
            (("W", self.capture_w_var), ("H", self.capture_h_var))
        ):
            tk.Label(
                parent, text=axis, bg=theme.SURFACE_PAPER, fg=theme.INK_MUTED
            ).grid(row=2, column=1 + col * 2, sticky="e", padx=(theme.SPACE_2, 2))
            spin = ttk.Spinbox(
                parent,
                textvariable=var,
                from_=MIN_CAPTURE_SIZE,
                to=MAX_CAPTURE_SIZE,
                width=5,
            )
            spin.grid(row=2, column=2 + col * 2, sticky="w", pady=1)
            for seq in ("<FocusOut>", "<<Increment>>", "<<Decrement>>"):
                spin.bind(seq, self._on_capture_size_change)
            self._bind_commit(spin, self._on_capture_size_change)

    @staticmethod
    def _bind_commit(widget: tk.Misc, handler: Callable[[], None]) -> None:
        """입력칸의 Enter는 값만 확정한다. 창의 Enter(적용)로 번지지 않게 끊는다."""

        def on_return(_event: object) -> str:
            handler()
            return "break"

        widget.bind("<Return>", on_return)
        widget.bind("<KP_Enter>", on_return)

    @staticmethod
    def _make_image_label(parent: tk.Misc) -> tk.Label:
        # macOS Tk: highlightthickness>0 + width/height draws an L-box inside
        # PhotoImage previews, so the 1px border comes from an outer Frame.
        border = tk.Frame(parent, bg=theme.SURFACE_DIVIDER, padx=1, pady=1)
        label = tk.Label(border, bg=theme.SURFACE_SUNKEN, highlightthickness=0, bd=0)
        label.pack()
        return label

    # -- state accessors ------------------------------------------------------

    def _shows_live(self) -> bool:
        return self._alt_down or self.capture_session.held_image is None

    def is_ready(self) -> bool:
        snap = self.capture_session.snapshot()
        return bool(
            snap.held_image is not None
            and snap.held_position is not None
            and snap.selected_position is not None
            and snap.reference_color is not None
        )

    def result(self) -> CaptureResult | None:
        snap = self.capture_session.snapshot()
        if (
            snap.held_image is None
            or snap.held_position is None
            or snap.selected_position is None
            or snap.reference_color is None
        ):
            return None
        return CaptureResult(
            position=snap.held_position,
            capture_size=self._held_size or self._current_capture_size(),
            image=snap.held_image.copy(),
            pixel=snap.selected_position,
            color=snap.reference_color,
        )

    def _current_capture_size(self) -> Position:
        try:
            w, h = self.capture_w_var.get(), self.capture_h_var.get()
        except (tk.TclError, ValueError):
            w, h = 100, 100
        return (
            max(MIN_CAPTURE_SIZE, min(MAX_CAPTURE_SIZE, w)),
            max(MIN_CAPTURE_SIZE, min(MAX_CAPTURE_SIZE, h)),
        )

    # -- actions --------------------------------------------------------------

    def capture(self) -> None:
        """현재 실시간 프레임을 고정한다. 고른 픽셀은 새 캡처본 안이면 유지한다."""
        session = self.capture_session
        if session.latest_image is None or not session.hold():
            self._feedback = (
                txt(
                    "Move the mouse with ALT until the preview follows it.",
                    "ALT를 누른 채 마우스를 움직여 미리보기가 따라오게 하세요.",
                ),
                theme.STATUS_WARN_FG,
            )
            self._render()
            return
        self._held_size = self._current_capture_size()
        self._feedback = None
        held = session.held_image
        selected = session.selected_position
        if held is not None and selected is not None:
            if not session.select(selected, held.size):
                session.selected_position = None
                session.reference_color = None
        self._mag_center = session.selected_position
        self._render()

    def recapture(self) -> None:
        self.capture_session.clear_hold()
        self._held_size = None
        self._feedback = None
        self._mag_center = None
        self._render()

    def apply(self) -> None:
        result = self.result()
        if result is None:
            self._feedback = (
                txt(
                    "Freeze the preview with CTRL and click the target pixel first.",
                    "먼저 CTRL로 고정하고 대상 픽셀을 클릭하세요.",
                ),
                theme.STATUS_WARN_FG,
            )
            self._render()
            return
        if self.mode == "single":
            if self.on_apply is not None:
                self.on_apply(result)
            self.close()
            return
        if self.profiles_dir is None:
            return
        name = append_quick_event(self.profiles_dir, result)
        self.saved_count += 1
        self.capture_session.clear_hold()
        self._held_size = None
        self._mag_center = None
        self._feedback = (
            txt(
                "Saved Quick event '{name}'. Move to the next target.",
                "Quick 이벤트 '{name}'을 저장했습니다. 다음 대상으로 옮기세요.",
                name=name,
            ),
            theme.STATUS_READY_FG,
        )
        self._render()

    def _on_ctrl(self) -> None:
        session = self.capture_session
        # 연속 모드에서 대상을 고른 뒤 다시 누른 CTRL은 적용이다. 새 프레임을
        # 찍지 않고 대상을 고른 캡처본을 그대로 저장한다.
        if (
            self.mode == "continuous"
            and self.is_ready()
            and session.held_position == session.current_position()
        ):
            self.apply()
            return
        self.capture()

    def _on_return(self, _event: object | None = None) -> str:
        self.apply()
        return "break"

    # -- input handlers -------------------------------------------------------

    def _on_name_edit(self, _event: object | None = None) -> None:
        if self.on_name_change is not None:
            self.on_name_change(self.name_var.get())

    def _commit_name(self, _event: object | None = None) -> str:
        self._on_name_edit()
        # 포커스를 입력칸에서 빼야 CTRL 캡처가 다시 동작한다.
        self.win.focus_set()
        return "break"

    def _select(self, pixel: Position) -> None:
        held = self.capture_session.held_image
        if held is None or not self.capture_session.select(pixel, held.size):
            return
        self._feedback = None
        self._render()

    def _on_preview_click(self, event: tk.Event[tk.Misc]) -> None:
        held = self.capture_session.held_image
        if held is None or self._shows_live():
            return
        pixel = display_to_image((event.x, event.y), self._preview_display, held.size)
        if pixel is not None:
            self._mag_center = pixel
            self._select(pixel)

    def _on_magnifier_click(self, event: tk.Event[tk.Misc]) -> None:
        held = self.capture_session.held_image
        if held is None or self._shows_live() or self._mag_center is None:
            return
        # 드래그 중에는 돋보기 중심을 움직이지 않는다. 움직이면 커서 아래
        # 픽셀이 계속 바뀐다.
        pixel = magnifier_to_image((event.x, event.y), self._mag_center, held.size)
        if pixel is not None:
            self._select(pixel)

    def _on_preview_motion(self, event: tk.Event[tk.Misc]) -> None:
        img = self._displayed_image()
        if img is None:
            return
        pixel = display_to_image((event.x, event.y), self._preview_display, img.size)
        if pixel is not None and pixel != self._mag_center:
            self._mag_center = pixel
            self._render_magnifier()

    def _on_preview_leave(self, _event: object | None = None) -> None:
        selected = self.capture_session.selected_position
        if selected is not None and selected != self._mag_center:
            self._mag_center = selected
            self._render_magnifier()

    def _nudge_entry(self, entry: ttk.Entry, kind: str, delta: int) -> str:
        try:
            value = int(entry.get()) + delta
        except ValueError:
            return "break"
        entry.delete(0, tk.END)
        entry.insert(0, str(value))
        if kind == "pos":
            self._on_pos_entry()
        else:
            self._on_pixel_entry()
        return "break"

    def _on_pos_entry(self, _event: object | None = None) -> None:
        try:
            pos = (int(self.pos_entries[0].get()), int(self.pos_entries[1].get()))
        except ValueError:
            return
        self.capture_session.set_position(pos)
        self._render_info()

    def _on_pixel_entry(self, _event: object | None = None) -> None:
        try:
            pixel = (
                int(self.pixel_entries[0].get()),
                int(self.pixel_entries[1].get()),
            )
        except ValueError:
            return
        if pixel != self.capture_session.selected_position:
            self._mag_center = pixel
            self._select(pixel)

    def _on_capture_size_change(self, _event: object | None = None) -> None:
        size = self._current_capture_size()
        try:
            if (self.capture_w_var.get(), self.capture_h_var.get()) != size:
                self.capture_w_var.set(size[0])
                self.capture_h_var.set(size[1])
        except (tk.TclError, ValueError):
            self.capture_w_var.set(size[0])
            self.capture_h_var.set(size[1])
        self.capture_session.set_capture_size(*size)

    def _toggle_advanced(self) -> None:
        self._advanced_open = not self._advanced_open
        if self._advanced_open:
            self.advanced.pack(fill="x", after=self.lbl_advanced)
        else:
            self.advanced.pack_forget()
        self._sync_advanced_label()

    def _sync_advanced_label(self) -> None:
        mark = theme.ICON_EXPANDED if self._advanced_open else theme.ICON_COLLAPSED
        self.lbl_advanced.config(text=f"{mark} {txt('Advanced', '고급')}")

    # -- polling --------------------------------------------------------------

    def _check_keys(self) -> None:
        if self._is_closing:
            return
        alt = KeyUtils.mod_key_pressed("alt")
        if alt:
            self.capture_session.set_position(self.win.winfo_pointerxy())
            self._render_info()
        if alt != self._alt_down:
            self._alt_down = alt
            self._render()

        ctrl = KeyUtils.mod_key_pressed("ctrl")
        if ctrl and not self._ctrl_was_pressed and ctrl_capture_allowed(
            self._focus_widget()
        ):
            self._on_ctrl()
        self._ctrl_was_pressed = ctrl

        self._avoid_capture_box()
        self._sync_border()

        self._permission_ticks -= 1
        if self._permission_ticks <= 0:
            self._permission_ticks = _PERMISSION_POLL_TICKS
            permission = self._compute_permission_message()
            if permission != self._permission_message:
                self._permission_message = permission
                self._render_status()

        self._modifier_after_id = self.win.after(100, self._check_keys)

    def _poll_capture(self) -> None:
        if self._is_closing:
            return
        snapshot = self.capture_session.snapshot()
        if snapshot.generation != self._capture_generation:
            self._capture_generation = snapshot.generation
            if self._shows_live():
                self._render()
        self._capture_after_id = self.win.after(50, self._poll_capture)

    def _focus_widget(self) -> tk.Misc | None:
        try:
            return self.win.focus_get()
        except (tk.TclError, KeyError):
            return None

    def _hud_rect(self) -> Rect | None:
        try:
            self.win.update_idletasks()
            x, y = self.win.winfo_x(), self.win.winfo_y()
            w, h = self.win.winfo_width(), self.win.winfo_height()
            title_bar = max(0, self.win.winfo_rooty() - y)
        except tk.TclError:
            return None
        if w <= 1 or h <= 1:
            return None
        return (x, y, w, h + title_bar)

    def _avoid_capture_box(self) -> None:
        hud = self._hud_rect()
        if hud is None:
            return
        box = capture_rect(
            self.capture_session.current_position(), self._current_capture_size()
        )
        screen = (self.win.winfo_screenwidth(), self.win.winfo_screenheight())
        target = hud_position(hud, box, screen)
        if target is not None:
            self.win.geometry(f"+{target[0]}+{target[1]}")

    def _sync_border(self) -> None:
        if self.border is None:
            return
        self.border.show(
            capture_rect(
                self.capture_session.current_position(), self._current_capture_size()
            )
        )

    @staticmethod
    def _compute_permission_message() -> str | None:
        missing = PermissionUtils.missing_macos_permissions()
        if not missing:
            return None
        labels: list[str] = []
        if "screen" in missing:
            labels.append(txt("Screen Recording", "화면 기록"))
        if "accessibility" in missing:
            labels.append(txt("Accessibility", "손쉬운 사용"))
        return txt(
            "macOS permission required: {missing}.",
            "macOS 권한 필요: {missing}.",
            missing=", ".join(labels),
        )

    # -- rendering ------------------------------------------------------------

    def _displayed_image(self) -> Image.Image | None:
        session = self.capture_session
        return session.latest_image if self._shows_live() else session.held_image

    def _render(self) -> None:
        if self._is_closing:
            return
        self._render_preview()
        self._render_magnifier()
        self._render_info()
        self._render_status()

    def _render_preview(self) -> None:
        img = self._displayed_image()
        if img is None:
            size = preview_size(self._current_capture_size())
            self._set_image(
                self.lbl_preview, Image.new("RGB", size, theme.SURFACE_SUNKEN)
            )
            self._preview_display = size
            return
        if not self._shows_live():
            img = render_overlay(
                img, self.capture_session.selected_position, self.region_size
            )
        size = preview_size(img.size)
        if size != img.size:
            img = cast(
                Image.Image, cast(Any, img).resize(size, Image.Resampling.LANCZOS)
            )
        self._preview_display = size
        self._set_image(self.lbl_preview, img)

    def _render_magnifier(self) -> None:
        img = self._displayed_image()
        size = MAGNIFIER_SPAN * MAGNIFIER_ZOOM
        if img is None:
            self._set_image(
                self.lbl_magnifier, Image.new("RGB", (size, size), theme.SURFACE_SUNKEN)
            )
            return
        center = self._mag_center or (img.width // 2, img.height // 2)
        selected = None if self._shows_live() else self.capture_session.selected_position
        self._set_image(self.lbl_magnifier, render_magnifier(img, center, selected))

    def _render_info(self) -> None:
        snap = self.capture_session.snapshot()
        color = snap.reference_color
        if snap.held_position is not None and snap.selected_position is not None:
            point = (
                snap.held_position[0] + snap.selected_position[0],
                snap.held_position[1] + snap.selected_position[1],
            )
        else:
            point = self.capture_session.current_position()
        rgb = ",".join(str(int(c)) for c in color[:3]) if color else "—"
        try:
            self.lbl_swatch.config(bg=_color_hex(color) if color else theme.SURFACE_SUNKEN)
            self.lbl_info.config(text=f"{rgb}  ({point[0]}, {point[1]})")
        except tk.TclError:
            return
        self._sync_entries(snap.selected_position)

    def _sync_entries(self, selected: Position | None) -> None:
        focus = self._focus_widget()
        pos = self.capture_session.current_position()
        for entry, value in zip(self.pos_entries, pos, strict=True):
            if entry is not focus:
                self._set_entry(entry, value)
        for i, entry in enumerate(self.pixel_entries):
            if entry is not focus:
                self._set_entry(entry, None if selected is None else selected[i])

    @staticmethod
    def _set_entry(entry: ttk.Entry, value: int | None) -> None:
        text = "" if value is None else str(value)
        if entry.get() != text:
            entry.delete(0, tk.END)
            entry.insert(0, text)

    def _status(self) -> tuple[str, str]:
        if self._permission_message:
            return self._permission_message, theme.STATUS_WARN_FG
        if self._feedback is not None:
            return self._feedback
        snap = self.capture_session.snapshot()
        if snap.latest_image is None:
            return (
                txt(
                    "Hold ALT and move the mouse over the target.",
                    "ALT를 누른 채 대상 위로 마우스를 옮기세요.",
                ),
                theme.INK_SECONDARY,
            )
        if snap.held_image is None:
            return (
                txt("Press CTRL to freeze this area.", "CTRL로 이 영역을 고정하세요."),
                theme.INK_SECONDARY,
            )
        if snap.selected_position is None:
            return (
                txt(
                    "Click the capture or magnifier to pick the target pixel.",
                    "캡처본이나 돋보기를 클릭해 대상 픽셀을 고르세요.",
                ),
                theme.INK_SECONDARY,
            )
        if self.mode == "continuous":
            return (
                txt(
                    "Press CTRL again (or Apply) to save to Quick.",
                    "CTRL을 한 번 더 누르거나 적용하면 Quick에 저장합니다.",
                ),
                theme.SIGNAL_BASE,
            )
        return (
            txt("Press Apply (Enter) to use this capture.", "적용(Enter)을 누르세요."),
            theme.SIGNAL_BASE,
        )

    def _render_status(self) -> None:
        text, color = self._status()
        try:
            self.lbl_status.config(text=text, fg=color)
            self.btn_apply.config(state="normal" if self.is_ready() else "disabled")
            if self.lbl_title is not None:
                self.lbl_title.config(
                    text=txt(
                        "Quick Add · {count} saved",
                        "빠른 추가 · {count}개 저장",
                        count=self.saved_count,
                    )
                )
        except tk.TclError:
            return

    @staticmethod
    def _set_image(label: tk.Label, img: Image.Image) -> None:
        try:
            photo = ImageTk.PhotoImage(img.convert("RGB"), master=label)
            label.configure(image=photo, width=img.width, height=img.height)
            cast(Any, label).image = photo
        except tk.TclError:
            return

    # -- lifecycle ------------------------------------------------------------

    def is_open(self) -> bool:
        if self._is_closing:
            return False
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _restore_state(self, *, restore_pointer: bool) -> None:
        state = StateUtils.load_main_app_state() or {}
        pos = StateUtils.parse_slash_int_pair(state.get("capture_hud_pos"))
        if pos is not None:
            self.win.geometry(f"+{pos[0]}+{pos[1]}")
        else:
            WindowUtils.center_window(self.win)
        if restore_pointer and (ptr := state.get(self._pointer_state_key)):
            point = StateUtils.parse_position_tuple(ptr)
            if point is not None:
                self.capture_session.set_position(point)

    def close(self, _event: object | None = None) -> None:
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
        if self.border is not None:
            self.border.destroy()
        try:
            StateUtils.save_main_app_state(
                capture_hud_pos=f"{self.win.winfo_x()}/{self.win.winfo_y()}",
                **{
                    self._pointer_state_key: str(
                        self.capture_session.current_position()
                    )
                },
            )
        except tk.TclError:
            pass
        try:
            self.win.grab_release()
            self.win.destroy()
        except tk.TclError:
            pass
        if self._grab:
            WindowUtils.restore_modal_grab(self.master)
        if self.on_close is not None:
            self.on_close()
