"""
Book, BookChapter, SearchBook, RuleData – 1:1 port of Legado entities.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any

from ..debug import snapshot_book, trace_event


@dataclass
class RuleData:
    """Mirrors RuleDataInterface + RuleData.kt – holds per-source variable state."""
    variable: str | None = None  # serialized JSON variable map
    _var_map: dict[str, str] = field(default_factory=dict, repr=False)

    def _sync_variable_blob(self) -> None:
        self.variable = json.dumps(self._var_map, ensure_ascii=False) if self._var_map else None

    def put_variable(self, key: str, value: str | None) -> None:
        if value is None:
            self._var_map.pop(key, None)
        else:
            self._var_map[key] = value
        self._sync_variable_blob()

    def get_variable(self, key: str) -> str | None:
        return self._var_map.get(key)

    def get_variable_map(self) -> dict[str, str]:
        return dict(self._var_map)

    def get_variable_json(self) -> str:
        return json.dumps(self._var_map, ensure_ascii=False)

    def load_variable(self, json_str: str | None) -> None:
        try:
            self._var_map = json.loads(json_str or "") or {}
        except Exception:
            self._var_map = {}
        self._sync_variable_blob()

    def load_variable_map(self, values: Optional[dict[str, Any]]) -> None:
        if values:
            self._var_map = {
                str(key): "" if value is None else str(value)
                for key, value in values.items()
            }
        else:
            self._var_map = {}
        self._sync_variable_blob()

    def putVariable(self, key: str, value: str | None) -> bool:  # noqa: N802
        self.put_variable(key, value)
        return True

    def getVariable(self, key: str) -> str:  # noqa: N802
        return self.get_variable(key) or ""

    def getVariableMap(self) -> dict[str, str]:  # noqa: N802
        return self.get_variable_map()


@dataclass
class Book(RuleData):
    """Mirrors Book.kt – represents a book being read."""
    bookUrl: str = ""
    origin: str = ""            # bookSourceUrl
    originName: str = ""
    originOrder: int = 0
    name: str = ""
    author: str = ""
    kind: str = ""
    intro: str = ""
    wordCount: str = ""
    coverUrl: str = ""
    tocUrl: str = ""
    tocHtml: str | None = None
    infoHtml: str | None = None
    latestChapterTitle: str = ""
    latestChapterTime: int = 0
    lastCheckTime: int = 0
    lastCheckCount: int = 0
    order: int = 0
    durChapterIndex: int = 0
    durChapterTitle: str = ""
    totalChapterNum: int = 0
    type: int = 0               # BookSourceType
    readConfig: Optional[dict[str, Any]] = None
    downloadUrls: Optional[list[str]] = None
    # Extra flags
    _reverse_toc: bool = False
    _use_replace_rule: bool = True
    _re_segment: bool = False

    def get_reverse_toc(self) -> bool:
        return self._reverse_toc

    def get_use_replace_rule(self) -> bool:
        return self._use_replace_rule

    def set_use_replace_rule(self, value: bool) -> None:
        self._use_replace_rule = bool(value)

    def get_re_segment(self) -> bool:
        if self.readConfig and "reSegment" in self.readConfig:
            return bool(self.readConfig["reSegment"])
        return self._re_segment

    def set_re_segment(self, value: bool) -> None:
        self._re_segment = bool(value)

    def to_search_book(self) -> "SearchBook":
        result = SearchBook(
            bookUrl=self.bookUrl,
            origin=self.origin,
            originName=self.originName,
            originOrder=self.originOrder,
            type=self.type,
            name=self.name,
            author=self.author,
            kind=self.kind,
            intro=self.intro,
            wordCount=self.wordCount,
            coverUrl=self.coverUrl,
            latestChapterTitle=self.latestChapterTitle,
            tocUrl=self.tocUrl,
            variable=self.variable,
            infoHtml=self.infoHtml,
            tocHtml=self.tocHtml,
        )
        trace_event("book.to_search_book", book=snapshot_book(self), search_book=snapshot_book(result))
        return result

    @property
    def is_web_file(self) -> bool:
        return self.type == 3


@dataclass
class BookChapter(RuleData):
    """Mirrors BookChapter.kt."""
    bookUrl: str = ""
    index: int = 0
    url: str = ""
    title: str = ""
    baseUrl: str = ""
    tag: str | None = None       # e.g. update time
    isVolume: bool = False
    isVip: bool = False
    isPay: bool = False
    wordCount: str | None = None
    titleMD5: str | None = None

    def get_display_title(self, replace_rules=None, use_replace=True) -> str:
        if not use_replace:
            return self.title
        if replace_rules:
            result = self.title
            for rule in replace_rules:
                if getattr(rule, "applies_to", None) and rule.applies_to([], is_title=True, is_content=False):
                    result = rule.apply(result)
            return result
        return self.title

    def get_file_name(self) -> str:
        import hashlib
        return hashlib.md5(self.url.encode()).hexdigest()


@dataclass
class SearchBook(RuleData):
    """Mirrors SearchBook.kt – result from search/explore."""
    bookUrl: str = ""
    origin: str = ""
    originName: str = ""
    originOrder: int = 0
    type: int = 0
    name: str = ""
    author: str = ""
    kind: str = ""
    intro: str = ""
    wordCount: str = ""
    coverUrl: str = ""
    latestChapterTitle: str = ""
    tocUrl: str = ""
    infoHtml: str | None = None
    tocHtml: str | None = None

    def to_book(self) -> Book:
        b = Book(
            bookUrl=self.bookUrl,
            origin=self.origin,
            originName=self.originName,
            originOrder=self.originOrder,
            type=self.type,
            name=self.name,
            author=self.author,
            kind=self.kind,
            intro=self.intro,
            wordCount=self.wordCount,
            coverUrl=self.coverUrl,
            latestChapterTitle=self.latestChapterTitle,
            tocUrl=self.tocUrl,
            variable=self.variable,
            infoHtml=self.infoHtml,
            tocHtml=self.tocHtml,
        )
        b.load_variable(self.variable)
        return b
