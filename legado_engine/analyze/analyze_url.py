from __future__ import annotations
"""
AnalyzeUrl – 1:1 port of AnalyzeUrl.kt.
"""


import json
import re
import urllib.parse
from typing import Any, Dict, Optional, TYPE_CHECKING

import requests as _requests
from requests.utils import get_encoding_from_headers

from .rule_analyzer import RuleAnalyzer
from ..engine import resolve_engine
from ..exceptions import UnsupportedHeadlessOperation
from ..js import eval_js, JsExtensions
from ..utils.network_utils import get_absolute_url, get_base_url, get_sub_domain
from ..utils.cookie_store import CookieStore, cookie_store

if TYPE_CHECKING:
    from ..models.book_source import BaseSource
    from ..models.book import Book, BookChapter, RuleData


# ---------------------------------------------------------------------------
# Patterns (mirror AnalyzeUrl companion object)
# ---------------------------------------------------------------------------

# Separates the URL from the JSON option block: "url , {...}"
_PARAM_PATTERN = re.compile(r"\s*,\s*(?=\{)")

# Page substitution: <p1,p2,p3>
_PAGE_PATTERN = re.compile(r"<(.*?)>")

# JS blocks in URL
_JS_PATTERN = re.compile(
    r"@js:([\s\S]*?)(?=@@|@CSS:|@XPath:|@Json:|$)"
    r"|<js>([\s\S]*?)</js>"
    r"|^js[:\s]([\s\S]*)$",
    re.IGNORECASE,
)

# Default User-Agent
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# UrlOption dataclass (mirrors AnalyzeUrl.UrlOption)
# ---------------------------------------------------------------------------

class UrlOption:
    """Mirrors AnalyzeUrl.UrlOption data class."""

    def __init__(self, d: Dict[str, Any]) -> None:
        self._method: Optional[str] = d.get("method")
        self._charset: Optional[str] = d.get("charset")
        self._headers: Any = d.get("headers")
        self._body: Any = d.get("body")
        self._origin: Optional[str] = d.get("origin")
        self._retry: Optional[int] = int(d["retry"]) if "retry" in d else None
        self._type: Optional[str] = d.get("type")
        self._webview: Any = d.get("webView")
        self._webjs: Optional[str] = d.get("webJs")
        self._js: Optional[str] = d.get("js")
        self._server_id: Optional[int] = int(d["serverID"]) if "serverID" in d else None
        self._webview_delay: Optional[int] = int(d["webViewDelayTime"]) if "webViewDelayTime" in d else None

    def get_method(self) -> Optional[str]:
        return self._method

    def get_charset(self) -> Optional[str]:
        return self._charset

    def get_header_map(self) -> Optional[Dict[str, str]]:
        h = self._headers
        if isinstance(h, dict):
            return {str(k): str(v) for k, v in h.items()}
        if isinstance(h, str):
            try:
                obj = json.loads(h)
                if isinstance(obj, dict):
                    return {str(k): str(v) for k, v in obj.items()}
            except Exception:
                pass
        return None

    def get_body(self) -> Optional[str]:
        b = self._body
        if b is None:
            return None
        if isinstance(b, str):
            return b
        return json.dumps(b, ensure_ascii=False)

    def get_type(self) -> Optional[str]:
        return self._type

    def get_retry(self) -> int:
        return self._retry or 0

    def use_webview(self) -> bool:
        return self._webview not in (None, "", False, "false")

    def get_webjs(self) -> Optional[str]:
        return self._webjs

    def get_js(self) -> Optional[str]:
        return self._js

    def get_server_id(self) -> Optional[int]:
        return self._server_id


def _parse_url_option(option_str: str) -> Optional[UrlOption]:
    """Try strict JSON then lenient JSON parse."""
    try:
        d = json.loads(option_str)
        if isinstance(d, dict):
            return UrlOption(d)
    except Exception:
        pass
    return None



import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import requests as _requests

from .rule_analyzer import RuleAnalyzer
from ..js import eval_js, JsExtensions
from ..utils.network_utils import get_absolute_url, get_base_url, get_sub_domain
from ..utils.cookie_store import cookie_store

if TYPE_CHECKING:
    from ..models.book_source import BaseSource
    from ..models.book import Book, BookChapter, RuleData


class StrResponse:
    """Mirrors StrResponse – wraps an HTTP response."""

    def __init__(self, url: str = "", body: Optional[str] = None,
                 status_code: int = 200, headers: Optional[Dict] = None) -> None:
        self.url = url
        self.body = body
        self.status_code = status_code
        self.headers: Dict[str, str] = headers or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "_legado_type": "StrResponse",
            "url": self.url,
            "bodyText": "" if self.body is None else str(self.body),
            "statusCode": int(self.status_code),
            "headersMap": {str(k): str(v) for k, v in self.headers.items()},
        }


class JsCookie:
    """Mirrors the 'cookie' object in JS context."""
    def __init__(self, store: Optional[CookieStore] = None) -> None:
        self._store = store or cookie_store

    def getCookie(self, url: str) -> str:  # noqa: N802
        domain = get_sub_domain(url)
        return self._store.get_cookie(domain) or ""

    def setCookie(self, url: str, cookie: str) -> None:  # noqa: N802
        domain = get_sub_domain(url)
        self._store.set_cookie(domain, cookie)

    def removeCookie(self, url: str) -> None:  # noqa: N802
        domain = get_sub_domain(url)
        self._store.set_cookie(domain, "")

    def getKey(self, url: str, key: str) -> Optional[str]:  # noqa: N802
        """Return the value of a specific cookie key for the given URL's domain."""
        cookie_str = self.getCookie(url)
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                if k.strip() == key:
                    return v.strip()
        return None


class AnalyzeUrl:
    """
    1:1 port of AnalyzeUrl.kt.
    Parses a Legado URL-rule string and provides HTTP fetch methods.
    """

    def __init__(
        self,
        m_url: str,
        key: Optional[str] = None,
        page: Optional[int] = None,
        speak_text: Optional[str] = None,
        speak_speed: Optional[int] = None,
        base_url: str = "",
        source: "Optional[BaseSource]" = None,
        rule_data: "Optional[RuleData]" = None,
        chapter: "Optional[BookChapter]" = None,
        read_timeout: Optional[int] = None,
        call_timeout: Optional[int] = None,
        header_map_f: Optional[Dict[str, str]] = None,
        engine=None,
    ) -> None:
        self._engine = resolve_engine(engine)
        self._m_url = m_url
        self._key = key
        self._page = page
        self._speak_text = speak_text
        self._speak_speed = speak_speed
        self._base_url = base_url
        self._source = source
        self._rule_data = rule_data
        self._chapter = chapter
        self._read_timeout = read_timeout
        self._call_timeout = call_timeout

        # Strip option block from base_url
        bm = _PARAM_PATTERN.search(base_url)
        if bm:
            self._base_url = base_url[: bm.start()]

        # Public state
        self.rule_url: str = ""
        self.url: str = ""
        self.type: Optional[str] = None
        self.header_map: Dict[str, str] = {}
        self._body: Optional[str] = None
        self._url_no_query: str = ""
        self._encoded_form: Optional[str] = None
        self._encoded_query: Optional[str] = None
        self._charset: Optional[str] = None
        self._method: str = "GET"
        self._proxy: Optional[str] = None
        self._retry: int = 0
        self._use_webview: bool = False
        self._web_js: Optional[str] = None
        self.server_id: Optional[int] = None
        self._enabled_cookie_jar: bool = source.enabledCookieJar is True if source is not None else True

        # Java/JS bindings
        self._java = JsExtensions(
            base_url=self._base_url,
            put_fn=lambda k, v: self._put(k, v),
            get_fn=lambda k: self._get(k),
            source_getter=lambda: self._source,
            header_map_getter=lambda: self.header_map,
            response_fn=lambda: self.get_str_response(),
            engine=self._engine,
        )

        # Merge source headers
        if header_map_f is not None:
            self.header_map.update(header_map_f)
        elif source is not None:
            src_headers = source.get_header_map(True, engine=self._engine)
            self.header_map.update(src_headers)
            if "proxy" in self.header_map:
                self._proxy = self.header_map.pop("proxy")

        self._init_url()

        # domain for cookie lookup
        self._domain = get_sub_domain(source.get_key() if source else self.url)

    # ------------------------------------------------------------------
    # Internal variable store (delegates to rule_data / chapter)
    # ------------------------------------------------------------------

    def _put(self, key: str, value: str) -> None:
        if self._chapter:
            self._chapter.put_variable(key, value)
        elif self._rule_data:
            self._rule_data.put_variable(key, value)

    def _get(self, key: str) -> str:
        val = (
            (self._chapter.get_variable(key) if self._chapter else None)
            or (self._rule_data.get_variable(key) if self._rule_data else None)
            or ""
        )
        return val or ""

    # ------------------------------------------------------------------
    # evalJS
    # ------------------------------------------------------------------

    def eval_js(self, js_str: str, result: Any = None) -> Any:
        from ..models.book import Book
        bindings = {
            "java":        self._java,
            "baseUrl":     self._base_url,
            "url":         self.url,
            "page":        self._page,
            "key":         self._key,
            "speakText":   self._speak_text,
            "speakSpeed":  self._speak_speed,
            "book":        self._rule_data if isinstance(self._rule_data, Book) else None,
            "source":      self._source,
            "result":      result,
            "cookie":      JsCookie(self._engine.cookie_store),
            "cache":       self._engine.cache,
            "engine":      self._engine,
        }
        return eval_js(js_str, result=result, bindings=bindings, java_obj=self._java)

    # ------------------------------------------------------------------
    # initUrl pipeline (mirrors AnalyzeUrl.initUrl())
    # ------------------------------------------------------------------

    def _init_url(self) -> None:
        self.rule_url = self._m_url
        self._analyze_js()
        self._replace_key_page_js()
        self._analyze_url()

    def _analyze_js(self) -> None:
        """Execute @js: / <js> blocks in URL, mirrors analyzeJs()."""
        start = 0
        result = self.rule_url
        matches = list(_JS_PATTERN.finditer(self.rule_url))
        for m in matches:
            if m.start() > start:
                prefix = self.rule_url[start: m.start()].strip()
                if prefix:
                    result = prefix.replace("@result", str(result))
            js_code = m.group(3) or m.group(2) or m.group(1)
            # Some sources have trailing /js which invalidates the script (evaluates to NaN)
            if js_code and js_code.strip().endswith("/js"):
                js_code = js_code.strip()[:-3]
            
            result = str(self.eval_js(js_code, result) or "")
            start = m.end()
        if len(self.rule_url) > start:
            suffix = self.rule_url[start:].strip()
            if suffix:
                result = suffix.replace("@result", str(result))
        self.rule_url = result

    def _replace_key_page_js(self) -> None:
        """Replace {{js}}, <page> tokens, mirrors replaceKeyPageJs()."""
        # Inline {{ }}
        if "{{" in self.rule_url and "}}" in self.rule_url:
            ra = RuleAnalyzer(self.rule_url)

            def _eval(js: str) -> Optional[str]:
                val = self.eval_js(js)
                if val is None:
                    return ""
                if isinstance(val, float) and val % 1.0 == 0:
                    return f"{int(val)}"
                return str(val)

            resolved = ra.inner_rule("{{", fr=_eval)
            if resolved:
                self.rule_url = resolved

        # Page substitution <p1,p2,...>
        if self._page is not None:
            def _page_repl(m: re.Match) -> str:
                pages = m.group(1).split(",")
                idx = self._page - 1  # type: ignore[operator]
                if idx < len(pages):
                    return pages[idx].strip()
                return pages[-1].strip()
            self.rule_url = _PAGE_PATTERN.sub(_page_repl, self.rule_url)

    def _analyze_url(self) -> None:
        """Parse the final URL string + option JSON, mirrors analyzeUrl()."""
        m = _PARAM_PATTERN.search(self.rule_url)
        url_no_option = self.rule_url[: m.start()] if m else self.rule_url
        self.url = get_absolute_url(self._base_url, url_no_option) or url_no_option
        new_base = get_base_url(self.url)
        if new_base:
            self._base_url = new_base

        if m:
            option_str = self.rule_url[m.end():]
            option = _parse_url_option(option_str)
            if option:
                method = option.get_method()
                if method and method.upper() == "POST":
                    self._method = "POST"
                hm = option.get_header_map()
                if hm:
                    self.header_map.update(hm)
                self._body = option.get_body()
                self.type = option.get_type()
                self._charset = option.get_charset()
                self._retry = option.get_retry()
                self._use_webview = option.use_webview()
                self._web_js = option.get_webjs()
                self.server_id = option.get_server_id()
                js = option.get_js()
                if js:
                    new_url = self.eval_js(js, self.url)
                    if new_url:
                        self.url = str(new_url)

        self._url_no_query = self.url
        if self._method == "GET":
            q_idx = self.url.find("?")
            if q_idx != -1:
                self._encode_query(self.url[q_idx + 1:])
                self._url_no_query = self.url[:q_idx]
        elif self._method == "POST" and self._body:
            import json as _json
            try:
                _json.loads(self._body)
                # It's JSON – leave as body
            except Exception:
                # form-encoded
                self._encode_form(self._body)

    def _encode_query(self, query: str) -> None:
        self._encoded_query = query  # keep as-is; requests handles encoding

    def _encode_form(self, fields: str) -> None:
        self._encoded_form = fields

    # ------------------------------------------------------------------
    # HTTP methods
    # ------------------------------------------------------------------

    def _build_session(self) -> _requests.Session:
        return self._engine.get_http_session(self._proxy or "")

    @staticmethod
    def _guess_response_encoding(response: _requests.Response, body_bytes: bytes) -> str:
        content_type = response.headers.get("Content-Type", "") or response.headers.get("content-type", "")
        header_encoding = None
        if "charset=" in content_type.lower():
            header_encoding = get_encoding_from_headers(response.headers)
        if header_encoding:
            return header_encoding
        sample = body_bytes[:4096]
        lowered = sample.lower()
        meta_patterns = (
            rb'charset=["\']?\s*([a-z0-9._-]+)',
            rb'encoding=["\']?\s*([a-z0-9._-]+)',
        )
        for pattern in meta_patterns:
            match = re.search(pattern, lowered)
            if match:
                try:
                    return match.group(1).decode("ascii", errors="ignore") or "utf-8"
                except Exception:
                    break
        return "utf-8"

    def _set_cookie(self, headers: Dict[str, str]) -> None:
        """Inject stored cookies, mirrors setCookie()."""
        if not self._enabled_cookie_jar:
            return
        stored = self._engine.cookie_store.get_cookie(self._domain)
        if stored:
            existing = headers.get("Cookie") or headers.get("cookie", "")
            merged = self._engine.cookie_store.merge_cookies(stored, existing or None)
            if merged:
                headers["Cookie"] = merged

    def _store_response_cookies(
        self,
        response: _requests.Response,
        session: Optional[_requests.Session] = None,
    ) -> None:
        if not self._enabled_cookie_jar:
            return
        combined: list[str] = []

        def collect_from_jar(jar: Any) -> None:
            try:
                for cookie in jar:
                    combined.append(f"{cookie.name}={cookie.value}")
            except Exception:
                pass

        for item in list(getattr(response, "history", []) or []) + [response]:
            collect_from_jar(getattr(item, "cookies", None))
        if session is not None:
            collect_from_jar(getattr(session, "cookies", None))
        if not combined:
            return
        cookie_text = "; ".join(dict.fromkeys(combined))
        for domain in {
            self._domain,
            get_sub_domain(str(response.url)),
        }:
            if not domain:
                continue
            existing = self._engine.cookie_store.get_cookie(domain)
            self._engine.cookie_store.set_cookie(
                domain,
                self._engine.cookie_store.merge_cookies(existing, cookie_text),
            )

    def is_post(self) -> bool:
        return self._method.upper() == "POST"

    def get_method(self) -> str:
        return self._method

    def get_body(self) -> Optional[str]:
        return self._body

    def get_str_response(
        self,
        js_str: Optional[str] = None,
        source_regex: Optional[str] = None,
        use_webview: bool = False,
    ) -> StrResponse:
        """
        Fetch URL and return StrResponse.
        Mirrors getStrResponse() (sync wrapper).
        """
        if self._use_webview or use_webview or js_str or source_regex:
            raise UnsupportedHeadlessOperation(
                "webViewFetch",
                self.url or self.rule_url or "source-defined request",
            )
        # Handle data: URI
        if self.url.startswith("data:"):
            try:
                import base64 as _b64
                import re as _re
                m = _re.search(r"base64,(.+)", self.url)
                if m:
                    content = m.group(1)
                    # Check for trailing options (comma separated)
                    # Base64 chars: A-Za-z0-9+/=
                    # URL options usually start with ,{ or similar.
                    # Safest is to split on first comma that looks like option separator?
                    # Or just split on first comma. Base64 doesn't have comma.
                    if "," in content:
                        content = content.split(",")[0]

                    decoded = _b64.b64decode(content).decode("utf-8")
                    return StrResponse(
                        url=self.url,
                        body=decoded,
                        status_code=200,
                        headers={}
                    )
            except Exception:
                import traceback
                traceback.print_exc()
                pass

        headers = dict(self.header_map)
        if "User-Agent" not in headers and "user-agent" not in {k.lower() for k in headers}:
            headers["User-Agent"] = _DEFAULT_UA
        self._set_cookie(headers)

        timeout = (self._call_timeout or 30000) / 1000.0
        last_exc: Optional[Exception] = None

        with self._engine.acquire_rate_limit(self._source):
            for attempt in range(max(1, self._retry + 1)):
                try:
                    sess = self._build_session()
                    if self._method == "POST":
                        if self._encoded_form:
                            # parse form fields into dict
                            fields: Dict[str, str] = {}
                            for part in self._encoded_form.split("&"):
                                if "=" in part:
                                    k, _, v = part.partition("=")
                                    fields[urllib.parse.unquote_plus(k)] = urllib.parse.unquote_plus(v)
                                elif part:
                                    fields[urllib.parse.unquote_plus(part)] = ""
                            resp = sess.post(
                                self._url_no_query, data=fields,
                                headers=headers, timeout=timeout, allow_redirects=True
                            )
                        elif self._body:
                            ct = headers.get("Content-Type", "")
                            if ct:
                                resp = sess.post(
                                    self._url_no_query, data=self._body.encode(),
                                    headers=headers, timeout=timeout, allow_redirects=True
                                )
                            else:
                                resp = sess.post(
                                    self._url_no_query, json=json.loads(self._body),
                                    headers=headers, timeout=timeout, allow_redirects=True
                                )
                        else:
                            resp = sess.post(
                                self._url_no_query, headers=headers,
                                timeout=timeout, allow_redirects=True
                            )
                    else:
                        if self._encoded_query:
                            full_url = f"{self._url_no_query}?{self._encoded_query}"
                        else:
                            full_url = self.url
                        resp = sess.get(
                            full_url, headers=headers,
                            timeout=timeout, allow_redirects=True
                        )

                    self._store_response_cookies(resp, sess)
                    body_bytes = resp.content
                    charset = self._charset or self._guess_response_encoding(resp, body_bytes)
                    try:
                        body = body_bytes.decode(charset, errors="replace")
                    except Exception:
                        body = body_bytes.decode("utf-8", errors="replace")
                    return StrResponse(
                        url=str(resp.url),
                        body=body,
                        status_code=resp.status_code,
                        headers=dict(resp.headers),
                    )
                except Exception as e:
                    last_exc = e
                    if attempt < self._retry:
                        time.sleep(0.5 * (attempt + 1))

        raise last_exc or RuntimeError(f"Failed to fetch {self.url}")

    def get_byte_array(self) -> bytes:
        """Fetch URL, return raw bytes."""
        if self._url_no_query.startswith("data:"):
            import base64 as _b64
            import re as _re
            m = _re.search(r"base64,(.+)", self._url_no_query)
            if m:
                return _b64.b64decode(m.group(1))
        headers = dict(self.header_map)
        self._set_cookie(headers)
        with self._engine.acquire_rate_limit(self._source):
            resp = self._build_session().get(
                self.url, headers=headers,
                timeout=(self._call_timeout or 30000) / 1000.0
            )
            self._store_response_cookies(resp)
            return resp.content

    def put(self, key: str, value: str) -> str:
        self._put(key, value)
        return value

    def get(self, key: str) -> str:
        return self._get(key)

    def get_source(self):
        return self._source
