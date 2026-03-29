"""
WebBook – high-level orchestration API.
Mirrors WebBook.kt: search, getBookInfo, getChapterList, getContent.
"""
from __future__ import annotations
import json
from typing import Callable, List, Optional, TYPE_CHECKING

from ..analyze_url import AnalyzeUrl
from ..models.book import Book, BookChapter, SearchBook
from ..models.book_source import BookSource
from .book_list import analyze_book_list
from .book_info import analyze_book_info
from .book_chapter_list import analyze_chapter_list
from .book_content import analyze_content
from ..analyze.analyze_rule import AnalyzeRule
from ..utils.network_utils import get_absolute_url

if TYPE_CHECKING:
    pass


# ─── Search ──────────────────────────────────────────────────────────────────

def search_book(
    book_source: BookSource,
    key: str,
    page: int = 1,
    filter_fn: Optional[Callable[[str, str], bool]] = None,
) -> List[SearchBook]:
    """
    Search for books using the given source.
    Returns a list of SearchBook results.
    """
    if not book_source.searchUrl:
        return []

    rule_data = Book()
    rule_data.origin = book_source.bookSourceUrl
    rule_data.put_variable("searchKey", key)
    rule_data.put_variable("searchPage", str(page))
    rule_data.put_variable("searchPage_1", str(page - 1))

    analyze_url = AnalyzeUrl(
        m_url=book_source.searchUrl,
        key=key,
        page=page,
        source=book_source,
        rule_data=rule_data,
    )
    res = analyze_url.get_str_response()
    if not res.body:
        raise ValueError(f"Empty search response from {book_source.bookSourceUrl}")

    return analyze_book_list(
        book_source=book_source,
        rule_data=rule_data,
        analyze_url=analyze_url,
        base_url=res.url,
        body=res.body,
        is_search=True,
        filter_fn=filter_fn,
    )


# ─── Explore ─────────────────────────────────────────────────────────────────

def explore_book(
    book_source: BookSource,
    url: str,
    page: int = 1,
) -> List[SearchBook]:
    """
    Fetch explore (discovery) page for the given source.
    """
    rule_data = Book()
    rule_data.origin = book_source.bookSourceUrl
    rule_data.put_variable("page", str(page))

    analyze_url = AnalyzeUrl(
        m_url=url,
        page=page,
        source=book_source,
        rule_data=rule_data,
    )
    res = analyze_url.get_str_response()
    if not res.body:
        raise ValueError(f"Empty explore response from {book_source.bookSourceUrl}")

    return analyze_book_list(
        book_source=book_source,
        rule_data=rule_data,
        analyze_url=analyze_url,
        base_url=res.url,
        body=res.body,
        is_search=False,
    )


# ─── Book Info ────────────────────────────────────────────────────────────────

def get_book_info(
    book_source: BookSource,
    book: Book,
    can_rename: bool = True,
) -> Book:
    """
    Fetch and fill in book metadata from its detail page.
    """
    if book.tocHtml:
        body = book.tocHtml
        base_url = book.tocUrl or book.bookUrl
        redirect_url = base_url
    elif book.infoHtml:
        body = book.infoHtml
        base_url = book.bookUrl
        redirect_url = base_url
    else:
        analyze_url = AnalyzeUrl(
            m_url=book.bookUrl,
            source=book_source,
            rule_data=book,
        )
        res = analyze_url.get_str_response()
        body = res.body
        base_url = book.bookUrl
        redirect_url = res.url

    if not body:
        raise ValueError(f"Empty book info body for {book.bookUrl}")

    analyze_rule = AnalyzeRule(book, book_source)
    analyze_rule.set_content(body).set_base_url(base_url)
    analyze_rule.set_redirect_url(redirect_url)

    analyze_book_info(book, body, analyze_rule, book_source, base_url, redirect_url, can_rename)
    return book


# ─── Chapter List ─────────────────────────────────────────────────────────────

def get_chapter_list(
    book_source: BookSource,
    book: Book,
) -> List[BookChapter]:
    """
    Fetch the table of contents and return a list of BookChapter objects.
    """
    toc_url = book.tocUrl or book.bookUrl

    if book.tocHtml and book.tocUrl == toc_url:
        body = book.tocHtml
        base_url = toc_url
        redirect_url = toc_url
    else:
        analyze_url = AnalyzeUrl(
            m_url=toc_url,
            source=book_source,
            rule_data=book,
        )
        res = analyze_url.get_str_response()
        body = res.body
        base_url = toc_url
        redirect_url = res.url

    return analyze_chapter_list(
        book_source=book_source,
        book=book,
        base_url=base_url,
        redirect_url=redirect_url,
        body=body,
    )


# ─── Content ──────────────────────────────────────────────────────────────────

def get_content(
    book_source: BookSource,
    book: Book,
    chapter: BookChapter,
    next_chapter: Optional[BookChapter] = None,
) -> str:
    """
    Fetch and return the text content for a single chapter.
    """
    next_chapter_url = next_chapter.url if next_chapter else None

    if chapter.url in (book.bookUrl, book.tocUrl, ""):
        raise ValueError(f"Chapter URL looks invalid: {chapter.url!r}")

    analyze_url = AnalyzeUrl(
        m_url=chapter.url,
        source=book_source,
        rule_data=book,
        chapter=chapter,
    )
    res = analyze_url.get_str_response()
    body = res.body
    base_url = res.url

    return analyze_content(
        book_source=book_source,
        book=book,
        chapter=chapter,
        base_url=base_url,
        body=body,
        next_chapter_url=next_chapter_url,
    )

# ─── Login ───────────────────────────────────────────────────────────────────

def do_login(
    book_source: BookSource,
    email: str = "",
    password: str = "",
    api_key: str = "",
    server: str = "",
) -> None:
    """
    Authenticate with the book source by executing its ``loginUrl`` JS.

    Pass ``email`` + ``password`` for account-based login, or ``api_key``
    alone to log in via token/key.  ``server`` overrides the default server
    URL stored in the source variables (useful for first-time setup).

    After a successful login the source's cookie jar, ``_variables``
    (server, proxy, etc.) and login-info (email, key) are all updated
    in-memory on *book_source* automatically.
    """
    if not book_source.loginUrl:
        raise ValueError("This source has no loginUrl defined.")

    # Build the loginUi form-data dict that login(true) expects as `result`
    form_data: dict = {
        "邮箱": email,
        "密码": password,
        "密钥": api_key,
        "自定义服务器(可不填)": server,
        "听书Ai音色填写后点击右上角✔": "",
        "自定义评论颜色(可不填)": "",
        "自定义搜索源(多个用英文,分割)": "",
    }

    from ..js_engine import eval_js, JsExtensions

    # eval_js will prepend jsLib; loginUrl defines login(), putLoginInfo(), etc.
    login_js = book_source.loginUrl + "\nlogin(true);"
    eval_js(
        login_js,
        result=form_data,
        bindings={"source": book_source},
        java_obj=JsExtensions(),
    )
