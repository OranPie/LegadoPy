from __future__ import annotations

import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, List

import requests as _requests
from requests.adapters import HTTPAdapter

from .cache import CacheStore
from .rate_limit import ConcurrentRateLease, acquire_rate_limit
from .utils.cookie_store import CookieStore


@dataclass
class ReplaceContext:
    source_key: str = ""
    source_name: str = ""
    book_url: str = ""
    book_name: str = ""
    chapter_title: str = ""
    article_link: str = ""
    article_title: str = ""

    def tokens(self) -> list[str]:
        return [
            token
            for token in (
                self.source_key,
                self.source_name,
                self.book_url,
                self.book_name,
                self.chapter_title,
                self.article_link,
                self.article_title,
            )
            if token
        ]


class LegadoEngine:
    """Explicit headless engine/session state."""

    def __init__(self) -> None:
        self.cookie_store = CookieStore()
        self.cache = CacheStore()
        self.replace_rules: list[Any] = []
        self._sorted_rules_cache: list[Any] | None = None
        self.rss_sources: dict[str, Any] = {}
        self._text_cache: dict[str, dict[str, Any]] = {}
        self._rate_limit_records: dict[str, Any] = {}
        self._rate_limit_lock = threading.Lock()
        self._http_sessions: dict[str, _requests.Session] = {}
        self._http_sessions_lock = threading.Lock()
        # Shared executor for all engine I/O work (search, TOC, parse)
        _workers = min(32, (os.cpu_count() or 1) * 4)
        self.executor = ThreadPoolExecutor(
            max_workers=_workers,
            thread_name_prefix="legado",
        )
        token = uuid.uuid4().hex
        self.device_id = token
        self.android_id = token[:16]
        self.cookie_jar_path = str(Path(tempfile.gettempdir()) / f"legado_cookies_{token}.txt")

    def get_http_session(self, proxy: str = "") -> _requests.Session:
        key = str(proxy or "")
        with self._http_sessions_lock:
            session = self._http_sessions.get(key)
            if session is not None:
                return session
            session = _requests.Session()
            adapter = HTTPAdapter(
                pool_connections=10,
                pool_maxsize=20,
                max_retries=0,
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            if proxy:
                session.proxies = {"http": proxy, "https": proxy}
            self._http_sessions[key] = session
            return session

    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> Future:
        """Submit a callable to the shared engine thread pool."""
        return self.executor.submit(fn, *args, **kwargs)

    def shutdown(self, wait: bool = True) -> None:
        """Release all engine resources (executor, HTTP sessions)."""
        self.executor.shutdown(wait=wait)
        with self._http_sessions_lock:
            for sess in self._http_sessions.values():
                sess.close()
            self._http_sessions.clear()

    def set_replace_rules(self, rules: Iterable[Any]) -> None:
        self.replace_rules = list(rules)
        self._sorted_rules_cache = None

    def add_replace_rule(self, rule: Any) -> None:
        self.replace_rules.append(rule)
        self._sorted_rules_cache = None

    def register_rss_sources(self, sources: Iterable[Any]) -> None:
        for source in sources:
            key = getattr(source, "get_key", lambda: "")() or getattr(source, "sourceUrl", "")
            if key:
                self.rss_sources[key] = source

    def get_rss_source(self, key: str) -> Any:
        return self.rss_sources.get(key)

    def build_replace_context(
        self,
        source: Any = None,
        book: Any = None,
        chapter: Any = None,
        article: Any = None,
    ) -> ReplaceContext:
        return ReplaceContext(
            source_key=(
                getattr(source, "get_key", lambda: "")()
                or getattr(source, "getKey", lambda: "")()
                or getattr(source, "bookSourceUrl", "")
                or getattr(source, "sourceUrl", "")
            ),
            source_name=(
                getattr(source, "get_tag", lambda: "")()
                or getattr(source, "getTag", lambda: "")()
                or getattr(source, "bookSourceName", "")
                or getattr(source, "sourceName", "")
            ),
            book_url=getattr(book, "bookUrl", ""),
            book_name=getattr(book, "name", ""),
            chapter_title=getattr(chapter, "title", ""),
            article_link=getattr(article, "link", ""),
            article_title=getattr(article, "title", ""),
        )

    def _iter_sorted_rules(self) -> list[Any]:
        if self._sorted_rules_cache is None:
            self._sorted_rules_cache = sorted(
                self.replace_rules,
                key=lambda rule: (getattr(rule, "order", 0), getattr(rule, "id", 0)),
            )
        return self._sorted_rules_cache

    def apply_replace_rules(
        self,
        text: str | None,
        *,
        is_title: bool,
        is_content: bool,
        source: Any = None,
        book: Any = None,
        chapter: Any = None,
        article: Any = None,
        use_replace: bool = True,
    ) -> str:
        if not text or not use_replace:
            return text or ""
        context = self.build_replace_context(source=source, book=book, chapter=chapter, article=article)
        result = text
        for rule in self._iter_sorted_rules():
            if getattr(rule, "applies_to", None) and rule.applies_to(
                context.tokens(),
                is_title=is_title,
                is_content=is_content,
            ):
                result = rule.apply(result)
        return result

    def apply_title(self, text: str | None, **context: Any) -> str:
        return self.apply_replace_rules(text, is_title=True, is_content=False, **context)

    def apply_content(self, text: str | None, **context: Any) -> str:
        return self.apply_replace_rules(text, is_title=False, is_content=True, **context)

    def get_cached_text(self, key: str) -> str | None:
        entry = self._text_cache.get(str(key))
        if not entry:
            return None
        expires_at = entry.get("expires_at")
        if expires_at and time.time() > float(expires_at):
            self._text_cache.pop(str(key), None)
            return None
        return str(entry.get("value", ""))

    def put_cached_text(self, key: str, value: str, save_seconds: int = 0) -> None:
        expires_at = time.time() + int(save_seconds) if save_seconds and int(save_seconds) > 0 else 0
        self._text_cache[str(key)] = {
            "value": str(value),
            "expires_at": expires_at,
        }

    def export_text_cache(self) -> dict[str, dict[str, Any]]:
        valid: dict[str, dict[str, Any]] = {}
        for key in list(self._text_cache.keys()):
            value = self.get_cached_text(key)
            if value is not None:
                valid[key] = dict(self._text_cache[key])
        return valid

    def replace_text_cache(self, values: dict[str, dict[str, Any]]) -> None:
        self._text_cache = {
            str(key): {
                "value": str((entry or {}).get("value", "")),
                "expires_at": float((entry or {}).get("expires_at", 0) or 0),
            }
            for key, entry in (values or {}).items()
        }

    def acquire_rate_limit(self, source: Any) -> ConcurrentRateLease:
        return acquire_rate_limit(source, self._rate_limit_records, self._rate_limit_lock)


_DEFAULT_ENGINE = LegadoEngine()


def get_default_engine() -> LegadoEngine:
    return _DEFAULT_ENGINE


def resolve_engine(engine: LegadoEngine | None = None) -> LegadoEngine:
    return engine or _DEFAULT_ENGINE
