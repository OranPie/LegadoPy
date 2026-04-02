from __future__ import annotations

from typing import List, Optional, Tuple

from .analyze.analyze_rule import AnalyzeRule
from .analyze.analyze_url import AnalyzeUrl
from .engine import resolve_engine
from .exceptions import UnsupportedHeadlessOperation
from .models.book import RuleData
from .models.rss_source import RssArticle, RssSource
from .pipeline import run_login_check
from .utils.html_formatter import format_html


def load_rss_sources(text: str) -> List[RssSource]:
    return RssSource.from_json_array(text)


def _ensure_headless_supported(source: RssSource) -> None:
    if source.injectJs or source.shouldOverrideUrlLoading:
        raise UnsupportedHeadlessOperation(
            "rssWebView",
            f"RSS source '{source.sourceName}' requires injected JS or URL interception.",
        )


def get_rss_articles(
    source: RssSource,
    page: int = 1,
    url: Optional[str] = None,
    *,
    engine=None,
) -> List[RssArticle]:
    """
    Fetch RSS articles for the given source page.

    Returns list of RssArticle objects.
    To also get the next-page URL, use get_rss_articles_with_next().
    """
    articles, _ = _get_rss_articles_impl(source, page=page, url=url, engine=engine)
    return articles


def get_rss_articles_with_next(
    source: RssSource,
    page: int = 1,
    url: Optional[str] = None,
    *,
    engine=None,
) -> Tuple[List[RssArticle], Optional[str]]:
    """
    Like get_rss_articles() but also returns the next-page URL extracted via ruleNextPage.
    Returns (articles, next_page_url) — next_page_url is None if not available.
    """
    return _get_rss_articles_impl(source, page=page, url=url, engine=engine)


def _get_rss_articles_impl(
    source: RssSource,
    page: int = 1,
    url: Optional[str] = None,
    *,
    engine=None,
) -> Tuple[List[RssArticle], Optional[str]]:
    engine = resolve_engine(engine)
    _ensure_headless_supported(source)
    rule_data = RuleData()
    rule_data.put_variable("page", str(page))
    feed_url = url or source.sortUrl or source.sourceUrl
    analyze_url = AnalyzeUrl(feed_url, page=page, source=source, rule_data=rule_data, engine=engine)
    res = analyze_url.get_str_response()
    res = run_login_check(analyze_url, source, res)
    if not res.body:
        return [], None
    analyze_rule = AnalyzeRule(rule_data, source, engine=engine)
    analyze_rule.set_content(res.body).set_base_url(res.url)
    analyze_rule.set_redirect_url(res.url)
    articles = _parse_article_page(source, analyze_rule, res.url, engine)
    # ruleNextPage: extract URL of next page (mirrors RssModel.kt nextPage handling)
    next_page_url: Optional[str] = None
    if source.ruleNextPage:
        try:
            analyze_rule.set_content(res.body).set_base_url(res.url)
            next_page_url = analyze_rule.get_string(source.ruleNextPage, is_url=True) or None
        except Exception:
            next_page_url = None
    return articles, next_page_url


def _parse_article_page(
    source: RssSource,
    analyze_rule: AnalyzeRule,
    base_url: str,
    engine,
) -> List[RssArticle]:
    items = analyze_rule.get_elements(source.ruleArticles or "") if source.ruleArticles else []
    if not items:
        items = [analyze_rule.get_element(source.ruleArticles or "")] if source.singleUrl else []
    articles: List[RssArticle] = []
    for item in items:
        analyze_rule.set_content(item).set_base_url(base_url)
        article = RssArticle(sourceUrl=source.sourceUrl, sourceName=source.sourceName, baseUrl=base_url)
        analyze_rule.set_rule_data(article)
        analyze_rule.set_rss_article(article)  # bind rssArticle variable for JS rules
        article.title = engine.apply_title(
            analyze_rule.get_string(source.ruleTitle) or "",
            source=source,
            article=article,
        )
        article.pubDate = analyze_rule.get_string(source.rulePubDate) or ""
        article.description = analyze_rule.get_string(source.ruleDescription) or ""
        article.image = analyze_rule.get_string(source.ruleImage, is_url=True) or ""
        article.link = analyze_rule.get_string(source.ruleLink, is_url=True) or ""
        raw_content = analyze_rule.get_string(source.ruleContent, unescape=False) if source.ruleContent else ""
        if raw_content:
            article.content = engine.apply_content(
                format_html(raw_content),
                source=source,
                article=article,
            )
        if article.title or article.link or article.content:
            articles.append(article)
    deduped: List[RssArticle] = []
    seen = set()
    for article in articles:
        key = article.link or article.title
        if key and key not in seen:
            seen.add(key)
            deduped.append(article)
    return deduped


def get_rss_article_content(
    source: RssSource,
    article: RssArticle,
    *,
    engine=None,
) -> RssArticle:
    engine = resolve_engine(engine)
    _ensure_headless_supported(source)
    if article.content:
        article.content = engine.apply_content(article.content, source=source, article=article)
        article.title = engine.apply_title(article.title, source=source, article=article)
        return article
    if not article.link:
        return article
    analyze_url = AnalyzeUrl(article.link, source=source, rule_data=article, engine=engine)
    res = analyze_url.get_str_response()
    res = run_login_check(analyze_url, source, res)
    if not res.body:
        return article
    analyze_rule = AnalyzeRule(article, source, engine=engine)
    analyze_rule.set_content(res.body).set_base_url(res.url)
    analyze_rule.set_redirect_url(res.url)
    analyze_rule.set_rss_article(article)  # bind rssArticle for JS rules
    if source.ruleTitle:
        title = analyze_rule.get_string(source.ruleTitle) or article.title
        article.title = engine.apply_title(title, source=source, article=article)
    raw_content = analyze_rule.get_string(source.ruleContent, unescape=False) if source.ruleContent else ""
    if raw_content:
        article.content = engine.apply_content(
            format_html(raw_content),
            source=source,
            article=article,
        )
    elif article.description:
        article.content = engine.apply_content(article.description, source=source, article=article)
    return article
