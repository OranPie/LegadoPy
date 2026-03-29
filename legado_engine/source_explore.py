"""
Helpers for Legado discover/explore categories.
Mirrors the original BookSource.exploreKinds() behavior closely enough for API use.
"""
from __future__ import annotations

import json
import re
import traceback
from typing import Any, List

from .analyze_url import JsCookie
from .js_engine import JsExtensions, eval_js
from .models.book_source import BookSource, ExploreKind


_KIND_SPLIT_RE = re.compile(r"(?:&&|\n)+")


def _parse_kind_item(item: Any) -> ExploreKind:
    if isinstance(item, ExploreKind):
        return item
    if isinstance(item, dict):
        return ExploreKind(
            title=str(item.get("title") or ""),
            url=item.get("url"),
            style=item.get("style") if isinstance(item.get("style"), dict) else None,
        )
    if item is None:
        return ExploreKind()
    return ExploreKind(title=str(item))


def _evaluate_explore_rule(book_source: BookSource) -> str:
    rule_str = book_source.exploreUrl or ""
    if not rule_str:
        return ""
    if not (rule_str.startswith("<js>") or rule_str.lower().startswith("@js:")):
        return rule_str

    if rule_str.lower().startswith("@js:"):
        js_str = rule_str[4:]
    else:
        end = rule_str.rfind("</js>")
        js_str = rule_str[4:end if end != -1 else None]

    java = JsExtensions(
        base_url=book_source.get_key(),
        put_fn=book_source.put,
        get_fn=book_source.get,
    )
    result = eval_js(
        js_str,
        bindings={
            "java": java,
            "source": book_source,
            "baseUrl": book_source.get_key(),
            "cookie": JsCookie(),
        },
        java_obj=java,
    )
    return "" if result is None else str(result).strip()


def get_explore_kinds(book_source: BookSource) -> List[ExploreKind]:
    rule_str = book_source.exploreUrl or ""
    if not rule_str.strip():
        return []

    try:
        resolved = _evaluate_explore_rule(book_source)
        if not resolved:
            return []
        try:
            data = json.loads(resolved)
        except Exception:
            data = None
        if isinstance(data, list):
            return [_parse_kind_item(item) for item in data]

        kinds: List[ExploreKind] = []
        for chunk in _KIND_SPLIT_RE.split(resolved):
            chunk = chunk.strip()
            if not chunk:
                continue
            title, _, url = chunk.partition("::")
            kinds.append(ExploreKind(title=title.strip(), url=url.strip() or None))
        return kinds
    except Exception as exc:
        return [ExploreKind(title=f"ERROR:{exc}", url=traceback.format_exc())]


def get_explore_kinds_json(book_source: BookSource) -> str:
    return json.dumps([
        {"title": kind.title, "url": kind.url, "style": kind.style}
        for kind in get_explore_kinds(book_source)
    ], ensure_ascii=False)
