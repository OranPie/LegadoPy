from __future__ import annotations


class LegadoEngineError(Exception):
    """Base exception for headless Legado engine failures."""


class UnsupportedHeadlessOperation(LegadoEngineError):
    """Raised when a source requires Android/WebView-only behavior."""

    def __init__(self, operation: str, detail: str = "") -> None:
        self.operation = operation
        self.detail = detail
        message = f"Unsupported headless operation: {operation}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)

