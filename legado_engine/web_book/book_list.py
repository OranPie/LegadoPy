"""
BookList – 1:1 port of BookList.kt (search & explore result parsing).
"""
from __future__ import annotations
import re
from typing import Any, Callable, List, Optional, TYPE_CHECKING

from ..analyze.analyze_rule import AnalyzeRule
from ..analyze_url import AnalyzeUrl, StrResponse
from ..models.book import Book, SearchBook
from ..utils.html_formatter import format_book_name, format_book_author, format_html
from ..utils.network_utils import get_absolute_url

if TYPE_CHECKING:
    from ..models.book_source import BookSource, BookListRule
    from ..models.book import RuleData


def analyze_book_list(
    book_source: "BookSource",
    rule_data: "RuleData",
    analyze_url: "AnalyzeUrl",
    base_url: str,
    body: Optional[str],
    is_search: bool = True,
    filter_fn: Optional[Callable[[str, str], bool]] = None,
) -> List[SearchBook]:
    """
    Mirrors BookList.analyzeBookList().
    Parses search/explore HTML/JSON into a list of SearchBook objects.
    """
    if body is None:
        raise ValueError(f"Empty body from {analyze_url.rule_url}")

    book_list: List[SearchBook] = []

    analyze_rule = AnalyzeRule(rule_data, book_source)
    analyze_rule.set_content(body).set_base_url(base_url)
    analyze_rule.set_redirect_url(base_url)

    # Check if URL directly matches book-detail pattern
    if is_search and book_source.bookUrlPattern:
        if re.search(book_source.bookUrlPattern, base_url):
            sb = _get_info_item(book_source, analyze_rule, analyze_url, body,
                                base_url, rule_data.get_variable_json(), filter_fn)
            if sb:
                sb.infoHtml = body
                book_list.append(sb)
            return book_list

    # Determine which rule set to use
    from ..models.book_source import ExploreRule, SearchRule
    if is_search:
        book_list_rule = book_source.get_search_rule()
    elif not book_source.get_explore_rule().bookList:
        book_list_rule = book_source.get_search_rule()
    else:
        book_list_rule = book_source.get_explore_rule()

    list_rule: str = book_list_rule.bookList or ""
    reverse = False
    if list_rule.startswith("-"):
        reverse = True
        list_rule = list_rule[1:]
    if list_rule.startswith("+"):
        list_rule = list_rule[1:]

    collections = analyze_rule.get_elements(list_rule)

    if not collections and not book_source.bookUrlPattern:
        sb = _get_info_item(book_source, analyze_rule, analyze_url, body,
                            base_url, rule_data.get_variable_json(), filter_fn)
        if sb:
            sb.infoHtml = body
            book_list.append(sb)
    else:
        rule_name         = analyze_rule.split_source_rule(book_list_rule.name)
        rule_book_url     = analyze_rule.split_source_rule(book_list_rule.bookUrl)
        rule_author       = analyze_rule.split_source_rule(book_list_rule.author)
        rule_cover_url    = analyze_rule.split_source_rule(book_list_rule.coverUrl)
        rule_intro        = analyze_rule.split_source_rule(book_list_rule.intro)
        rule_kind         = analyze_rule.split_source_rule(book_list_rule.kind)
        rule_last_chapter = analyze_rule.split_source_rule(book_list_rule.lastChapter)
        rule_word_count   = analyze_rule.split_source_rule(book_list_rule.wordCount)

        for item in collections:
            sb = _get_search_item(
                book_source, analyze_rule, item, base_url,
                rule_data.get_variable_json(), filter_fn,
                rule_name=rule_name,
                rule_book_url=rule_book_url,
                rule_author=rule_author,
                rule_cover_url=rule_cover_url,
                rule_intro=rule_intro,
                rule_kind=rule_kind,
                rule_last_chapter=rule_last_chapter,
                rule_word_count=rule_word_count,
            )
            if sb:
                if base_url == sb.bookUrl:
                    sb.infoHtml = body
                book_list.append(sb)

        # De-duplicate
        seen = set()
        deduped: List[SearchBook] = []
        for sb in book_list:
            if sb.bookUrl not in seen:
                seen.add(sb.bookUrl)
                deduped.append(sb)
        book_list = deduped
        if reverse:
            book_list.reverse()

    return book_list


def _get_info_item(
    book_source: "BookSource",
    analyze_rule: AnalyzeRule,
    analyze_url: AnalyzeUrl,
    body: str,
    base_url: str,
    variable: str,
    filter_fn: Optional[Callable[[str, str], bool]],
) -> Optional[SearchBook]:
    from .book_info import analyze_book_info
    book = Book(variable=variable)
    book.load_variable(variable)
    book.bookUrl = base_url
    book.origin = book_source.bookSourceUrl
    book.originName = book_source.bookSourceName
    book.type = book_source.bookSourceType
    analyze_rule.set_rule_data(book)
    analyze_book_info(book, body, analyze_rule, book_source, base_url, base_url, False)
    if filter_fn and not filter_fn(book.name, book.author):
        return None
    if book.name:
        return book.to_search_book()
    return None


def _get_search_item(
    book_source: "BookSource",
    analyze_rule: AnalyzeRule,
    item: Any,
    base_url: str,
    variable: str,
    filter_fn: Optional[Callable[[str, str], bool]],
    **rules,
) -> Optional[SearchBook]:
    book = Book(variable=variable)
    book.load_variable(variable)
    book.origin = book_source.bookSourceUrl
    book.originName = book_source.bookSourceName
    book.type = book_source.bookSourceType

    analyze_rule.set_content(item).set_base_url(base_url)
    analyze_rule.set_rule_data(book)

    book.name   = format_book_name(analyze_rule._get_string(rules["rule_name"]) or "")
    book.bookUrl = analyze_rule._get_string(rules["rule_book_url"], is_url=True) or ""
    book.author  = format_book_author(analyze_rule._get_string(rules["rule_author"]) or "")

    cover = analyze_rule._get_string(rules["rule_cover_url"])
    if cover:
        book.coverUrl = get_absolute_url(base_url, cover)

    intro_raw = analyze_rule._get_string(rules["rule_intro"])
    if intro_raw:
        book.intro = format_html(intro_raw)

    kind_list = analyze_rule._get_string_list(rules["rule_kind"])
    if kind_list:
        book.kind = ",".join(kind_list)

    book.latestChapterTitle = analyze_rule._get_string(rules["rule_last_chapter"])
    book.wordCount = analyze_rule._get_string(rules["rule_word_count"])

    if filter_fn and not filter_fn(book.name, book.author):
        return None
    if not book.name:
        return None
    return book.to_search_book()
