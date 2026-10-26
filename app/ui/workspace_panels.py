"""작업 공간의 사이드바, 프로필 헤더, 실행 옵션(단축키 묶음), 실행 세트 편집, 그래프."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QKeySequence, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import ProfileModel
from app.domain.runtime_toggle import (
    display_runtime_toggle_trigger,
    normalize_runtime_toggle_capture_key,
    normalize_runtime_toggle_trigger,
    normalize_runtime_toggle_wheel_event,
)
from app.presenters.workspace_sidebar import ItemKind, sidebar_actions
from app.ui import tokens
from app.ui.event_graph import ensure_profile_graph_image
from app.ui import style
from app.utils.i18n import txt

# Renaming a profile renames its file, so typing waits for a pause.
NAME_COMMIT_DELAY_MS = 700
_ITEM_ROLE = Qt.ItemDataRole.UserRole + 1


def _error_style() -> str:
    return f"color: {style.status_colors('error')[1]};"


# ── sidebar ────────────────────────────────────────────────────────────


class WorkspaceSidebar(QWidget):
    """프로필과 실행 세트 목록. 우클릭으로 이름 바꾸기·복사·삭제."""

    def __init__(
        self,
        *,
        on_select: Callable[[ItemKind, str], None],
        on_action: Callable[[ItemKind, str, str], None],
        on_new: Callable[[ItemKind], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_select = on_select
        self.on_action = on_action
        self._syncing = False
        self._current: tuple[ItemKind, str] | None = None
        box = QVBoxLayout(self)
        box.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, 0, tokens.SPACE_2)
        box.setSpacing(tokens.SPACE_2)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(10)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.roots: dict[ItemKind, QTreeWidgetItem] = {}
        labels: tuple[tuple[ItemKind, str], ...] = (
            ("profile", txt("Profiles", "프로필")),
            ("run_set", txt("Run sets", "실행 세트")),
        )
        for kind, label in labels:
            root = QTreeWidgetItem([label])
            root.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = root.font(0)
            font.setBold(True)
            root.setFont(0, font)
            self.tree.addTopLevelItem(root)
            root.setExpanded(True)
            self.roots[kind] = root
        box.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        self.btn_new_profile = QPushButton(txt("＋ Profile", "＋ 프로필"))
        self.btn_new_profile.clicked.connect(lambda: on_new("profile"))
        self.btn_new_run_set = QPushButton(txt("＋ Run set", "＋ 실행 세트"))
        self.btn_new_run_set.clicked.connect(lambda: on_new("run_set"))
        for button in (self.btn_new_profile, self.btn_new_run_set):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        buttons.addStretch(1)
        box.addLayout(buttons)

    def set_items(
        self,
        profiles: Sequence[str],
        favorites: set[str],
        run_sets: Sequence[str],
        current: tuple[ItemKind, str] | None,
    ) -> None:
        self._syncing = True
        try:
            for root in self.roots.values():
                root.takeChildren()
            for name in profiles:
                fav = name in favorites
                item = QTreeWidgetItem(
                    [f"{tokens.ICON_FAVORITE} {name}" if fav else name]
                )
                item.setData(0, _ITEM_ROLE, ("profile", name))
                if fav:
                    font = item.font(0)
                    font.setBold(True)
                    item.setFont(0, font)
                self.roots["profile"].addChild(item)
            for name in run_sets:
                item = QTreeWidgetItem([name])
                item.setData(0, _ITEM_ROLE, ("run_set", name))
                self.roots["run_set"].addChild(item)
            self.mark_current(current)
        finally:
            self._syncing = False

    def item_for(self, kind: ItemKind, name: str) -> QTreeWidgetItem | None:
        root = self.roots[kind]
        for index in range(root.childCount()):
            child = root.child(index)
            if child is not None and child.data(0, _ITEM_ROLE) == (kind, name):
                return child
        return None

    def names(self, kind: ItemKind) -> list[str]:
        root = self.roots[kind]
        out: list[str] = []
        for index in range(root.childCount()):
            parsed = self._parse(root.child(index))
            if parsed is not None:
                out.append(parsed[1])
        return out

    def mark_current(self, current: tuple[ItemKind, str] | None) -> None:
        was = self._syncing
        self._syncing = True
        try:
            self._current = current
            self.tree.clearSelection()
            if current is None:
                return
            item = self.item_for(*current)
            if item is not None:
                item.setSelected(True)
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
        finally:
            self._syncing = was

    @staticmethod
    def _parse(item: QTreeWidgetItem | None) -> tuple[ItemKind, str] | None:
        if item is None:
            return None
        data: object = item.data(0, _ITEM_ROLE)
        if not isinstance(data, tuple) or len(data) != 2:  # pyright: ignore[reportUnknownArgumentType]
            return None
        kind, name = data  # pyright: ignore[reportUnknownVariableType]
        if kind == "profile":
            return ("profile", str(name))  # pyright: ignore[reportUnknownArgumentType]
        if kind == "run_set":
            return ("run_set", str(name))  # pyright: ignore[reportUnknownArgumentType]
        return None

    def _on_selection_changed(self) -> None:
        if self._syncing:
            return
        items = self.tree.selectedItems()
        parsed = self._parse(items[0]) if items else None
        if parsed is None or parsed == self._current:
            return
        self.on_select(*parsed)

    def _on_context(self, pos: QPoint) -> None:
        parsed = self._parse(self.tree.itemAt(pos))
        if parsed is None:
            return
        kind, name = parsed
        menu = QMenu(self)
        for action, label in sidebar_actions(kind, name):
            item = menu.addAction(label)
            item.setObjectName(action)
            item.triggered.connect(
                lambda _checked=False, a=action: self.on_action(kind, a, name)
            )
        menu.exec(self.tree.viewport().mapToGlobal(pos))


# ── profile header ─────────────────────────────────────────────────────


class ProfileHeader(QWidget):
    """프로필 이름(입력이 멈추면 저장)과 즐겨찾기."""

    def __init__(
        self,
        *,
        on_name: Callable[[str], None],
        on_favorite: Callable[[bool], None],
        validate: Callable[[str], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_name = on_name
        self.on_favorite = on_favorite
        self.validate = validate
        self._committed = ""
        self._syncing = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(txt("Profile Name:", "프로필 이름:")))
        self.entry = QLineEdit()
        self.entry.setMinimumWidth(200)
        self.entry.textEdited.connect(self._on_typed)
        self.entry.editingFinished.connect(self.commit)
        row.addWidget(self.entry)
        self.chk_favorite = QCheckBox(txt("Favorite", "즐겨찾기"))
        self.chk_favorite.toggled.connect(self._on_favorite)
        row.addWidget(self.chk_favorite)
        self.lbl_warn = QLabel()
        self.lbl_warn.setStyleSheet(_error_style())
        row.addWidget(self.lbl_warn)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(NAME_COMMIT_DELAY_MS)
        self.timer.timeout.connect(self.commit)

    def load(self, name: str, favorite: bool, *, locked: bool) -> None:
        self._syncing = True
        try:
            self.timer.stop()
            self._committed = name
            self.entry.setText(name)
            self.chk_favorite.setChecked(favorite)
            self.lbl_warn.setText("")
            self.set_locked(locked)
        finally:
            self._syncing = False

    def set_locked(self, locked: bool) -> None:
        self.entry.setEnabled(not locked)

    def _on_typed(self, text: str) -> None:
        """검사는 바로 보이고 저장은 입력이 멈춘 뒤에 한다."""
        self.lbl_warn.setText(self.validate(text))
        self.timer.start()

    def commit(self) -> None:
        self.timer.stop()
        if self._syncing:
            return
        typed = self.entry.text()
        if typed == self._committed:
            return
        self._committed = typed
        self.lbl_warn.setText(self.validate(typed))
        self.on_name(typed)

    def _on_favorite(self, checked: bool) -> None:
        if not self._syncing:
            self.on_favorite(checked)


# ── run options: hotkey set ────────────────────────────────────────────


class RuntimeToggleBox(QGroupBox):
    """단축키 묶음 사용 여부와 켜고 끄는 단축키(키·마우스 휠)."""

    def __init__(
        self,
        *,
        on_change: Callable[[bool, str | None], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(txt("Hotkey set", "단축키 묶음"), parent)
        self.on_change = on_change
        self._trigger: str | None = None
        self._capturing = False
        self._syncing = False
        box = QVBoxLayout(self)
        row = QHBoxLayout()
        self.chk_enabled = QCheckBox(txt("Enable", "사용"))
        self.chk_enabled.toggled.connect(self._on_enabled)
        row.addWidget(self.chk_enabled)
        self.lbl_trigger = QLabel(txt("On/off hotkey:", "켜고 끄는 단축키:"))
        row.addWidget(self.lbl_trigger)
        self.key_entry = QLineEdit()
        self.key_entry.setReadOnly(True)
        self.key_entry.setMaximumWidth(200)
        row.addWidget(self.key_entry, 1)
        self.btn_capture = QPushButton(txt("Capture", "입력 받기"))
        self.btn_capture.setAutoDefault(False)
        self.btn_capture.clicked.connect(self.start_capture)
        row.addWidget(self.btn_capture)
        self.btn_clear = QPushButton(txt("Clear", "지우기"))
        self.btn_clear.setAutoDefault(False)
        self.btn_clear.clicked.connect(self._clear_trigger)
        row.addWidget(self.btn_clear)
        self.lbl_collapsed = QLabel(
            txt(
                "Off — enable to turn a set of events on and off with one key while running.",
                "사용 안 함 — 켜면 실행 중 키 하나로 이벤트 묶음을 한 번에 켜고 끕니다.",
            )
        )
        style.caption(self.lbl_collapsed)
        row.addWidget(self.lbl_collapsed, 1)
        box.addLayout(row)
        self.lbl_capture = QLabel()
        self.lbl_capture.setStyleSheet(f"color: {style.status_colors('ready')[1]};")
        box.addWidget(self.lbl_capture)
        self.lbl_help = QLabel(
            txt(
                "Checked events start off. While running, press the hotkey to enable or disable them together (CDs, optional skills, etc.). Click Capture, then press a key or scroll the mouse wheel.",
                "체크한 이벤트는 시작 시 꺼져 있습니다. 실행 중 단축키로 한 번에 켜고 끕니다(쿨기·옵션 스킬 등). 입력 받기를 누른 뒤 키를 누르거나 마우스 휠을 움직이세요.",
            )
        )
        self.lbl_help.setWordWrap(True)
        style.caption(self.lbl_help)
        box.addWidget(self.lbl_help)

    def load(self, profile: ProfileModel) -> None:
        self._syncing = True
        try:
            self.stop_capture()
            self._trigger = normalize_runtime_toggle_trigger(profile.runtime_toggle_key)
            self.chk_enabled.setChecked(bool(profile.runtime_toggle_enabled))
            self.key_entry.setText(display_runtime_toggle_trigger(self._trigger) or "")
            self.lbl_capture.setText("")
            self._sync_state()
        finally:
            self._syncing = False

    def _sync_state(self) -> None:
        enabled = self.chk_enabled.isChecked()
        for widget in (
            self.lbl_trigger,
            self.key_entry,
            self.btn_capture,
            self.btn_clear,
            self.lbl_help,
        ):
            widget.setVisible(enabled)
        self.lbl_capture.setVisible(enabled and bool(self.lbl_capture.text()))
        self.lbl_collapsed.setVisible(not enabled)
        if not enabled:
            self.stop_capture()
            self.lbl_capture.setText("")

    def _notify(self) -> None:
        self._sync_state()
        if not self._syncing:
            self.on_change(self.chk_enabled.isChecked(), self._trigger)

    def _on_enabled(self, _checked: bool) -> None:
        self._notify()

    def _set_status(self, text: str) -> None:
        self.lbl_capture.setText(text)
        self.lbl_capture.setVisible(bool(text))

    def _set_trigger(self, trigger: str | None) -> None:
        self._trigger = normalize_runtime_toggle_trigger(trigger)
        self.key_entry.setText(display_runtime_toggle_trigger(self._trigger) or "")
        self._notify()

    def _clear_trigger(self) -> None:
        self.stop_capture()
        self._set_status("")
        self._set_trigger(None)

    @property
    def capturing(self) -> bool:
        return self._capturing

    def start_capture(self) -> None:
        if not self.chk_enabled.isChecked() or self._capturing:
            return
        app = QApplication.instance()
        if app is None:
            return
        self._capturing = True
        self._set_status(
            txt(
                "Waiting for input... Press a key or scroll the mouse wheel. Press Esc to cancel.",
                "입력을 기다리는 중... 키를 누르거나 마우스 휠을 움직이세요. Esc 로 취소합니다.",
            )
        )
        app.installEventFilter(self)

    def stop_capture(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not self._capturing:
            return False
        kind = event.type()
        if kind == QEvent.Type.ShortcutOverride:
            # Esc·⌘Z 같은 창 단축키보다 먼저 받는다.
            event.accept()
            return True
        if kind == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            self.handle_key(event)
            return True
        if kind == QEvent.Type.Wheel and isinstance(event, QWheelEvent):
            self.handle_wheel(event.angleDelta().y())
            return True
        return False

    def handle_key(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.stop_capture()
            self._set_status(
                txt("Input capture cancelled.", "입력 받기를 취소했습니다.")
            )
            return
        if event.isAutoRepeat():
            return
        keysym = QKeySequence(event.key()).toString() or None
        text = event.text() or None
        trigger = normalize_runtime_toggle_capture_key(
            keysym, text, event.nativeVirtualKey() or None
        )
        if not trigger:
            return
        self._captured(trigger)

    def handle_wheel(self, delta: int) -> None:
        trigger = normalize_runtime_toggle_wheel_event(delta=delta)
        if trigger:
            self._captured(trigger)

    def _captured(self, trigger: str) -> None:
        self.stop_capture()
        self._set_status(
            txt(
                "Captured: {trigger}",
                "입력됨: {trigger}",
                trigger=display_runtime_toggle_trigger(trigger),
            )
        )
        self._set_trigger(trigger)


# ── run set editor ─────────────────────────────────────────────────────


class RunSetEditor(QWidget):
    """실행 세트 구성 편집. 체크를 바꾸면 바로 저장한다."""

    def __init__(
        self,
        *,
        on_members_changed: Callable[[list[str]], bool],
        on_rename: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_members_changed = on_members_changed
        self.on_rename = on_rename
        self.name = ""
        self.available: list[str] = []
        self.checks: dict[str, QCheckBox] = {}
        self._saved: list[str] = []
        box = QVBoxLayout(self)
        box.setContentsMargins(
            tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3
        )
        header = QHBoxLayout()
        header.addWidget(QLabel(txt("Run set", "실행 세트")))
        self.entry_name = QLineEdit()
        self.entry_name.setMaximumWidth(260)
        self.entry_name.editingFinished.connect(self._commit_name)
        header.addWidget(self.entry_name)
        header.addStretch(1)
        box.addLayout(header)
        hint = QLabel(
            txt(
                "Profiles checked here run together when this set is started.",
                "여기서 체크한 프로필이 이 세트를 시작할 때 함께 실행됩니다.",
            )
        )
        style.caption(hint)
        box.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_host = QWidget()
        self.list_box = QVBoxLayout(self.list_host)
        self.list_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.list_host)
        box.addWidget(scroll, 1)
        self.lbl_error = QLabel()
        self.lbl_error.setStyleSheet(_error_style())
        box.addWidget(self.lbl_error)

    def load(self, name: str, members: list[str], available: list[str]) -> None:
        self.name = name
        self.available = list(available)
        self.entry_name.setText(name)
        self.lbl_error.setText("")
        for check in self.checks.values():
            check.deleteLater()
        self.checks = {}
        chosen = set(members)
        self._saved = [p for p in available if p in chosen]
        for profile in available:
            check = QCheckBox(profile)
            check.setChecked(profile in chosen)
            check.toggled.connect(self._on_toggle)
            self.list_box.addWidget(check)
            self.checks[profile] = check

    def members(self) -> list[str]:
        return [name for name in self.available if self.checks[name].isChecked()]

    def _on_toggle(self, _checked: bool) -> None:
        if self.on_members_changed(self.members()):
            self.lbl_error.setText("")
            self._saved = self.members()
            return
        # 거부된 선택을 화면에 남기지 않는다. 남기면 다음 체크 때 빠진
        # 구성원이 그대로 저장된다.
        for name, check in self.checks.items():
            check.blockSignals(True)
            check.setChecked(name in self._saved)
            check.blockSignals(False)
        self.lbl_error.setText(
            txt("Keep at least one profile.", "프로필을 하나 이상 남겨 두세요.")
        )

    def _commit_name(self) -> None:
        new = self.entry_name.text().strip()
        if new and new != self.name:
            self.on_rename(new)


# ── graph ──────────────────────────────────────────────────────────────


class GraphView(QScrollArea):
    """목록 자리의 그래프 탭. 기존 PNG 렌더링을 그대로 쓴다."""

    def __init__(self, cache_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cache_dir = cache_dir
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setWidget(self.label)
        self.setWidgetResizable(False)

    def show_profile(self, profile: ProfileModel, name: str) -> None:
        try:
            path = ensure_profile_graph_image(
                profile, name or "profile", self.cache_dir
            )
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                raise ValueError(f"cannot read {path}")
        except Exception as exc:
            logger.error(f"Graph render failed: {exc}")
            self.label.setPixmap(QPixmap())
            self.label.setText(txt("Graph failed: {e}", "그래프 오류: {e}", e=exc))
            self.label.adjustSize()
            return
        self.label.setText("")
        self.label.setPixmap(pixmap)
        self.label.resize(pixmap.size())
