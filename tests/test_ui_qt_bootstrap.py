"""Tests for the desktop application's native Qt DLL bootstrap."""

from __future__ import annotations

from types import SimpleNamespace

import reawarp.ui as ui


def test_windows_qt_dll_directories_are_registered_and_retained(
    monkeypatch, tmp_path
):
    site_packages = tmp_path / "site-packages"
    pyside_directory = site_packages / "PySide6"
    shiboken_directory = site_packages / "shiboken6"
    pyside_directory.mkdir(parents=True)
    shiboken_directory.mkdir()

    registered: list[str] = []
    handles: list[object] = []

    def fake_add_dll_directory(path: str) -> object:
        registered.append(path)
        handle = object()
        return handle

    monkeypatch.setattr(ui.sys, "platform", "win32")
    monkeypatch.setattr(
        ui,
        "find_spec",
        lambda name: SimpleNamespace(
            submodule_search_locations=[str(pyside_directory)]
        ),
    )
    monkeypatch.setattr(ui.os, "add_dll_directory", fake_add_dll_directory, raising=False)
    monkeypatch.setattr(ui, "_DLL_DIRECTORY_HANDLES", handles)

    ui._configure_windows_qt_dll_search_path()

    assert registered == [str(pyside_directory), str(shiboken_directory)]
    assert len(handles) == 2


def test_qt_dll_bootstrap_is_a_noop_off_windows(monkeypatch):
    monkeypatch.setattr(ui.sys, "platform", "linux")
    monkeypatch.setattr(
        ui,
        "find_spec",
        lambda _name: (_ for _ in ()).throw(AssertionError("must not search for Qt")),
    )

    ui._configure_windows_qt_dll_search_path()
