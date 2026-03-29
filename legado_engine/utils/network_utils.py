"""
Network utilities – mirrors NetworkUtils.kt and related helpers.
"""
from __future__ import annotations
import json
import re
from typing import Optional
from urllib.parse import urlparse, urljoin


def get_absolute_url(base: Optional[str], url: Optional[str]) -> str:
    """
    Mirrors NetworkUtils.getAbsoluteURL().
    Resolves a potentially-relative url against base.
    """
    if not url:
        return ""
    url = url.strip()
    if url.startswith(("http://", "https://", "data:", "ftp://")):
        return url
    if not base:
        return url
    try:
        return urljoin(base, url)
    except Exception:
        return url


def get_base_url(url: str) -> Optional[str]:
    """Mirrors NetworkUtils.getBaseUrl() – returns scheme+host."""
    try:
        p = urlparse(url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    except Exception:
        pass
    return None


def get_sub_domain(url: str) -> str:
    """Returns the domain (host) portion of a URL."""
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


def is_json(text: str) -> bool:
    """Quick heuristic: is this string likely a JSON object or array?"""
    s = text.strip()
    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
        try:
            json.loads(s)
            return True
        except Exception:
            pass
    return False


def is_data_url(url: str) -> bool:
    return url.strip().startswith("data:")


def encoded_query(params: str) -> bool:
    """Rough check: already percent-encoded?"""
    return "%" in params


_ABSOLUTE_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://")


def is_absolute_url(url: str) -> bool:
    return bool(_ABSOLUTE_URL_RE.match(url))
