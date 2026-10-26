"""작업 공간 가운데 목록: 신호/규칙 묶음, 드래그로 순서(=우선순위) 바꾸기."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QPalette,
    QResizeEvent,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTreeView, QWidget

from app.domain.display_text import row_badges, row_detail, section_note, section_title
from app.domain.models import EventModel
from app.domain.profile_events import (
    EventSection,
    build_event_sections,
    event_matches_query,
    event_needs_attention,
    referenced_event_names,
)
from app.ui import style
from app.utils.i18n import txt

DRAG_HANDLE = "⋮⋮"
_EVENT_ROLE = Qt.ItemDataRole.UserRole + 1
_SECTION_ROLE = Qt.ItemDataRole.UserRole + 2

SelectCallback = Callable[[list[EventModel]], None]
MoveCallback = Callable[[EventModel, EventModel], bool]
ContextCallback = Callable[[QPoint, list[EventModel], EventSection | None], None]


class EventTree(QTreeView):
    """묶음(부모 행) 아래 이벤트(자식 행). 같은 묶음 안에서만 끌어 옮긴다."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_select: SelectCallback,
        on_move: MoveCallback,
        on_context: ContextCallback,
        on_delete: Callable[[], object],
        on_copy: Callable[[], object],
        on_activate: Callable[[], object],
        on_drop_rejected: Callable[[], object],
    ) -> None:
        super().__init__(parent)
        self.on_select = on_select
        self.on_move = on_move
        self.on_context = on_context
        self.on_delete = on_delete
        self.on_copy = on_copy
        self.on_activate = on_activate
        self.on_drop_rejected = on_drop_rejected
        self.events: list[EventModel] = []
        self.sections: list[EventSection] = []
        self.query = ""
        self._toggle_enabled = False
        self._by_id: dict[int, EventModel] = {}
        self._syncing = False
        self._drag_event: EventModel | None = None

        self.store = QStandardItemModel(0, 4, self)
        self.setModel(self.store)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_requested)
        self.doubleClicked.connect(self._on_double_click)
        self.selectionModel().selectionChanged.connect(self._on_selection_changed)

        header = self.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self._set_headers()
        self.setColumnWidth(0, 210)
        self.setColumnWidth(2, 180)

        self.lbl_empty = QLabel(self.viewport())
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setWordWrap(True)
        style.caption(self.lbl_empty)
        self.lbl_empty.hide()

    def _set_headers(self) -> None:
        self.store.setHorizontalHeaderLabels(
            [
                txt("Name", "이름"),
                txt("Key", "키"),
                txt("Conditions / screen", "조건 / 화면"),
                "",
            ]
        )

    # ── data ───────────────────────────────────────────────────────────

    def set_events(
        self,
        events: Sequence[EventModel],
        *,
        toggle_enabled: bool,
        keep_selection: bool = True,
    ) -> None:
        selected = self.selected_events() if keep_selection else []
        self.events = list(events)
        self._toggle_enabled = toggle_enabled
        self._rebuild()
        self.select(selected, see=False)

    def set_query(self, query: str) -> None:
        self.query = query
        selected = self.selected_events()
        self._rebuild()
        self.select(selected, see=False)

    def _rebuild(self) -> None:
        self._syncing = True
        try:
            self.store.removeRows(0, self.store.rowCount())
            self._by_id.clear()
            referenced = referenced_event_names(self.events)
            self.sections = build_event_sections(self.events)
            muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
            warn = QColor(style.status_colors("warn")[1])
            shown = 0
            for index, section in enumerate(self.sections):
                visible = [
                    e for e in section.events if event_matches_query(e, self.query)
                ]
                if not visible:
                    continue
                head = self._section_row(section, index)
                for event in visible:
                    head[0].appendRow(self._event_row(event, referenced, muted, warn))
                    shown += 1
                self.store.appendRow(head)
            self.expandAll()
            self._sync_empty(shown)
        finally:
            self._syncing = False

    def _section_row(self, section: EventSection, index: int) -> list[QStandardItem]:
        cells = [
            QStandardItem(section_title(section)),
            QStandardItem(""),
            QStandardItem(section_note(section)),
            QStandardItem(""),
        ]
        font = self.font()
        font.setBold(True)
        for cell in cells:
            cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
            cell.setData(index, _SECTION_ROLE)
        cells[0].setFont(font)
        return cells

    def _event_row(
        self, event: EventModel, referenced: set[str], muted: QColor, warn: QColor
    ) -> list[QStandardItem]:
        self._by_id[id(event)] = event
        badges = row_badges(
            event,
            referenced=(event.event_name or "") in referenced,
            toggle_enabled=self._toggle_enabled,
        )
        cells = [
            QStandardItem(f"{DRAG_HANDLE} {event.event_name or ''}"),
            QStandardItem((event.key_to_enter or "") if event.execute_action else ""),
            QStandardItem(row_detail(event)),
            QStandardItem(" · ".join(badges)),
        ]
        color: QColor | None = None
        if not event.use_event:
            color = muted
        elif event_needs_attention(event):
            color = warn
        flags = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        for cell in cells:
            cell.setFlags(flags)
            cell.setData(id(event), _EVENT_ROLE)
            if color is not None:
                cell.setForeground(QBrush(color))
        return cells

    def _sync_empty(self, shown: int) -> None:
        if shown:
            self.lbl_empty.hide()
            return
        self.lbl_empty.setText(
            txt("No events match the search.", "검색과 일치하는 이벤트가 없습니다.")
            if self.events
            else txt(
                "No events yet. Add a signal (screen watch) or a rule (key input).",
                "이벤트가 없습니다. 신호(화면 감시)나 규칙(키 입력)을 추가하세요.",
            )
        )
        self._place_empty()
        self.lbl_empty.show()

    def _place_empty(self) -> None:
        rect = self.viewport().rect()
        width = max(rect.width() - 40, 100)
        self.lbl_empty.setFixedWidth(width)
        self.lbl_empty.adjustSize()
        self.lbl_empty.move((rect.width() - width) // 2, int(rect.height() * 0.3))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.lbl_empty.isVisible():
            self._place_empty()

    # ── selection ──────────────────────────────────────────────────────

    def event_at(self, index: QModelIndex) -> EventModel | None:
        if not index.isValid():
            return None
        key = index.data(_EVENT_ROLE)
        return self._by_id.get(key) if isinstance(key, int) else None

    def section_at(self, index: QModelIndex) -> EventSection | None:
        if not index.isValid():
            return None
        key = index.data(_SECTION_ROLE)
        if isinstance(key, int) and 0 <= key < len(self.sections):
            return self.sections[key]
        return None

    def selected_events(self) -> list[EventModel]:
        rows = self.selectionModel().selectedRows(0)
        found = [self.event_at(index) for index in rows]
        chosen = {id(e) for e in found if e is not None}
        # 목록에 보이는 순서대로.
        return [e for e in self._visible_events() if id(e) in chosen]

    def _visible_events(self) -> list[EventModel]:
        out: list[EventModel] = []
        for row in range(self.store.rowCount()):
            head = self.store.item(row, 0)
            for child in range(head.rowCount()):
                event = self.event_at(head.child(child, 0).index())
                if event is not None:
                    out.append(event)
        return out

    def index_of(self, event: EventModel) -> QModelIndex:
        for row in range(self.store.rowCount()):
            head = self.store.item(row, 0)
            for child in range(head.rowCount()):
                item = head.child(child, 0)
                if item.data(_EVENT_ROLE) == id(event):
                    return item.index()
        return QModelIndex()

    def select(self, events: Sequence[EventModel], *, see: bool = True) -> None:
        self._syncing = True
        try:
            selection = QItemSelection()
            first: QModelIndex | None = None
            for event in events:
                index = self.index_of(event)
                if not index.isValid():
                    continue
                selection.select(index, index.siblingAtColumn(3))
                first = first or index
            flags = (
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows
            )
            self.selectionModel().select(selection, flags)
            if first is not None:
                self.selectionModel().setCurrentIndex(
                    first, QItemSelectionModel.SelectionFlag.NoUpdate
                )
                if see:
                    self.scrollTo(first)
        finally:
            self._syncing = False
        self.on_select(self.selected_events())

    def _on_selection_changed(self, *_args: object) -> None:
        if self._syncing:
            return
        self.on_select(self.selected_events())

    # ── keys / mouse ───────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and not mods & ~(
            Qt.KeyboardModifier.KeypadModifier
        ):
            self.on_delete()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.on_activate()
            return
        if key == Qt.Key.Key_D and mods & Qt.KeyboardModifier.ControlModifier:
            # macOS의 ⌘는 Qt에서 ControlModifier다.
            self.on_copy()
            return
        super().keyPressEvent(event)

    def _on_double_click(self, index: QModelIndex) -> None:
        if self.event_at(index) is not None:
            self.on_activate()

    def _on_context_requested(self, pos: QPoint) -> None:
        index = self.indexAt(pos)
        global_pos = self.viewport().mapToGlobal(pos)
        section = self.section_at(index)
        if section is not None:
            self.on_context(global_pos, [], section)
            return
        event = self.event_at(index)
        if event is not None and not any(e is event for e in self.selected_events()):
            self.select([event], see=False)
        self.on_context(global_pos, self.selected_events(), None)

    # ── drag ───────────────────────────────────────────────────────────

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        self._drag_event = self.event_at(self.currentIndex())
        if self._drag_event is None:
            return
        try:
            super().startDrag(supportedActions)
        finally:
            self._drag_event = None

    def _drop_target(self, pos: QPoint) -> EventModel | None:
        return self.event_at(self.indexAt(pos))

    def _same_section(self, a: EventModel, b: EventModel) -> bool:
        return any(
            any(e is a for e in s.events) and any(e is b for e in s.events)
            for s in self.sections
        )

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        super().dragMoveEvent(event)
        moved = self._drag_event
        target = self._drop_target(event.position().toPoint())
        if (
            moved is None
            or target is None
            or target is moved
            or self.query.strip()
            or not self._same_section(moved, target)
        ):
            event.ignore()
            return
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        moved = self._drag_event
        target = self._drop_target(event.position().toPoint())
        # 모델은 직접 바꾸지 않는다. 우선순위를 쓴 뒤 목록을 다시 그린다.
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        self.dragLeaveEvent(QDragLeaveEvent())
        if moved is not None and target is not None and target is not moved:
            # 드래그가 끝난 뒤 목록을 다시 만든다.
            QTimer.singleShot(0, lambda: self.drop(moved, target))

    def drop(self, moved: EventModel, target: EventModel) -> bool:
        """`moved`를 `target` 자리로 옮긴다. 같은 묶음 안에서만 된다."""
        if self.query.strip() or not self._same_section(moved, target):
            # 검색 중에는 보이는 행만으로 순서를 알 수 없다.
            self.on_drop_rejected()
            return False
        return self.on_move(moved, target)
