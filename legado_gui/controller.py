from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from legado_engine import (
    Book,
    BookChapter,
    BookSource,
    ExploreKind,
    SearchBook,
    explore_book,
    get_explore_kinds,
    get_book_info,
    get_chapter_list,
    get_content,
    search_book,
)
from legado_engine.auth.login import (
    SourceUiActionResult,
    UiRow,
    execute_source_ui_action,
    get_source_form_data,
    parse_source_ui,
    submit_source_form_detailed,
)
from legado_engine.web_book.web_book import search_books_parallel

from reader_state import ReaderState


def load_source_text(text: str) -> BookSource:
    try:
        return BookSource.from_json(text)
    except Exception:
        data = json.loads(text)
        if isinstance(data, list) and data:
            return BookSource.from_dict(data[0])
        raise


def load_source_file(path: str | Path) -> BookSource:
    return load_source_text(Path(path).read_text(encoding="utf-8"))


def _rank_search_results(
    results: List[SearchBook],
    query: str,
    *,
    precision_search: bool = False,
) -> List[SearchBook]:
    """
    Rank and merge search results matching Android SearchModel.mergeItems().

    3-tier bucketing (Kotlin: equalData / containsData / otherData):
      Tier 3 — name == query  OR  author == query  (exact)
      Tier 2 — name contains query  OR  author contains query
      Tier 1 — any other result  (discarded when precision_search=True)

    Within each tier, results with the same (name, author) are *merged*:
    the first entry is kept as the representative and its ``origin_count``
    is incremented for every additional source that returned the same title.
    Books with more origins sort higher within the same tier.
    """
    q_lower = query.strip().lower()
    words = [w for w in re.split(r'\s+', q_lower) if w]

    def _tier(sb: SearchBook) -> int:
        name = (sb.name or "").lower()
        author = (sb.author or "").lower()
        if name == q_lower or author == q_lower:
            return 3
        if q_lower in name or q_lower in author:
            return 2
        if words and (any(w in name for w in words) or any(w in author for w in words)):
            return 1
        return 0

    # Assign tiers
    tiered = [(sb, _tier(sb)) for sb in results]

    if precision_search:
        tiered = [(sb, t) for sb, t in tiered if t >= 2]

    # Merge same (name, author) items, tracking origin count
    # key → (representative SearchBook, tier, origin_count)
    merged: dict[tuple, tuple] = {}
    for sb, t in tiered:
        key = ((sb.name or "").lower(), (sb.author or "").lower())
        if key in merged:
            rep, rep_t, cnt = merged[key]
            # Keep the entry from the higher-tier source; accumulate count
            if t > rep_t:
                merged[key] = (sb, t, cnt + 1)
            else:
                merged[key] = (rep, rep_t, cnt + 1)
        else:
            merged[key] = (sb, t, 1)

    # Sort: tier desc, then origin_count desc (more sources → higher rank)
    sorted_entries = sorted(merged.values(), key=lambda x: (x[1], x[2]), reverse=True)

    # Attach origin_count to the SearchBook objects for display use
    ranked: List[SearchBook] = []
    for rep, _t, cnt in sorted_entries:
        if cnt > 1:
            rep = copy.copy(rep)
            rep._origin_count = cnt  # type: ignore[attr-defined]
        ranked.append(rep)
    return ranked


@dataclass
class ReaderSession:
    source_path: Optional[str] = None
    source: Optional[BookSource] = None
    search_results: List[SearchBook] = field(default_factory=list)
    explore_kinds: List[ExploreKind] = field(default_factory=list)
    active_explore_kind: Optional[ExploreKind] = None
    explore_results: List[SearchBook] = field(default_factory=list)
    book: Optional[Book] = None
    chapters: List[BookChapter] = field(default_factory=list)
    current_chapter_index: Optional[int] = None


class ReaderController:
    def __init__(self, state: Optional[ReaderState] = None) -> None:
        self.state = state or ReaderState()
        self.session = ReaderSession()
        self._search_cache: Dict[Tuple[str, str, int], List[SearchBook]] = {}
        self._explore_kind_cache: Dict[str, List[ExploreKind]] = {}
        self._explore_cache: Dict[Tuple[str, str, int], List[SearchBook]] = {}
        self._book_cache: Dict[Tuple[str, str], Book] = {}
        self._chapter_cache: Dict[Tuple[str, str], List[BookChapter]] = {}

    def _require_source(self) -> BookSource:
        if not self.session.source:
            raise ValueError("No source loaded")
        return self.session.source

    def has_source_auth(self) -> bool:
        source = self._require_source()
        return bool(source.loginUi or source.loginUrl)

    def get_source_auth_rows(self) -> List[UiRow]:
        source = self._require_source()
        rows = parse_source_ui(source)
        if rows:
            return rows
        if source.loginUrl:
            return [
                UiRow(name="邮箱", type="text"),
                UiRow(name="密码", type="password"),
                UiRow(name="密钥", type="text"),
                UiRow(name="自定义服务器(可不填)", type="text"),
            ]
        return []

    def get_source_auth_form_data(self) -> Dict[str, str]:
        return dict(get_source_form_data(self._require_source()))

    def describe_source_auth(self) -> str:
        source = self._require_source()
        info = [
            f"Source: {source.bookSourceName or '—'}",
            f"URL: {source.bookSourceUrl or '—'}",
            f"loginUi: {'yes' if source.loginUi else 'no'}",
            f"loginUrl: {'yes' if source.loginUrl else 'no'}",
            f"saved_header: {'yes' if source.getLoginHeader().strip() else 'no'}",
            f"saved_fields: {len(source.getLoginInfoMap())}",
        ]
        return "\n".join(info)

    def get_source_login_header(self) -> str:
        return self._require_source().getLoginHeader().strip()

    def clear_source_login_header(self) -> None:
        source = self._require_source()
        source.removeLoginHeader()
        self.state.set_current_source(source)

    def submit_source_auth(self, form_data: Dict[str, str]) -> SourceUiActionResult:
        source = self._require_source()
        outcome = submit_source_form_detailed(source, form_data)
        self.state.set_current_source(source)
        return outcome

    def run_source_auth_action(
        self,
        action: str,
        form_data: Dict[str, str],
    ) -> SourceUiActionResult:
        source = self._require_source()
        outcome = execute_source_ui_action(source, action, form_data)
        self.state.set_current_source(source)
        return outcome

    def load_source(self, path: str | Path) -> BookSource:
        source = load_source_file(path)
        self._clear_source_cache(source.bookSourceUrl)
        self.session = ReaderSession(source_path=str(path), source=source)
        self.state.set_current_source(source)
        return source

    def set_source(self, source: BookSource, source_path: Optional[str] = None) -> None:
        self.session = ReaderSession(source_path=source_path, source=source)
        self.state.set_current_source(source)

    def reload_source(self) -> BookSource:
        if not self.session.source_path:
            raise ValueError("No source file path recorded")
        return self.load_source(self.session.source_path)

    def search(self, query: str, page: int = 1, *, force_refresh: bool = False, precision_search: bool = False) -> List[SearchBook]:
        source = self._require_source()
        cache_key = (source.bookSourceUrl, query, page)
        results = None if force_refresh else self._search_cache.get(cache_key)
        if results is None:
            results = search_book(source, query, page=page)
            results = _rank_search_results(results, query, precision_search=precision_search)
            self._search_cache[cache_key] = copy.deepcopy(results)
        else:
            results = copy.deepcopy(results)
        self.session.search_results = results
        return results

    def search_all_sources(
        self,
        sources: List[BookSource],
        query: str,
        page: int = 1,
        *,
        force_refresh: bool = False,
        precision_search: bool = False,
        result_callback: Optional[Callable[[List[SearchBook]], None]] = None,
    ) -> List[SearchBook]:
        """
        Search across multiple sources in parallel and return ranked+merged results.

        Implements Android SearchModel.mergeItems() 3-tier ranking with
        origin-count deduplication: same (name, author) across sources are merged
        and sorted by how many sources returned them.

        ``result_callback`` is called incrementally as each source returns,
        allowing streaming UIs to show results before all sources finish.
        """
        if not sources:
            return []

        # Check the per-source caches first unless force_refresh
        uncached_sources: List[BookSource] = []
        cached_results: List[SearchBook] = []
        for src in sources:
            key = (src.bookSourceUrl, query, page)
            if not force_refresh and key in self._search_cache:
                cached_results.extend(copy.deepcopy(self._search_cache[key]))
            else:
                uncached_sources.append(src)

        all_results = list(cached_results)

        if uncached_sources:
            from legado_engine.engine import resolve_engine
            from concurrent.futures import as_completed

            engine = resolve_engine(None)

            def _fetch_one(src: BookSource) -> List[SearchBook]:
                try:
                    r = search_book(src, query, page=page)
                    self._search_cache[(src.bookSourceUrl, query, page)] = copy.deepcopy(r)
                    return r
                except Exception:
                    return []

            futures = {engine.executor.submit(_fetch_one, src): src for src in uncached_sources}
            for fut in as_completed(futures):
                try:
                    batch = fut.result()
                    if batch:
                        all_results.extend(batch)
                        if result_callback:
                            result_callback(_rank_search_results(
                                list(all_results), query,
                                precision_search=precision_search,
                            ))
                except Exception:
                    pass

        ranked = _rank_search_results(all_results, query, precision_search=precision_search)
        self.session.search_results = ranked
        return ranked

    def load_explore_kinds(self, *, force_refresh: bool = False) -> List[ExploreKind]:
        source = self._require_source()
        source_key = source.bookSourceUrl
        kinds = None if force_refresh else self._explore_kind_cache.get(source_key)
        if kinds is None:
            kinds = get_explore_kinds(source)
            self._explore_kind_cache[source_key] = copy.deepcopy(kinds)
        else:
            kinds = copy.deepcopy(kinds)
        self.session.explore_kinds = kinds
        self.session.active_explore_kind = None
        self.session.explore_results = []
        return kinds

    def explore(self, kind: ExploreKind, page: int = 1, *, force_refresh: bool = False) -> List[SearchBook]:
        source = self._require_source()
        if not kind.url:
            raise ValueError("Selected category has no URL")
        cache_key = (source.bookSourceUrl, kind.url, page)
        results = None if force_refresh else self._explore_cache.get(cache_key)
        if results is None:
            results = explore_book(source, kind.url, page=page)
            self._explore_cache[cache_key] = copy.deepcopy(results)
        else:
            results = copy.deepcopy(results)
        self.session.active_explore_kind = kind
        self.session.explore_results = results
        return results

    def open_search_result(self, result: SearchBook, *, force_refresh: bool = False) -> Book:
        if not self.session.source:
            raise ValueError("No source loaded")
        book = result.to_book()
        return self.open_book(book, force_refresh=force_refresh)

    def open_explore_result(self, result: SearchBook, *, force_refresh: bool = False) -> Book:
        return self.open_search_result(result, force_refresh=force_refresh)

    def open_book(self, book: Book, *, force_refresh: bool = False) -> Book:
        source = self._require_source()
        cache_key = self._book_cache_key(source, book)
        hydrated = None if force_refresh else self._book_cache.get(cache_key)
        if hydrated is None and not force_refresh:
            # Try persistent disk cache before network fetch
            hydrated = self.state.get_cached_book_info(source, book)
        if hydrated is None:
            hydrated = get_book_info(source, book, can_rename=True)
            self.state.set_cached_book_info(source, hydrated)
        self._book_cache[cache_key] = copy.deepcopy(hydrated)
        hydrated = copy.deepcopy(hydrated)
        self.session.book = hydrated
        self.session.chapters = []
        self.session.current_chapter_index = None
        self.state.remember_book(source, hydrated)
        return hydrated

    def load_chapters(
        self,
        chapter_batch_fn: Callable[[List[BookChapter]], None] | None = None,
        *,
        force_refresh: bool = False,
    ) -> List[BookChapter]:
        source = self._require_source()
        if not self.session.book:
            raise ValueError("No active book")
        cache_key = self._chapter_cache_key(source, self.session.book)
        if force_refresh:
            self.state.invalidate_cached_toc(source, self.session.book)
        chapters = None if force_refresh else self._chapter_cache.get(cache_key)
        if chapters is None and not force_refresh:
            # Try persistent disk TOC cache
            chapters = self.state.get_cached_toc(source, self.session.book)
        if chapters is None:
            chapters = get_chapter_list(
                source, self.session.book, chapter_batch_fn=chapter_batch_fn
            )
            self.state.set_cached_toc(source, self.session.book, chapters)
            self._chapter_cache[cache_key] = copy.deepcopy(chapters)
        else:
            # Serve from cache but still stream a single batch so callers
            # don't need to special-case the cached path.
            chapters = copy.deepcopy(chapters)
            self._chapter_cache[cache_key] = copy.deepcopy(chapters)
            if chapter_batch_fn:
                chapter_batch_fn(list(chapters))
        self.session.chapters = chapters
        return chapters
        self.session.chapters = chapters
        return chapters

    def list_bookshelf_entries(self) -> List[Dict[str, Any]]:
        return self.state.list_bookshelf()

    def open_bookshelf_entry(self, key: str) -> Book:
        for entry in self.state.list_bookshelf():
            if entry.get("key") == key:
                source = self.state.restore_source(entry)
                book = self.state.restore_book(entry)
                self.set_source(source, source_path=None)
                self.session.book = book
                self.session.chapters = []
                self.session.current_chapter_index = None
                self.state.set_current_source(source)
                return book
        raise KeyError(f"Bookshelf entry not found: {key}")

    def remove_bookshelf_entry(self, key: str) -> None:
        self.state.remove_book(key)

    def get_current_progress(self) -> Optional[Dict[str, Any]]:
        if not self.session.source or not self.session.book:
            return None
        entry = self.state.get_bookshelf_entry(self.session.source, self.session.book)
        if not entry:
            return None
        progress = entry.get("progress")
        return dict(progress) if isinstance(progress, dict) else None

    def resume_current_book(self) -> str:
        if not self.session.book:
            raise ValueError("No active book")
        if not self.session.chapters:
            self.load_chapters()
        progress = self.get_current_progress() or {}
        chapter_index = int(progress.get("chapter_index", 0) or 0)
        chapter_index = max(0, min(chapter_index, max(0, len(self.session.chapters) - 1)))
        return self._load_chapter_content(chapter_index, preserve_progress=True)

    def update_settings(self, **changes: Any) -> None:
        self.state.update_settings(**changes)

    def get_settings(self) -> Dict[str, Any]:
        return self.state.get_settings()

    def get_chapter_content(self, chapter_index: int, *, force_refresh: bool = False) -> str:
        return self._load_chapter_content(chapter_index, preserve_progress=False, force_refresh=force_refresh)

    def force_refresh_chapter(self, chapter_index: int) -> str:
        """Re-fetch a chapter bypassing all caches, update the cache with fresh content."""
        return self._load_chapter_content(chapter_index, preserve_progress=False, force_refresh=True)

    def force_refresh_current_chapter(self) -> str:
        """Re-fetch the current chapter bypassing all caches."""
        if self.session.current_chapter_index is None:
            raise ValueError("No chapter currently loaded")
        return self.force_refresh_chapter(self.session.current_chapter_index)

    def update_current_scroll(self, scroll_ratio: float) -> Optional[Dict[str, Any]]:
        if not self.session.source or not self.session.book:
            return None
        chapter = self.get_current_chapter()
        if chapter is None:
            return None
        clamped_ratio = max(0.0, min(1.0, float(scroll_ratio)))
        self.state.update_progress(
            self.session.source,
            self.session.book,
            chapter,
            scroll_y=clamped_ratio,
            max_scroll_y=1.0,
            total_chapters=len(self.session.chapters),
        )
        return self.get_current_progress()

    def _load_chapter_content(self, chapter_index: int, *, preserve_progress: bool, force_refresh: bool = False) -> str:
        if not self.session.source or not self.session.book:
            raise ValueError("No active book")
        if chapter_index < 0 or chapter_index >= len(self.session.chapters):
            raise IndexError("Chapter index out of range")
        chapter = self.session.chapters[chapter_index]
        if force_refresh:
            self.state.invalidate_cached_content(self.session.source, self.session.book, chapter)
        cached = self.state.get_cached_content(self.session.source, self.session.book, chapter)
        if cached is None:
            next_chapter = (
                self.session.chapters[chapter_index + 1]
                if chapter_index + 1 < len(self.session.chapters)
                else None
            )
            # Apply reader settings to the book before fetching
            settings = self.state.get_settings()
            self.session.book.set_re_segment(settings.get("re_segment", False))
            self.session.book.set_use_replace_rule(settings.get("use_replace_rules", True))
            self.session.book.set_chinese_convert(int(settings.get("chinese_convert", 0)))
            cached = get_content(self.session.source, self.session.book, chapter, next_chapter)
            self.state.set_cached_content(self.session.source, self.session.book, chapter, cached)
        self.session.current_chapter_index = chapter_index
        progress = self.get_current_progress() or {}
        progress_chapter_index_raw = progress.get("chapter_index")
        progress_chapter_index = (
            int(progress_chapter_index_raw) if progress_chapter_index_raw is not None else -1
        )
        scroll_y = 0.0
        max_scroll_y = 0.0
        if preserve_progress and progress_chapter_index == chapter_index:
            scroll_y = float(progress.get("scroll_y", 0.0) or 0.0)
            max_scroll_y = float(progress.get("max_scroll_y", 0.0) or 0.0)
        self.state.update_progress(
            self.session.source,
            self.session.book,
            chapter,
            scroll_y=scroll_y,
            max_scroll_y=max_scroll_y,
            total_chapters=len(self.session.chapters),
        )
        settings = self.state.get_settings()
        preload_count = int(settings.get("preload_count", 0) or 0)
        if preload_count > 0:
            self.state.preload_chapters(
                self.session.source,
                self.session.book,
                self.session.chapters,
                chapter_index,
                preload_count,
            )
        return cached

    def get_current_chapter(self) -> Optional[BookChapter]:
        if self.session.current_chapter_index is None:
            return None
        if 0 <= self.session.current_chapter_index < len(self.session.chapters):
            return self.session.chapters[self.session.current_chapter_index]
        return None

    def can_go_previous(self) -> bool:
        return self.session.current_chapter_index is not None and self.session.current_chapter_index > 0

    def can_go_next(self) -> bool:
        return (
            self.session.current_chapter_index is not None
            and self.session.current_chapter_index + 1 < len(self.session.chapters)
        )

    def go_previous(self) -> str:
        if not self.can_go_previous():
            raise ValueError("No previous chapter")
        return self.get_chapter_content(int(self.session.current_chapter_index) - 1)

    def go_next(self) -> str:
        if not self.can_go_next():
            raise ValueError("No next chapter")
        return self.get_chapter_content(int(self.session.current_chapter_index) + 1)

    @staticmethod
    def _book_cache_key(source: BookSource, book: Book) -> Tuple[str, str]:
        return (source.bookSourceUrl, book.bookUrl)

    @staticmethod
    def _chapter_cache_key(source: BookSource, book: Book) -> Tuple[str, str]:
        return (source.bookSourceUrl, book.tocUrl or book.bookUrl)

    def _clear_source_cache(self, source_url: str) -> None:
        self._search_cache = {
            key: value for key, value in self._search_cache.items() if key[0] != source_url
        }
        self._explore_kind_cache.pop(source_url, None)
        self._explore_cache = {
            key: value for key, value in self._explore_cache.items() if key[0] != source_url
        }
        self._book_cache = {
            key: value for key, value in self._book_cache.items() if key[0] != source_url
        }
        self._chapter_cache = {
            key: value for key, value in self._chapter_cache.items() if key[0] != source_url
        }
