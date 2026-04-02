"""
Book, BookChapter, SearchBook, RuleData – 1:1 port of Legado entities.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any

from ..debug import snapshot_book, trace_event


class BookType:
    """Mirrors BookType.kt — bitmask flags for book type classification."""
    text = 0b1000            # 8  – text book
    updateError = 0b10000   # 16 – update failed
    audio = 0b100000        # 32 – audio book
    image = 0b1000000       # 64 – image/comic book
    webFile = 0b10000000    # 128 – download-only site
    local = 0b100000000     # 256 – local file
    archive = 0b1000000000  # 512 – extracted from archive
    notShelf = 0b10000000000  # 1024 – temporary reading, not on shelf
    allBookType = text | image | audio | webFile
    localTag = "loc_book"
    webDavTag = "webDav::"


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
    type: int = 0               # BookType bitmask (see BookType class)
    canUpdate: bool = True      # mirrors Book.canUpdate — false prevents auto-refresh
    readConfig: Optional[dict[str, Any]] = None
    downloadUrls: Optional[list[str]] = None
    # Extra flags
    _reverse_toc: bool = False
    _use_replace_rule: bool = True
    _re_segment: bool = False
    _chinese_convert: int = 0

    def get_reverse_toc(self) -> bool:
        return self._reverse_toc

    def set_reverse_toc(self, value: bool) -> None:
        self._reverse_toc = bool(value)

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

    def get_chinese_convert(self) -> int:
        """Return Chinese conversion mode: 0=none, 1=s→t, 2=t→s."""
        if self.readConfig and "chineseConverterType" in self.readConfig:
            return int(self.readConfig["chineseConverterType"])
        return self._chinese_convert

    def set_chinese_convert(self, mode: int) -> None:
        self._chinese_convert = int(mode)

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
        return bool(self.type & BookType.webFile)

    @property
    def is_audio(self) -> bool:
        return bool(self.type & BookType.audio)

    @property
    def is_image(self) -> bool:
        return bool(self.type & BookType.image)

    @property
    def is_local(self) -> bool:
        return bool(self.type & BookType.local)

    def get_book_type(self, source_type: int) -> int:
        """
        Derive BookType bitmask from BookSourceType (mirrors Kotlin Book.getBookType()).
        BookSourceType: 0=text, 1=audio, 2=image, 3=webFile
        """
        if source_type == 1:
            return BookType.audio
        if source_type == 2:
            return BookType.image
        if source_type == 3:
            return BookType.webFile
        return BookType.text


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
    # Set after content fetch: names of replace rules that actually changed the content
    effectiveReplaceRules: list = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.effectiveReplaceRules is None:
            self.effectiveReplaceRules = []

    def get_display_title(self, replace_rules=None, use_replace=True, chinese_convert: int = 0) -> str:
        result = self.title
        if use_replace and replace_rules:
            for rule in replace_rules:
                if getattr(rule, "applies_to", None) and rule.applies_to([], is_title=True, is_content=False):
                    result = rule.apply(result)
        if chinese_convert:
            try:
                from ..utils.content_help import chinese_convert as _cc
                result = _cc(result, chinese_convert)
            except Exception:
                pass
        return result

    def get_file_name(self, suffix: str = "") -> str:
        import hashlib
        name = hashlib.md5(self.url.encode()).hexdigest()
        return f"{name}{suffix}" if suffix else name

    def get_absolute_url(self, base_url: str = "") -> str:
        """Resolve chapter URL against base_url (mirrors BookChapter.getAbsoluteURL())."""
        from ..utils.network_utils import get_absolute_url as _abs
        effective_base = self.baseUrl or base_url
        if not effective_base:
            return self.url
        return _abs(effective_base, self.url) or self.url

    def needs_pay(self) -> bool:
        """True when chapter is VIP-locked and not yet purchased."""
        return self.isVip and not self.isPay


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
    # Mirrors SearchBook.origins: LinkedHashSet<String> — tracks all sources having this book
    origins: list = field(default_factory=list)

    def add_origin(self, origin_url: str) -> None:
        """Add a source origin to this book's origin set (mirrors SearchBook.addOrigin)."""
        if origin_url and origin_url not in self.origins:
            self.origins.append(origin_url)

    def release_html_data(self) -> None:
        """Free cached HTML to reduce memory usage (mirrors SearchBook.releaseHtmlData)."""
        self.infoHtml = None
        self.tocHtml = None

    @property
    def origin_count(self) -> int:
        """Number of sources that have this book."""
        return max(1, len(self.origins))

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
