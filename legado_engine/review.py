from __future__ import annotations

from typing import List

from .analyze.analyze_rule import AnalyzeRule
from .analyze_url import AnalyzeUrl
from .engine import resolve_engine
from .models.review import ReviewEntry
from .pipeline import run_login_check


def _normalize_string_list(values):
    if not values:
        return []
    return [str(value or "") for value in values]


def get_reviews(
    book_source,
    book,
    chapter,
    *,
    engine=None,
) -> List[ReviewEntry]:
    engine = resolve_engine(engine)
    review_rule = book_source.get_review_rule()
    if not review_rule.reviewUrl or not review_rule.contentRule:
        return []

    analyze_url = AnalyzeUrl(
        m_url=review_rule.reviewUrl,
        base_url=chapter.url or book.tocUrl or book.bookUrl,
        source=book_source,
        rule_data=book,
        chapter=chapter,
        engine=engine,
    )
    res = analyze_url.get_str_response()
    res = run_login_check(analyze_url, book_source, res)
    if not res.body:
        return []

    parser_base_url = res.url
    if parser_base_url.startswith("data:"):
        parser_base_url = chapter.url or book.tocUrl or book.bookUrl or parser_base_url

    analyze_rule = AnalyzeRule(book, book_source, engine=engine)
    analyze_rule.set_content(res.body).set_base_url(parser_base_url)
    analyze_rule.set_redirect_url(res.url)
    analyze_rule.set_chapter(chapter)

    content_list = _normalize_string_list(analyze_rule.get_string_list(review_rule.contentRule))
    avatar_list = _normalize_string_list(analyze_rule.get_string_list(review_rule.avatarRule, is_url=True))
    post_time_list = _normalize_string_list(analyze_rule.get_string_list(review_rule.postTimeRule))
    quote_url_list = _normalize_string_list(analyze_rule.get_string_list(review_rule.reviewQuoteUrl, is_url=True))

    if not content_list:
        single_content = analyze_rule.get_string(review_rule.contentRule)
        if not single_content:
            return []
        content_list = [single_content]
    if not avatar_list and review_rule.avatarRule:
        single_avatar = analyze_rule.get_string(review_rule.avatarRule, is_url=True)
        avatar_list = [single_avatar] if single_avatar else []
    if not post_time_list and review_rule.postTimeRule:
        single_post_time = analyze_rule.get_string(review_rule.postTimeRule)
        post_time_list = [single_post_time] if single_post_time else []
    if not quote_url_list and review_rule.reviewQuoteUrl:
        single_quote_url = analyze_rule.get_string(review_rule.reviewQuoteUrl, is_url=True)
        quote_url_list = [single_quote_url] if single_quote_url else []

    size = max(
        len(content_list),
        len(avatar_list),
        len(post_time_list),
        len(quote_url_list),
    )
    if size == 0:
        return []

    reviews: List[ReviewEntry] = []
    for index in range(size):
        content = content_list[index] if index < len(content_list) else ""
        if not content:
            continue
        review = ReviewEntry(
            avatar=avatar_list[index] if index < len(avatar_list) else "",
            content=engine.apply_content(
                content,
                source=book_source,
                book=book,
                chapter=chapter,
                use_replace=book.get_use_replace_rule(),
            ),
            postTime=post_time_list[index] if index < len(post_time_list) else "",
            quoteUrl=quote_url_list[index] if index < len(quote_url_list) else "",
        )
        reviews.append(review)
    return reviews


__all__ = ["get_reviews"]
