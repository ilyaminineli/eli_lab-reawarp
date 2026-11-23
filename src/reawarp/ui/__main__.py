"""Start the Reawarp desktop application."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from reawarp.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Reawarp")
    app.setOrganizationName("ELI LAB")
    window = MainWindow()
    app.setQuitOnLastWindowClosed(not window._tray_available)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
