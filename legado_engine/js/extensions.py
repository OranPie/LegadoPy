"""JsExtensions – Java bridge object exposed as `java` in JS contexts."""
from __future__ import annotations
import base64
import hashlib
import html
import json
import os
import re
import shutil
import tempfile
import threading
import urllib.parse
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests as _requests

from ..engine import resolve_engine
from ..exceptions import UnsupportedHeadlessOperation
from ..models.js_url import JsURL
from ..utils.html_formatter import format_keep_img


class JsExtensions:
    """
    Provides the 'java' object available in JS context.
    Mirrors io.legado.app.help.JsExtensions.
    """

    def __init__(
        self,
        base_url: str = "",
        put_fn: Optional[Callable[[str, str], None]] = None,
        get_fn: Optional[Callable[[str], str]] = None,
        ajax_fn: Optional[Callable[[str], Optional[str]]] = None,
        source_getter: Optional[Callable[[], Any]] = None,
        header_map_getter: Optional[Callable[[], Dict[str, str]]] = None,
        response_fn: Optional[Callable[[], Any]] = None,
        engine=None,
    ) -> None:
        self.engine = resolve_engine(engine)
        self._base_url = base_url
        self._put = put_fn or (lambda k, v: None)
        self._get = get_fn or (lambda k: "")
        self._ajax = ajax_fn or self._default_ajax
        self._source_getter = source_getter or (lambda: None)
        self._header_map_getter = header_map_getter or (lambda: {})
        self._response_fn = response_fn or (lambda: None)
        self._allow_browser_capture = False
        self.logs = []
        self.toasts = []
        self.browser_url = ""
        self.browser_title = ""

    def _default_ajax(self, url: str) -> Optional[str]:
        try:
            r = _requests.get(url, timeout=15)
            r.raise_for_status()
            return r.text
        except Exception:
            return None

    # ---- network ----

    def ajax(self, url: Any) -> Optional[str]:
        url_str = url[0] if isinstance(url, list) else str(url)
        return self._ajax(url_str)

    def ajaxAll(self, url_list) -> list:  # noqa: N802
        return [self.connect(u) for u in url_list]

    def connect(self, url: str, header: Optional[str] = None) -> Any:
        from ..analyze.analyze_url import AnalyzeUrl
        header_map = None
        if header:
            try:
                parsed = json.loads(header)
                if isinstance(parsed, dict):
                    header_map = {str(k): str(v) for k, v in parsed.items()}
            except Exception:
                header_map = None
        source = self.get_source()
        return AnalyzeUrl(
            url,
            source=source,
            header_map_f=header_map,
            engine=self.engine,
        ).get_str_response()

    # ---- variable store ----

    def put(self, key: str, value: str) -> str:
        self._put(str(key), str(value))
        return str(value)

    def get(self, key: str, headers: Optional[Dict[str, str]] = None) -> Any:
        if headers is None:
            return self._get(str(key))
        if isinstance(headers, str):
            try:
                import json

                headers = json.loads(headers) or {}
            except Exception:
                headers = {}
        return self._request_compat("GET", str(key), headers=headers)

    def get_source(self) -> Any:
        return self._source_getter()

    def getHeaderMap(self) -> Dict[str, str]:  # noqa: N802
        return self._header_map_getter()

    def getResponse(self) -> Any:  # noqa: N802
        return self._response_fn()

    def cachePut(self, key: str, value: Any) -> Any:  # noqa: N802
        return self.engine.cache.put(key, value)

    def cacheGet(self, key: str, default: Any = "") -> Any:  # noqa: N802
        return self.engine.cache.get(key, default)

    def cacheRemove(self, key: str) -> None:  # noqa: N802
        self.engine.cache.remove(key)

    def cacheClear(self) -> None:  # noqa: N802
        self.engine.cache.clear()

    # ---- encoding ----

    def base64Encode(self, text: str, charset: str = "UTF-8") -> str:  # noqa: N802
        return base64.b64encode(text.encode(charset, errors="replace")).decode()

    def base64Decode(self, text: str, charset: str = "UTF-8") -> str:  # noqa: N802
        try:
            return base64.b64decode(text).decode(charset, errors="replace")
        except Exception:
            return ""

    def base64DecodeToByteArray(self, text: str) -> bytes:  # noqa: N802
        try:
            return base64.b64decode(text)
        except Exception:
            return b""

    def strToBytes(self, text: str, charset: str = "UTF-8") -> bytes:  # noqa: N802
        try:
            return str(text).encode(charset, errors="replace")
        except Exception:
            return str(text).encode("utf-8", errors="replace")

    def bytesToStr(self, data: Any, charset: str = "UTF-8") -> str:  # noqa: N802
        if isinstance(data, str):
            return data
        if isinstance(data, (bytes, bytearray)):
            try:
                return bytes(data).decode(charset, errors="replace")
            except Exception:
                return bytes(data).decode("utf-8", errors="replace")
        if isinstance(data, list):
            try:
                return bytes(int(item) & 0xFF for item in data).decode(charset, errors="replace")
            except Exception:
                return ""
        return str(data)

    def hexDecodeToByteArray(self, hex_str: str) -> bytes:  # noqa: N802
        try:
            return bytes.fromhex(hex_str)
        except Exception:
            return b""

    def hexEncode(self, data: Any) -> str:  # noqa: N802
        if isinstance(data, (bytes, bytearray)):
            return data.hex()
        return str(data).encode().hex()

    def hexDecode(self, hex_str: str) -> str:  # noqa: N802
        try:
            return bytes.fromhex(hex_str).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def hexDecodeToString(self, hex_str: str) -> str:  # noqa: N802
        return self.hexDecode(hex_str)

    def hexEncodeToString(self, text: str) -> str:  # noqa: N802
        return self.hexEncode(text)

    def md5(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def md5Encode(self, text: str) -> str:  # noqa: N802
        return self.md5(text)

    def md5Encode16(self, text: str) -> str:  # noqa: N802
        digest = self.md5(text)
        return digest[8:24]

    def sha1(self, text: str) -> str:
        return hashlib.sha1(text.encode()).hexdigest()

    def sha256(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def urlEncode(self, text: str, charset: str = "UTF-8") -> str:  # noqa: N802
        return urllib.parse.quote(text, encoding=charset)

    def encodeURI(self, text: str, charset: str = "UTF-8") -> str:  # noqa: N802
        return self.urlEncode(text, charset)

    def urlDecode(self, text: str, charset: str = "UTF-8") -> str:  # noqa: N802
        return urllib.parse.unquote(text, encoding=charset)

    def htmlEscape(self, text: str) -> str:  # noqa: N802
        return html.escape(text)

    def htmlUnescape(self, text: str) -> str:  # noqa: N802
        return html.unescape(text)

    def strToJson(self, text: str) -> Any:  # noqa: N802
        import json
        try:
            return json.loads(text)
        except Exception:
            return None

    def jsonToStr(self, obj: Any) -> str:  # noqa: N802
        import json
        return json.dumps(obj, ensure_ascii=False)

    def log(self, msg: str) -> None:
        self.logs.append(str(msg))
        return msg

    def logType(self, any_value: Any) -> None:  # noqa: N802
        if any_value is None:
            self.log("null")
        else:
            self.log(type(any_value).__name__)

    def longToast(self, msg: str) -> None:  # noqa: N802
        self.toasts.append(str(msg))

    def toast(self, msg: str) -> None:
        self.toasts.append(str(msg))

    def deviceID(self) -> str:  # noqa: N802
        return str(getattr(self.engine, "device_id", ""))

    def androidId(self) -> str:  # noqa: N802
        return str(getattr(self.engine, "android_id", getattr(self.engine, "device_id", "")))

    def startBrowser(self, url: str, title: str = "") -> None:  # noqa: N802
        raise UnsupportedHeadlessOperation("startBrowser", str(url))

    def startBrowserAwait(self, url: str, title: str = "") -> Any:  # noqa: N802
        raise UnsupportedHeadlessOperation("startBrowserAwait", str(url))

    def webView(self, html: Optional[str], url: Optional[str], js: Optional[str]) -> str:  # noqa: N802
        raise UnsupportedHeadlessOperation("webView", str(url or "")[:120])

    def webViewGetSource(  # noqa: N802
        self,
        html: Optional[str],
        url: Optional[str],
        js: Optional[str],
        sourceRegex: str,
    ) -> str:
        raise UnsupportedHeadlessOperation("webViewGetSource", sourceRegex)

    def webViewGetOverrideUrl(  # noqa: N802
        self,
        html: Optional[str],
        url: Optional[str],
        js: Optional[str],
        overrideUrlRegex: str,
    ) -> str:
        raise UnsupportedHeadlessOperation("webViewGetOverrideUrl", overrideUrlRegex)

    def getVerificationCode(self, imageUrl: str) -> str:  # noqa: N802
        raise UnsupportedHeadlessOperation("getVerificationCode", imageUrl)

    def getBaseUrl(self) -> str:  # noqa: N802
        return self._base_url

    def htmlFormat(self, text: str) -> str:  # noqa: N802
        return format_keep_img(text, self._base_url)

    def toURL(self, url: str, baseUrl: Optional[str] = None) -> JsURL:  # noqa: N802
        return JsURL.from_url(str(url), baseUrl or self._base_url or None)

    def timeFormat(self, time_ms: Any) -> str:  # noqa: N802
        try:
            value = float(time_ms)
        except Exception:
            return ""
        if value > 10_000_000_000:
            value /= 1000.0
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")

    def timeFormatUTC(self, time_ms: Any, fmt: str, sh: int) -> str:  # noqa: N802
        try:
            value = float(time_ms)
        except Exception:
            return ""
        if value > 10_000_000_000:
            value /= 1000.0
        tz = timezone(timedelta(hours=int(sh)))
        py_fmt = (
            str(fmt or "yyyy-MM-dd HH:mm:ss")
            .replace("yyyy", "%Y")
            .replace("MM", "%m")
            .replace("dd", "%d")
            .replace("HH", "%H")
            .replace("mm", "%M")
            .replace("ss", "%S")
        )
        return datetime.fromtimestamp(value, tz=tz).strftime(py_fmt)

    def getWebViewUA(self) -> str:  # noqa: N802
        return (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        )

    def startBrowserDp(self, url: str, title: str = "") -> None:  # noqa: N802
        self.startBrowser(url, title)

    def showReadingBrowser(self, url: str, title: str = "") -> None:  # noqa: N802
        self.startBrowser(url, title)

    def qread(self) -> bool:
        return False

    def randomUUID(self) -> str:  # noqa: N802
        return str(uuid.uuid4())

    def cacheFile(self, url: str, saveTime: int = 0) -> str:  # noqa: N802
        cache_key = self.md5Encode16(str(url))
        cached = self.engine.get_cached_text(cache_key)
        if cached is not None:
            return cached
        text = self._read_text_resource(str(url))
        self.engine.put_cached_text(cache_key, text, int(saveTime or 0))
        return text

    def importScript(self, path: str) -> str:  # noqa: N802
        path_str = str(path)
        if path_str.startswith(("http://", "https://")):
            return self.cacheFile(path_str)
        return self._read_text_resource(path_str)

    def _read_text_resource(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            response = self.connect(path_or_url)
            body_obj = getattr(response, "body", None)
            if callable(body_obj):
                body_obj = body_obj()
            if hasattr(body_obj, "string") and callable(body_obj.string):
                return str(body_obj.string())
            if isinstance(body_obj, str):
                return body_obj
            if hasattr(response, "body") and not callable(getattr(response, "body")):
                return str(getattr(response, "body") or "")
            return ""
        path = Path(path_or_url).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.read_text(encoding="utf-8")

    def _request_compat(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[str] = None,
    ) -> Any:
        from ..pipeline import JsBody, JsHeaders

        session = self.engine.get_http_session("")
        request_headers = {str(k): str(v) for k, v in (headers or {}).items()}
        try:
            response = session.request(
                method.upper(),
                str(url),
                headers=request_headers,
                data=body,
                allow_redirects=False,
                timeout=30,
            )
        except Exception as exc:
            response = None
            error_text = str(exc)
        else:
            error_text = ""

        class _RequestInfo:
            def __init__(self, request_url: str) -> None:
                self._request_url = request_url

            def url(self) -> str:
                return self._request_url

        class _RawInfo:
            def __init__(self, request_url: str) -> None:
                self._request_url = request_url

            def request(self) -> _RequestInfo:
                return _RequestInfo(self._request_url)

        class _CompatResponse:
            def __init__(self) -> None:
                if response is None:
                    self._url = str(url)
                    self._body = error_text
                    self._status = 599
                    self._headers: Dict[str, str] = {}
                    self._message = error_text
                    self._request_url = str(url)
                else:
                    self._url = str(response.url)
                    self._body = response.text if method.upper() != "HEAD" else ""
                    self._status = int(response.status_code)
                    self._headers = {str(k): str(v) for k, v in response.headers.items()}
                    self._message = getattr(response, "reason", "") or ""
                    self._request_url = str(getattr(response.request, "url", url))

            def body(self) -> JsBody:
                return JsBody(self._body)

            def code(self) -> int:
                return self._status

            def header(self, name: str) -> Optional[str]:
                return self.headers().get(name)

            def headers(self) -> JsHeaders:
                return JsHeaders(self._headers)

            def message(self) -> str:
                return self._message

            def raw(self) -> _RawInfo:
                return _RawInfo(self._request_url)

        return _CompatResponse()

    def head(self, url: str, headers: Dict[str, str]) -> Any:  # noqa: N802
        if isinstance(headers, str):
            try:
                headers = json.loads(headers) or {}
            except Exception:
                headers = {}
        return self._request_compat("HEAD", url, headers=headers)

    def post(self, url: str, body: str, headers: Dict[str, str]) -> Any:
        if isinstance(headers, str):
            try:
                headers = json.loads(headers) or {}
            except Exception:
                headers = {}
        return self._request_compat("POST", url, headers=headers, body=body)

    # ------------------------------------------------------------------
    # Cookie helpers (mirrors JsExtensions.getCookie / setCookie)
    # ------------------------------------------------------------------

    def getCookie(self, tag: str, key: Optional[str] = None) -> str:  # noqa: N802
        """Return cookie for *tag*. With *key*, extract a single cookie attribute."""
        cookie_store = getattr(self.engine, "cookie_store", None)
        if cookie_store is None:
            return ""
        full = cookie_store.getCookie(str(tag)) if hasattr(cookie_store, "getCookie") else ""
        if key is None:
            return full or ""
        # Extract key=value from a Cookie header string
        for part in (full or "").split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                if k.strip() == key:
                    return v.strip()
        return ""

    def setCookie(self, tag: str, cookie: str) -> None:  # noqa: N802
        cookie_store = getattr(self.engine, "cookie_store", None)
        if cookie_store and hasattr(cookie_store, "setCookie"):
            cookie_store.setCookie(str(tag), str(cookie))

    # ------------------------------------------------------------------
    # File-system helpers (mirrors JsExtensions file section)
    # ------------------------------------------------------------------

    @staticmethod
    def _files_cache_dir() -> Path:
        """Return (and create) the base cache directory for downloaded files."""
        d = Path.home() / ".legadopy" / "cache" / "files"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _safe_path(self, relative: str) -> Path:
        """Resolve *relative* against the files cache dir with path-traversal guard."""
        base = self._files_cache_dir()
        # Strip leading separator so Path joining works correctly
        rel = relative.lstrip("/\\")
        full = (base / rel).resolve()
        if not str(full).startswith(str(base.resolve())):
            raise SecurityError(f"Path traversal blocked: {relative!r}")
        return full

    def getFile(self, path: str) -> Path:  # noqa: N802
        """Return a Path for *path* relative to the files cache directory."""
        return self._safe_path(str(path))

    def readFile(self, path: str) -> Optional[bytes]:  # noqa: N802
        """Read and return bytes from a cached file, or None if not found."""
        f = self._safe_path(str(path))
        if f.exists() and f.is_file():
            return f.read_bytes()
        return None

    def readTxtFile(self, path: str, charsetName: str = "") -> str:  # noqa: N802
        """Read text from a cached file with optional charset override."""
        f = self._safe_path(str(path))
        if not f.exists() or not f.is_file():
            return ""
        raw = f.read_bytes()
        if charsetName:
            return raw.decode(charsetName, errors="replace")
        # Auto-detect: try UTF-8, then GBK
        for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                pass
        return raw.decode("latin-1")

    def deleteFile(self, path: str) -> bool:  # noqa: N802
        """Delete a file relative to the files cache directory. Returns True on success."""
        try:
            f = self._safe_path(str(path))
            if f.exists():
                if f.is_file():
                    f.unlink()
                elif f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
                return True
            return False
        except Exception:
            return False

    def downloadFile(self, url_or_content: str, url: Optional[str] = None) -> str:  # noqa: N802
        """Download *url* to cache dir; return relative path.
        Legacy two-arg form: first arg is hex content, second is url for extension."""
        base = self._files_cache_dir()
        if url is not None:
            # Deprecated two-arg form: hex-encoded content + url for ext detection
            try:
                import binascii
                raw = binascii.unhexlify(str(url_or_content))
            except Exception:
                raw = str(url_or_content).encode()
            # Guess extension from URL
            ext = str(url).rsplit(".", 1)[-1].split("?")[0][:8] if "." in str(url) else "bin"
            name = f"{self.md5Encode16(str(url))}.{ext}"
            f = base / name
            f.write_bytes(raw)
            return f"/{name}"

        # Normal form: download from URL
        actual_url = str(url_or_content)
        ext = actual_url.rsplit(".", 1)[-1].split("?")[0][:8] if "." in actual_url else "bin"
        name = f"{self.md5Encode16(actual_url)}.{ext}"
        f = base / name
        if f.exists():
            return f"/{name}"
        try:
            r = _requests.get(actual_url, timeout=30, stream=True)
            r.raise_for_status()
            with open(f, "wb") as fh:
                for chunk in r.iter_content(65536):
                    fh.write(chunk)
        except Exception:
            f.unlink(missing_ok=True)
            return ""
        return f"/{name}"

    def unzipFile(self, zipPath: str) -> str:  # noqa: N802
        return self.unArchiveFile(zipPath)

    def un7zFile(self, zipPath: str) -> str:  # noqa: N802
        return self.unArchiveFile(zipPath)

    def unrarFile(self, zipPath: str) -> str:  # noqa: N802
        return self.unArchiveFile(zipPath)

    def unArchiveFile(self, zipPath: str) -> str:  # noqa: N802
        """Extract an archive at *zipPath* (relative). Returns relative folder path."""
        if not zipPath:
            return ""
        try:
            src = self._safe_path(str(zipPath))
            if not src.exists():
                return ""
            folder_name = self.md5Encode16(src.name)
            out_dir = self._files_cache_dir() / folder_name
            out_dir.mkdir(parents=True, exist_ok=True)
            # Try zipfile first; for rar/7z fall back to shutil.unpack_archive
            try:
                with zipfile.ZipFile(src) as zf:
                    zf.extractall(out_dir)
            except zipfile.BadZipFile:
                try:
                    shutil.unpack_archive(str(src), str(out_dir))
                except Exception:
                    return ""
            return f"/{folder_name}"
        except Exception:
            return ""

    def getTxtInFolder(self, path: str) -> str:  # noqa: N802
        """Read and concatenate all text files in a cache folder."""
        if not path:
            return ""
        try:
            folder = self._safe_path(str(path))
            if not folder.is_dir():
                return ""
            parts: list[str] = []
            for f in sorted(folder.iterdir()):
                if f.is_file():
                    parts.append(self.readTxtFile(str(f.relative_to(self._files_cache_dir()))))
            # Clean up folder after reading
            shutil.rmtree(folder, ignore_errors=True)
            return "\n".join(parts)
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # preUpdateJs-only callbacks (set by AnalyzeRule when pre_update_js=True)
    # ------------------------------------------------------------------

    def reGetBook(self) -> None:  # noqa: N802
        """Re-fetch book info + URL via precise search (only valid in preUpdateJs)."""
        fn = getattr(self, "_re_get_book_fn", None)
        if callable(fn):
            fn()

    def refreshTocUrl(self) -> None:  # noqa: N802
        """Refresh tocUrl by re-fetching book info (only valid in preUpdateJs)."""
        fn = getattr(self, "_refresh_toc_url_fn", None)
        if callable(fn):
            fn()
