from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable

try:
    import regex as _regex  # type: ignore[import]
except Exception:  # pragma: no cover - optional dependency
    _regex = None


def _split_scope(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[\n,]+", value) if part.strip()]


@dataclass
class ReplaceRule:
    id: int = 0
    name: str = ""
    group: str | None = None
    pattern: str = ""
    replacement: str = ""
    scope: str | None = None
    scopeTitle: bool = False
    scopeContent: bool = True
    excludeScope: str | None = None
    isEnabled: bool = True
    isRegex: bool = True
    timeoutMillisecond: int = 3000
    order: int = 0

    def is_valid(self) -> bool:
        if not self.pattern:
            return False
        if not self.isRegex:
            return True
        try:
            re.compile(self.pattern)
            return not (self.pattern.endswith("|") and not self.pattern.endswith("\\|"))
        except re.error:
            return False

    def applies_to(self, tokens: Iterable[str], *, is_title: bool, is_content: bool) -> bool:
        if not self.isEnabled or not self.is_valid():
            return False
        if is_title and not self.scopeTitle:
            return False
        if is_content and not self.scopeContent:
            return False
        scope_terms = _split_scope(self.scope)
        exclude_terms = _split_scope(self.excludeScope)
        lowered_tokens = [token.lower() for token in tokens if token]
        if scope_terms and not any(
            term.lower() in token for term in scope_terms for token in lowered_tokens
        ):
            return False
        if exclude_terms and any(
            term.lower() in token for term in exclude_terms for token in lowered_tokens
        ):
            return False
        return True

    def apply(self, text: str) -> str:
        if not text:
            return text
        if not self.isRegex:
            return text.replace(self.pattern, self.replacement)
        if _regex is not None:
            try:
                return _regex.sub(
                    self.pattern,
                    self.replacement,
                    text,
                    timeout=max(0.1, self.get_valid_timeout_millisecond() / 1000.0),
                )
            except Exception:
                return text
        try:
            return re.sub(self.pattern, self.replacement, text)
        except re.error:
            return text

    def get_valid_timeout_millisecond(self) -> int:
        return self.timeoutMillisecond if self.timeoutMillisecond > 0 else 3000

    @classmethod
    def from_dict(cls, data: dict) -> "ReplaceRule":
        return cls(
            id=int(data.get("id", 0) or 0),
            name=str(data.get("name", "") or ""),
            group=data.get("group"),
            pattern=str(data.get("pattern", "") or ""),
            replacement=str(data.get("replacement", "") or ""),
            scope=data.get("scope"),
            scopeTitle=bool(data.get("scopeTitle", False)),
            scopeContent=bool(data.get("scopeContent", True)),
            excludeScope=data.get("excludeScope"),
            isEnabled=bool(data.get("isEnabled", True)),
            isRegex=bool(data.get("isRegex", True)),
            timeoutMillisecond=int(data.get("timeoutMillisecond", 3000) or 3000),
            order=int(data.get("sortOrder", data.get("order", 0)) or 0),
        )

    @classmethod
    def from_json(cls, text: str) -> "ReplaceRule":
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_json_array(cls, text: str) -> list["ReplaceRule"]:
        data = json.loads(text)
        if isinstance(data, dict):
            return [cls.from_dict(data)]
        return [cls.from_dict(item) for item in data if isinstance(item, dict)]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "group": self.group,
            "pattern": self.pattern,
            "replacement": self.replacement,
            "scope": self.scope,
            "scopeTitle": self.scopeTitle,
            "scopeContent": self.scopeContent,
            "excludeScope": self.excludeScope,
            "isEnabled": self.isEnabled,
            "isRegex": self.isRegex,
            "timeoutMillisecond": self.timeoutMillisecond,
            "sortOrder": self.order,
        }

