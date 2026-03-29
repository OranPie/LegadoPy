"""
legado_engine – Python port of Legado's book-scraping engine.

Public API:
    from legado_engine import search_book, get_book_info, get_chapter_list, get_content
    from legado_engine import BookSource, Book, BookChapter, SearchBook
"""
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
from .engine import CacheStore, LegadoEngine, get_default_engine, resolve_engine
from .debug import configure_trace_logging, trace_enabled, trace_event, trace_exception
from .exceptions import LegadoEngineError, UnsupportedHeadlessOperation
from .analyze.analyze_rule import AnalyzeRule, SourceRule, Mode
from .analyze_url import AnalyzeUrl, StrResponse
from .web_book import (
    search_book,
    search_books_parallel,
    explore_book,
    get_book_info,
    get_chapter_list,
    get_content,
)
from .js_engine import eval_js
from .source_explore import get_explore_kinds, get_explore_kinds_json
from .rss import load_rss_sources, get_rss_articles, get_rss_article_content
from .review import get_reviews
from .image import (
    decode_image_bytes,
    fetch_image_bytes,
    fetch_book_cover_bytes,
    fetch_content_image_bytes,
    fetch_rss_image_bytes,
)
from .source_login import (
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
)

__all__ = [
    # Models
    "BookSource",
    "BookSourcePart",
    "SearchRule",
    "ExploreRule",
    "ReplaceRule",
    "RssSource",
    "RssArticle",
    "ReviewEntry",
    "ExploreKind",
    "BookInfoRule",
    "TocRule",
    "ContentRule",
    "ReviewRule",
    "to_book_source_parts",
    "Book",
    "BookChapter",
    "SearchBook",
    "RuleData",
    "CacheStore",
    "LegadoEngine",
    "get_default_engine",
    "resolve_engine",
    "configure_trace_logging",
    "trace_enabled",
    "trace_event",
    "trace_exception",
    "LegadoEngineError",
    "UnsupportedHeadlessOperation",
    # Analyze core
    "AnalyzeRule",
    "SourceRule",
    "Mode",
    "AnalyzeUrl",
    "StrResponse",
    # High-level API
    "search_book",
    "search_books_parallel",
    "explore_book",
    "get_book_info",
    "get_chapter_list",
    "get_content",
    "get_explore_kinds",
    "get_explore_kinds_json",
    "load_rss_sources",
    "get_rss_articles",
    "get_rss_article_content",
    "get_reviews",
    "decode_image_bytes",
    "fetch_image_bytes",
    "fetch_book_cover_bytes",
    "fetch_content_image_bytes",
    "fetch_rss_image_bytes",
    "UiRow",
    "LoginRow",
    "SourceUiActionResult",
    "parse_ui_rows",
    "parse_source_ui",
    "parse_login_ui",
    "get_source_form_data",
    "get_login_form_data",
    "submit_source_form",
    "submit_source_form_detailed",
    "submit_login",
    "submit_login_detailed",
    "run_source_ui_action",
    "execute_source_ui_action",
    "run_login_button_action",
    "execute_login_button_action",
    # JS
    "eval_js",
]
