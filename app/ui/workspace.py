"""작업 공간 창: 프로필·실행 세트 관리와 이벤트 편집을 한 창에서 한다.

모달이 아니어서 게임 창과 번갈아 쓸 수 있다. 실행은 시작 시점에 불러온
프로필을 쓰므로, 실행 중 편집은 다음 시작부터 반영된다. 상태와 동작은
`WorkspaceModel`이 맡고 이 창은 표시와 입력 전달만 한다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from loguru import logger
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.capture_geometry import CaptureResult
from app.domain.models import EventModel, UserSettings
from app.domain.profile_events import EventSection
from app.presenters.workspace_model import WorkspaceError, WorkspaceModel
from app.presenters.workspace_sidebar import ItemKind
from app.storage.app_state import StateUtils
from app.storage.profile_display import QUICK_PROFILE_NAME
from app.ui import tokens
from app.ui import style
from app.ui.workspace_detail import PANEL_WIDTH, EventDetailPanel
from app.ui.workspace_panels import (
    GraphView,
    ProfileHeader,
    RunSetEditor,
    RuntimeToggleBox,
    WorkspaceSidebar,
)
from app.ui.workspace_tree import EventTree
from app.utils.i18n import txt

if TYPE_CHECKING:
    from app.ui.capture_hud import CaptureHud

WORKSPACE_DEFAULT_SIZE = (1180, 720)
WORKSPACE_MIN_SIZE = (980, 600)
STATUS_CLEAR_MS = 6000
SIDEBAR_WIDTH = 210


class _RunState(Protocol):
    is_running: bool


class WorkspaceHost(Protocol):
    """작업 공간을 여는 실행 창(`RunWindow`)이 주는 것."""

    workspace: QWidget | None
    profiles_dir: Path
    run_sets_path: Path

    @property
    def run(self) -> _RunState: ...
    @property
    def settings(self) -> UserSettings: ...
    def reload_targets(self, new_name: str | None = None) -> None: ...
    def follow_renamed_run_set(self, old: str, new: str) -> None: ...
    def update_ui(self) -> None: ...


def profiles_dir_cache(profiles_dir: Path) -> Path:
    return profiles_dir / "_graphs"


class WorkspaceWindow(QMainWindow):
    def __init__(self, host: WorkspaceHost, *, kind: str, name: str) -> None:
        # 부모 없이 띄운다: 실행 창 위에 붙어 있지 않고(topmost 아님) 따로 움직인다.
        super().__init__(None)
        self.host = host
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumSize(*WORKSPACE_MIN_SIZE)
        self._closed = False
        self._quitting = False
        self._running = False
        self._options_open = False
        self.new_signal_hud: CaptureHud | None = None
        self.model = WorkspaceModel(
            self,
            profiles_dir=host.profiles_dir,
            run_sets_path=host.run_sets_path,
            scheduler=self._schedule,
            running_getter=lambda: bool(host.run.is_running),
            settings_getter=lambda: host.settings,
            on_catalog_changed=host.reload_targets,
            on_run_set_renamed=host.follow_renamed_run_set,
        )
        self._build()
        self._bind_keys()
        self._restore_geometry()
        self.on_catalog_changed()
        item_kind: ItemKind = "run_set" if kind == "run_set" else "profile"
        self.model.open_item(item_kind, name or QUICK_PROFILE_NAME)
        self.set_running(bool(host.run.is_running))

    # ── layout ─────────────────────────────────────────────────────────

    def _build(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QWidget()
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(tokens.SPACE_3, tokens.SPACE_2, tokens.SPACE_3, 0)
        self.header = ProfileHeader(
            on_name=self.model.set_profile_name,
            on_favorite=self.model.set_favorite,
            validate=self.model.profile_name_problem,
        )
        self.lbl_run_set_title = QLabel()
        font = self.lbl_run_set_title.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() + 2)
        self.lbl_run_set_title.setFont(font)
        top_row.addWidget(self.header)
        top_row.addWidget(self.lbl_run_set_title)
        top_row.addStretch(1)
        self.lbl_running = QLabel(
            txt(
                "{icon} Running — edits apply from the next start",
                "{icon} 실행 중 — 편집 내용은 다음 시작부터 반영됩니다",
                icon=tokens.STATUS_RUNNING_ICON,
            )
        )
        self.lbl_running.setStyleSheet(style.badge_qss("running"))
        self.lbl_running.hide()
        top_row.addWidget(self.lbl_running)
        root.addWidget(top)

        self.options_bar = QWidget()
        options = QVBoxLayout(self.options_bar)
        options.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, tokens.SPACE_1)
        options.setSpacing(tokens.SPACE_1)
        self.btn_options = QToolButton()
        self.btn_options.setAutoRaise(True)
        self.btn_options.clicked.connect(self._toggle_options)
        options.addWidget(self.btn_options, 0, Qt.AlignmentFlag.AlignLeft)
        self.toggle_box = RuntimeToggleBox(on_change=self._on_toggle_changed)
        self.toggle_box.hide()
        options.addWidget(self.toggle_box)
        root.addWidget(self.options_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.sidebar = WorkspaceSidebar(
            on_select=self._on_sidebar_select,
            on_action=self._on_sidebar_action,
            on_new=self._on_sidebar_new,
        )
        self.sidebar.setMinimumWidth(170)
        self.splitter.addWidget(self.sidebar)

        self.center = QStackedWidget()
        self.profile_view = QWidget()
        profile_box = QVBoxLayout(self.profile_view)
        profile_box.setContentsMargins(
            tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, 0
        )
        toolbar = QHBoxLayout()
        self.entry_search = QLineEdit()
        self.entry_search.setPlaceholderText(
            f"{tokens.ICON_SEARCH} {txt('Search', '검색')}"
        )
        self.entry_search.setClearButtonEnabled(True)
        self.entry_search.setMaximumWidth(220)
        self.entry_search.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.entry_search)
        toolbar.addStretch(1)
        self.btn_sort = QPushButton(txt("Sort by name", "이름순 정렬"))
        self.btn_sort.clicked.connect(self.model.sort_by_name)
        self.btn_add_signal = QPushButton(txt("＋ Signal", "＋ 신호"))
        self.btn_add_signal.clicked.connect(self.add_signal)
        self.btn_add_rule = QPushButton(txt("＋ Rule", "＋ 규칙"))
        self.btn_add_rule.clicked.connect(self.add_rule)
        for button in (self.btn_sort, self.btn_add_signal, self.btn_add_rule):
            button.setAutoDefault(False)
            toolbar.addWidget(button)
        profile_box.addLayout(toolbar)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tree = EventTree(
            on_select=self._on_tree_select,
            on_move=self.model.move_event,
            on_context=self._on_list_context,
            on_delete=self.delete_selected,
            on_copy=self.copy_selected,
            on_activate=self._focus_name,
            on_drop_rejected=lambda: self.on_status(
                txt(
                    "Drag within the same section (and clear the search first).",
                    "같은 묶음 안에서만 옮길 수 있습니다(검색 중에는 옮길 수 없습니다).",
                )
            ),
        )
        self.graph = GraphView(profiles_dir_cache(self.model.profiles_dir))
        self.tabs.addTab(self.tree, txt("List", "목록"))
        self.tabs.addTab(self.graph, txt("Graph", "그래프"))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        profile_box.addWidget(self.tabs, 1)
        self.center.addWidget(self.profile_view)

        self.run_set_view = RunSetEditor(
            on_members_changed=self.model.set_run_set_members,
            on_rename=self._rename_current_run_set,
        )
        self.center.addWidget(self.run_set_view)
        self.splitter.addWidget(self.center)

        self.detail = EventDetailPanel(
            self.model,
            running_getter=self.model.running_getter,
            selection_getter=self.tree.selected_events,
        )
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        width = WORKSPACE_DEFAULT_SIZE[0]
        self.splitter.setSizes(
            [SIDEBAR_WIDTH, width - SIDEBAR_WIDTH - PANEL_WIDTH, PANEL_WIDTH]
        )
        root.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        status = self.statusBar()
        status.setSizeGripEnabled(True)
        self.lbl_save = QLabel()
        status.addWidget(self.lbl_save)
        self.lbl_status = QLabel()
        style.caption(self.lbl_status)
        status.addWidget(self.lbl_status)
        self.btn_undo = QPushButton(txt("Undo", "되돌리기"))
        self.btn_undo.setAutoDefault(False)
        self.btn_undo.clicked.connect(self.undo)
        status.addWidget(self.btn_undo)
        self.lbl_counts = QLabel()
        status.addPermanentWidget(self.lbl_counts)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._clear_status)

    def _bind_keys(self) -> None:
        # 입력칸에 포커스가 있으면 입력칸이 ⌘Z를 먼저 받는다(Tk와 같다).
        undo = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        undo.activated.connect(self.undo)
        find = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        find.activated.connect(self._focus_search)
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.activated.connect(self._on_escape)

    # ── scheduler (model autosave) ─────────────────────────────────────

    def _schedule(
        self, delay_ms: int, action: Callable[[], object]
    ) -> Callable[[], None]:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(action)
        timer.timeout.connect(timer.deleteLater)
        timer.start(delay_ms)

        def cancel() -> None:
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                pass  # already fired and deleted

        return cancel

    # ── WorkspaceView ──────────────────────────────────────────────────

    def on_opened(self) -> None:
        model = self.model
        if model.mode == "profile":
            self.lbl_run_set_title.hide()
            self.header.show()
            self.header.load(
                model.prof_name, model.favorite_draft, locked=model.name_locked
            )
            self.toggle_box.load(model.profile)
            self.options_bar.show()
            self._sync_options_label()
            self.center.setCurrentWidget(self.profile_view)
            self.detail.show()
            self.entry_search.blockSignals(True)
            self.entry_search.clear()
            self.entry_search.blockSignals(False)
            self.tree.query = ""
            self.tree.set_events(
                model.profile.event_list,
                toggle_enabled=bool(model.profile.runtime_toggle_enabled),
                keep_selection=False,
            )
            self.detail.show_events([])
            self._refresh_chrome()
            self._refresh_graph_if_visible()
        else:
            self.header.hide()
            self.lbl_run_set_title.setText(
                txt("Run set · {n}", "실행 세트 · {n}", n=model.run_set_name)
            )
            self.lbl_run_set_title.show()
            self.options_bar.hide()
            self.detail.hide()
            self.run_set_view.load(
                model.run_set_name, model.run_set_members, model.all_profiles()
            )
            self.center.setCurrentWidget(self.run_set_view)
            self.lbl_counts.setText("")
            self.btn_undo.hide()
            self.setWindowTitle(
                f"{txt('Workspace', '작업 공간')} - {model.run_set_name}"
            )
        self.sidebar.mark_current(model.current_item())

    def on_events_changed(self, select: list[EventModel] | None) -> None:
        model = self.model
        if select:
            # 새로 넣은 이벤트가 검색에 가려지지 않게 한다.
            self.entry_search.blockSignals(True)
            self.entry_search.clear()
            self.entry_search.blockSignals(False)
            self.tree.query = ""
        self.tree.set_events(
            model.profile.event_list,
            toggle_enabled=bool(model.profile.runtime_toggle_enabled),
            keep_selection=select is None,
        )
        if select:
            self.tree.select(select)
        self._sync_options_label()
        self._refresh_chrome()

    def on_catalog_changed(self) -> None:
        profiles, favorites, run_sets = self.model.catalog()
        current = (
            self.model.current_item()
            if self.model.prof_name or self.model.run_set_name
            else None
        )
        self.sidebar.set_items(profiles, favorites, run_sets, current)

    def on_save_state_changed(self) -> None:
        state = self.model.save_state
        if state == "saving":
            self.lbl_save.setText(txt("Saving…", "저장 중…"))
            self.lbl_save.setStyleSheet(style.badge_qss("warn"))
        elif state == "saved":
            self.lbl_save.setText(txt("Saved {t}", "저장됨 {t}", t=self.model.saved_at))
            self.lbl_save.setStyleSheet(style.badge_qss("ready"))
            if self.model.mode == "profile":
                self.setWindowTitle(
                    f"{txt('Workspace', '작업 공간')} - {self.model.prof_name}"
                )
                self._refresh_graph_if_visible()
        else:
            self.lbl_save.setText(txt("Save failed", "저장 실패"))
            self.lbl_save.setStyleSheet(style.badge_qss("error"))
            self._status_timer.stop()
            self.lbl_status.setText(self.model.save_detail)
            self.lbl_status.setStyleSheet(f"color: {style.status_colors('error')[1]};")

    def on_status(self, text: str) -> None:
        style.caption(self.lbl_status)
        self.lbl_status.setText(text)
        self._status_timer.start(STATUS_CLEAR_MS)

    def _clear_status(self) -> None:
        self.lbl_status.setText("")

    def show_error(self, message: str) -> None:
        if self._quitting:
            logger.warning(f"Workspace not saved on quit: {message}")
            return
        QMessageBox.warning(self, txt("Error", "오류"), message)

    def close_for_quit(self) -> None:
        """시그널 종료: 저장을 시도하되 실패해도 묻지 않고 닫는다."""
        self._quitting = True
        self.close()

    def commit_pending_edits(self) -> None:
        self.header.commit()
        self.detail.commit_name()

    # ── chrome ─────────────────────────────────────────────────────────

    def _refresh_chrome(self) -> None:
        model = self.model
        self.lbl_counts.setText(model.counts_text())
        label = model.undo_label
        self.btn_undo.show()
        self.btn_undo.setEnabled(label is not None)
        self.btn_undo.setText(
            txt("Undo: {l}", "되돌리기: {l}", l=label)
            if label
            else txt("Undo", "되돌리기")
        )
        self.setWindowTitle(f"{txt('Workspace', '작업 공간')} - {model.prof_name}")

    def _sync_options_label(self) -> None:
        mark = tokens.ICON_EXPANDED if self._options_open else tokens.ICON_COLLAPSED
        state = (
            txt("hotkey on/off: on", "단축키로 켜고 끄기: 사용")
            if self.model.profile.runtime_toggle_enabled
            else txt("hotkey on/off: off", "단축키로 켜고 끄기: 안 씀")
        )
        self.btn_options.setText(f"{mark} {txt('Run options', '실행 옵션')} · {state}")

    def _toggle_options(self) -> None:
        self._options_open = not self._options_open
        self.toggle_box.setVisible(self._options_open)
        self._sync_options_label()

    def _on_toggle_changed(self, enabled: bool, key: str | None) -> None:
        self.model.set_runtime_toggle(enabled, key)
        self._sync_options_label()

    def _on_tab_changed(self, _index: int) -> None:
        self._refresh_graph_if_visible()

    def _refresh_graph_if_visible(self) -> None:
        if self._closed or self.model.mode != "profile":
            return
        if self.tabs.currentWidget() is self.graph:
            self.graph.show_profile(self.model.profile, self.model.prof_name)

    # ── running policy ─────────────────────────────────────────────────

    def set_running(self, running: bool) -> None:
        if self._closed:
            return
        self._running = running
        self.lbl_running.setVisible(running)
        self.header.set_locked(self.model.name_locked)

    # ── sidebar ────────────────────────────────────────────────────────

    def _ask_name(self, title: str, initial: str) -> str | None:
        value, ok = QInputDialog.getText(
            self, title, txt("Name:", "이름:"), QLineEdit.EchoMode.Normal, initial
        )
        if not ok:
            return None
        value = value.strip()
        return value or None

    def _confirm(self, title: str, message: str) -> bool:
        answer = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Ok

    def _on_sidebar_select(self, kind: ItemKind, name: str) -> None:
        if kind == "profile":
            self.model.open_profile(name)
        else:
            self.model.open_run_set(name)

    def _on_sidebar_new(self, kind: ItemKind) -> None:
        title = (
            txt("New profile", "새 프로필")
            if kind == "profile"
            else txt("New run set", "새 실행 세트")
        )
        name = self._ask_name(title, self.model.default_new_name(kind))
        if name is None:
            return
        try:
            if kind == "profile":
                self.model.new_profile(name)
            else:
                self.model.new_run_set(name)
        except WorkspaceError as exc:
            self.show_error(str(exc))

    def _on_sidebar_action(self, kind: ItemKind, action: str, name: str) -> None:
        try:
            if kind == "profile":
                self._profile_action(action, name)
            else:
                self._run_set_action(action, name)
        except Exception as exc:
            self.show_error(str(exc))

    def _profile_action(self, action: str, name: str) -> None:
        model = self.model
        if action == "copy":
            model.copy_profile_item(name)
        elif action == "favorite":
            model.toggle_favorite(name)
            if model.mode == "profile" and name == model.prof_name:
                self.header.load(
                    model.prof_name, model.favorite_draft, locked=model.name_locked
                )
        elif action == "rename":
            if name == QUICK_PROFILE_NAME:
                return
            model.guard_running()
            new = self._ask_name(txt("Rename profile", "프로필 이름 바꾸기"), name)
            if new is None or new == name:
                return
            model.rename_profile(name, new)
        elif action == "delete":
            if name == QUICK_PROFILE_NAME:
                return
            model.guard_running()
            if self._confirm(
                txt("Delete profile", "프로필 삭제"),
                txt("Delete profile '{n}'?", "프로필 '{n}'을(를) 삭제할까요?", n=name),
            ):
                model.delete_profile(name)

    def _run_set_action(self, action: str, name: str) -> None:
        model = self.model
        if action == "copy":
            model.copy_run_set_item(name)
            return
        model.guard_running()
        if action == "rename":
            new = self._ask_name(txt("Rename run set", "실행 세트 이름 바꾸기"), name)
            if new is None or new == name:
                return
            model.rename_run_set_item(name, new)
        elif action == "delete":
            if self._confirm(
                txt("Delete run set", "실행 세트 삭제"),
                txt(
                    "Delete run set '{n}'?", "실행 세트 '{n}'을(를) 삭제할까요?", n=name
                ),
            ):
                model.delete_run_set_item(name)

    def _rename_current_run_set(self, new: str) -> None:
        old = self.model.run_set_name
        try:
            self.model.rename_current_run_set(new)
        except WorkspaceError as exc:
            self.run_set_view.entry_name.setText(old)
            self.show_error(str(exc))

    # ── list ───────────────────────────────────────────────────────────

    def _on_search_changed(self, text: str) -> None:
        self.tree.set_query(text)

    def _focus_search(self) -> None:
        if self.model.mode == "profile":
            self.entry_search.setFocus()
            self.entry_search.selectAll()

    def _on_escape(self) -> None:
        """검색어가 있으면 먼저 지우고, 없으면 창을 닫는다."""
        if self.entry_search.hasFocus() and self.entry_search.text():
            self.entry_search.clear()
            return
        self.close()

    def _on_tree_select(self, events: list[EventModel]) -> None:
        self.detail.show_events(events)

    def _focus_name(self) -> None:
        if self.detail.current is not None:
            self.detail.entry_name.setFocus()
            self.detail.entry_name.selectAll()

    def add_rule(self) -> None:
        self.model.add_rule()
        self._focus_name()

    def add_signal(self) -> None:
        hud = self.new_signal_hud
        if hud is not None and hud.is_open():
            return  # 이미 열린 HUD를 쓴다(HUD 참조에는 is_open/close만 부른다)
        from app.ui.capture_hud import CaptureHud

        name = self.model.next_signal_name()
        state = {"name": name}

        def on_name(new: str) -> None:
            state["name"] = new

        def on_apply(result: CaptureResult) -> None:
            self.model.add_signal(state["name"], result, fallback=name)

        def on_close() -> None:
            self.new_signal_hud = None

        self.new_signal_hud = CaptureHud(
            self,
            mode="single",
            name=name,
            on_name_change=on_name,
            on_apply=on_apply,
            grab=True,
            border=not self.model.running_getter(),
            on_close=on_close,
        )

    def copy_selected(self) -> None:
        self.model.copy_events(self.tree.selected_events())

    def delete_selected(self) -> None:
        self.model.delete_events(self.tree.selected_events())

    def undo(self) -> None:
        self.model.undo()

    def _on_list_context(
        self, pos: QPoint, selected: list[EventModel], section: EventSection | None
    ) -> None:
        menu = QMenu(self)
        if section is not None:
            if section.kind != "group":
                return
            group = section.group
            menu.addAction(
                txt("Rename group…", "그룹 이름 바꾸기…"),
                lambda: self.rename_group(group),
            )
            menu.addAction(
                txt("Ungroup", "그룹 해제"), lambda: self.model.clear_group(group)
            )
        elif selected:
            menu.addAction(txt("Duplicate", "복사"), self.copy_selected)
            copy_menu = menu.addMenu(txt("Copy to profile", "다른 프로필로 복사"))
            for name in self.model.all_profiles():
                if name != self.model.prof_name:
                    copy_menu.addAction(name, lambda n=name: self.copy_to_profile(n))
            if len(selected) == 1 and selected[0].clicked_position is not None:
                source = selected[0]
                menu.addAction(
                    txt(
                        "Apply target to same-area events",
                        "같은 위치 이벤트에 대상 적용",
                    ),
                    lambda: self.model.apply_target(source),
                )
            menu.addSeparator()
            menu.addAction(txt("Delete", "삭제"), self.delete_selected)
        else:
            return
        menu.exec(pos)

    def rename_group(self, old: str) -> None:
        new = self._ask_name(txt("Rename group", "그룹 이름 바꾸기"), old)
        if new is None:
            return
        try:
            self.model.rename_group(old, new)
        except WorkspaceError as exc:
            self.show_error(str(exc))

    def copy_to_profile(self, target: str) -> None:
        try:
            self.model.copy_to_profile(target, self.tree.selected_events())
        except WorkspaceError as exc:
            self.show_error(str(exc))

    # ── lifecycle ──────────────────────────────────────────────────────

    def select_item(self, kind: str, name: str) -> None:
        if self._closed:
            return
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        item_kind: ItemKind = "run_set" if kind == "run_set" else "profile"
        self.model.open_item(item_kind, name)

    def is_open(self) -> bool:
        return not self._closed

    def _restore_geometry(self) -> None:
        self.resize(*WORKSPACE_DEFAULT_SIZE)
        state = StateUtils.load_main_app_state() or {}
        pos = StateUtils.parse_slash_int_pair(state.get("workspace_pos"))
        size = StateUtils.parse_slash_int_pair(state.get("workspace_size"))
        if pos is not None and size is not None:
            width = max(size[0], WORKSPACE_MIN_SIZE[0])
            height = max(size[1], WORKSPACE_MIN_SIZE[1])
            # 저장된 위치가 지금 화면 밖이면(모니터 분리 등) 가운데에 둔다.
            title_bar = QPoint(pos[0] + width // 2, pos[1] + 10)
            if any(
                s.availableGeometry().contains(title_bar)
                for s in QGuiApplication.screens()
            ):
                self.resize(width, height)
                self.move(pos[0], pos[1])
                return
            self.resize(width, height)
        self._center()

    def _center(self) -> None:
        area: QRect = QGuiApplication.primaryScreen().availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        self.move(frame.topLeft())

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closed:
            event.accept()
            return
        if not self.model.close() and not self._quitting:
            event.ignore()
            return
        self._closed = True
        self.toggle_box.stop_capture()
        for hud in (self.detail.capture_hud, self.new_signal_hud):
            if hud is not None and hud.is_open():
                hud.close()
        pos = self.pos()
        StateUtils.save_main_app_state(
            workspace_pos=f"{pos.x()}/{pos.y()}",
            workspace_size=f"{self.width()}/{self.height()}",
        )
        event.accept()
        host = self.host
        if host.workspace is self:
            host.workspace = None
        host.reload_targets(None)


def open_workspace(parent: QWidget, *, kind: str, name: str) -> None:
    """실행 창의 "편집…"·작업 공간 열기. 이미 열려 있으면 그 창에서 고른다."""
    host = cast(WorkspaceHost, parent)
    existing = host.workspace
    if isinstance(existing, WorkspaceWindow) and existing.is_open():
        existing.select_item(kind, name)
        return
    window = WorkspaceWindow(host, kind=kind, name=name)
    host.workspace = window
    window.show()
    window.raise_()
    window.activateWindow()
