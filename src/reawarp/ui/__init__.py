"""PySide6 desktop application for Reawarp.

On Windows, explicitly register the PySide6 and shiboken6 package directories
for native DLL lookup before any Qt extension module is imported.
"""

from __future__ import annotations

import os
import sys
from importlib.util import find_spec
from pathlib import Path

# Keep these handles alive for the lifetime of the process. Closing a handle
# removes its directory from Windows' DLL search path.
_DLL_DIRECTORY_HANDLES: list[object] = []


def _configure_windows_qt_dll_search_path() -> None:
    """Register the Qt and Shiboken wheel directories for Windows DLL lookup."""
    if sys.platform != "win32":
        return

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        return

    spec = find_spec("PySide6")
    if spec is None:
        return

    for package_location in spec.submodule_search_locations or ():
        pyside_directory = Path(package_location)
        for dll_directory in (pyside_directory, pyside_directory.parent / "shiboken6"):
            if dll_directory.is_dir():
                try:
                    handle = add_dll_directory(str(dll_directory))
                except OSError:
                    # Let the eventual Qt import report the native loading error.
                    continue
                _DLL_DIRECTORY_HANDLES.append(handle)


_configure_windows_qt_dll_search_path()
