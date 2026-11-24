"""Grouped workspace navigation for the Reawarp desktop application.

The navigator is deliberately data-driven: a future workspace can be added to
an existing group or registered in a new group without extending a flat tab bar.
Each workspace still operates on the shared MainWindow project/session context.
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

        for group_name, entries in groups:
            group = QTreeWidgetItem([str(group_name).upper()])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.addTopLevelItem(group)
            group.setExpanded(True)
            for label, description, index in entries:
                item = QTreeWidgetItem([str(label)])
                item.setData(0, Qt.ItemDataRole.UserRole, int(index))
                item.setToolTip(0, str(description))
                group.addChild(item)
                self._workspace_items[int(index)] = item

        self.itemClicked.connect(self._on_item_clicked)

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
