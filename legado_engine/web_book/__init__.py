"""
legado_engine.web_book – orchestration layer.
"""
from .web_book import (
    search_book,
    search_books_parallel,
    explore_book,
    get_book_info,
    get_chapter_list,
    get_content,
)
from .book_list import analyze_book_list
from .book_info import analyze_book_info
from .book_chapter_list import analyze_chapter_list
from .book_content import analyze_content

__all__ = [
    "search_book",
    "search_books_parallel",
    "explore_book",
    "get_book_info",
    "get_chapter_list",
    "get_content",
    "analyze_book_list",
    "analyze_book_info",
    "analyze_chapter_list",
    "analyze_content",
]
