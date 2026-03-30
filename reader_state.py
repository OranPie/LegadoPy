from __future__ import annotations

import dataclasses
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from legado_engine import Book, BookChapter, BookSource, get_content

# Shared pool for background chapter preloads
_preload_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="legado-preload")


DEFAULT_READER_SETTINGS: Dict[str, Any] = {
    "reader_style": "comfortable",
    "preload_count": 2,
}


class ReaderState:
    """Persistent bookshelf, progress, settings, and chapter cache."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = Path(base_dir or (Path.home() / ".legado_py"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self.base_dir / "chapter_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.base_dir / "reader_state.json"
        self._lock = threading.RLock()
        self._active_preloads: set[str] = set()
        self._state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"settings": dict(DEFAULT_READER_SETTINGS), "bookshelf": [], "current_source": None}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data.setdefault("settings", {})
        merged_settings = dict(DEFAULT_READER_SETTINGS)
        merged_settings.update(data["settings"])
        data["settings"] = merged_settings
        data.setdefault("bookshelf", [])
        if not isinstance(data["bookshelf"], list):
            data["bookshelf"] = []
        data.setdefault("current_source", None)
        return data

    def _save(self) -> None:
        with self._lock:
            self.state_path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    @staticmethod
    def _book_key(source: BookSource, book: Book) -> str:
        return f"{source.bookSourceUrl}::{book.bookUrl}"

    @staticmethod
    def _serialize_book(book: Book) -> Dict[str, Any]:
        data = dataclasses.asdict(book)
        data["variable"] = book.variable
        data.pop("_var_map", None)
        return data

    @staticmethod
    def _deserialize_book(data: Dict[str, Any]) -> Book:
        book = Book(**{k: v for k, v in data.items() if k in Book.__dataclass_fields__})
        if book.variable:
            book.load_variable(book.variable)
        return book

    @staticmethod
    def _serialize_chapter(chapter: BookChapter) -> Dict[str, Any]:
        data = dataclasses.asdict(chapter)
        data["variable"] = chapter.variable
        data.pop("_var_map", None)
        return data

    @staticmethod
    def _deserialize_chapter(data: Dict[str, Any]) -> BookChapter:
        chapter = BookChapter(**{k: v for k, v in data.items() if k in BookChapter.__dataclass_fields__})
        if chapter.variable:
            chapter.load_variable(chapter.variable)
        return chapter

    def get_settings(self) -> Dict[str, Any]:
        return dict(self._state["settings"])

    def update_settings(self, **changes: Any) -> None:
        with self._lock:
            self._state["settings"].update(changes)
            self._save()

    def clear_cache(self) -> None:
        for path in self.cache_dir.glob("*.txt"):
            path.unlink(missing_ok=True)

    def get_current_source(self) -> Optional[BookSource]:
        data = self._state.get("current_source")
        if not isinstance(data, dict):
            return None
        try:
            source = BookSource.from_dict(data.get("source") or {})
            source._variables.update(data.get("source_variables") or {})
            return source
        except Exception:
            return None

    def set_current_source(self, source: BookSource) -> None:
        with self._lock:
            self._state["current_source"] = {
                "source": source.to_dict(),
                "source_variables": dict(source._variables),
            }
            self._save()

    def clear_current_source(self) -> None:
        with self._lock:
            self._state["current_source"] = None
            self._save()

    def list_bookshelf(self) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._state["bookshelf"])
        items.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
        return items

    def get_bookshelf_entry(self, source: BookSource, book: Book) -> Optional[Dict[str, Any]]:
        key = self._book_key(source, book)
        with self._lock:
            for entry in self._state["bookshelf"]:
                if entry.get("key") == key:
                    return dict(entry)
        return None

    def remember_book(self, source: BookSource, book: Book) -> Dict[str, Any]:
        key = self._book_key(source, book)
        now = int(time.time())
        with self._lock:
            for entry in self._state["bookshelf"]:
                if entry.get("key") == key:
                    entry["book"] = self._serialize_book(book)
                    entry["source"] = source.to_dict()
                    entry["source_variables"] = dict(source._variables)
                    entry["updated_at"] = now
                    self._save()
                    return dict(entry)
            entry = {
                "key": key,
                "added_at": now,
                "updated_at": now,
                "book": self._serialize_book(book),
                "source": source.to_dict(),
                "source_variables": dict(source._variables),
                "progress": {},
            }
            self._state["bookshelf"].append(entry)
            self._save()
            return dict(entry)

    def remove_book(self, key: str) -> None:
        with self._lock:
            self._state["bookshelf"] = [
                entry for entry in self._state["bookshelf"] if entry.get("key") != key
            ]
            self._save()

    def update_progress(
        self,
        source: BookSource,
        book: Book,
        chapter: BookChapter,
        *,
        scroll_y: float = 0.0,
        max_scroll_y: float = 0.0,
        total_chapters: Optional[int] = None,
    ) -> None:
        key = self._book_key(source, book)
        now = int(time.time())
        scroll_ratio = 0.0
        if max_scroll_y > 0:
            scroll_ratio = max(0.0, min(1.0, float(scroll_y) / float(max_scroll_y)))
        with self._lock:
            target = None
            for entry in self._state["bookshelf"]:
                if entry.get("key") == key:
                    target = entry
                    break
            if target is None:
                target = self.remember_book(source, book)
                for entry in self._state["bookshelf"]:
                    if entry.get("key") == key:
                        target = entry
                        break
            target["book"] = self._serialize_book(book)
            target["source"] = source.to_dict()
            target["source_variables"] = dict(source._variables)
            target["updated_at"] = now
            target["progress"] = {
                "chapter_index": chapter.index,
                "chapter_title": chapter.title,
                "chapter_url": chapter.url,
                "scroll_y": scroll_y,
                "max_scroll_y": max_scroll_y,
                "scroll_ratio": scroll_ratio,
                "chapter_total": total_chapters,
                "updated_at": now,
            }
            self._save()

    @staticmethod
    def restore_source(entry: Dict[str, Any]) -> BookSource:
        source = BookSource.from_dict(entry["source"])
        source._variables.update(entry.get("source_variables") or {})
        return source

    @classmethod
    def restore_book(cls, entry: Dict[str, Any]) -> Book:
        return cls._deserialize_book(entry["book"])

    @staticmethod
    def chapter_cache_key(source: BookSource, book: Book, chapter: BookChapter) -> str:
        raw = f"{source.bookSourceUrl}\n{book.bookUrl}\n{chapter.url}\n{chapter.title}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def get_cached_content(
        self,
        source: BookSource,
        book: Book,
        chapter: BookChapter,
    ) -> Optional[str]:
        path = self.cache_dir / f"{self.chapter_cache_key(source, book, chapter)}.txt"
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def set_cached_content(
        self,
        source: BookSource,
        book: Book,
        chapter: BookChapter,
        text: str,
    ) -> None:
        path = self.cache_dir / f"{self.chapter_cache_key(source, book, chapter)}.txt"
        path.write_text(text, encoding="utf-8")

    def preload_chapters(
        self,
        source: BookSource,
        book: Book,
        chapters: List[BookChapter],
        current_index: int,
        count: int,
    ) -> None:
        if count <= 0:
            return
        source_data = source.to_dict()
        book_data = self._serialize_book(book)
        chapter_data = [self._serialize_chapter(ch) for ch in chapters]
        preload_key = self._book_key(source, book)
        with self._lock:
            if preload_key in self._active_preloads:
                return
            self._active_preloads.add(preload_key)
        _preload_pool.submit(
            self._preload_worker,
            preload_key, source_data, book_data, chapter_data, current_index, count,
        )

    def _preload_worker(
        self,
        preload_key: str,
        source_data: Dict[str, Any],
        book_data: Dict[str, Any],
        chapter_data: List[Dict[str, Any]],
        current_index: int,
        count: int,
    ) -> None:
        try:
            source = BookSource.from_dict(source_data)
            book = self._deserialize_book(book_data)
            chapters = [self._deserialize_chapter(ch) for ch in chapter_data]
            start = current_index + 1
            stop = min(len(chapters), start + count)
            for idx in range(start, stop):
                chapter = chapters[idx]
                if self.get_cached_content(source, book, chapter) is not None:
                    continue
                next_chapter = chapters[idx + 1] if idx + 1 < len(chapters) else None
                try:
                    text = get_content(source, book, chapter, next_chapter)
                except Exception:
                    continue
                self.set_cached_content(source, book, chapter, text)
        finally:
            with self._lock:
                self._active_preloads.discard(preload_key)
