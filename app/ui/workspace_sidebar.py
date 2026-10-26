"""작업 공간 왼쪽 사이드바: 프로필과 실행 세트 목록."""

from __future__ import annotations

import tkinter as tk
import tkinter.ttk as ttk
from collections.abc import Callable, Sequence

from app.presenters.workspace_sidebar import ItemKind, sidebar_actions
from app.ui import theme
from app.utils.i18n import txt

SelectCallback = Callable[[ItemKind, str], None]
ActionCallback = Callable[[ItemKind, str, str], None]
NewCallback = Callable[[ItemKind], None]

_ROOTS: dict[ItemKind, str] = {"profile": "root:profile", "run_set": "root:run_set"}


def item_iid(kind: ItemKind, name: str) -> str:
    return f"{kind}:{name}"


class WorkspaceSidebar(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_select: SelectCallback,
        on_action: ActionCallback,
        on_new: NewCallback,
    ) -> None:
        super().__init__(master, bg=theme.SURFACE_PANEL)
        self.on_select = on_select
        self.on_action = on_action
        self._syncing = False
        # selection_set은 <<TreeviewSelect>>를 나중에 보낸다. 현재 항목을
        # 기억해 두고, 그 항목으로 돌아온 이벤트는 사용자 선택으로 보지 않는다.
        self._current_iid: str | None = None
        self.tree = ttk.Treeview(self, show="tree", selectmode="browse")
        self.tree.column("#0", width=190, stretch=True)
        self.tree.tag_configure(
            "root", font=theme.fonts()["body_bold"], foreground=theme.INK_SECONDARY
        )
        self.tree.tag_configure("favorite", font=theme.fonts()["body_bold"])
        self.tree.pack(fill="both", expand=True, padx=theme.SPACE_2, pady=theme.SPACE_2)
        roots: tuple[tuple[ItemKind, str], ...] = (
            ("profile", txt("Profiles", "프로필")),
            ("run_set", txt("Run sets", "실행 세트")),
        )
        for kind, label in roots:
            self.tree.insert(
                "", "end", iid=_ROOTS[kind], text=label, open=True, tags=("root",)
            )
        f_new = tk.Frame(self, bg=theme.SURFACE_PANEL)
        f_new.pack(fill="x", padx=theme.SPACE_2, pady=(0, theme.SPACE_2))
        ttk.Button(
            f_new,
            text=txt("＋ Profile", "＋ 프로필"),
            command=lambda: on_new("profile"),
        ).pack(side="left")
        ttk.Button(
            f_new,
            text=txt("＋ Run set", "＋ 실행 세트"),
            command=lambda: on_new("run_set"),
        ).pack(side="left", padx=(theme.SPACE_1, 0))
        self.menu = tk.Menu(self, tearoff=0)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        for seq in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.tree.bind(seq, self._on_context)

    def set_items(
        self,
        profiles: Sequence[str],
        favorites: set[str],
        run_sets: Sequence[str],
        current: tuple[ItemKind, str] | None,
    ) -> None:
        self._syncing = True
        try:
            kinds: tuple[ItemKind, ...] = ("profile", "run_set")
            for kind in kinds:
                for iid in self.tree.get_children(_ROOTS[kind]):
                    self.tree.delete(iid)
            for name in profiles:
                self.tree.insert(
                    _ROOTS["profile"],
                    "end",
                    iid=item_iid("profile", name),
                    text=f"{theme.ICON_FAVORITE} {name}" if name in favorites else f"   {name}",
                    tags=("favorite",) if name in favorites else (),
                )
            for name in run_sets:
                self.tree.insert(
                    _ROOTS["run_set"], "end", iid=item_iid("run_set", name), text=f"   {name}"
                )
            self.mark_current(current)
        finally:
            self._syncing = False

    def mark_current(self, current: tuple[ItemKind, str] | None) -> None:
        self._syncing = True
        try:
            if current is None:
                self._current_iid = None
                self.tree.selection_set([])
                return
            iid = item_iid(*current)
            self._current_iid = iid
            if self.tree.exists(iid):
                self.tree.selection_set([iid])
                self.tree.see(iid)
        finally:
            self._syncing = False

    @staticmethod
    def _parse(iid: str) -> tuple[ItemKind, str] | None:
        if iid.startswith("root:") or ":" not in iid:
            return None
        kind, name = iid.split(":", 1)
        if kind == "profile":
            return ("profile", name)
        if kind == "run_set":
            return ("run_set", name)
        return None

    def _on_tree_select(self, _event: object | None = None) -> None:
        if self._syncing:
            return
        selection = self.tree.selection()
        if not selection or selection[0] == self._current_iid:
            return
        parsed = self._parse(selection[0])
        if parsed is None:
            return
        self.on_select(*parsed)

    def _on_context(self, event: tk.Event[tk.Misc]) -> str:
        parsed = self._parse(self.tree.identify_row(event.y))
        if parsed is None:
            return "break"
        kind, name = parsed
        self.menu.delete(0, "end")
        for action, label in sidebar_actions(kind, name):
            self.menu.add_command(
                label=label,
                command=lambda a=action, k=kind, n=name: self.on_action(k, a, n),
            )
        self.menu.tk_popup(event.x_root, event.y_root)
        return "break"
