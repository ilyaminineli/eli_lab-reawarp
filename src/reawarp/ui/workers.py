"""Background rendering jobs for the PySide6 desktop interface."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class RenderWorker(QRunnable):
    """Run expensive deterministic rendering outside the GUI thread."""

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.finished.emit(self.operation())
        except Exception as exc:
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")
