"""
BookContent – 1:1 port of BookContent.kt.
Handles single-page and multi-page content extraction.
"""
from __future__ import annotations
import re
from typing import List, Optional, TYPE_CHECKING

from ..analyze.analyze_rule import AnalyzeRule
from ..analyze_url import AnalyzeUrl
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
) -> str:
    """
    Mirrors BookContent.analyzeContent().
    Returns the chapter text (HTML-stripped or formatted).
    """
    if body is None:
        raise ValueError(f"Empty body for chapter {chapter.title}")

    content_rule = book_source.get_content_rule()
    analyze_rule = AnalyzeRule(book, book_source)
    analyze_rule.set_content(body).set_base_url(base_url)
    analyze_rule.set_redirect_url(base_url)
    analyze_rule.set_chapter(chapter)

    content_rule_str = content_rule.content or ""
    content_data = analyze_rule.get_string_list(content_rule_str)
    content = "\n".join(content_data) if content_data else ""

    # Format
    if content_rule.replaceRegex:
        content = _replace_content(content, content_rule.replaceRegex, "")
    if content_rule.imageStyle and content_rule.imageStyle.upper() != "TEXT":
        content = format_keep_img(content)
    else:
        content = format_html(content)

    # Multi-page content via dedicated nextContentUrl field
    if content_rule.nextContentUrl:
        content, _ = _get_next_page_content(
            book_source, book, chapter, analyze_rule,
            content, content_rule.nextContentUrl, base_url, body, {base_url}
        )

    return content


def _get_next_page_content(
    book_source: "BookSource",
    book: "Book",
    chapter: "BookChapter",
    analyze_rule: AnalyzeRule,
    content: str,
    next_url_rule: str,
    base_url: str,
    body: str,
    visited: set,
) -> tuple:
    """Recursively fetch next pages and append content."""
    content_rule = book_source.get_content_rule()
    content_rule_str = content_rule.content or ""

    next_url = analyze_rule.get_string(next_url_rule, is_url=True) or ""
    if not next_url or next_url in visited:
        return content, visited

    visited.add(next_url)
    try:
        au = AnalyzeUrl(m_url=next_url, source=book_source, rule_data=book, chapter=chapter)
        res = au.get_str_response()
        if not res.body:
            return content, visited

        ar2 = AnalyzeRule(book, book_source)
        ar2.set_content(res.body).set_base_url(next_url)
        ar2.set_redirect_url(res.url)
        ar2.set_chapter(chapter)

        more = ar2.get_string_list(content_rule_str)
        more_text = "\n".join(more) if more else ""

        if content_rule.replaceRegex:
            more_text = _replace_content(more_text, content_rule.replaceRegex, "")
        if content_rule.imageStyle and content_rule.imageStyle.upper() != "TEXT":
            more_text = format_keep_img(more_text)
        else:
            more_text = format_html(more_text)

        if more_text:
            content = content + "\n" + more_text

        # Follow further pages via nextContentUrl
        if content_rule.nextContentUrl:
            content, visited = _get_next_page_content(
                book_source, book, chapter, ar2,
                content, content_rule.nextContentUrl, next_url, res.body, visited
            )
    except Exception:
        pass

    return content, visited


def _replace_content(content: str, pattern: str, repl: str) -> str:
    """Apply a replaceRegex rule to content. Pattern may include @@replacement."""
    if "@@" in pattern:
        parts = pattern.split("@@", 1)
        regex_pat = parts[0]
        replacement = parts[1]
    else:
        regex_pat = pattern
        replacement = repl
    try:
        return re.sub(regex_pat, replacement, content)
    except re.error:
        return content
