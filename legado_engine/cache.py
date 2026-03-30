from __future__ import annotations

from typing import Any, Dict


class CacheStore:
    """Simple shared in-process cache exposed to JS and fetch pipelines."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get(self, key: Any, default: Any = "") -> Any:
        return self._store.get(str(key), default)

    def put(self, key: Any, value: Any) -> Any:
        self._store[str(key)] = value
        return value

    def remove(self, key: Any) -> None:
        self._store.pop(str(key), None)

    def contains(self, key: Any) -> bool:
        return str(key) in self._store

    def clear(self) -> None:
        self._store.clear()

    def export(self) -> dict[str, Any]:
        return dict(self._store)

    def replace_all(self, values: dict[str, Any]) -> None:
        self._store = dict(values)
