"""
Book, BookChapter, SearchBook, RuleData – 1:1 port of Legado entities.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RuleData:
    """Mirrors RuleDataInterface + RuleData.kt – holds per-source variable state."""
    variable: Optional[str] = None  # serialized JSON variable map
    _var_map: Dict[str, str] = field(default_factory=dict, repr=False)

    def _sync_variable_blob(self) -> None:
        self.variable = json.dumps(self._var_map, ensure_ascii=False) if self._var_map else None

    def put_variable(self, key: str, value: Optional[str]) -> None:
        if value is None:
            self._var_map.pop(key, None)
        else:
            self._var_map[key] = value
        self._sync_variable_blob()

    def get_variable(self, key: str) -> Optional[str]:
        return self._var_map.get(key)

    def get_variable_map(self) -> Dict[str, str]:
        return dict(self._var_map)

    def get_variable_json(self) -> str:
        return json.dumps(self._var_map, ensure_ascii=False)

    def load_variable(self, json_str: Optional[str]) -> None:
        try:
            self._var_map = json.loads(json_str or "") or {}
        except Exception:
            self._var_map = {}
        self._sync_variable_blob()

    def putVariable(self, key: str, value: Optional[str]) -> bool:  # noqa: N802
        self.put_variable(key, value)
        return True

    def getVariable(self, key: str) -> str:  # noqa: N802
        return self.get_variable(key) or ""

    def getVariableMap(self) -> Dict[str, str]:  # noqa: N802
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
    kind: Optional[str] = None
    intro: Optional[str] = None
    wordCount: Optional[str] = None
    coverUrl: Optional[str] = None
    tocUrl: str = ""
    tocHtml: Optional[str] = None
    infoHtml: Optional[str] = None
    latestChapterTitle: Optional[str] = None
    latestChapterTime: int = 0
    lastCheckTime: int = 0
    lastCheckCount: int = 0
    order: int = 0
    durChapterIndex: int = 0
    durChapterTitle: Optional[str] = None
    totalChapterNum: int = 0
    type: int = 0               # BookSourceType
    readConfig: Optional[Dict[str, Any]] = None
    downloadUrls: Optional[List[str]] = None
    # Extra flags
    _reverse_toc: bool = False
    _use_replace_rule: bool = True

    def get_reverse_toc(self) -> bool:
        return self._reverse_toc

    def get_use_replace_rule(self) -> bool:
        return self._use_replace_rule

    def to_search_book(self) -> "SearchBook":
        return SearchBook(
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
    tag: Optional[str] = None       # e.g. update time
    isVolume: bool = False
    isVip: bool = False
    isPay: bool = False
    wordCount: Optional[str] = None
    titleMD5: Optional[str] = None

    def get_display_title(self, replace_rules=None, use_replace=True) -> str:
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
    kind: Optional[str] = None
    intro: Optional[str] = None
    wordCount: Optional[str] = None
    coverUrl: Optional[str] = None
    latestChapterTitle: Optional[str] = None
    tocUrl: str = ""
    infoHtml: Optional[str] = None
    tocHtml: Optional[str] = None

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
