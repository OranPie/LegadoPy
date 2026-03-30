from __future__ import annotations

import base64
from typing import Any, Optional

from .analyze.analyze_url import AnalyzeUrl
from .engine import resolve_engine
from .js import JsExtensions, eval_js


def _get_decode_rule(source: Any, *, is_cover: bool) -> Optional[str]:
    if source is None:
        return None
    if hasattr(source, "coverDecodeJs"):
        if is_cover:
            return getattr(source, "coverDecodeJs", None)
        get_content_rule = getattr(source, "get_content_rule", None) or getattr(source, "getContentRule", None)
        if callable(get_content_rule):
            content_rule = get_content_rule()
            if content_rule is not None:
                return getattr(content_rule, "imageDecode", None)
    return None


def _normalize_binary_result(value: Any, fallback: bytes) -> bytes:
    if value is None:
        return fallback
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, list):
        try:
            return bytes(int(item) & 0xFF for item in value)
        except Exception:
            return fallback
    if isinstance(value, dict):
        if value.get("_legado_type") == "ByteArray" and value.get("base64") is not None:
            try:
                return base64.b64decode(str(value["base64"]))
            except Exception:
                return fallback
        if value.get("type") == "Buffer" and isinstance(value.get("data"), list):
            try:
                return bytes(int(item) & 0xFF for item in value["data"])
            except Exception:
                return fallback
    if hasattr(value, "to_list"):
        try:
            return bytes(int(item) & 0xFF for item in value.to_list())
        except Exception:
            return fallback
    return fallback


def decode_image_bytes(
    src: str,
    data: bytes,
    *,
    source: Any = None,
    book: Any = None,
    article: Any = None,
    is_cover: bool = False,
    engine=None,
) -> bytes:
    engine = resolve_engine(engine)
    rule_js = _get_decode_rule(source, is_cover=is_cover)
    if not rule_js or not str(rule_js).strip():
        return data
    result = eval_js(
        str(rule_js),
        result=data,
        bindings={
            "source": source,
            "book": book,
            "rssArticle": article,
            "src": src,
            "engine": engine,
        },
        java_obj=JsExtensions(source_getter=lambda: source, engine=engine),
    )
    return _normalize_binary_result(result, data)


def fetch_image_bytes(
    url: str,
    *,
    source: Any = None,
    book: Any = None,
    article: Any = None,
    is_cover: bool = False,
    engine=None,
) -> bytes:
    engine = resolve_engine(engine)
    analyze_url = AnalyzeUrl(url, source=source, rule_data=book or article, engine=engine)
    raw = analyze_url.get_byte_array()
    return decode_image_bytes(
        url,
        raw,
        source=source,
        book=book,
        article=article,
        is_cover=is_cover,
        engine=engine,
    )


def fetch_book_cover_bytes(source: Any, book: Any, *, engine=None) -> bytes:
    cover_url = getattr(book, "coverUrl", None) or ""
    if not cover_url:
        return b""
    return fetch_image_bytes(cover_url, source=source, book=book, is_cover=True, engine=engine)


def fetch_content_image_bytes(source: Any, book: Any, image_url: str, *, engine=None) -> bytes:
    return fetch_image_bytes(image_url, source=source, book=book, is_cover=False, engine=engine)


def fetch_rss_image_bytes(source: Any, article: Any, *, engine=None) -> bytes:
    image_url = getattr(article, "image", None) or ""
    if not image_url:
        return b""
    return fetch_image_bytes(image_url, source=source, article=article, is_cover=True, engine=engine)


__all__ = [
    "decode_image_bytes",
    "fetch_image_bytes",
    "fetch_book_cover_bytes",
    "fetch_content_image_bytes",
    "fetch_rss_image_bytes",
]
