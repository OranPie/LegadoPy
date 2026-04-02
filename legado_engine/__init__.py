"""
legado_engine – Python port of Legado's book-scraping engine.

Quick start::

    from legado_engine import search_book, get_book_info, get_chapter_list, get_content
    from legado_engine import BookSource, Book, BookChapter, SearchBook
"""

# ── Models ────────────────────────────────────────────────────────────────────
from .models.book_source import (
    BookSource,
    BookSourcePart,
    SearchRule,
    ExploreRule,
    ExploreKind,
    BookInfoRule,
    TocRule,
    ContentRule,
    ReviewRule,
    to_book_source_parts,
)
from .models.replace_rule import ReplaceRule
from .models.rss_source import RssSource, RssArticle
from .models.review import ReviewEntry
from .models.book import Book, BookChapter, SearchBook, RuleData

# ── Engine & Cache ────────────────────────────────────────────────────────────
from .cache import CacheStore
from .engine import LegadoEngine, ReplaceContext, get_default_engine, resolve_engine

# ── Analysis ─────────────────────────────────────────────────────────────────
from .analyze.source_rule import Mode, SourceRule
from .analyze.analyze_rule import AnalyzeRule
from .analyze.analyze_url import AnalyzeUrl, StrResponse, JsCookie

# ── Web API ───────────────────────────────────────────────────────────────────
from .web_book import (
    search_book,
    search_books_parallel,
    precise_search,
    explore_book,
    get_book_info,
    get_chapter_list,
    get_content,
    get_reviews,
    VipContentError,
)

# ── Auth & Login ──────────────────────────────────────────────────────────────
from .auth import (
    UiRow,
    LoginRow,
    SourceUiActionResult,
    parse_ui_rows,
    parse_source_ui,
    parse_login_ui,
    get_source_form_data,
    get_login_form_data,
    submit_source_form,
    submit_source_form_detailed,
    submit_login,
    submit_login_detailed,
    run_source_ui_action,
    execute_source_ui_action,
    run_login_button_action,
    execute_login_button_action,
    get_explore_kinds,
    get_explore_kinds_json,
)

# ── JavaScript ────────────────────────────────────────────────────────────────
from .js import eval_js, JsExtensions

# ── Media ─────────────────────────────────────────────────────────────────────
from .image import (
    decode_image_bytes,
    fetch_image_bytes,
    fetch_book_cover_bytes,
    fetch_content_image_bytes,
    fetch_rss_image_bytes,
)

# ── RSS & Reviews ─────────────────────────────────────────────────────────────
from .rss import load_rss_sources, get_rss_articles, get_rss_article_content
from .review import get_reviews

# ── Debug ─────────────────────────────────────────────────────────────────────
from .debug import configure_trace_logging, trace_enabled, trace_event, trace_exception

# ── Exceptions ────────────────────────────────────────────────────────────────
from .exceptions import LegadoEngineError, UnsupportedHeadlessOperation

__all__ = [
    # Models
    "BookSource", "BookSourcePart", "SearchRule", "ExploreRule", "ExploreKind",
    "BookInfoRule", "TocRule", "ContentRule", "ReviewRule", "to_book_source_parts",
    "ReplaceRule", "RssSource", "RssArticle", "ReviewEntry",
    "Book", "BookChapter", "SearchBook", "RuleData",
    # Engine & Cache
    "CacheStore", "LegadoEngine", "ReplaceContext", "get_default_engine", "resolve_engine",
    # Analysis
    "Mode", "SourceRule", "AnalyzeRule", "AnalyzeUrl", "StrResponse", "JsCookie",
    # Web API
    "search_book", "search_books_parallel", "precise_search", "explore_book",
    "get_book_info", "get_chapter_list", "get_content", "get_reviews", "VipContentError",
    # Auth & Login
    "UiRow", "LoginRow", "SourceUiActionResult",
    "parse_ui_rows", "parse_source_ui", "parse_login_ui",
    "get_source_form_data", "get_login_form_data",
    "submit_source_form", "submit_source_form_detailed",
    "submit_login", "submit_login_detailed",
    "run_source_ui_action", "execute_source_ui_action",
    "run_login_button_action", "execute_login_button_action",
    "get_explore_kinds", "get_explore_kinds_json",
    # JavaScript
    "eval_js", "JsExtensions",
    # Media
    "decode_image_bytes", "fetch_image_bytes", "fetch_book_cover_bytes",
    "fetch_content_image_bytes", "fetch_rss_image_bytes",
    # RSS & Reviews
    "load_rss_sources", "get_rss_articles", "get_rss_article_content", "get_reviews",
    # Debug
    "configure_trace_logging", "trace_enabled", "trace_event", "trace_exception",
    # Exceptions
    "LegadoEngineError", "UnsupportedHeadlessOperation",
]
