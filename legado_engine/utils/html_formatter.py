"""
HTML formatter utilities – mirrors HtmlFormatter.kt.
"""
from __future__ import annotations
import re
from typing import Optional


def format_html(html: Optional[str]) -> str:
    """
    Mirrors HtmlFormatter.format() – strips tags, normalises whitespace.
    Used for intro/synopsis text.
    """
    if not html:
        return ""
    # Strip tags
    text = re.sub(r"<[^>]+>", "", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def format_keep_img(html: Optional[str], base_url: Optional[str] = None) -> str:
    """
    Mirrors HtmlFormatter.formatKeepImg() – keeps <img> tags,
    resolves relative src attributes.
    """
    if not html:
        return ""
    if base_url:
        from .network_utils import get_absolute_url

        def _fix_src(m: re.Match) -> str:
            src = m.group(1)
            abs_src = get_absolute_url(base_url, src)
            return f'src="{abs_src}"'

        html = re.sub(r'src="([^"]*)"', _fix_src, html, flags=re.IGNORECASE)
        html = re.sub(r"src='([^']*)'", lambda m: f"src=\"{get_absolute_url(base_url, m.group(1))}\"", html, flags=re.IGNORECASE)
    return html


def format_book_name(name: str) -> str:
    """Strips common suffixes/prefixes from book names."""
    if not name:
        return ""
    return re.sub(r"^\s*|\s*$|《|》", "", name).strip()


def format_book_author(author: str) -> str:
    """Strips common author label prefixes."""
    if not author:
        return ""
    cleaned = re.sub(r"^(作者|Author|By)[：:]\s*", "", author, flags=re.IGNORECASE)
    return cleaned.strip()
