from __future__ import annotations

import dataclasses
import json
import logging
import os
from typing import Any, Dict, Iterable


TRACE_ENV = "LEGADO_TRACE"
TRACE_FILE_ENV = "LEGADO_TRACE_FILE"
_TRACE_LOGGER_NAME = "legado.trace"
_TRACE_CONFIGURED = False


def trace_enabled() -> bool:
    value = os.getenv(TRACE_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on", "debug", "trace"}


def configure_trace_logging(*, force: bool = False) -> logging.Logger:
    global _TRACE_CONFIGURED
    logger = logging.getLogger(_TRACE_LOGGER_NAME)
    if _TRACE_CONFIGURED or (not force and not trace_enabled()):
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        trace_file = os.getenv(TRACE_FILE_ENV, "").strip()
        handler: logging.Handler
        if trace_file:
            handler = logging.FileHandler(trace_file, encoding="utf-8")
        else:
            handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)
    _TRACE_CONFIGURED = True
    return logger


def _trim_text(value: str, *, limit: int = 240) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...<{len(value)} chars>"


def _safe_iterable(value: Iterable[Any], *, limit: int = 5) -> list[Any]:
    items = list(value)
    return [_safe_value(item) for item in items[:limit]] + (
        [f"...<{len(items)} items>"] if len(items) > limit else []
    )


def _safe_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _trim_text(value)
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if dataclasses.is_dataclass(value):
        return {
            field.name: _safe_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if not field.name.startswith("_")
        }
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 10:
                result["..."] = f"<{len(value)} items>"
                break
            result[str(key)] = _safe_value(item)
        return result
    if isinstance(value, (list, tuple, set)):
        return _safe_iterable(value)
    return _trim_text(repr(value))


def trace_event(event: str, **fields: Any) -> None:
    if not trace_enabled():
        return
    logger = configure_trace_logging()
    payload = {key: _safe_value(value) for key, value in fields.items()}
    logger.debug("%s %s", event, json.dumps(payload, ensure_ascii=False, sort_keys=True))


def trace_exception(event: str, exc: BaseException, **fields: Any) -> None:
    if not trace_enabled():
        return
    logger = configure_trace_logging()
    payload = {key: _safe_value(value) for key, value in fields.items()}
    logger.exception(
        "%s %s",
        event,
        json.dumps(
            {
                **payload,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )


def snapshot_source(source: Any) -> Dict[str, Any]:
    return {
        "bookSourceName": getattr(source, "bookSourceName", None),
        "bookSourceUrl": getattr(source, "bookSourceUrl", None),
        "searchUrl": getattr(source, "searchUrl", None),
        "exploreUrl": getattr(source, "exploreUrl", None),
        "bookSourceType": getattr(source, "bookSourceType", None),
    }


def snapshot_book(book: Any) -> Dict[str, Any]:
    return {
        "name": getattr(book, "name", None),
        "author": getattr(book, "author", None),
        "kind": getattr(book, "kind", None),
        "wordCount": getattr(book, "wordCount", None),
        "latestChapterTitle": getattr(book, "latestChapterTitle", None),
        "bookUrl": getattr(book, "bookUrl", None),
        "tocUrl": getattr(book, "tocUrl", None),
        "coverUrl": getattr(book, "coverUrl", None),
        "intro_len": len(getattr(book, "intro", "") or ""),
        "type": getattr(book, "type", None),
        "durChapterIndex": getattr(book, "durChapterIndex", None),
        "durChapterTitle": getattr(book, "durChapterTitle", None),
        "totalChapterNum": getattr(book, "totalChapterNum", None),
    }


def snapshot_chapter(chapter: Any) -> Dict[str, Any]:
    return {
        "index": getattr(chapter, "index", None),
        "title": getattr(chapter, "title", None),
        "url": getattr(chapter, "url", None),
        "isVolume": getattr(chapter, "isVolume", None),
        "isVip": getattr(chapter, "isVip", None),
        "isPay": getattr(chapter, "isPay", None),
    }
