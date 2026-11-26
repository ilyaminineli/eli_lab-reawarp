"""Grouped workspace navigation for the Reawarp desktop application.

The navigator is deliberately data-driven and supports arbitrary group depth.
A future sub-workspace can be registered under a path such as
("COMPOSE", "GENERATOR", "ADVANCED") without growing a flat tab strip. All
workspaces continue to operate on the shared MainWindow project/session context.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

WorkspaceEntry = tuple[str, str, int]
WorkspaceGroup = tuple[str, Sequence[WorkspaceEntry]]


class WorkspaceNavigator(QTreeWidget):
    """Collapsible category tree that emits the selected workspace index."""

    workspaceSelected = Signal(int)

    def __init__(
        self,
        groups: Sequence[WorkspaceGroup],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceNavigator")
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(14)
        self.setAnimated(True)
        self.setUniformRowHeights(True)
        self.setMinimumWidth(185)
        self.setMaximumWidth(250)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._workspace_items: dict[int, QTreeWidgetItem] = {}
        self._group_items: dict[tuple[str, ...], QTreeWidgetItem] = {}

        for group_name, entries in groups:
            for label, description, index in entries:
                self.register_workspace(
                    (str(group_name),), str(label), str(description), int(index)
                )

        self.itemClicked.connect(self._on_item_clicked)

    def register_group(self, path: Sequence[str]) -> QTreeWidgetItem:
        """Create or return a nested category path, preserving existing groups."""
        parts = tuple(str(part).strip() for part in path)
        if not parts or any(not part for part in parts):
            raise ValueError("group path must contain non-empty names")

        parent = None
        current_path: tuple[str, ...] = ()
        for part in parts:
            current_path += (part,)
            item = self._group_items.get(current_path)
            if item is None:
                item = QTreeWidgetItem([part.upper()])
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if parent is None:
                    self.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                item.setExpanded(True)
                self._group_items[current_path] = item
            parent = item
        return parent

    def register_workspace(
        self,
        group_path: Sequence[str],
        label: str,
        description: str,
        index: int,
    ) -> QTreeWidgetItem:
        """Register a selectable page beneath any existing or new group path."""
        index = int(index)
        if index in self._workspace_items:
            raise ValueError(f"workspace index {index} is already registered")
        parent = self.register_group(group_path)
        item = QTreeWidgetItem([str(label)])
        item.setData(0, Qt.ItemDataRole.UserRole, index)
        item.setToolTip(0, str(description))
        parent.addChild(item)
        self._workspace_items[index] = item
        return item

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is not None:
            self.workspaceSelected.emit(int(index))

    def select_workspace(self, index: int) -> None:
        """Reflect programmatic navigation without emitting a second selection."""
        item = self._workspace_items.get(int(index))
        if item is not None:
            self.setCurrentItem(item)

    def workspace_count(self) -> int:
        return len(self._workspace_items)
