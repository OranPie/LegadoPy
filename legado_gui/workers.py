"""
Qt6 worker threads for background engine calls.
Uses QRunnable + QThreadPool so the GUI stays responsive.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    result = Signal(object)
    error = Signal(str, object)   # (message, exception)
    progress = Signal(str)


class Worker(QRunnable):
    """
    Generic worker: runs ``fn()`` on the thread pool and emits
    ``signals.result`` or ``signals.error`` back on the main thread.
    """

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self._fn = fn
        self.signals = _Signals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._fn()
            self.signals.result.emit(result)
        except Exception as exc:
            self.signals.error.emit(str(exc), exc)


def submit(fn: Callable[[], Any], *, pool: QThreadPool | None = None) -> Worker:
    """
    Convenience: create a Worker, submit it to *pool* (or global pool),
    and return it so callers can connect signals before the task completes.
    """
    worker = Worker(fn)
    (pool or QThreadPool.globalInstance()).start(worker)
    return worker
