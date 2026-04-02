"""
WebBook – high-level orchestration API.
Mirrors WebBook.kt: search, getBookInfo, getChapterList, getContent.
"""
from __future__ import annotations
import json
from concurrent.futures import as_completed
from typing import Callable, List, Optional, TYPE_CHECKING

from ..analyze.analyze_url import AnalyzeUrl
from ..debug import (
    snapshot_book,
    snapshot_chapter,
    snapshot_source,
    trace_event,
    trace_exception,
)
from ..engine import resolve_engine
from ..models.book import Book, BookChapter, SearchBook
from ..models.book_source import BookSource
from ..pipeline import run_login_check
from .book_list import analyze_book_list
from .book_info import analyze_book_info
from .book_chapter_list import analyze_chapter_list
from .book_content import analyze_content
from ..analyze.analyze_rule import AnalyzeRule
from ..utils.network_utils import get_absolute_url
from ..js import JsExtensions, eval_js

if TYPE_CHECKING:
    pass


class VipContentError(Exception):
    """Raised when a chapter requires payment.

    Attributes:
        pay_url: Optional URL the user should visit to purchase the chapter.
    """

    def __init__(self, message: str, pay_url: Optional[str] = None) -> None:
        super().__init__(message)
        self.pay_url = pay_url


def _is_inline_book_marker(book: Book, body: str) -> bool:
    if not book.bookUrl.startswith("data:"):
        return False
    try:
        payload = json.loads(body)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    return {"book_id", "sources", "tab"}.issubset(payload.keys())


# ─── Search ──────────────────────────────────────────────────────────────────

def search_book(
    book_source: BookSource,
    key: str,
    page: int = 1,
    filter_fn: Optional[Callable[[str, str], bool]] = None,
    engine=None,
) -> List[SearchBook]:
    """
    Search for books using the given source.
    Returns a list of SearchBook results.
    """
    engine = resolve_engine(engine)
    trace_event(
        "web_book.search.start",
        source=snapshot_source(book_source),
        key=key,
        page=page,
    )
    if not book_source.searchUrl:
        trace_event(
            "web_book.search.skip_no_search_url",
            source=snapshot_source(book_source),
            key=key,
            page=page,
        )
        return []
    try:
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
            engine=engine,
        )
        res = analyze_url.get_str_response()
        res = run_login_check(analyze_url, book_source, res)
        if not res.body:
            raise ValueError(f"Empty search response from {book_source.bookSourceUrl}")

        results = analyze_book_list(
            book_source=book_source,
            rule_data=rule_data,
            analyze_url=analyze_url,
            base_url=res.url,
            body=res.body,
            is_search=True,
            filter_fn=filter_fn,
            engine=engine,
        )
        trace_event(
            "web_book.search.complete",
            source=snapshot_source(book_source),
            key=key,
            page=page,
            response_url=res.url,
            response_body_len=len(res.body or ""),
            results_count=len(results),
            first_result=snapshot_book(results[0]) if results else None,
        )
        return results
    except Exception as exc:
        trace_exception(
            "web_book.search.failed",
            exc,
            source=snapshot_source(book_source),
            key=key,
            page=page,
        )
        raise


# ─── Explore ─────────────────────────────────────────────────────────────────

def explore_book(
    book_source: BookSource,
    url: str,
    page: int = 1,
    engine=None,
) -> List[SearchBook]:
    """
    Fetch explore (discovery) page for the given source.
    """
    engine = resolve_engine(engine)
    trace_event(
        "web_book.explore.start",
        source=snapshot_source(book_source),
        url=url,
        page=page,
    )
    try:
        rule_data = Book()
        rule_data.origin = book_source.bookSourceUrl
        rule_data.put_variable("page", str(page))

        analyze_url = AnalyzeUrl(
            m_url=url,
            page=page,
            source=book_source,
            rule_data=rule_data,
            engine=engine,
        )
        res = analyze_url.get_str_response()
        res = run_login_check(analyze_url, book_source, res)
        if not res.body:
            raise ValueError(f"Empty explore response from {book_source.bookSourceUrl}")

        results = analyze_book_list(
            book_source=book_source,
            rule_data=rule_data,
            analyze_url=analyze_url,
            base_url=res.url,
            body=res.body,
            is_search=False,
            engine=engine,
        )
        trace_event(
            "web_book.explore.complete",
            source=snapshot_source(book_source),
            url=url,
            page=page,
            response_url=res.url,
            response_body_len=len(res.body or ""),
            results_count=len(results),
            first_result=snapshot_book(results[0]) if results else None,
        )
        return results
    except Exception as exc:
        trace_exception(
            "web_book.explore.failed",
            exc,
            source=snapshot_source(book_source),
            url=url,
            page=page,
        )
        raise


# ─── Book Info ────────────────────────────────────────────────────────────────

def get_book_info(
    book_source: BookSource,
    book: Book,
    can_rename: bool = True,
    engine=None,
) -> Book:
    """
    Fetch and fill in book metadata from its detail page.
    """
    engine = resolve_engine(engine)
    trace_event(
        "web_book.book_info.start",
        source=snapshot_source(book_source),
        book=snapshot_book(book),
        can_rename=can_rename,
    )
    try:
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
                engine=engine,
            )
            res = analyze_url.get_str_response()
            res = run_login_check(analyze_url, book_source, res)
            body = res.body
            base_url = book.bookUrl
            redirect_url = res.url

        if not body:
            raise ValueError(f"Empty book info body for {book.bookUrl}")

        trace_event(
            "web_book.book_info.response",
            source=snapshot_source(book_source),
            book=snapshot_book(book),
            base_url=base_url,
            redirect_url=redirect_url,
            body_len=len(body or ""),
            using_toc_html=bool(book.tocHtml),
            using_info_html=bool(book.infoHtml),
        )

        if _is_inline_book_marker(book, body):
            if not book.tocUrl:
                book.tocUrl = book.bookUrl
            trace_event(
                "web_book.book_info.skip_inline_marker",
                source=snapshot_source(book_source),
                book=snapshot_book(book),
                inline_body=body,
            )
            return book

        analyze_rule = AnalyzeRule(book, book_source, engine=engine)
        analyze_rule.set_content(body).set_base_url(base_url)
        analyze_rule.set_redirect_url(redirect_url)

        analyze_book_info(
            book,
            body,
            analyze_rule,
            book_source,
            base_url,
            redirect_url,
            can_rename,
            engine=engine,
        )
        trace_event(
            "web_book.book_info.complete",
            source=snapshot_source(book_source),
            book=snapshot_book(book),
        )
        return book
    except Exception as exc:
        trace_exception(
            "web_book.book_info.failed",
            exc,
            source=snapshot_source(book_source),
            book=snapshot_book(book),
            can_rename=can_rename,
        )
        raise


# ─── Chapter List ─────────────────────────────────────────────────────────────

def get_chapter_list(
    book_source: BookSource,
    book: Book,
    engine=None,
    progress_fn: Callable[[int, int], None] | None = None,
    chapter_batch_fn: Callable[[list], None] | None = None,
) -> List[BookChapter]:
    """
    Fetch the table of contents and return a list of BookChapter objects.
    Mirrors WebBook.getChapterListAwait() including preUpdateJs execution.
    """
    engine = resolve_engine(engine)
    toc_url = book.tocUrl or book.bookUrl
    trace_event(
        "web_book.chapters.start",
        source=snapshot_source(book_source),
        book=snapshot_book(book),
        toc_url=toc_url,
    )
    try:
        # Execute preUpdateJs before fetching the TOC (mirrors WebBook.kt:213-221)
        toc_rule = book_source.get_toc_rule()
        pre_update_js = toc_rule.preUpdateJs if toc_rule else None
        if pre_update_js and str(pre_update_js).strip():
            try:
                from ..js import eval_js, JsExtensions
                rule = AnalyzeRule(book=book, book_source=book_source, pre_update_js=True)
                rule.eval_js(str(pre_update_js))
            except Exception as _pre_exc:
                trace_exception(
                    "web_book.chapters.preUpdateJs_failed",
                    _pre_exc,
                    source=snapshot_source(book_source),
                    book=snapshot_book(book),
                )

        if book.tocHtml and book.tocUrl == toc_url:
            body = book.tocHtml
            base_url = toc_url
            redirect_url = toc_url
        else:
            analyze_url = AnalyzeUrl(
                m_url=toc_url,
                source=book_source,
                rule_data=book,
                engine=engine,
            )
            res = analyze_url.get_str_response()
            res = run_login_check(analyze_url, book_source, res)
            body = res.body
            base_url = toc_url
            redirect_url = res.url

        chapters = analyze_chapter_list(
            book_source=book_source,
            book=book,
            base_url=base_url,
            redirect_url=redirect_url,
            body=body,
            engine=engine,
            progress_fn=progress_fn,
            chapter_batch_fn=chapter_batch_fn,
        )
        trace_event(
            "web_book.chapters.complete",
            source=snapshot_source(book_source),
            book=snapshot_book(book),
            toc_url=toc_url,
            base_url=base_url,
            redirect_url=redirect_url,
            body_len=len(body or ""),
            chapter_count=len(chapters),
            first_chapter=snapshot_chapter(chapters[0]) if chapters else None,
            last_chapter=snapshot_chapter(chapters[-1]) if chapters else None,
        )
        return chapters
    except Exception as exc:
        trace_exception(
            "web_book.chapters.failed",
            exc,
            source=snapshot_source(book_source),
            book=snapshot_book(book),
            toc_url=toc_url,
        )
        raise


# ─── Content ──────────────────────────────────────────────────────────────────

def get_content(
    book_source: BookSource,
    book: Book,
    chapter: BookChapter,
    next_chapter: Optional[BookChapter] = None,
    engine=None,
) -> str:
    """
    Fetch and return the text content for a single chapter.
    Mirrors WebBook.kt content(), including volume-chapter shortcut.
    """
    engine = resolve_engine(engine)
    next_chapter_url = next_chapter.url if next_chapter else None
    trace_event(
        "web_book.content.start",
        source=snapshot_source(book_source),
        book=snapshot_book(book),
        chapter=snapshot_chapter(chapter),
        next_chapter=snapshot_chapter(next_chapter) if next_chapter else None,
    )

    # Volume chapters are TOC-only dividers – return their tag or title directly
    if chapter.isVolume and chapter.url.startswith(chapter.title or ""):
        return chapter.tag or ""

    if chapter.url in (book.bookUrl, book.tocUrl, ""):
        raise ValueError(f"Chapter URL looks invalid: {chapter.url!r}")
    try:
        content_rule = book_source.get_content_rule()

        # ── payAction handling (mirrors ReadBookActivity.payAction()) ──────────
        if chapter.isVip and not chapter.isPay:
            pay_action = getattr(content_rule, "payAction", None) or ""
            if pay_action.strip():
                analyze_rule = AnalyzeRule(book, book_source, engine=engine)
                analyze_rule.set_chapter(chapter)
                try:
                    result = str(analyze_rule.eval_js(pay_action) or "")
                except Exception:
                    result = ""
                # If result looks like a URL, surface it for the UI; otherwise just notify
                pay_url = result if result.startswith(("http://", "https://")) else None
                raise VipContentError(
                    f"付费章节 – {result or '需要购买'}", pay_url=pay_url
                )
            raise VipContentError("付费章节，无法加载内容")

        analyze_url = AnalyzeUrl(
            m_url=chapter.url,
            source=book_source,
            rule_data=book,
            chapter=chapter,
            engine=engine,
        )
        # Pass webJs/sourceRegex if set; they'll raise UnsupportedHeadlessOperation
        # if the source strictly requires a WebView. Catch and retry without them.
        try:
            res = analyze_url.get_str_response(
                js_str=content_rule.webJs or None,
                source_regex=content_rule.sourceRegex or None,
            )
        except Exception:
            # Fall back to plain HTTP fetch when WebView features are unavailable
            res = analyze_url.get_str_response()
        res = run_login_check(analyze_url, book_source, res)
        body = res.body
        base_url = res.url

        content = analyze_content(
            book_source=book_source,
            book=book,
            chapter=chapter,
            base_url=base_url,
            body=body,
            next_chapter_url=next_chapter_url,
            engine=engine,
        )
        trace_event(
            "web_book.content.complete",
            source=snapshot_source(book_source),
            book=snapshot_book(book),
            chapter=snapshot_chapter(chapter),
            base_url=base_url,
            body_len=len(body or ""),
            content_len=len(content or ""),
        )
        return content
    except Exception as exc:
        trace_exception(
            "web_book.content.failed",
            exc,
            source=snapshot_source(book_source),
            book=snapshot_book(book),
            chapter=snapshot_chapter(chapter),
            next_chapter=snapshot_chapter(next_chapter) if next_chapter else None,
        )
        raise

# ─── Parallel multi-source search ────────────────────────────────────────────

def search_books_parallel(
    sources: List[BookSource],
    key: str,
    page: int = 1,
    filter_fn: Optional[Callable[[str, str], bool]] = None,
    should_break_fn: Optional[Callable[[List["SearchBook"]], bool]] = None,
    engine=None,
) -> List[SearchBook]:
    """
    Search multiple book sources concurrently and return merged results.
    Sources that raise exceptions are silently skipped.
    Concurrency is controlled by the engine's shared executor.

    should_break_fn(results_so_far) → bool: called after each source completes;
      return True to cancel remaining in-flight searches early.
    """
    engine = resolve_engine(engine)
    if not sources:
        return []

    def _search_one(source: BookSource) -> List[SearchBook]:
        try:
            return search_book(source, key, page, filter_fn, engine)
        except Exception:
            return []

    all_results: List[SearchBook] = []
    futures = {engine.executor.submit(_search_one, src): src for src in sources}
    for fut in as_completed(futures):
        try:
            all_results.extend(fut.result())
        except Exception:
            pass
        if should_break_fn and should_break_fn(all_results):
            # Cancel remaining futures (best-effort)
            for remaining in futures:
                remaining.cancel()
            break

    # De-duplicate by bookUrl while preserving order
    seen: set = set()
    deduped: List[SearchBook] = []
    for sb in all_results:
        if sb.bookUrl not in seen:
            seen.add(sb.bookUrl)
            deduped.append(sb)
    return deduped


def precise_search(
    sources: List[BookSource],
    name: str,
    author: str,
    engine=None,
) -> Optional[tuple]:
    """
    Mirrors WebBook.preciseSearch(): iterate sources until an exact
    name+author match is found.

    Returns the first (SearchBook, BookSource) pair where the result's
    name and author exactly match (case-insensitive), or None if not found.
    """
    engine = resolve_engine(engine)
    name_l = name.strip().lower()
    author_l = author.strip().lower()

    def _try_source(source: BookSource):
        try:
            results = search_book(source, name, engine=engine)
            for sb in results:
                if (sb.name or "").strip().lower() == name_l and (sb.author or "").strip().lower() == author_l:
                    return (sb, source)
        except Exception:
            pass
        return None

    futures = {engine.executor.submit(_try_source, src): src for src in sources}
    for fut in as_completed(futures):
        try:
            result = fut.result()
            if result is not None:
                # Cancel remaining once we have a match
                for f in futures:
                    f.cancel()
                return result
        except Exception:
            pass
    return None



# ─── Login ───────────────────────────────────────────────────────────────────

def do_login(
    book_source: BookSource,
    email: str = "",
    password: str = "",
    api_key: str = "",
    server: str = "",
    engine=None,
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

    engine = resolve_engine(engine)
    from ..js import eval_js, JsExtensions

    # eval_js will prepend jsLib; loginUrl defines login(), putLoginInfo(), etc.
    login_js = book_source.loginUrl + "\nlogin(true);"
    eval_js(
        login_js,
        result=form_data,
        bindings={"source": book_source, "engine": engine},
        java_obj=JsExtensions(engine=engine),
    )


# ─── Reviews ─────────────────────────────────────────────────────────────────

def get_reviews(
    book_source: "BookSource",
    book: "Book",
    chapter: Optional["BookChapter"] = None,
    page: int = 1,
    engine=None,
) -> List[dict]:
    """
    Fetch paragraph/book reviews using ruleReview (mirrors ReviewRule.kt).

    Returns a list of dicts with keys: avatar, content, postTime.
    Empty list if the source has no reviewUrl or rule is incomplete.
    """
    engine = resolve_engine(engine)
    review_rule = book_source.get_review_rule()
    if not review_rule.reviewUrl:
        return []

    rule_data = chapter if chapter is not None else book
    try:
        au = AnalyzeUrl(
            m_url=review_rule.reviewUrl,
            source=book_source,
            rule_data=rule_data,
            page=page,
            engine=engine,
        )
        res = au.get_str_response()
        res = run_login_check(au, book_source, res)
        if not res.body:
            return []

        ar = AnalyzeRule(book, book_source, engine=engine)
        ar.set_content(res.body).set_base_url(res.url)

        # Each review item is a separate element (list of comment nodes)
        items: list = ar.get_elements(review_rule.contentRule or "") if review_rule.contentRule else []
        if not items:
            # Try flat extraction: content, avatar, time from top-level
            content_list = ar.get_string_list(review_rule.contentRule or "") if review_rule.contentRule else []
            avatar_list = ar.get_string_list(review_rule.avatarRule or "") if review_rule.avatarRule else []
            time_list = ar.get_string_list(review_rule.postTimeRule or "") if review_rule.postTimeRule else []
            return [
                {
                    "content": content_list[i] if i < len(content_list) else "",
                    "avatar": avatar_list[i] if i < len(avatar_list) else "",
                    "postTime": time_list[i] if i < len(time_list) else "",
                }
                for i in range(len(content_list))
            ]

        reviews: List[dict] = []
        for item in items:
            item_ar = AnalyzeRule(book, book_source, engine=engine)
            item_ar.set_content(item).set_base_url(res.url)
            reviews.append({
                "content": item_ar.get_string(review_rule.contentRule or "") if review_rule.contentRule else "",
                "avatar": item_ar.get_string(review_rule.avatarRule or "") if review_rule.avatarRule else "",
                "postTime": item_ar.get_string(review_rule.postTimeRule or "") if review_rule.postTimeRule else "",
            })
        return reviews

    except Exception as e:
        trace_exception("web_book.get_reviews", e)
        return []
