from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import parse_qsl, urljoin, urlparse


@dataclass
class JsURL:
    host: str
    origin: str
    pathname: str
    searchParams: Optional[Dict[str, str]]

    @classmethod
    def from_url(cls, url: str, base_url: Optional[str] = None) -> "JsURL":
        resolved = urljoin(base_url, url) if base_url else url
        parsed = urlparse(resolved)
        host = parsed.hostname or ""
        origin = f"{parsed.scheme}://{host}" if parsed.scheme and host else ""
        if parsed.port:
            origin = f"{origin}:{parsed.port}"
        params = dict(parse_qsl(parsed.query, keep_blank_values=True)) or None
        return cls(
            host=host,
            origin=origin,
            pathname=parsed.path or "",
            searchParams=params,
        )

    def to_dict(self):
        return {
            "host": self.host,
            "origin": self.origin,
            "pathname": self.pathname,
            "searchParams": dict(self.searchParams or {}) if self.searchParams is not None else None,
        }


__all__ = ["JsURL"]
