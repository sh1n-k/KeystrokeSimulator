from __future__ import annotations

import platform
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Any, cast

from loguru import logger
from app.utils.i18n import txt

from app.domain.models import UserSettings
from app.presenters.run_controller import (
    Readiness,
    RunController,
    RunSelection,
    StatusTone,
    migrate_legacy_run_profiles,
    safe_call,
)
from app.ui.dialogs import ask_confirm
from app.ui.modkeys import ModificationKeysWindow
from app.ui.main_frames import (
    HoverTip,
    ModKeySetFrame,
    ProcessFrame,
    RunTargetFrame,
)
from app.platform.input_router import InputRouter
from app.ui.tk_dispatcher import TkDispatcher
from app.storage.modkey_sets_storage import (
    DEFAULT_MODKEY_SET_NAME,
    DEFAULT_MODKEY_SETS_PATH,
)
from app.storage.run_sets_storage import (
    CURRENT_RUN_SET_ID,
    DEFAULT_RUN_SETS_PATH,
    is_current_run_set,
    list_run_set_names,
)
from app.storage.profile_storage import list_profile_names
from app.ui.capture_hud import CaptureHud
from app.ui.workspace import Workspace
from app.ui.settings import KeystrokeSettings
from app.utils.sounds import SoundPlayer
from app.platform.system import PermissionUtils
from app.utils.exception_hooks import install_exception_hooks
from app.storage.app_state import StateUtils
from app.ui.tk_window import WindowUtils
from app.ui import theme

STATUS_BG_RUN = theme.STATUS_RUNNING_BG
STATUS_FG_RUN = theme.STATUS_RUNNING_FG
# Readiness tone → (bg, fg).
STATUS_COLORS: dict[StatusTone, tuple[str, str]] = {
    "ready": (theme.STATUS_READY_BG, theme.STATUS_READY_FG),
    "warn": (theme.STATUS_WARN_BG, theme.STATUS_WARN_FG),
    "error": (theme.STATUS_ERROR_BG, theme.STATUS_ERROR_FG),
}

VoidCallback = Callable[[], None]


class KeystrokeSimulatorApp(tk.Tk):
    # Class-level default: Tk.__getattr__ recurses on instances without .tk.
    _quick_hud: CaptureHud | None = None
    _workspace: Workspace | None = None

    def __init__(self) -> None:
        super().__init__()
        install_exception_hooks(self)
        self.title("Keystroke Simulator")
        self.profiles_dir = Path("profiles")
        self.profiles_dir.mkdir(exist_ok=True)
        self.modkey_sets_path = Path(DEFAULT_MODKEY_SETS_PATH)
        self.selected_process: tk.StringVar = tk.StringVar()
        self.selected_profile: tk.StringVar = tk.StringVar()
        self.selected_modkey_set: tk.StringVar = tk.StringVar(
            value=DEFAULT_MODKEY_SET_NAME
        )
        self.selected_run_set: tk.StringVar = tk.StringVar(value=CURRENT_RUN_SET_ID)
        self.run_sets_path = Path(DEFAULT_RUN_SETS_PATH)
        self.settings_window: KeystrokeSettings | None = None
        self.sound_player: SoundPlayer = SoundPlayer()
        self._selection_trace_handles: list[str] = []
        self.run = RunController(
            self,
            router=InputRouter(TkDispatcher(self)),
            sound_player=self.sound_player,
            profiles_dir=self.profiles_dir,
            modkey_sets_path=self.modkey_sets_path,
            run_sets_path=self.run_sets_path,
        )

        self._create_ui()
        self._bind_selection_traces()
        self.load_settings()
        self.setup_event_handlers()
        self.update_ui()

    def _create_ui(self) -> None:
        # Paper-tone root + ttk styles.
        self.configure(bg=theme.SURFACE_PAPER)
        try:
            ttk.Style(self).theme_use("default")
        except tk.TclError:
            pass
        theme.install_styles(self)
        f = theme.fonts()

        # --- Title bar with the ⚙ tools menu ---------------------------------
        self.context_bar: tk.Frame = tk.Frame(
            self,
            bg=theme.SURFACE_PANEL,
            padx=theme.SPACE_3,
            pady=theme.SPACE_2,
        )
        self.context_bar.pack(fill="x", side="top")
        self.lbl_app_title: tk.Label = tk.Label(
            self.context_bar,
            text="KEYSTROKE SIMULATOR",
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_SECONDARY,
            font=f["heading"],
        )
        self.lbl_app_title.pack(side=tk.LEFT)
        # A plain Label: Aqua draws an up/down indicator on every Menubutton.
        self.tools_button: tk.Label = tk.Label(
            self.context_bar,
            text=theme.ICON_TOOLS,
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_SECONDARY,
            font=f["icon"],
            cursor="hand2",
            padx=theme.SPACE_1,
        )
        self.tools_button.pack(side=tk.RIGHT)
        self.tools_menu: tk.Menu = tk.Menu(self.tools_button, tearoff=0)
        self.tools_button.bind("<Button-1>", self._show_tools_menu)
        self._tools_menus: list[tk.Menu] = [self.tools_menu]
        if platform.system() == "Darwin":
            # macOS: the same tools live in the system menu bar.
            menubar = tk.Menu(self)
            self.menubar_tools: tk.Menu = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label=txt("Tools", "도구"), menu=self.menubar_tools)
            self.config(menu=menubar)
            self._tools_menus.append(self.menubar_tools)
        tk.Frame(self, bg=theme.SURFACE_DIVIDER, height=1).pack(fill="x", side="top")

        # --- Run dock (bottom, packed before body so it stays anchored) -------
        tk.Frame(self, bg=theme.SURFACE_DIVIDER, height=1).pack(fill="x", side="bottom")
        self.run_dock: tk.Frame = tk.Frame(
            self,
            bg=theme.SURFACE_PAPER,
            padx=theme.SPACE_3,
            pady=theme.SPACE_3,
        )
        self.run_dock.pack(fill="x", side="bottom")

        self.body: tk.Frame = tk.Frame(
            self,
            bg=theme.SURFACE_PAPER,
            padx=theme.SPACE_3,
            pady=theme.SPACE_3,
        )
        self.body.pack(fill="both", expand=True, side="top")
        self.target_card: tk.Frame
        self.target_card, target_body = self._make_card(self.body, "")
        self.target_card.pack(fill="x")
        self.process_frame: ProcessFrame = ProcessFrame(target_body, self.selected_process)
        self.process_frame.configure(bg=theme.SURFACE_CANVAS)
        self.process_frame.pack(fill="x", pady=(0, theme.SPACE_1))
        self.run_target_frame: RunTargetFrame = RunTargetFrame(
            target_body,
            self.selected_profile,
            self.selected_run_set,
            profiles_dir=self.profiles_dir,
            sets_path=self.run_sets_path,
            edit_cb=self.open_workspace_for,
        )
        self.run_target_frame.configure(bg=theme.SURFACE_CANVAS)
        self.run_target_frame.pack(fill="x", pady=(0, theme.SPACE_1))
        self.modkey_set_frame: ModKeySetFrame = ModKeySetFrame(
            target_body,
            self.selected_modkey_set,
            sets_path=self.modkey_sets_path,
            edit_cb=self.open_modkeys,
        )
        self.modkey_set_frame.configure(bg=theme.SURFACE_CANVAS)
        self.modkey_set_frame.pack(fill="x")

        # --- Status: one line, plus one fix button only when blocked ---------
        status_row = tk.Frame(self.body, bg=theme.SURFACE_PAPER)
        status_row.pack(fill="x", pady=(theme.SPACE_3, 0))
        self.lbl_status_badge: tk.Label = tk.Label(
            status_row,
            bg=theme.STATUS_READY_BG,
            fg=theme.STATUS_READY_FG,
            font=f["body_bold"],
            padx=theme.SPACE_2,
            pady=theme.SPACE_1,
            anchor="w",
            justify="left",
        )
        self.lbl_status_badge.pack(side=tk.LEFT, fill="x", expand=True)
        self.status_tooltip = HoverTip(self.lbl_status_badge)
        self._status_action: str | None = None
        self.btn_status_fix: tk.Button = tk.Button(
            status_row, command=self._on_status_fix
        )
        self._apply_outline_button(self.btn_status_fix)

        for widget in (
            self.process_frame.lbl_process,
            self.run_target_frame.lbl_target,
            self.modkey_set_frame.lbl_sets,
        ):
            widget.configure(
                bg=theme.SURFACE_CANVAS,
                fg=theme.INK_SECONDARY,
                font=f["body"],
            )
        for btn in (self.process_frame.refresh_button, self.run_target_frame.edit_button):
            self._apply_outline_button(btn)

        # --- Run dock contents ------------------------------------------------
        self.lbl_run_status: tk.Label = tk.Label(
            self.run_dock,
            bg=theme.SURFACE_PAPER,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
        )
        self.lbl_run_status.pack(side=tk.LEFT)
        # Label (not tk.Button): Aqua ignores Button bg/fg, so solid fill never shows.
        self.run_start_button: tk.Label = tk.Label(
            self.run_dock,
            text=txt("Start", "시작"),
            cursor="hand2",
        )
        self._run_start_enabled = True
        self._apply_accent_button(self.run_start_button)
        self.run_start_button.bind("<Button-1>", self._on_run_start_clicked)
        self.run_start_button.pack(side=tk.RIGHT)

        style = ttk.Style(self)
        style.configure("TEntry", fieldbackground=theme.SURFACE_CANVAS)
        self._refresh_ui_texts()
        self._restore_window_position()

    # Tools menu entries: (key, en, ko, command, idle_only).
    def _tools_entries(self) -> list[tuple[str, str, str, VoidCallback, bool]]:
        return [
            ("workspace", "Open workspace…", "작업 공간 열기…", self.open_profile, False),
            ("quick", "Quick events…", "빠른 이벤트…", self.open_quick_events, True),
            ("sep", "", "", lambda: None, False),
            ("modkey_edit", "Edit modifier keys…", "수정키 세트 편집…", self.open_modkeys, True),
            ("modkey_copy", "Duplicate modifier keys", "수정키 세트 복사", self._copy_modkey_set, True),
            ("modkey_delete", "Delete modifier keys", "수정키 세트 삭제", self._delete_modkey_set, True),
            ("sep", "", "", lambda: None, False),
            ("settings", "Settings…", "설정…", self.open_settings, True),
            ("clear_logs", "Clear logs", "로그 삭제", self.clear_local_logs, True),
        ]

    def _show_tools_menu(self, _event: object | None = None) -> None:
        button = self.tools_button
        self.tools_menu.tk_popup(
            button.winfo_rootx(), button.winfo_rooty() + button.winfo_height()
        )

    def _build_tools_menus(self) -> None:
        for menu in getattr(self, "_tools_menus", []):
            menu.delete(0, "end")
            for key, en, ko, command, _idle in self._tools_entries():
                if key == "sep":
                    menu.add_separator()
                else:
                    menu.add_command(label=txt(en, ko), command=command)

    def _sync_tools_menus(self, running: bool) -> None:
        for menu in self.__dict__.get("_tools_menus", []):
            for index, (key, _en, _ko, _cmd, idle_only) in enumerate(
                self._tools_entries()
            ):
                if key == "sep":
                    continue
                state = "disabled" if running and idle_only else "normal"
                safe_call(menu.entryconfigure, index, state=state)

    def _copy_modkey_set(self) -> None:
        self.modkey_set_frame.copy_set()
        self._update_main_status()

    def _delete_modkey_set(self) -> None:
        self.modkey_set_frame.delete_set()
        self._update_main_status()

    def _make_card(self, parent: tk.Misc, title: str) -> tuple[tk.Frame, tk.Frame]:
        """Create a workstation-style card with a thin divider title."""
        f = theme.fonts()
        outer = tk.Frame(
            parent,
            bg=theme.SURFACE_CANVAS,
            highlightthickness=1,
            highlightbackground=theme.SURFACE_DIVIDER,
        )
        header = tk.Frame(outer, bg=theme.SURFACE_CANVAS)
        if title:
            header.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_2, 0))
        title_label = tk.Label(
            header,
            text=title,
            bg=theme.SURFACE_CANVAS,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
        )
        title_label.pack(side=tk.LEFT, anchor="w")
        # Track the label so refresh_texts can update it later if needed.
        cast(Any, outer)._title_label = title_label
        body = tk.Frame(outer, bg=theme.SURFACE_CANVAS)
        body.pack(
            fill="x",
            padx=theme.SPACE_3,
            pady=(theme.SPACE_1 if title else theme.SPACE_3, theme.SPACE_3),
        )
        return outer, body

    def _on_run_start_clicked(self, _event: object | None = None) -> None:
        if not getattr(self, "_run_start_enabled", False):
            return
        self.toggle_start_stop()

    @staticmethod
    def _style_run_control(
        btn: tk.Misc,
        *,
        bg: str,
        fg: str,
        cursor: str = "hand2",
    ) -> None:
        """Color the Start/Stop control (Label on Aqua; Button elsewhere)."""
        widget = cast(Any, btn)
        try:
            widget.configure(
                bg=bg,
                fg=fg,
                # The control is set to state="disabled" when start is blocked;
                # Tk's default disabled text is nearly invisible on the muted fill.
                disabledforeground=fg,
                relief="flat",
                borderwidth=0,
                highlightthickness=0,
                padx=theme.SPACE_3,
                pady=theme.SPACE_2,
                cursor=cursor,
            )
        except tk.TclError:
            try:
                widget.configure(bg=bg, fg=fg)
            except tk.TclError:
                pass
        try:
            widget.configure(font=theme.fonts()["body_bold"])
        except Exception:
            pass

    @classmethod
    def _apply_accent_button(cls, btn: tk.Misc) -> None:
        """Solid green + white text (Label preferred: Aqua ignores Button bg/fg)."""
        cls._style_run_control(btn, bg=theme.SIGNAL_BASE, fg="#FFFFFF")

    @classmethod
    def _apply_run_stop_button(cls, btn: tk.Misc) -> None:
        """Running-state Start→Stop control (amber fill, white text)."""
        cls._style_run_control(btn, bg=theme.STATUS_RUNNING_FG, fg="#FFFFFF")

    @classmethod
    def _apply_run_disabled_button(cls, btn: tk.Misc) -> None:
        """Muted control when start is not available."""
        cls._style_run_control(
            btn, bg=theme.SURFACE_SUNKEN, fg=theme.INK_MUTED, cursor="arrow"
        )

    @staticmethod
    def _apply_outline_button(btn: tk.Button) -> None:
        f = theme.fonts()
        btn.configure(
            bg=theme.SURFACE_CANVAS,
            fg=theme.INK_PRIMARY,
            activebackground=theme.SURFACE_SUNKEN,
            activeforeground=theme.INK_PRIMARY,
            disabledforeground=theme.INK_MUTED,
            relief="flat",
            borderwidth=1,
            highlightbackground=theme.SURFACE_DIVIDER,
            highlightcolor=theme.SURFACE_DIVIDER,
            highlightthickness=1,
            font=f["body"],
        )

    def _bind_selection_traces(self) -> None:
        def schedule_update(*_args: object) -> None:
            self.after_idle(self.update_ui)

        for var in (
            self.selected_process,
            self.selected_profile,
            self.selected_modkey_set,
            self.selected_run_set,
        ):
            self._selection_trace_handles.append(var.trace_add("write", schedule_update))

    # ── RunHost ────────────────────────────────────────────────────────

    def selection(self) -> RunSelection:
        return RunSelection(
            process=self.selected_process.get(),
            profile=self.selected_profile.get(),
            run_set=self.selected_run_set.get(),
            modkey_set=self.selected_modkey_set.get(),
        )

    def on_run_state_changed(self) -> None:
        self.update_ui()

    def on_status_changed(self) -> None:
        self._update_main_status()

    def before_start(self) -> None:
        quick_hud = self._quick_hud
        if quick_hud is not None and quick_hud.is_open():
            quick_hud.close()

    def defer(self, action: Callable[[], None]) -> None:
        self.after(0, action)

    def window_position(self) -> str | None:
        try:
            return f"{self.winfo_x()}/{self.winfo_y()}"
        except tk.TclError:
            return None

    def is_alive(self) -> bool:
        return bool(self.winfo_exists())

    # ── run controller delegation (settings window, buttons) ───────────

    @property
    def settings(self) -> UserSettings:
        return self.run.settings

    def setup_event_handlers(self) -> None:
        self.run.setup_event_handlers()
        # Esc는 앱을 끄지 않는다(M-05). 창 닫기로만 종료한다.
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def unbind_events(self) -> None:
        self.run.unbind_events()

    def toggle_start_stop(self, event: object | None = None) -> None:
        self.run.toggle_start_stop()

    def load_settings(self) -> None:
        self.run.load_settings()
        self._refresh_ui_texts()

        # Load state
        state = StateUtils.load_main_app_state() or {}
        proc = state.get("process")
        if isinstance(proc, str) and proc:
            match = next(
                (
                    p
                    for p in cast(tuple[str, ...], self.process_frame.process_combobox.cget("values"))
                    if p.startswith(proc)
                ),
                None,
            )
            if match:
                self.selected_process.set(match)
        prof = state.get("profile")
        if isinstance(prof, str) and prof:
            self.run_target_frame.set_target("profile", prof)
        self._restore_run_set_selection(state)
        modkey_set = state.get("modkey_set")
        if isinstance(modkey_set, str) and modkey_set:
            self.modkey_set_frame.set_selected_set(modkey_set)
        self.update_ui()

    def _refresh_ui_texts(self) -> None:
        if hasattr(self, "process_frame"):
            self.process_frame.refresh_texts()
        if hasattr(self, "run_target_frame"):
            self.run_target_frame.refresh_texts()
        if hasattr(self, "modkey_set_frame"):
            self.modkey_set_frame.refresh_texts()
        self._build_tools_menus()
        run_start_button = self.__dict__.get("run_start_button")
        if run_start_button is not None:
            self._apply_accent_button(run_start_button)
        if hasattr(self, "lbl_status_badge"):
            self._update_main_status()

    def _restore_run_set_selection(self, state: dict[str, object]) -> None:
        """Restore a named run set, or migrate the legacy run_profiles list.

        Earlier versions stored the virtual "__current__" set for single-profile
        runs; that simply means the profile stays selected.
        """
        frame = self.__dict__.get("run_target_frame")
        if frame is None:
            return
        run_set = state.get("run_set")
        if isinstance(run_set, str) and run_set.strip():
            if not is_current_run_set(run_set):
                frame.set_target("run_set", run_set.strip())
            return
        # Legacy: run_profiles list from earlier multi-select UI.
        migrated = migrate_legacy_run_profiles(
            state, list(frame.run_set_names), self.run_sets_path
        )
        if migrated:
            frame.load(select=("run_set", migrated))

    def _update_main_status(self) -> None:
        """상태는 한 줄. 막혔을 때만 해결 버튼 하나를 보인다."""
        if not hasattr(self, "lbl_status_badge"):
            return
        snapshot = self.run.readiness()
        bg, fg = STATUS_COLORS[snapshot["tone"]]
        running = self.run.is_running
        if running:
            bg, fg = STATUS_BG_RUN, STATUS_FG_RUN
        icon = self._icon_for_status(bg, running)
        summary = snapshot.get("summary") or snapshot["title"]
        self.lbl_status_badge.config(
            text=f"{icon}  {snapshot['badge_text']} · {summary}",
            bg=bg,
            fg=fg,
        )
        tooltip = self.__dict__.get("status_tooltip")
        if tooltip is not None:
            hint = self.run.hotkey_hint_text()
            detail = self.run.status_detail_with_selection(snapshot["detail"])
            tooltip.update_text(f"{detail}\n{hint}" if hint else detail)
        action = None if running else snapshot.get("action")
        self._status_action = action
        fix = self.__dict__.get("btn_status_fix")
        if fix is not None:
            if action:
                fix.config(text=self._status_action_label(action))
                fix.pack(side=tk.RIGHT, padx=(theme.SPACE_2, 0))
            else:
                fix.pack_forget()
        self._missing_permissions = list(snapshot.get("missing_permissions", []))
        if hasattr(self, "lbl_run_status"):
            self.lbl_run_status.config(text=self.run.run_dock_text(running))

    @staticmethod
    def _status_action_label(action: str) -> str:
        return {
            "permissions": txt("Open settings", "권한 설정 열기"),
            "process": txt("Refresh", "새로고침"),
        }.get(action, txt("Open workspace", "작업 공간에서 보기"))

    def _on_status_fix(self) -> None:
        action = getattr(self, "_status_action", None)
        if action == "permissions":
            missing = getattr(self, "_missing_permissions", [])
            if missing:
                self._open_macos_permission_setting(missing[0])
        elif action == "process":
            self.process_frame.refresh_processes()
        elif action == "workspace":
            self.open_profile()

    def _open_macos_permission_setting(self, permission: str) -> None:
        if PermissionUtils.open_macos_permission_settings(permission):
            return
        messagebox.showinfo(
            txt("Open Settings", "설정 열기"),
            txt(
                "Open macOS System Settings and grant this executable the required permission.",
                "macOS 시스템 설정을 열어 이 실행 파일에 필요한 권한을 허용하세요.",
            ),
        )

    @staticmethod
    def _icon_for_status(bg: str, running: bool) -> str:
        if running:
            return theme.STATUS_RUNNING_ICON
        return {
            theme.STATUS_INFO_BG: theme.STATUS_INFO_ICON,
            theme.STATUS_READY_BG: theme.STATUS_READY_ICON,
            theme.STATUS_WARN_BG: theme.STATUS_WARN_ICON,
            theme.STATUS_ERROR_BG: theme.STATUS_ERROR_ICON,
            theme.STATUS_RUNNING_BG: theme.STATUS_RUNNING_ICON,
        }.get(bg, theme.STATUS_INFO_ICON)

    def clear_local_logs(self) -> None:
        log_dir = Path("logs")
        confirmed = ask_confirm(
            self if "tk" in self.__dict__ else None,
            title=txt("Confirm", "확인"),
            message=txt(
                "Delete old log files?",
                "오래된 로그 파일을 삭제하시겠습니까?",
            ),
            ok_text=txt("OK", "확인"),
            cancel_text=txt("Cancel", "취소"),
        )
        if not confirmed:
            return

        deleted_size, count = 0, 0
        if log_dir.exists():
            for p in log_dir.glob("*"):
                if p.name != "keysym.log" and p.is_file():
                    try:
                        deleted_size += p.stat().st_size
                        p.unlink()
                        count += 1
                    except Exception as e:
                        logger.warning(f"Del failed {p}: {e}")

        # No follow-up dialog (Cancel or OK) — keep feedback in logs/status only.
        if count:
            logger.info(
                "Cleared {count} old log files ({size:.2f} MB)",
                count=count,
                size=deleted_size / 1048576,
            )
        else:
            logger.info("No old log files to clear")
        run_status = self.__dict__.get("lbl_run_status")
        if run_status is not None:
            run_status.config(
                text=(
                    txt(
                        "Cleared {count} old log file(s).",
                        "오래된 로그 {count}개 삭제했습니다.",
                        count=count,
                    )
                    if count
                    else txt(
                        "No old logs to clear.",
                        "정리할 오래된 로그가 없습니다.",
                    )
                )
            )

    def update_ui(self) -> None:
        running = self.run.is_running
        state = "disabled" if running else "normal"
        readonly_state = "disabled" if running else "readonly"
        readiness: Readiness = self.run.readiness()

        self.process_frame.process_combobox.config(state=readonly_state)
        self.process_frame.refresh_button.config(state=state)
        self.run_target_frame.combobox.config(state=readonly_state)
        # 작업 공간은 실행 중에도 연다. 편집은 다음 시작부터 반영된다.
        self.run_target_frame.edit_button.config(state="normal")
        self.modkey_set_frame.sets_combobox.config(state=readonly_state)
        self._sync_tools_menus(running)

        run_start_button = self.__dict__.get("run_start_button")
        if run_start_button is not None:
            can_press = bool(running or readiness["can_start"])
            self._run_start_enabled = can_press
            label = (
                f"{theme.ICON_STOP} {txt('Stop', '중지')}"
                if running
                else f"{theme.ICON_START} {txt('Start', '시작')}"
            )
            if hotkey := self.run.hotkey_short():
                label = f"{label}  {hotkey}"
            start_state = "normal" if can_press else "disabled"
            # Prefer single config() for Button/mocks; Label ignores state=.
            try:
                run_start_button.config(text=label, state=start_state)  # type: ignore[attr-defined]
            except tk.TclError:
                try:
                    run_start_button.configure(text=label)  # type: ignore[attr-defined]
                except tk.TclError:
                    pass
            # Label-based control: colors encode enablement (Aqua ignores Button bg/fg).
            if running:
                self._apply_run_stop_button(run_start_button)
            elif can_press:
                self._apply_accent_button(run_start_button)
            else:
                self._apply_run_disabled_button(run_start_button)
        workspace = self._workspace
        if workspace is not None and workspace.is_open():
            workspace.set_running(running)
        self._update_main_status()

    def open_modkeys(self) -> None:
        if self.run.is_running:
            return
        set_name = self.selected_modkey_set.get()
        if not set_name:
            return
        win = ModificationKeysWindow(
            self, set_name, sets_path=self.modkey_sets_path
        )
        # Only block when a real Tk interpreter is attached (skip unit stubs).
        if "tk" in self.__dict__:
            safe_call(self.wait_window, win)
        self._update_main_status()

    def open_profile(self) -> None:
        """작업 공간을 연다. 모달이 아니며 실행 중에도 편집할 수 있다."""
        frame = self.__dict__.get("run_target_frame")
        if frame is not None:
            self.open_workspace_for(frame.get_target())
            return
        self._open_workspace(profile=self.selected_profile.get() or None)

    def open_workspace_for(self, target: tuple[str, str]) -> None:
        """"편집…": 실행 콤보에서 고른 프로필이나 실행 세트로 연다(M-06)."""
        kind, name = target
        if kind == "run_set":
            self._open_workspace(profile=self.selected_profile.get() or None, run_set=name)
        else:
            self._open_workspace(profile=name or None)

    def _open_workspace(
        self, *, profile: str | None = None, run_set: str | None = None
    ) -> None:
        workspace = self._workspace
        if workspace is not None and workspace.is_open():
            if run_set:
                workspace.select_item("run_set", run_set)
            elif profile:
                workspace.select_item("profile", profile)
            return
        self._workspace = Workspace(
            self,
            profiles_dir=self.profiles_dir,
            run_sets_path=self.run_sets_path,
            running_getter=lambda: self.run.is_running,
            settings_getter=lambda: getattr(self, "settings", None),
            on_catalog_changed=self.reload_profiles,
            on_run_set_renamed=self._on_run_set_renamed,
            on_close=self._on_workspace_closed,
            profile=profile,
            run_set=run_set,
        )

    def _on_run_set_renamed(self, old: str, new: str) -> None:
        """고른 실행 세트의 이름이 바뀌면 새 이름을 계속 고른다."""
        if (self.selected_run_set.get() or "").strip() == old:
            self.selected_run_set.set(new)

    def _on_workspace_closed(self) -> None:
        self._workspace = None
        self.reload_profiles(None)

    def reload_profiles(self, new_name: str | None) -> None:
        """작업 공간에서 프로필·실행 세트가 바뀌면 실행 콤보를 다시 읽는다.
        고른 프로필이 사라졌을 때만(이름 변경) 새 이름으로 옮긴다."""
        frame = self.run_target_frame
        kind, name = frame.get_target()
        if kind == "profile" and new_name and name not in list_profile_names(self.profiles_dir):
            name = new_name
        if kind == "run_set" and name not in list_run_set_names(self.run_sets_path):
            kind, name = "profile", self.selected_profile.get()
        frame.load(select=(kind, name))
        self.update_ui()

    def open_quick_events(self) -> None:
        if self.run.is_running:
            return
        # HUD는 모달이 아니므로 두 번 열지 않고 기존 창을 앞으로 가져온다.
        existing = self._quick_hud
        if existing is not None and existing.is_open():
            safe_call(cast(Any, existing.win).lift)
            return
        self._quick_hud = CaptureHud(
            self,
            mode="continuous",
            profiles_dir=self.profiles_dir,
            on_close=self.update_ui,
        )

    def open_settings(self) -> None:
        existing_window = self.settings_window
        if existing_window and safe_call(existing_window.winfo_exists):
            window = cast(Any, existing_window)
            safe_call(window.lift)
            safe_call(window.focus_force)
            safe_call(window.grab_set)
            return
        if existing_window:
            self.settings_window = None
        self.unbind_events()
        self.settings_window = KeystrokeSettings(self)

    def _restore_window_position(self) -> None:
        pos = StateUtils.parse_slash_int_pair(
            (StateUtils.load_main_app_state() or {}).get("main_pos")
        )
        if pos is not None:
            try:
                self.geometry(f"+{pos[0]}+{pos[1]}")
                return
            except tk.TclError:
                pass
        WindowUtils.center_window(self)

    def on_closing(self, event: object | None = None) -> None:
        if getattr(self, "_is_closing", False):
            return
        self._is_closing = True
        logger.info("Shutting down...")

        self.run.shutdown()
        sound_player = getattr(self, "sound_player", None)
        if sound_player is not None:
            safe_call(getattr(sound_player, "close", lambda: None))
        safe_call(self.destroy)
        safe_call(self.quit)
