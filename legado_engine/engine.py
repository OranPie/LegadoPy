from __future__ import annotations

import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests as _requests
from requests.adapters import HTTPAdapter

from .utils.cookie_store import CookieStore


class CacheStore:
    """Simple shared in-process cache exposed to JS and fetch pipelines."""

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}

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

    def export(self) -> Dict[str, Any]:
        return dict(self._store)

    def replace_all(self, values: Dict[str, Any]) -> None:
        self._store = dict(values)


@dataclass
class ReplaceContext:
    source_key: str = ""
    source_name: str = ""
    book_url: str = ""
    book_name: str = ""
    chapter_title: str = ""
    article_link: str = ""
    article_title: str = ""

    def tokens(self) -> List[str]:
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


@dataclass
class ConcurrentRateRecord:
    is_concurrent: bool
    time_ms: int
    frequency: int
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class ConcurrentRateLease:
    def __init__(self, record: Optional[ConcurrentRateRecord]) -> None:
        self._record = record

    def release(self) -> None:
        if self._record is None or self._record.is_concurrent:
            return
        with self._record.lock:
            self._record.frequency -= 1

    def __enter__(self) -> "ConcurrentRateLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class LegadoEngine:
    """Explicit headless engine/session state."""

    def __init__(self) -> None:
        self.cookie_store = CookieStore()
        self.cache = CacheStore()
        self.replace_rules: List[Any] = []
        self.rss_sources: Dict[str, Any] = {}
        self._text_cache: Dict[str, Dict[str, Any]] = {}
        self._rate_limit_records: Dict[str, ConcurrentRateRecord] = {}
        self._rate_limit_lock = threading.Lock()
        self._http_sessions: Dict[str, _requests.Session] = {}
        self._http_sessions_lock = threading.Lock()
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

    def set_replace_rules(self, rules: Iterable[Any]) -> None:
        self.replace_rules = list(rules)

    def add_replace_rule(self, rule: Any) -> None:
        self.replace_rules.append(rule)

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

    def _iter_sorted_rules(self) -> List[Any]:
        return sorted(
            self.replace_rules,
            key=lambda rule: (getattr(rule, "order", 0), getattr(rule, "id", 0)),
        )

    def apply_replace_rules(
        self,
        text: Optional[str],
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

    def apply_title(self, text: Optional[str], **context: Any) -> str:
        return self.apply_replace_rules(text, is_title=True, is_content=False, **context)

    def apply_content(self, text: Optional[str], **context: Any) -> str:
        return self.apply_replace_rules(text, is_title=False, is_content=True, **context)

    def get_cached_text(self, key: str) -> Optional[str]:
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

    def export_text_cache(self) -> Dict[str, Dict[str, Any]]:
        valid: Dict[str, Dict[str, Any]] = {}
        for key in list(self._text_cache.keys()):
            value = self.get_cached_text(key)
            if value is not None:
                valid[key] = dict(self._text_cache[key])
        return valid

    def replace_text_cache(self, values: Dict[str, Dict[str, Any]]) -> None:
        self._text_cache = {
            str(key): {
                "value": str((entry or {}).get("value", "")),
                "expires_at": float((entry or {}).get("expires_at", 0) or 0),
            }
            for key, entry in (values or {}).items()
        }

    def acquire_rate_limit(self, source: Any) -> ConcurrentRateLease:
        source_key = ""
        if source is not None:
            source_key = (
                getattr(source, "get_key", lambda: "")()
                or getattr(source, "getKey", lambda: "")()
                or getattr(source, "bookSourceUrl", "")
                or getattr(source, "sourceUrl", "")
            )
        concurrent_rate = (getattr(source, "concurrentRate", None) or "").strip()
        if not source_key or not concurrent_rate or concurrent_rate == "0":
            return ConcurrentRateLease(None)

        rate_index = concurrent_rate.find("/")
        while True:
            now_ms = int(time.time() * 1000)
            with self._rate_limit_lock:
                record = self._rate_limit_records.get(source_key)
                if record is None:
                    record = ConcurrentRateRecord(
                        is_concurrent=rate_index > 0,
                        time_ms=now_ms,
                        frequency=1,
                    )
                    self._rate_limit_records[source_key] = record
                    return ConcurrentRateLease(record)

            wait_ms = 0
            with record.lock:
                try:
                    if not record.is_concurrent:
                        limit_ms = int(concurrent_rate)
                        if record.frequency > 0:
                            wait_ms = limit_ms
                        else:
                            next_time = record.time_ms + limit_ms
                            if now_ms >= next_time:
                                record.time_ms = now_ms
                                record.frequency = 1
                                return ConcurrentRateLease(record)
                            wait_ms = next_time - now_ms
                    else:
                        max_count = int(concurrent_rate[:rate_index])
                        window_ms = int(concurrent_rate[rate_index + 1:])
                        next_time = record.time_ms + window_ms
                        if now_ms >= next_time:
                            record.time_ms = now_ms
                            record.frequency = 1
                            return ConcurrentRateLease(record)
                        if record.frequency > max_count:
                            wait_ms = next_time - now_ms
                        else:
                            record.frequency += 1
                            return ConcurrentRateLease(record)
                except Exception:
                    return ConcurrentRateLease(None)

            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)


_DEFAULT_ENGINE = LegadoEngine()


def get_default_engine() -> LegadoEngine:
    return _DEFAULT_ENGINE


def resolve_engine(engine: Optional[LegadoEngine] = None) -> LegadoEngine:
    return engine or _DEFAULT_ENGINE
