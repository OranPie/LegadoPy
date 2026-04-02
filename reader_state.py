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
    "re_segment": False,         # re-segment poorly-formatted chapters
    "use_replace_rules": True,   # apply user replace rules to content
    "paragraph_indent": True,    # prepend　　to each paragraph
}


class ReaderState:
    """Persistent bookshelf, progress, settings, and chapter cache."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = Path(base_dir or (Path.home() / ".legado_py"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self.base_dir / "chapter_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.toc_cache_dir = self.base_dir / "toc_cache"
        self.toc_cache_dir.mkdir(parents=True, exist_ok=True)
        self.book_info_dir = self.base_dir / "book_info"
        self.book_info_dir.mkdir(parents=True, exist_ok=True)
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
        data.setdefault("search_history", [])
        if not isinstance(data["search_history"], list):
            data["search_history"] = []
        return data

    def _save(self) -> None:
        with self._lock:
            self.state_path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # ------------------------------------------------------------------
    # Search history
    # ------------------------------------------------------------------

    def add_search_history(self, query: str, max_entries: int = 50) -> None:
        """Prepend query to history, deduplicate, cap at max_entries."""
        query = query.strip()
        if not query:
            return
        with self._lock:
            history = self._state["search_history"]
            # Remove existing occurrence for dedup
            history = [q for q in history if q != query]
            history.insert(0, query)
            self._state["search_history"] = history[:max_entries]
            self._save()

    def get_search_history(self) -> List[str]:
        return list(self._state.get("search_history", []))

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

    def invalidate_cached_content(
        self,
        source: BookSource,
        book: Book,
        chapter: BookChapter,
    ) -> None:
        """Delete the on-disk cache entry for a single chapter."""
        path = self.cache_dir / f"{self.chapter_cache_key(source, book, chapter)}.txt"
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Persistent TOC (chapter list) cache
    # ------------------------------------------------------------------

    @staticmethod
    def _toc_cache_key(source: "BookSource", book: "Book") -> str:
        raw = f"{source.bookSourceUrl}\n{book.bookUrl}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def get_cached_toc(
        self,
        source: "BookSource",
        book: "Book",
    ) -> Optional[List["BookChapter"]]:
        path = self.toc_cache_dir / f"{self._toc_cache_key(source, book)}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [self._deserialize_chapter(ch) for ch in data]
        except Exception:
            return None

    def set_cached_toc(
        self,
        source: "BookSource",
        book: "Book",
        chapters: List["BookChapter"],
    ) -> None:
        path = self.toc_cache_dir / f"{self._toc_cache_key(source, book)}.json"
        try:
            path.write_text(
                json.dumps([self._serialize_chapter(ch) for ch in chapters], ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def invalidate_cached_toc(self, source: "BookSource", book: "Book") -> None:
        path = self.toc_cache_dir / f"{self._toc_cache_key(source, book)}.json"
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Persistent book-info cache
    # ------------------------------------------------------------------

    @staticmethod
    def _book_info_key(source: "BookSource", book: "Book") -> str:
        raw = f"{source.bookSourceUrl}\n{book.bookUrl}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def get_cached_book_info(
        self,
        source: "BookSource",
        book: "Book",
    ) -> Optional["Book"]:
        path = self.book_info_dir / f"{self._book_info_key(source, book)}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return self._deserialize_book(data)
        except Exception:
            return None

    def set_cached_book_info(self, source: "BookSource", book: "Book") -> None:
        path = self.book_info_dir / f"{self._book_info_key(source, book)}.json"
        try:
            path.write_text(
                json.dumps(self._serialize_book(book), ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def invalidate_cached_book_info(self, source: "BookSource", book: "Book") -> None:
        path = self.book_info_dir / f"{self._book_info_key(source, book)}.json"
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

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
        # Only serialise the chapters we'll actually fetch (skip already-cached ones)
        start = current_index + 1
        stop = min(len(chapters), start + count)
        targets = [i for i in range(start, stop)
                   if self.get_cached_content(source, book, chapters[i]) is None]
        if not targets:
            return

        source_data = source.to_dict()
        book_data = self._serialize_book(book)
        chapter_data = [self._serialize_chapter(ch) for ch in chapters]

        # Use per-chapter keys so multiple chapters can preload simultaneously
        with self._lock:
            new_targets = [i for i in targets
                           if f"{self._book_key(source, book)}:{i}" not in self._active_preloads]
            for i in new_targets:
                self._active_preloads.add(f"{self._book_key(source, book)}:{i}")
        if not new_targets:
            return

        _preload_pool.submit(
            self._preload_worker,
            self._book_key(source, book), source_data, book_data,
            chapter_data, new_targets,
        )

    def _preload_worker(
        self,
        book_key: str,
        source_data: Dict[str, Any],
        book_data: Dict[str, Any],
        chapter_data: List[Dict[str, Any]],
        target_indices: List[int],
    ) -> None:
        """Fetch target chapter indices concurrently, write each to disk as it finishes."""
        from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _as_completed

        source = BookSource.from_dict(source_data)
        book = self._deserialize_book(book_data)
        chapters = [self._deserialize_chapter(ch) for ch in chapter_data]

        def _fetch(idx: int) -> tuple[int, str]:
            chapter = chapters[idx]
            next_chapter = chapters[idx + 1] if idx + 1 < len(chapters) else None
            return idx, get_content(source, book, chapter, next_chapter)

        n_workers = min(len(target_indices), 4)
        try:
            with _TPE(max_workers=n_workers, thread_name_prefix="legado-preload-inner") as pool:
                futures = {pool.submit(_fetch, i): i for i in target_indices}
                for fut in _as_completed(futures):
                    idx = futures[fut]
                    try:
                        _, text = fut.result()
                        self.set_cached_content(source, book, chapters[idx], text)
                    except Exception:
                        pass
        finally:
            with self._lock:
                for i in target_indices:
                    self._active_preloads.discard(f"{book_key}:{i}")
