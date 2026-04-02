"""
BookContent – 1:1 port of BookContent.kt.
Handles single-page and multi-page content extraction.
"""
from __future__ import annotations

import re
from concurrent.futures import as_completed
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from ..engine import resolve_engine
from ..analyze.analyze_rule import AnalyzeRule
from ..analyze.analyze_url import AnalyzeUrl
from ..pipeline import run_login_check
from ..utils.html_formatter import format_html, format_keep_img
from ..utils.network_utils import get_absolute_url
from ..utils.content_help import re_segment, chinese_convert

if TYPE_CHECKING:
    from ..models.book_source import BookSource, ContentRule
    from ..models.book import Book, BookChapter

# Default paragraph indent (matches ReadBookConfig.paragraphIndent in Android)
PARAGRAPH_INDENT = "　　"


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
        # All page URLs are known — fetch concurrently, reassemble in order
        filtered = [
            (i, u) for i, u in enumerate(next_urls)
            if u not in visited and not (
                next_chapter_url
                and get_absolute_url(base_url, u) == get_absolute_url(base_url, next_chapter_url)
            )
        ]

        def _fetch_page(order_url: tuple) -> tuple:
            order, url = order_url
            au = AnalyzeUrl(m_url=url, source=book_source, rule_data=book, chapter=chapter, engine=engine)
            res = au.get_str_response()
            res = run_login_check(au, book_source, res)
            if not res.body:
                return order, ""
            page_text, _ = _analyze_content_page(
                book_source, book, chapter, res.body, url, res.url,
                next_chapter_url, get_next_page_url=False, engine=engine,
            )
            return order, page_text or ""

        page_results: Dict[int, str] = {}
        futures = {engine.executor.submit(_fetch_page, item): item for item in filtered}
        for fut in as_completed(futures):
            try:
                order, text = fut.result()
                if text:
                    page_results[order] = text
            except Exception:
                pass
        for order in sorted(page_results):
            content_pages.append(page_results[order])

    content = "\n".join(part for part in content_pages if part)
    if content_rule.replaceRegex:
        normalized = "\n".join(line.strip() for line in content.splitlines())
        content = analyze_rule.get_string(content_rule.replaceRegex, normalized, unescape=False)
        content = "\n".join(f"　　{line}" if line else "" for line in content.splitlines())
    content = engine.apply_content(content, source=book_source, book=book, chapter=chapter, use_replace=book.get_use_replace_rule())
    content = _post_process_content(content, book, chapter)
    if not chapter.isVolume and not content.strip():
        raise ValueError("Content is empty")
    return content


def _post_process_content(content: str, book: "Book", chapter: "BookChapter") -> str:
    """
    Post-processing pipeline matching Android's ContentProcessor.getContent():

    1. Strip duplicate chapter title from content start.
    2. Re-segment paragraphs if book.get_re_segment().
    3. Add paragraph indentation (　　) to each non-empty paragraph.
    """
    if not content or content == "null":
        return content

    # --- 1. Remove duplicate title (mirrors ContentProcessor lines 96-119) ---
    try:
        book_name = re.escape(book.name or "")
        title_raw = re.escape(chapter.title or "")
        # Allow whitespace-equivalents between title chars
        title_pat = re.sub(r'\\ ', r'\\s*', title_raw)
        # \p{P} (Unicode punctuation) – fall back to a broad bracket class
        try:
            import regex as _re_mod  # type: ignore[import]
            pat = _re_mod.compile(
                rf'^(\s|\p{{P}}|{book_name})*{title_pat}(\s)*',
                _re_mod.UNICODE,
            )
        except Exception:
            pat = re.compile(
                rf'^([\s\W]|{book_name})*{title_pat}(\s)*',
                re.UNICODE,
            )
        m = pat.match(content)
        if m and m.end() > 0:
            content = content[m.end():]
    except Exception:
        pass

    # --- 2. Re-segment ---
    if book.get_re_segment():
        try:
            content = re_segment(content, chapter.title or "")
        except Exception:
            pass

    # --- 3. Paragraph indentation ---
    lines = content.splitlines()
    indented: list[str] = []
    for line in lines:
        paragraph = line.strip('\u0020\u3000\t\r\n')
        if paragraph:
            indented.append(f"{PARAGRAPH_INDENT}{paragraph}")
    content = "\n".join(indented)

    # --- 4. Chinese script conversion ---
    convert_mode = book.get_chinese_convert() if hasattr(book, "get_chinese_convert") else 0
    if convert_mode:
        content = chinese_convert(content, convert_mode)

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
