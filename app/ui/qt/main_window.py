"""실행 창: 대상·실행·수정키 세트를 고르고 시작/중지한다.

상태와 동작은 `RunController`가 맡고, 이 창은 `RunHost`로 선택값과 화면
갱신만 제공한다. 작업 공간·빠른 캡처·설정·수정키 창은 각 모듈이 연다.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import UserSettings
from app.domain.display_text import ellipsize_display, run_set_display
from app.platform.input_router import InputRouter
from app.platform.system import PermissionUtils, ProcessCollector
from app.presenters.run_controller import (
    RunController,
    RunSelection,
    StatusAction,
    migrate_legacy_run_profiles,
)
from app.storage.app_state import StateUtils
from app.storage.modkey_sets_storage import (
    DEFAULT_MODKEY_SET_NAME,
    DEFAULT_MODKEY_SETS_PATH,
    copy_modkey_set,
    delete_modkey_set,
    ensure_default_modkey_set,
    list_modkey_set_names,
)
from app.storage.profile_display import QUICK_PROFILE_NAME, build_profile_display_values
from app.storage.profile_storage import list_profile_names, ordered_profile_names
from app.storage.run_sets_storage import (
    CURRENT_RUN_SET_ID,
    DEFAULT_RUN_SETS_PATH,
    is_current_run_set,
    list_run_set_names,
)
from app.ui import tokens
from app.ui.qt import style
from app.ui.qt.dispatcher import QtDispatcher
from app.utils.i18n import txt
from app.utils.sounds import SoundPlayer

TargetKind = str  # "profile" | "run_set"
RunTarget = tuple[TargetKind, str]
VoidCallback = Callable[[], None]


class RunWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Keystroke Simulator")
        self.profiles_dir = Path("profiles")
        self.profiles_dir.mkdir(exist_ok=True)
        self.modkey_sets_path = Path(DEFAULT_MODKEY_SETS_PATH)
        self.run_sets_path = Path(DEFAULT_RUN_SETS_PATH)
        self.sound_player = SoundPlayer()
        self.run = RunController(
            self,
            router=InputRouter(QtDispatcher()),
            sound_player=self.sound_player,
            profiles_dir=self.profiles_dir,
            modkey_sets_path=self.modkey_sets_path,
            run_sets_path=self.run_sets_path,
        )
        self._closing = False
        self._status_action: StatusAction | None = None
        self._missing_permissions: list[str] = []
        self._run_set_names: list[str] = []
        # Child windows, opened lazily by their own modules.
        self.workspace: QWidget | None = None
        self.quick_hud: QWidget | None = None
        self.settings_dialog: QWidget | None = None

        self._build()
        self.load_settings()
        self._restore_state()
        self.setup_event_handlers()
        self.update_ui()

    # ── layout ─────────────────────────────────────────────────────────

    def _build(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 14)
        root.setSpacing(12)

        header = QHBoxLayout()
        self.lbl_title = QLabel("Keystroke Simulator")
        title_font = self.lbl_title.font()
        title_font.setBold(True)
        title_font.setPointSizeF(title_font.pointSizeF() + 2)
        self.lbl_title.setFont(title_font)
        header.addWidget(self.lbl_title)
        header.addStretch(1)
        self.tools_button = QToolButton()
        self.tools_button.setText(tokens.ICON_TOOLS)
        self.tools_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.tools_button.setAutoRaise(True)
        self.tools_button.setStyleSheet(
            "QToolButton { font-size: 18px; padding: 0 4px; }"
            " QToolButton::menu-indicator { image: none; width: 0; }"
        )
        self.tools_menu = QMenu(self)
        self.tools_button.setMenu(self.tools_menu)
        header.addWidget(self.tools_button)
        root.addLayout(header)

        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        self.lbl_process = QLabel()
        self.process_combo = QComboBox()
        self.process_combo.setMinimumContentsLength(24)
        self.process_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.refresh_button.clicked.connect(self.refresh_processes)
        grid.addWidget(self.lbl_process, 0, 0)
        grid.addWidget(self.process_combo, 0, 1)
        grid.addWidget(self.refresh_button, 0, 2)

        self.lbl_target = QLabel()
        self.target_combo = QComboBox()
        self.target_combo.setMinimumContentsLength(24)
        self.target_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.edit_button = QPushButton()
        self.edit_button.clicked.connect(lambda: self.open_workspace_for(self.target()))
        grid.addWidget(self.lbl_target, 1, 0)
        grid.addWidget(self.target_combo, 1, 1)
        grid.addWidget(self.edit_button, 1, 2)

        self.lbl_modkeys = QLabel()
        self.modkey_combo = QComboBox()
        grid.addWidget(self.lbl_modkeys, 2, 0)
        grid.addWidget(self.modkey_combo, 2, 1)
        root.addWidget(card)

        status_row = QHBoxLayout()
        self.lbl_status = QLabel()
        self.lbl_status.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.lbl_status.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.btn_status_fix = QPushButton()
        self.btn_status_fix.clicked.connect(self._on_status_fix)
        status_row.addWidget(self.lbl_status, 1)
        status_row.addWidget(self.btn_status_fix)
        root.addLayout(status_row)
        root.addStretch(1)

        dock = QHBoxLayout()
        self.lbl_run_status = QLabel()
        style.caption(self.lbl_run_status)
        self.run_button = QPushButton()
        self.run_button.setDefault(False)
        self.run_button.setAutoDefault(False)
        self.run_button.clicked.connect(self._on_run_clicked)
        dock.addWidget(self.lbl_run_status, 1)
        dock.addWidget(self.run_button)
        root.addLayout(dock)

        self.setCentralWidget(central)

        self._tools_actions: dict[str, QAction] = {}
        self._menubar_tools: QMenu | None = None
        if sys.platform == "darwin":
            # macOS: the same tools live in the system menu bar.
            self._menubar_tools = self.menuBar().addMenu("")

        self.process_combo.currentIndexChanged.connect(self._on_selection_changed)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        self.modkey_combo.currentIndexChanged.connect(self._on_selection_changed)

        self._last_target: RunTarget = ("profile", QUICK_PROFILE_NAME)
        self.refresh_processes()
        self.load_targets()
        self.load_modkey_sets()

    # Tools menu entries: (key, en, ko, command, idle_only).
    def _tools_entries(self) -> list[tuple[str, str, str, VoidCallback, bool]]:
        return [
            ("workspace", "Open workspace…", "작업 공간 열기…", self.open_profile, False),
            ("quick", "Quick events…", "빠른 이벤트…", self.open_quick_events, True),
            ("sep", "", "", lambda: None, False),
            ("modkey_edit", "Edit modifier keys…", "수정키 세트 편집…", self.open_modkeys, True),
            ("modkey_copy", "Duplicate modifier keys", "수정키 세트 복사", self.copy_modkey_set, True),
            ("modkey_delete", "Delete modifier keys", "수정키 세트 삭제", self.delete_modkey_set, True),
            ("sep", "", "", lambda: None, False),
            ("settings", "Settings…", "설정…", self.open_settings, True),
            ("clear_logs", "Clear logs", "로그 삭제", self.clear_local_logs, True),
        ]

    def _build_tools_menus(self) -> None:
        self._tools_actions.clear()
        menus = [self.tools_menu]
        if self._menubar_tools is not None:
            self._menubar_tools.setTitle(txt("Tools", "도구"))
            menus.append(self._menubar_tools)
        for menu in menus:
            menu.clear()
            for key, en, ko, command, _idle in self._tools_entries():
                if key == "sep":
                    menu.addSeparator()
                    continue
                action = menu.addAction(txt(en, ko))
                action.triggered.connect(command)
                # Both menus share enablement through the first action's key.
                self._tools_actions.setdefault(key, action)
                action.setObjectName(key)

    def _sync_tools_menus(self, running: bool) -> None:
        menus = [self.tools_menu]
        if self._menubar_tools is not None:
            menus.append(self._menubar_tools)
        idle_only = {key for key, *_rest, idle in self._tools_entries() if idle}
        for menu in menus:
            for action in menu.actions():
                if action.isSeparator():
                    continue
                action.setEnabled(not (running and action.objectName() in idle_only))

    def refresh_texts(self) -> None:
        self.lbl_process.setText(txt("Target", "대상"))
        self.lbl_target.setText(txt("Run", "실행"))
        self.edit_button.setText(txt("Edit…", "편집…"))
        self.lbl_modkeys.setText(txt("Modifier keys", "수정키"))
        self.refresh_button.setToolTip(txt("Refresh", "새로고침"))
        self.tools_button.setToolTip(txt("Tools", "도구"))
        self._build_tools_menus()
        self.load_targets(self.target())
        self.update_ui()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            # Light/dark switch: recolor the status badge and run button.
            QTimer.singleShot(0, self.update_ui)
        super().changeEvent(event)

    # ── selections ─────────────────────────────────────────────────────

    def refresh_processes(self) -> None:
        current = self.process_combo.currentText()
        current_name = current.rsplit(" (", 1)[0] if "(" in current else None
        procs = sorted(ProcessCollector.get(), key=lambda x: x[0].lower())
        self.process_combo.blockSignals(True)
        self.process_combo.clear()
        self.process_combo.addItems([f"{n} ({p})" for n, p, _ in procs])
        idx = next((i for i, (n, _, _) in enumerate(procs) if n == current_name), 0)
        if procs:
            self.process_combo.setCurrentIndex(idx)
        self.process_combo.blockSignals(False)
        self._on_selection_changed()

    def load_targets(self, select: RunTarget | None = None) -> None:
        """"실행" 콤보: 프로필, 구분선, 저장된 실행 세트."""
        profile_names, favorites = ordered_profile_names(self.profiles_dir)
        self._run_set_names = list_run_set_names(self.run_sets_path)
        wanted = select or self.target()
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        values = build_profile_display_values(profile_names, favorites)
        for name, value in zip(profile_names, values, strict=True):
            self.target_combo.addItem(ellipsize_display(value), ("profile", name))
        if self._run_set_names:
            self.target_combo.insertSeparator(self.target_combo.count())
            for name in self._run_set_names:
                self.target_combo.addItem(run_set_display(name), ("run_set", name))
        self.target_combo.blockSignals(False)
        if not self.set_target(*wanted) and not self.set_target(
            "profile", self._last_target[1] if self._last_target[0] == "profile" else ""
        ):
            self.set_target("profile", QUICK_PROFILE_NAME)

    def target(self) -> RunTarget:
        data = self.target_combo.currentData()
        if isinstance(data, tuple) and len(data) == 2:  # pyright: ignore[reportUnknownArgumentType]
            kind, name = data  # pyright: ignore[reportUnknownVariableType]
            return (str(kind), str(name))  # pyright: ignore[reportUnknownArgumentType]
        return self._last_target

    def set_target(self, kind: TargetKind, name: str) -> bool:
        for index in range(self.target_combo.count()):
            if self.target_combo.itemData(index) == (kind, name):
                self.target_combo.setCurrentIndex(index)
                self._last_target = (kind, name)
                return True
        return False

    def _on_target_changed(self, _index: int) -> None:
        self._last_target = self.target()
        self._on_selection_changed()

    def load_modkey_sets(self, select_name: str | None = None) -> None:
        ensure_default_modkey_set(self.modkey_sets_path)
        names = list_modkey_set_names(self.modkey_sets_path)
        wanted = select_name or self.modkey_combo.currentText() or DEFAULT_MODKEY_SET_NAME
        self.modkey_combo.blockSignals(True)
        self.modkey_combo.clear()
        self.modkey_combo.addItems(names)
        index = names.index(wanted) if wanted in names else 0
        if names:
            self.modkey_combo.setCurrentIndex(index)
        self.modkey_combo.blockSignals(False)
        self._on_selection_changed()

    def _on_selection_changed(self, *_args: object) -> None:
        if hasattr(self, "run"):
            QTimer.singleShot(0, self.update_ui)

    # ── RunHost ────────────────────────────────────────────────────────

    def selection(self) -> RunSelection:
        kind, name = self.target()
        if kind == "run_set":
            profile, run_set = "", name
        else:
            profile, run_set = name, CURRENT_RUN_SET_ID
        return RunSelection(
            process=self.process_combo.currentText(),
            profile=profile,
            run_set=run_set,
            modkey_set=self.modkey_combo.currentText(),
        )

    def on_run_state_changed(self) -> None:
        self.update_ui()

    def on_status_changed(self) -> None:
        self._update_status()

    def before_start(self) -> None:
        hud = self.quick_hud
        if hud is not None and hud.isVisible():
            hud.close()

    def defer(self, action: Callable[[], None]) -> None:
        QTimer.singleShot(0, action)

    def window_position(self) -> str | None:
        pos = self.pos()
        return f"{pos.x()}/{pos.y()}"

    def is_alive(self) -> bool:
        return not self._closing

    # ── settings / listeners ───────────────────────────────────────────

    def load_settings(self) -> None:
        self.run.load_settings()
        self.refresh_texts()

    def setup_event_handlers(self) -> None:
        self.run.setup_event_handlers()

    def unbind_events(self) -> None:
        self.run.unbind_events()

    @property
    def settings(self) -> UserSettings:
        return self.run.settings

    def _restore_state(self) -> None:
        state = StateUtils.load_main_app_state() or {}
        proc = state.get("process")
        if isinstance(proc, str) and proc:
            for index in range(self.process_combo.count()):
                if self.process_combo.itemText(index).startswith(proc):
                    self.process_combo.setCurrentIndex(index)
                    break
        prof = state.get("profile")
        if isinstance(prof, str) and prof:
            self.set_target("profile", prof)
        run_set = state.get("run_set")
        if isinstance(run_set, str) and run_set.strip():
            if not is_current_run_set(run_set):
                self.set_target("run_set", run_set.strip())
        else:
            migrated = migrate_legacy_run_profiles(
                state, list(self._run_set_names), self.run_sets_path
            )
            if migrated:
                self.load_targets(("run_set", migrated))
        modkey_set = state.get("modkey_set")
        if isinstance(modkey_set, str) and modkey_set:
            self.load_modkey_sets(modkey_set)
        pos = StateUtils.parse_slash_int_pair(state.get("main_pos"))
        if pos is not None:
            self.move(pos[0], pos[1])

    # ── status / run button ────────────────────────────────────────────

    def update_ui(self) -> None:
        running = self.run.is_running
        readiness = self.run.readiness()
        for widget in (self.process_combo, self.refresh_button, self.target_combo, self.modkey_combo):
            widget.setEnabled(not running)
        # 작업 공간은 실행 중에도 연다. 편집은 다음 시작부터 반영된다.
        self.edit_button.setEnabled(True)
        self._sync_tools_menus(running)

        can_press = bool(running or readiness["can_start"])
        label = (
            f"{tokens.ICON_STOP} {txt('Stop', '중지')}"
            if running
            else f"{tokens.ICON_START} {txt('Start', '시작')}"
        )
        if hotkey := self.run.hotkey_short():
            label = f"{label}  {hotkey}"
        self.run_button.setText(label)
        self.run_button.setEnabled(can_press)
        self.run_button.setStyleSheet(
            style.run_button_qss(
                "stop" if running else ("start" if can_press else "disabled")
            )
        )
        set_running = getattr(self.workspace, "set_running", None)
        if callable(set_running):
            set_running(running)
        self._update_status()

    def _update_status(self) -> None:
        """상태는 한 줄. 막혔을 때만 해결 버튼 하나를 보인다."""
        snapshot = self.run.readiness()
        running = self.run.is_running
        tone: style.StatusTone = "running" if running else snapshot["tone"]
        summary = snapshot.get("summary") or snapshot["title"]
        self.lbl_status.setText(
            f"{style.STATUS_ICONS[tone]}  {snapshot['badge_text']} · {summary}"
        )
        self.lbl_status.setStyleSheet(style.badge_qss(tone))
        hint = self.run.hotkey_hint_text()
        detail = self.run.status_detail_with_selection(snapshot["detail"])
        self.lbl_status.setToolTip(f"{detail}\n{hint}" if hint else detail)
        action = None if running else snapshot.get("action")
        self._status_action = action
        if action:
            self.btn_status_fix.setText(self._status_action_label(action))
            self.btn_status_fix.show()
        else:
            self.btn_status_fix.hide()
        self._missing_permissions = list(snapshot.get("missing_permissions", []))
        self.lbl_run_status.setText(self.run.run_dock_text(running))

    @staticmethod
    def _status_action_label(action: StatusAction) -> str:
        return {
            "permissions": txt("Open settings", "권한 설정 열기"),
            "process": txt("Refresh", "새로고침"),
        }.get(action, txt("Open workspace", "작업 공간에서 보기"))

    def _on_status_fix(self) -> None:
        action = self._status_action
        if action == "permissions":
            if self._missing_permissions:
                self._open_macos_permission_setting(self._missing_permissions[0])
        elif action == "process":
            self.refresh_processes()
        elif action == "workspace":
            self.open_profile()

    def _open_macos_permission_setting(self, permission: str) -> None:
        if PermissionUtils.open_macos_permission_settings(permission):
            return
        QMessageBox.information(
            self,
            txt("Open Settings", "설정 열기"),
            txt(
                "Open macOS System Settings and grant this executable the required permission.",
                "macOS 시스템 설정을 열어 이 실행 파일에 필요한 권한을 허용하세요.",
            ),
        )

    def _on_run_clicked(self) -> None:
        self.toggle_start_stop()

    def toggle_start_stop(self) -> None:
        self.run.toggle_start_stop()

    # ── tools ──────────────────────────────────────────────────────────

    def open_profile(self) -> None:
        """작업 공간을 연다. 모달이 아니며 실행 중에도 편집할 수 있다."""
        self.open_workspace_for(self.target())

    def open_workspace_for(self, target: RunTarget) -> None:
        """"편집…": 실행 콤보에서 고른 프로필이나 실행 세트로 연다(M-06)."""
        from app.ui.qt.workspace import open_workspace

        kind, name = target
        open_workspace(self, kind=kind, name=name)

    def open_quick_events(self) -> None:
        if self.run.is_running:
            return
        from app.ui.qt.capture_hud import open_quick_capture

        open_quick_capture(self)

    def open_settings(self) -> None:
        from app.ui.qt.settings_dialog import open_settings

        open_settings(self)

    def open_modkeys(self) -> None:
        if self.run.is_running:
            return
        set_name = self.modkey_combo.currentText()
        if not set_name:
            return
        from app.ui.qt.modkeys_dialog import edit_modkey_set

        edit_modkey_set(self, set_name, self.modkey_sets_path)
        self._update_status()

    def reload_targets(self, new_name: str | None = None) -> None:
        """작업 공간에서 프로필·실행 세트가 바뀌면 실행 콤보를 다시 읽는다.
        고른 프로필이 사라졌을 때만(이름 변경) 새 이름으로 옮긴다."""
        kind, name = self.target()
        if kind == "profile" and new_name and name not in list_profile_names(self.profiles_dir):
            name = new_name
        if kind == "run_set" and name not in list_run_set_names(self.run_sets_path):
            kind, name = "profile", self._last_target[1] if self._last_target[0] == "profile" else QUICK_PROFILE_NAME
        self.load_targets((kind, name))
        self.update_ui()

    def follow_renamed_run_set(self, old: str, new: str) -> None:
        """고른 실행 세트의 이름이 바뀌면 새 이름을 계속 고른다."""
        if self.target() == ("run_set", old):
            self.load_targets(("run_set", new))

    def copy_modkey_set(self) -> None:
        curr = self.modkey_combo.currentText()
        if not curr:
            return
        dst_name = f"{curr} - Copied"
        if dst_name in list_modkey_set_names(self.modkey_sets_path):
            QMessageBox.warning(
                self,
                txt("Warning", "경고"),
                txt(
                    "Modifier key set '{name}' already exists.",
                    "수정키 세트 '{name}'이(가) 이미 존재합니다.",
                    name=dst_name,
                ),
            )
            return
        try:
            copy_modkey_set(curr, dst_name, self.modkey_sets_path)
            self.load_modkey_sets(dst_name)
            QMessageBox.information(
                self,
                txt("Modifier Key Set Copied", "수정키 세트 복사 완료"),
                txt(
                    "Copied '{src}' to '{dst}' and selected it.",
                    "'{src}' 세트를 '{dst}'(으)로 복사하고 선택했습니다.",
                    src=curr,
                    dst=dst_name,
                ),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                txt("Error", "오류"),
                txt("Copy failed: {error}", "복사 실패: {error}", error=e),
            )
        self._update_status()

    def delete_modkey_set(self) -> None:
        curr = self.modkey_combo.currentText()
        if not curr:
            return
        if self.modkey_combo.count() <= 1:
            QMessageBox.information(
                self,
                txt("Info", "안내"),
                txt(
                    "The last modifier key set cannot be deleted.",
                    "마지막 수정키 세트는 삭제할 수 없습니다.",
                ),
            )
            return
        answer = QMessageBox.question(
            self,
            txt("Warning", "경고"),
            txt(
                "Delete modifier key set '{name}'?",
                "수정키 세트 '{name}'을(를) 삭제하시겠습니까?",
                name=curr,
            ),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        try:
            next_name = delete_modkey_set(curr, self.modkey_sets_path)
            self.load_modkey_sets(next_name)
            QMessageBox.information(
                self,
                txt("Modifier Key Set Deleted", "수정키 세트 삭제 완료"),
                txt("Deleted '{name}'.", "'{name}' 세트를 삭제했습니다.", name=curr),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                txt("Error", "오류"),
                txt("Delete failed: {error}", "삭제 실패: {error}", error=e),
            )
        self._update_status()

    def clear_local_logs(self) -> None:
        answer = QMessageBox.question(
            self,
            txt("Confirm", "확인"),
            txt("Delete old log files?", "오래된 로그 파일을 삭제하시겠습니까?"),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        deleted_size, count = 0, 0
        log_dir = Path("logs")
        if log_dir.exists():
            for p in log_dir.glob("*"):
                if p.name != "keysym.log" and p.is_file():
                    try:
                        deleted_size += p.stat().st_size
                        p.unlink()
                        count += 1
                    except Exception as e:
                        logger.warning(f"Del failed {p}: {e}")
        if count:
            logger.info(
                "Cleared {count} old log files ({size:.2f} MB)",
                count=count,
                size=deleted_size / 1048576,
            )
        else:
            logger.info("No old log files to clear")
        self.lbl_run_status.setText(
            txt(
                "Cleared {count} old log file(s).",
                "오래된 로그 {count}개 삭제했습니다.",
                count=count,
            )
            if count
            else txt("No old logs to clear.", "정리할 오래된 로그가 없습니다.")
        )

    # ── shutdown ───────────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closing:
            self._closing = True
            logger.info("Shutting down...")
            for child in (self.quick_hud, self.workspace, self.settings_dialog):
                if child is not None:
                    child.close()
            self.run.shutdown()
            close = getattr(self.sound_player, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        event.accept()
