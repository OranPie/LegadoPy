"""
BookInfo – 1:1 port of BookInfo.kt.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from ..analyze.analyze_rule import AnalyzeRule
from ..utils.html_formatter import format_book_name, format_book_author, format_html
from ..utils.network_utils import get_absolute_url

if TYPE_CHECKING:
    from ..models.book_source import BookSource
    from ..models.book import Book


def analyze_book_info(
    book: "Book",
    body: str,
    analyze_rule: AnalyzeRule,
    book_source: "BookSource",
    base_url: str,
    redirect_url: str,
    can_rename: bool,
) -> None:
    """
    Mirrors BookInfo.analyzeBookInfo() (inner form).
    Fills all fields of `book` in place using book_source.ruleBookInfo rules.
    """
    info_rule = book_source.get_book_info_rule()

    # init rule (pre-processing step)
    if info_rule.init:
        content = analyze_rule.get_element(info_rule.init)
        if content is not None:
            analyze_rule.set_content(content)

    m_can_rename = can_rename and bool(info_rule.canReName)

    # name
    name = format_book_name(analyze_rule.get_string(info_rule.name) or "")
    if name and (m_can_rename or not book.name):
        book.name = name

    # author
    author = format_book_author(analyze_rule.get_string(info_rule.author) or "")
    if author and (m_can_rename or not book.author):
        book.author = author

    # kind
    kind_list = analyze_rule.get_string_list(info_rule.kind)
    if kind_list:
        book.kind = ",".join(k for k in kind_list if k)

    # word count
    wc = analyze_rule.get_string(info_rule.wordCount)
    if wc:
        book.wordCount = wc

    # latest chapter
    lc = analyze_rule.get_string(info_rule.lastChapter)
    if lc:
        book.latestChapterTitle = lc

    # intro
    intro_raw = analyze_rule.get_string(info_rule.intro)
    if intro_raw:
        book.intro = format_html(intro_raw)

    # cover
    cover = analyze_rule.get_string(info_rule.coverUrl)
    if cover:
        book.coverUrl = get_absolute_url(redirect_url, cover)

    # toc url (only for non-file sources)
    if not book.is_web_file:
        toc_url = analyze_rule.get_string(info_rule.tocUrl, is_url=True)
        book.tocUrl = toc_url or base_url
        if book.tocUrl == base_url:
            book.tocHtml = body
    else:
        dl_urls = analyze_rule.get_string_list(info_rule.downloadUrls, is_url=True)
        if not dl_urls:
            raise ValueError("Download URLs empty")
        book.downloadUrls = dl_urls
