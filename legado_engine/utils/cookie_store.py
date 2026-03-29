"""
Cookie store – in-memory mirror of CookieStore.kt.
"""
from __future__ import annotations
from typing import Dict, Optional


class CookieStore:
    """Simple in-memory per-domain cookie store."""

    def __init__(self) -> None:
        self._store: Dict[str, str] = {}

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        if "://" in domain:
            try:
                from urllib.parse import urlparse
                domain = urlparse(domain).netloc
            except Exception:
                pass
        return domain

    def get_cookie(self, domain: str) -> str:
        domain = self._normalize_domain(domain)
        return self._store.get(domain, "")

    def getCookie(self, domain: str) -> str:  # noqa: N802
        return self.get_cookie(domain)

    def set_cookie(self, domain: str, cookie: str) -> None:
        self._store[self._normalize_domain(domain)] = cookie

    def setCookie(self, domain: str, cookie: str) -> None:  # noqa: N802
        self.set_cookie(domain, cookie)


    def put_cookie(self, domain: str, cookie: str) -> None:
        self.set_cookie(domain, cookie)

    def replace_cookie(self, domain: str, cookie: str) -> None:
        self.set_cookie(domain, cookie)

    def remove_cookie(self, domain: str) -> None:
        self._store.pop(self._normalize_domain(domain), None)

    def clear(self) -> None:
        self._store.clear()

    def merge_cookies(self, a: str, b: Optional[str]) -> str:
        if not b:
            return a
        if not a:
            return b
        d = {}
        for s in (a, b):
            for part in s.split(";"):
                part = part.strip()
                if not part:
                    continue
                if "=" in part:
                    k, _, v = part.partition("=")
                    d[k.strip()] = v.strip()
                else:
                    d[part] = ""
        return "; ".join(f"{k}={v}" if v else k for k, v in d.items())

    def load_from_file(self, path: str) -> None:
        """Load cookies from a Netscape-format cookie jar file."""
        import os
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7:
                        domain = parts[0]
                        name = parts[5]
                        value = parts[6]
                        # Convert to our storage format: domain -> "k=v; k2=v2"
                        # We need to append, not overwrite
                        existing = self._store.get(domain, "")
                        new_c = f"{name}={value}"
                        self._store[domain] = self.merge_cookies(existing, new_c)
        except Exception:
            pass

    @staticmethod
    def _parse(s: str) -> dict:  # Old parse helper not needed
        pass


# Module-level singleton (mirrors Kotlin object)
cookie_store = CookieStore()
