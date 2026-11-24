import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from reawarp.ui.main_window import MainWindow
from reawarp.ui.navigation import WorkspaceNavigator


_APP = None


def _application():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
        app = _APP
    return app


def test_navigator_supports_nested_groups_and_emits_only_workspace_selections():
    _application()
    navigator = WorkspaceNavigator([
        ("COMPOSE", [
            ("Generator", "Compose a new project.", 0),
            ("Break Lab", "Transform break material.", 1),
        ]),
    ])
    selected = []
    navigator.workspaceSelected.connect(selected.append)

    navigator.register_workspace(
        ("COMPOSE", "GENERATOR", "ADVANCED"),
        "Motif Lab",
        "Inspect and transform shared motifs.",
        2,
    )
    assert navigator.workspace_count() == 3
    assert navigator.topLevelItemCount() == 1

    navigator.itemClicked.emit(navigator._workspace_items[2], 0)
    assert selected == [2]
    navigator.itemClicked.emit(navigator._group_items[("COMPOSE",)], 0)
    assert selected == [2]

    navigator.select_workspace(1)
    assert navigator.currentItem() is navigator._workspace_items[1]
    assert selected == [2]

    with pytest.raises(ValueError, match="already registered"):
        navigator.register_workspace(("COMPOSE",), "Duplicate", "Invalid", 1)


def test_main_window_navigation_keeps_workspace_stack_and_transport_in_sync():
    app = _application()
    window = MainWindow()
    expected_titles = ["GENERATOR", "BREAK LAB", "STEM MIXER", "FX LAB", "LIBRARY"]

    for index, expected_title in enumerate(expected_titles):
        window._set_workspace(index)
        assert window.workspace_stack.currentIndex() == index
        assert window.workspace_title.text() == expected_title
        assert window.navigator.currentItem() is window.navigator._workspace_items[index]
        assert window.transport_bar.isHidden() is (index not in (0, 2))

    window.navigator.itemClicked.emit(window.navigator._workspace_items[4], 0)
    assert window.workspace_stack.currentIndex() == 4
    assert "NO COMPOSITION" in window.project_context.text()

    window._set_workspace(99)
    assert window.workspace_stack.currentIndex() == 4
    window.close()
    app.processEvents()
