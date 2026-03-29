"""
BookContent – 1:1 port of BookContent.kt.
Handles single-page and multi-page content extraction.
"""
from __future__ import annotations
from typing import List, Optional, Tuple, TYPE_CHECKING

from ..engine import resolve_engine
from ..analyze.analyze_rule import AnalyzeRule
from ..analyze_url import AnalyzeUrl
from ..pipeline import run_login_check
from ..utils.html_formatter import format_html, format_keep_img
from ..utils.network_utils import get_absolute_url

if TYPE_CHECKING:
    from ..models.book_source import BookSource, ContentRule
    from ..models.book import Book, BookChapter


def analyze_content(
    book_source: "BookSource",
    book: "Book",
    chapter: "BookChapter",
    base_url: str,
    body: Optional[str],
    next_chapter_url: Optional[str] = None,
    engine=None,
) -> str:
    """
    Mirrors BookContent.analyzeContent().
    Returns the chapter text (HTML-stripped or formatted).
    """
    engine = resolve_engine(engine)
    if body is None:
        raise ValueError(f"Empty body for chapter {chapter.title}")

    content_rule = book_source.get_content_rule()
    analyze_rule = AnalyzeRule(book, book_source, engine=engine)
    analyze_rule.set_content(body).set_base_url(base_url)
    analyze_rule.set_redirect_url(base_url)
    analyze_rule.set_chapter(chapter)
    analyze_rule.set_next_chapter_url(next_chapter_url)

    if content_rule.title:
        title = analyze_rule.get_string(content_rule.title) or ""
        if title:
            chapter.title = engine.apply_title(title, source=book_source, book=book, chapter=chapter)

    content_pages: List[str] = []
    visited = [base_url]
    first_page, next_urls = _analyze_content_page(
        book_source,
        book,
        chapter,
        body,
        base_url,
        base_url,
        next_chapter_url,
        engine=engine,
    )
    content_pages.append(first_page)

    if len(next_urls) == 1:
        next_url = next_urls[0]
        while next_url and next_url not in visited:
            if next_chapter_url and get_absolute_url(base_url, next_url) == get_absolute_url(base_url, next_chapter_url):
                break
            visited.append(next_url)
            au = AnalyzeUrl(m_url=next_url, source=book_source, rule_data=book, chapter=chapter, engine=engine)
            res = au.get_str_response()
            res = run_login_check(au, book_source, res)
            if not res.body:
                break
            page_text, more_urls = _analyze_content_page(
                book_source,
                book,
                chapter,
                res.body,
                next_url,
                res.url,
                next_chapter_url,
                engine=engine,
            )
            if page_text:
                content_pages.append(page_text)
            next_url = more_urls[0] if more_urls else ""
    elif len(next_urls) > 1:
        for next_url in next_urls:
            if next_url in visited:
                continue
            if next_chapter_url and get_absolute_url(base_url, next_url) == get_absolute_url(base_url, next_chapter_url):
                continue
            visited.append(next_url)
            au = AnalyzeUrl(m_url=next_url, source=book_source, rule_data=book, chapter=chapter, engine=engine)
            res = au.get_str_response()
            res = run_login_check(au, book_source, res)
            if not res.body:
                continue
            page_text, _ = _analyze_content_page(
                book_source,
                book,
                chapter,
                res.body,
                next_url,
                res.url,
                next_chapter_url,
                get_next_page_url=False,
                engine=engine,
            )
            if page_text:
                content_pages.append(page_text)

    content = "\n".join(part for part in content_pages if part)
    if content_rule.replaceRegex:
        normalized = "\n".join(line.strip() for line in content.splitlines())
        content = analyze_rule.get_string(content_rule.replaceRegex, normalized, unescape=False)
        content = "\n".join(f"　　{line}" if line else "" for line in content.splitlines())
    content = engine.apply_content(content, source=book_source, book=book, chapter=chapter, use_replace=book.get_use_replace_rule())
    if not chapter.isVolume and not content.strip():
        raise ValueError("Content is empty")
    return content


def _analyze_content_page(
    book_source: "BookSource",
    book: "Book",
    chapter: "BookChapter",
    body: str,
    base_url: str,
    redirect_url: str,
    next_chapter_url: Optional[str],
    get_next_page_url: bool = True,
    engine=None,
) -> Tuple[str, List[str]]:
    engine = resolve_engine(engine)
    content_rule = book_source.get_content_rule()
    analyze_rule = AnalyzeRule(book, book_source, engine=engine)
    analyze_rule.set_content(body).set_base_url(base_url)
    analyze_rule.set_redirect_url(redirect_url)
    analyze_rule.set_chapter(chapter)
    analyze_rule.set_next_chapter_url(next_chapter_url)

    raw_content = analyze_rule.get_string(content_rule.content, unescape=False) if content_rule.content else ""
    if content_rule.imageStyle and content_rule.imageStyle.upper() != "TEXT":
        content = format_keep_img(raw_content, redirect_url)
    else:
        content = format_html(raw_content)

    next_urls: List[str] = []
    if get_next_page_url and content_rule.nextContentUrl:
        next_urls = analyze_rule.get_string_list(content_rule.nextContentUrl, is_url=True) or []
    return content, next_urls
