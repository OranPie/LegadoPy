from __future__ import annotations

import json
import sys
from dataclasses import fields, is_dataclass
from typing import Any, Dict

from bs4 import Tag

from .analyze.analyze_rule import AnalyzeRule
from .models.book import Book, BookChapter, RuleData
from .models.book_source import BaseSource, BookSource
from .models.rss_source import RssSource


def _build_dataclass(cls, data: Dict[str, Any]) -> Any:
    allowed = {field.name for field in fields(cls)}
    kwargs = {key: value for key, value in (data or {}).items() if key in allowed}
    obj = cls(**kwargs)
    if hasattr(obj, "load_variable") and data.get("variable") is not None:
        obj.load_variable(data.get("variable"))
    return obj


def _build_source(data: Dict[str, Any]) -> BaseSource | None:
    if not isinstance(data, dict) or not data:
        return None
    if "bookSourceUrl" in data:
        return BookSource.from_dict(data)
    if "sourceUrl" in data:
        return RssSource.from_dict(data)
    return _build_dataclass(BaseSource, data)


def _build_rule_data(data: Dict[str, Any]) -> RuleData | None:
    if not isinstance(data, dict) or not data:
        return None
    if "bookUrl" in data or "name" in data or "author" in data:
        return _build_dataclass(Book, data)
    return _build_dataclass(RuleData, data)


def _build_chapter(data: Dict[str, Any]) -> BookChapter | None:
    if not isinstance(data, dict) or not data:
        return None
    return _build_dataclass(BookChapter, data)


def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Tag):
        return str(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if is_dataclass(value):
        return {field.name: _serialize(getattr(value, field.name)) for field in fields(value)}
    return str(value)


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    operation = payload.get("operation")
    source = _build_source(payload.get("source") or {})
    rule_data = _build_rule_data(payload.get("book") or {})
    chapter = _build_chapter(payload.get("chapter") or {})
    base_url = str(payload.get("baseUrl") or "")
    redirect_url = str(payload.get("redirectUrl") or base_url)
    content = payload.get("content")

    analyze_rule = AnalyzeRule(rule_data or RuleData(), source)
    if content is None:
        content = ""
    analyze_rule.set_content(content, base_url=base_url)
    analyze_rule.set_redirect_url(redirect_url)
    analyze_rule.set_chapter(chapter)

    if operation == "set_content":
        result: Any = {
            "content": payload.get("newContent"),
            "baseUrl": payload.get("newBaseUrl") or base_url,
        }
    elif operation == "get_string":
        result = analyze_rule.get_string(
            payload.get("rule"),
            payload.get("mContent"),
            bool(payload.get("isUrl", False)),
        )
    elif operation == "get_string_list":
        result = analyze_rule.get_string_list(
            payload.get("rule"),
            payload.get("mContent"),
            bool(payload.get("isUrl", False)),
        )
    elif operation == "get_element":
        result = analyze_rule.get_element(payload.get("rule") or "")
        if isinstance(result, list):
            result = result[0] if result else None
    elif operation == "get_elements":
        result = analyze_rule.get_elements(payload.get("rule") or "")
    else:
        raise ValueError(f"Unsupported operation: {operation}")

    sys.stdout.write(json.dumps({"result": _serialize(result)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
