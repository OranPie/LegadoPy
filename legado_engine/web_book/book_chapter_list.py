"""
BookChapterList – 1:1 port of BookChapterList.kt.
"""
from __future__ import annotations
from typing import List, Optional, Tuple, TYPE_CHECKING

from ..analyze.analyze_rule import AnalyzeRule
from ..analyze_url import AnalyzeUrl
from ..models.book import BookChapter
from ..utils.network_utils import get_absolute_url

if TYPE_CHECKING:
    from ..models.book_source import BookSource, TocRule
    from ..models.book import Book


def analyze_chapter_list(
    book_source: "BookSource",
    book: "Book",
    base_url: str,
    redirect_url: str,
    body: Optional[str],
) -> List[BookChapter]:
    """
    Mirrors BookChapterList.analyzeChapterList() (outer form).
    Handles multi-page TOC by following nextTocUrl.
    """
    if body is None:
        raise ValueError(f"Empty TOC body from {base_url}")

    toc_rule = book_source.get_toc_rule()
    next_url_list = [redirect_url]
    reverse = False

    list_rule: str = toc_rule.chapterList or ""
    if list_rule.startswith("-"):
        reverse = True
        list_rule = list_rule[1:]
    if list_rule.startswith("+"):
        list_rule = list_rule[1:]

    chapter_list: List[BookChapter] = []

    # First page
    chapters, next_urls = _analyze_chapter_page(
        book, base_url, redirect_url, body, toc_rule, list_rule, book_source
    )
    chapter_list.extend(chapters)

    # Single next-page chain
    if len(next_urls) == 1:
        next_url = next_urls[0]
        while next_url and next_url not in next_url_list:
            next_url_list.append(next_url)
            au = AnalyzeUrl(
                m_url=next_url,
                source=book_source,
                rule_data=book,
            )
            res = au.get_str_response()
            if res.body:
                more_chapters, next_urls2 = _analyze_chapter_page(
                    book, next_url, res.url, res.body, toc_rule, list_rule, book_source
                )
                chapter_list.extend(more_chapters)
                next_url = next_urls2[0] if next_urls2 else ""
            else:
                break

    elif len(next_urls) > 1:
        # Concurrent multi-page fetch
        for url_str in next_urls:
            au = AnalyzeUrl(m_url=url_str, source=book_source, rule_data=book)
            try:
                res = au.get_str_response()
                if res.body:
                    more, _ = _analyze_chapter_page(
                        book, url_str, res.url, res.body, toc_rule, list_rule, book_source
                    )
                    chapter_list.extend(more)
            except Exception:
                pass

    if not chapter_list:
        raise ValueError("Chapter list is empty")

    # Reverse if needed then sort
    if not reverse:
        chapter_list.reverse()

    # De-duplicate
    seen = set()
    deduped: List[BookChapter] = []
    for ch in chapter_list:
        if ch.url not in seen:
            seen.add(ch.url)
            deduped.append(ch)
    chapter_list = deduped

    if not book.get_reverse_toc():
        chapter_list.reverse()

    # Assign indices
    for i, ch in enumerate(chapter_list):
        ch.index = i

    book.totalChapterNum = len(chapter_list)
    if chapter_list:
        book.latestChapterTitle = chapter_list[-1].title

    return chapter_list


def _analyze_chapter_page(
    book: "Book",
    base_url: str,
    redirect_url: str,
    body: str,
    toc_rule: "TocRule",
    list_rule: str,
    book_source: "BookSource",
) -> Tuple[List[BookChapter], List[str]]:
    """Single-page TOC parsing. Returns (chapters, next_urls)."""
    analyze_rule = AnalyzeRule(book, book_source)
    analyze_rule.set_content(body).set_base_url(base_url)
    analyze_rule.set_redirect_url(redirect_url)

    elements = analyze_rule.get_elements(list_rule)

    # Next-page URLs
    next_urls: List[str] = []
    if toc_rule.nextTocUrl:
        raw = analyze_rule.get_string_list(toc_rule.nextTocUrl, is_url=True) or []
        next_urls = [u for u in raw if u and u != redirect_url]

    chapters: List[BookChapter] = []
    if elements:
        name_rule      = analyze_rule.split_source_rule(toc_rule.chapterName)
        url_rule       = analyze_rule.split_source_rule(toc_rule.chapterUrl)
        vip_rule       = analyze_rule.split_source_rule(toc_rule.isVip)
        pay_rule       = analyze_rule.split_source_rule(toc_rule.isPay)
        uptime_rule    = analyze_rule.split_source_rule(toc_rule.updateTime)
        volume_rule    = analyze_rule.split_source_rule(toc_rule.isVolume)

        for idx, item in enumerate(elements):
            analyze_rule.set_content(item)
            ch = BookChapter(bookUrl=book.bookUrl, baseUrl=redirect_url)
            analyze_rule.set_chapter(ch)

            ch.title  = analyze_rule._get_string(name_rule) or ""
            ch.url    = analyze_rule._get_string(url_rule) or ""
            ch.tag    = analyze_rule._get_string(uptime_rule)
            is_volume = analyze_rule._get_string(volume_rule) or ""
            ch.isVolume = _is_true(is_volume)

            if not ch.url:
                if ch.isVolume:
                    ch.url = f"{ch.title}{idx}"
                else:
                    ch.url = base_url

            if ch.title:
                is_vip = analyze_rule._get_string(vip_rule) or ""
                is_pay = analyze_rule._get_string(pay_rule) or ""
                ch.isVip = _is_true(is_vip)
                ch.isPay = _is_true(is_pay)
                chapters.append(ch)

    return chapters, next_urls


def _is_true(val: str) -> bool:
    """Mirrors .isTrue() – checks for truthy string values."""
    return val.lower() in ("true", "1", "yes", "是", "✓")
