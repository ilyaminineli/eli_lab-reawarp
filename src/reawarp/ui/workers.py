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


class CancellableRenderWorker(QRunnable):
    """Background operation with cooperative cancellation and stale-result safety.

    The operation receives a threading.Event and should check it at safe
    boundaries (for example between stems, buses and expensive DSP calls).
    """
    def __init__(self, operation: Callable[[object], object]) -> None:
        super().__init__()
        import threading

        self.operation = operation
        self.cancel_event = threading.Event()
        self.signals = WorkerSignals()

    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation(self.cancel_event)
        except Exception as exc:
            if self.cancel_event.is_set():
                self.signals.error.emit("CANCELLED: " + str(exc))
            else:
                self.signals.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            if self.cancel_event.is_set():
                self.signals.error.emit("CANCELLED: FX render cancelled")
            else:
                self.signals.finished.emit(result)
