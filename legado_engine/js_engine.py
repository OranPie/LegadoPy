"""
JS engine – executes JavaScript snippets in a sandboxed environment.

Mirrors the Rhino-based evalJS() in Legado, providing:
  - java.ajax(url)       → HTTP GET → string
  - java.put(key, value) → store variable
  - java.get(key)        → retrieve variable
  - java.base64Encode/Decode
  - java.md5 / sha1 / sha256
  - java.encode / decode (URL encoding)
  - base64, cookie, cache, source, book, result, baseUrl, page, key

Uses js2py (pure-Python JS engine) as primary; falls back to execjs (requires
Node.js) if available.  Both are optional – missing engines degrade gracefully.
"""
from __future__ import annotations
import base64
import hashlib
import re
import urllib.parse
import html
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional


# ---------------------------------------------------------------------------
# Select JS runtime
# ---------------------------------------------------------------------------

_JS_RUNTIME = None
_JS_ENGINE = "none"

# Try execjs (Node.js) first for better ES6+ support
try:
    import execjs  # type: ignore[import]
    _JS_RUNTIME = execjs.get()
    _JS_ENGINE = "execjs"
except Exception:
    # Fallback to js2py (ES5 only)
    try:
        import js2py  # type: ignore[import]
        _JS_ENGINE = "js2py"
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# JsExtensions – mirrors JsExtensions interface methods exposed to JS as java.XXX
# ---------------------------------------------------------------------------

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
    ) -> None:
        self._base_url = base_url
        self._put = put_fn or (lambda k, v: None)
        self._get = get_fn or (lambda k: "")
        self._ajax = ajax_fn or self._default_ajax

    def _default_ajax(self, url: str) -> Optional[str]:
        try:
            import requests  # type: ignore[import]
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            return r.text
        except Exception:
            return None

    # ---- network ----

    def ajax(self, url: Any) -> Optional[str]:
        url_str = url[0] if isinstance(url, list) else str(url)
        return self._ajax(url_str)

    def ajaxAll(self, url_list) -> list:  # noqa: N802
        return [self.ajax(u) for u in url_list]

    def connect(self, url: str) -> Any:
        return self.ajax(url)

    # ---- variable store ----

    def put(self, key: str, value: str) -> str:
        self._put(str(key), str(value))
        return str(value)

    def get(self, key: str) -> str:
        return self._get(str(key))

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

    def md5(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def sha1(self, text: str) -> str:
        return hashlib.sha1(text.encode()).hexdigest()

    def sha256(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def urlEncode(self, text: str, charset: str = "UTF-8") -> str:  # noqa: N802
        return urllib.parse.quote(text, encoding=charset)

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
        pass  # no-op in headless mode

    def longToast(self, msg: str) -> None:  # noqa: N802
        pass  # no-op in headless mode

    def toast(self, msg: str) -> None:
        pass  # no-op in headless mode

    def deviceID(self) -> str:  # noqa: N802
        raise NotImplementedError("deviceID not available in headless mode")

    def androidId(self) -> str:  # noqa: N802
        raise NotImplementedError("androidId not available in headless mode")

    def startBrowser(self, url: str, title: str = "") -> None:  # noqa: N802
        pass  # no-op in headless mode

    def startBrowserAwait(self, url: str, title: str = "") -> Any:  # noqa: N802
        # Return a stub with a body() method so JS can call .body()
        class _Resp:
            def body(self):
                return ""
        return _Resp()

    def getBaseUrl(self) -> str:  # noqa: N802
        return self._base_url

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


# ---------------------------------------------------------------------------
# eval_js – main entry point
# ---------------------------------------------------------------------------

def eval_js(
    js_str: str,
    result: Any = None,
    bindings: Optional[Dict[str, Any]] = None,
    java_obj: Optional[JsExtensions] = None,
) -> Any:
    """
    Execute a JavaScript snippet and return the result.
    Mirrors AnalyzeRule.evalJS() / AnalyzeUrl.evalJS().

    Bindings injected into scope:
      java, result, baseUrl, book, source, page, key, cookie, cache, chapter,
      title, src, nextChapterUrl, rssArticle
    """
    if not js_str or not js_str.strip():
        return result

    source = bindings.get("source") if bindings else None
    if source and hasattr(source, "jsLib") and source.jsLib:
        js_str = f"{source.jsLib}\n\n{js_str}"

    ctx: Dict[str, Any] = {
        "result": result,
        "baseUrl": "",
        "book": None,
        "source": None,
        "page": 1,
        "key": "",
        "speakText": None,
        "speakSpeed": None,
        "chapter": None,
        "title": None,
        "src": None,
        "nextChapterUrl": None,
        "rssArticle": None,
        "java": java_obj or JsExtensions(),
    }
    if bindings:
        ctx.update(bindings)

    return _run_js(js_str, ctx)


def _run_js(js_str: str, ctx: Dict[str, Any]) -> Any:
    if _JS_ENGINE == "js2py":
        return _run_js2py(js_str, ctx)
    if _JS_ENGINE == "execjs":
        return _run_execjs(js_str, ctx)
    # No JS engine – return result unchanged
    return ctx.get("result")


def _run_js2py(js_str: str, ctx: Dict[str, Any]) -> Any:
    try:
        js_ctx = js2py.EvalJs(ctx)
        # Wrap so final expression value is returned
        wrapped = f"(function(){{ {js_str} }})()"
        return js_ctx.eval(wrapped)
    except Exception as e:
        import traceback
        # traceback.print_exc()  # Debugging only
        try:
            return js2py.eval_js(js_str)
        except Exception as e2:
            print(f"JS Engine Error: {e} | Fallback Error: {e2}")
            return None


_EXECJS_WRAPPER = r"""
function run(ctx) {
    var child_process = require('child_process');
    var crypto = require('crypto');

    // ------------------------------------------------------------------
    // Polyfills
    // ------------------------------------------------------------------

    var fs = require('fs');
    var logFile = '/tmp/js_engine.log';
    
    function logToFile(msg) {
        try {
            fs.appendFileSync(logFile, msg + '\n');
        } catch (e) {}
    }

    var java = {
        ajax: function(url) {
            try {
                logToFile("JAVA.AJAX CALL: " + url.substring(0, 200));
                var actualUrl = url;
                var options = {};
                
                // Parse options if present (url,options format)
                // We scan from right to left for ",{" to find the split point
                var splitIdx = -1;
                for (var i = url.length - 2; i >= 0; i--) {
                    if (url.substring(i, i+2) === ',{') {
                         try {
                             var jsonStr = url.substring(i + 1);
                             options = JSON.parse(jsonStr);
                             splitIdx = i;
                             break;
                         } catch(e) {}
                    }
                }
                
                if (splitIdx !== -1) {
                    actualUrl = url.substring(0, splitIdx);
                }

                // Construct curl command
                // Use -s (silent), -L (follow redirects), --compressed
                // Add cookie jar support
                var cookieJar = '/tmp/legado_cookies.txt';
                var cmd = 'curl -s -L --compressed --connect-timeout 10 --max-time 30 -c ' + cookieJar + ' -b ' + cookieJar;
                
                if (options.method) {
                    cmd += ' -X ' + options.method;
                }
                
                if (options.headers) {
                    for (var key in options.headers) {
                        var val = options.headers[key];
                        // Escape double quotes in value
                        val = String(val).replace(/"/g, '\\"');
                        cmd += ' -H "' + key + ': ' + val + '"';
                    }
                }
                
                if (options.body) {
                    var bodyStr = options.body;
                    if (typeof bodyStr !== 'string') {
                        bodyStr = JSON.stringify(bodyStr);
                    }
                    // Escape single quotes for shell single-quoted string
                    // ' -> '\''
                    bodyStr = bodyStr.replace(/'/g, "'\\''"); 
                    cmd += " -d '" + bodyStr + "'";
                }
                
                // Escape double quotes in URL
                actualUrl = actualUrl.replace(/"/g, '\\"');
                cmd += ' "' + actualUrl + '"';
                
                logToFile("CURL CMD: " + cmd);
                var res = child_process.execSync(cmd).toString();
                // logToFile("CURL RES: " + res.substring(0, 500));
                return res;
            } catch (e) {
                logToFile("AJAX ERROR: " + e);
                return null;
            }
        },
        put: function(k, v) {
            var val = v == null ? "" : String(v);
            ctx._updates[k] = val;
            ctx._vars[k] = val;
            return val;
        },
        get: function(k) {
            var val = ctx._vars[k];
            return val == null ? "" : String(val);
        },
        log: function(msg) {
            logToFile("JS LOG: " + msg);
            ctx._events.logs.push(String(msg));
        },
        
        // Crypto / Encoding
        base64Encode: function(str) { return Buffer.from(str).toString('base64'); },
        base64Decode: function(str) { return Buffer.from(str, 'base64').toString('utf8'); },
        hexDecodeToString: function(str) { 
            try {
                if (!str) return "";
                // If starts with { or [ it's likely JSON, not hex
                if (str.trim().startsWith('{') || str.trim().startsWith('[')) return str;
                
                var buf = Buffer.from(str, 'hex');
                if (buf.length > 0) return buf.toString('utf8');
                return str;
            } catch(e) { return str; }
        },
        md5: function(str) { return crypto.createHash('md5').update(str).digest('hex'); },
        sha1: function(str) { return crypto.createHash('sha1').update(str).digest('hex'); },
        sha256: function(str) { return crypto.createHash('sha256').update(str).digest('hex'); },
        
        // Utils
        strToJson: function(str) { try { return JSON.parse(str); } catch(e) { return null; } },
        jsonToStr: function(obj) { return JSON.stringify(obj); },
        htmlEscape: function(str) { 
             return str.replace(/&/g, '&amp;')
                       .replace(/</g, '&lt;')
                       .replace(/>/g, '&gt;')
                       .replace(/"/g, '&quot;')
                       .replace(/'/g, '&#039;');
        },
        htmlUnescape: function(str) {
             return str.replace(/&amp;/g, '&')
                       .replace(/&lt;/g, '<')
                       .replace(/&gt;/g, '>')
                       .replace(/&quot;/g, '"')
                       .replace(/&#039;/g, "'");
        },

        // Legado specific
        longToast: function(msg) {
            logToFile("TOAST: " + msg);
            ctx._events.toasts.push(String(msg));
        },
        toast: function(msg) {
            logToFile("TOAST: " + msg);
            ctx._events.toasts.push(String(msg));
        },
        startBrowserAwait: function(url, title) {
            ctx._events.browserUrl = String(url || "");
            ctx._events.browserTitle = String(title || "");
            return { body: function() { return ""; } };
        },
        startBrowser: function(url, title) {
            ctx._events.browserUrl = String(url || "");
            ctx._events.browserTitle = String(title || "");
        },
        deviceID: function() { return "0000000000000000"; },
        androidId: function() { return "0000000000000000"; },
        getCookie: function(url) { return ""; },
        timeFormat: function(timeMs) {
            try {
                var value = Number(timeMs);
                if (value > 10000000000) value = value / 1000;
                var d = new Date(value * 1000);
                var pad = function(n) { return String(n).padStart(2, '0'); };
                return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' +
                    pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
            } catch (e) { return ""; }
        },
        timeFormatUTC: function(timeMs, format, sh) {
            try {
                var value = Number(timeMs);
                if (value > 10000000000) value = value / 1000;
                var d = new Date((value + Number(sh || 0) * 3600) * 1000);
                var pad = function(n) { return String(n).padStart(2, '0'); };
                return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) + ' ' +
                    pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds());
            } catch (e) { return ""; }
        },
        getWebViewUA: function() {
            return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36";
        },
        startBrowserDp: function(url, title) {
            ctx._events.browserUrl = String(url || "");
            ctx._events.browserTitle = String(title || "");
        },
        showReadingBrowser: function(url, title) {
            ctx._events.browserUrl = String(url || "");
            ctx._events.browserTitle = String(title || "");
        },
        qread: function() { return false; }
    };
    
    // Global Helper: getArguments
    var getArguments = function(jsonStr, key) {
        try {
            if (!jsonStr) return "";
            var obj = JSON.parse(jsonStr);
            return obj[key] || "";
        } catch(e) { return ""; }
    };

    var cookie = {
        getCookie: function(url) {
            try {
                var cookiesMap = {};
                var domain = new URL(url).hostname;
                
                // 1. From Python ctx._cookies
                for (var d in ctx._cookies) {
                    if (domain.endsWith(d)) {
                         var parts = ctx._cookies[d].split(';');
                         for (var i = 0; i < parts.length; i++) {
                             var p = parts[i].trim().split('=');
                             if (p.length >= 2) cookiesMap[p[0]] = p.slice(1).join('=');
                         }
                    }
                }
                
                // 2. From file
                try {
                    var content = fs.readFileSync('/tmp/legado_cookies.txt', 'utf8');
                    var lines = content.split('\n');
                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i].trim();
                        if (!line || line.startsWith('#')) continue;
                        var parts = line.split('\t');
                        if (parts.length >= 7) {
                            var d = parts[0];
                            // domain match logic
                            if (d === domain || domain.endsWith(d) || (d.startsWith('.') && domain.endsWith(d.substring(1)))) {
                                 cookiesMap[parts[5]] = parts[6];
                            }
                        }
                    }
                } catch(e) {}
                
                var res = [];
                for (var k in cookiesMap) {
                    res.push(k + '=' + cookiesMap[k]);
                }
                return res.join('; ');
            } catch (e) { return ""; }
        },
        removeCookie: function(url) {
             try {
                var content = "";
                try { content = fs.readFileSync('/tmp/legado_cookies.txt', 'utf8'); } catch(e) {}
                var domain = new URL(url).hostname;
                var lines = content.split('\n');
                var newLines = [];
                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line || line.startsWith('#')) {
                        newLines.push(lines[i]);
                        continue;
                    }
                    var parts = line.split('\t');
                    if (parts.length >= 7) {
                        var d = parts[0];
                        if (d === domain || d === '.'+domain || domain.endsWith(d)) {
                            continue;
                        }
                    }
                    newLines.push(lines[i]);
                }
                fs.writeFileSync('/tmp/legado_cookies.txt', newLines.join('\n'));
            } catch(e) {}
        },
        setCookie: function(url, c) {
            try {
                 var domain = new URL(url).hostname;
                 var parts = c.split(';');
                 var kv = parts[0].trim().split('=');
                 var name = kv[0];
                 var value = kv.slice(1).join('=');
                 var now = Math.floor(Date.now() / 1000);
                 var exp = now + 31536000; 
                 var line = `${domain}\tTRUE\t/\tFALSE\t${exp}\t${name}\t${value}`;
                 fs.appendFileSync('/tmp/legado_cookies.txt', line + '\n');
            } catch(e) {}
        },
        getKey: function(url, key) {
            try {
                var cookieStr = cookie.getCookie(url);
                if (!cookieStr) return null;
                var parts = cookieStr.split(';');
                for (var i = 0; i < parts.length; i++) {
                    var p = parts[i].trim();
                    var idx = p.indexOf('=');
                    if (idx !== -1 && p.substring(0, idx).trim() === key) {
                        return p.substring(idx + 1).trim();
                    }
                }
            } catch(e) {}
            return null;
        }
    };

    var source = {
        getVariable: function() { return ctx._source_vars && ctx._source_vars.custom_variable_blob ? ctx._source_vars.custom_variable_blob : ""; },
        setVariable: function(v) { ctx._updates['source_var'] = v; },
        loginVariable: function() { return ""; },
        getLoginInfo: function() { return ctx._source_vars && ctx._source_vars._login_info ? ctx._source_vars._login_info : "{}"; },
        getLoginInfoMap: function() {
            var info = ctx._source_vars && ctx._source_vars._login_info ? ctx._source_vars._login_info : "{}";
            try { return JSON.parse(info); } catch(e) { return {}; }
        },
        putLoginInfo: function(info) { ctx._updates['login_info'] = info; },
        getKey: function() { return ctx.source_data ? (ctx.source_data.bookSourceUrl || "") : ""; },
        put: function(k, v) {
            var key = String(k);
            var val = v == null ? "" : String(v);
            ctx._source_updates[key] = val;
            ctx._source_cache[key] = val;
            return val;
        },
        get: function(k) {
            var val = ctx._source_cache[String(k)];
            return val == null ? "" : String(val);
        }
    };
    if (ctx.source_data) {
        Object.assign(source, ctx.source_data);
        // Restore methods overwritten by Object.assign
        source.getVariable = function() { return ctx._source_vars && ctx._source_vars.custom_variable_blob ? ctx._source_vars.custom_variable_blob : ""; };
        source.setVariable = function(v) { ctx._updates['source_var'] = v; };
        source.getLoginInfo = function() { return ctx._source_vars && ctx._source_vars._login_info ? ctx._source_vars._login_info : "{}"; };
        source.getLoginInfoMap = function() {
            var info = ctx._source_vars && ctx._source_vars._login_info ? ctx._source_vars._login_info : "{}";
            try { return JSON.parse(info); } catch(e) { return {}; }
        };
        source.putLoginInfo = function(info) { ctx._updates['login_info'] = info; };
        source.getKey = function() { return ctx.source_data ? (ctx.source_data.bookSourceUrl || "") : ""; };
        source.loginVariable = function() { return ""; };
        source.put = function(k, v) {
            var key = String(k);
            var val = v == null ? "" : String(v);
            ctx._source_updates[key] = val;
            ctx._source_cache[key] = val;
            return val;
        };
        source.get = function(k) {
            var val = ctx._source_cache[String(k)];
            return val == null ? "" : String(val);
        };
    }

    // ------------------------------------------------------------------
    // Context Injection
    // ------------------------------------------------------------------
    
    var baseUrl = ctx.baseUrl;
    var result = ctx.result;
    var book = ctx.book;
    if (book) {
        logToFile("Injecting book methods for: " + (book.name || "unnamed"));
        book.getVariable = function(key) {
             try {
                 if (!this.variable) return null;
                 var obj = JSON.parse(this.variable);
                 return obj[key];
             } catch(e) { return null; }
        };
        book.setUseReplaceRule = function(val) {
             // stub
             logToFile("book.setUseReplaceRule called with " + val);
        };
    } else {
        logToFile("ctx.book is null/undefined");
    }
    var page = ctx.page;
    var key = ctx.key;
    var chapter = ctx.chapter;
    var title = ctx.title;
    var nextChapterUrl = ctx.nextChapterUrl;
    var rssArticle = ctx.rssArticle;

    var root = (typeof globalThis !== 'undefined') ? globalThis : this;
    root.java = java;
    root.cookie = cookie;
    root.source = source;
    root.baseUrl = baseUrl;
    root.result = result;
    root.book = book;
    root.page = page;
    root.key = key;
    root.chapter = chapter;
    root.title = title;
    root.nextChapterUrl = nextChapterUrl;
    root.rssArticle = rssArticle;
    root.cache = {};
    root.Packages = root.Packages || {};
    // ... other bindings injected by python loop ...
    
    // Inject extra bindings from ctx.extra
    if (ctx.extra) {
        for (var k in ctx.extra) {
            if (k !== 'java' && k !== 'cookie' && k !== 'source') {
                 // Use eval to set local var? No, just assign to this scope?
                 // In strict mode (which function might be), we can't.
                 // We rely on user code accessing them via 'ctx.extra'? No.
                 // We must declare them.
                 // Handled by Python prepending var decls.
            }
        }
    }

    // ------------------------------------------------------------------
    // Execution
    // ------------------------------------------------------------------
    
    // We expect 'code' to be passed in ctx.code
    // Python handles prepending declarations.
    try {
        var r = eval(ctx.code);
        return {
            result: r,
            updates: ctx._updates,
            source_updates: ctx._source_updates,
            events: ctx._events
        };
    } catch(e) {
        throw e;
    }
}
"""

def _to_json_safe(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return obj

def _run_execjs(js_str: str, ctx: Dict[str, Any]) -> Any:
    if _JS_RUNTIME is None:
        return ctx.get("result")
    
    # Prepare context for serialization
    source_data = {}
    source_vars = {}
    src = ctx.get("source")
    if src:
        if hasattr(src, "to_dict"):
            source_data = src.to_dict()
        if hasattr(src, "_variables"):
             source_vars = src._variables
    
    _cookies = {}
    try:
        from .utils.cookie_store import cookie_store
        _cookies = cookie_store._cookies
    except Exception:
        pass

    vars_map = {}
    if src and hasattr(src, "_variables"):
        vars_map.update({str(k): "" if v is None else str(v) for k, v in src._variables.items()})
    book_obj = ctx.get("book")
    if book_obj and hasattr(book_obj, "get_variable_map"):
        vars_map.update({str(k): "" if v is None else str(v) for k, v in book_obj.get_variable_map().items()})
    chapter_obj = ctx.get("chapter")
    if chapter_obj and hasattr(chapter_obj, "get_variable_map"):
        vars_map.update({str(k): "" if v is None else str(v) for k, v in chapter_obj.get_variable_map().items()})

    # Build the run context
    run_ctx = {
        "baseUrl": ctx.get("baseUrl"),
        "result": ctx.get("result"),
        "book": _to_json_safe(ctx.get("book")),
        "chapter": _to_json_safe(ctx.get("chapter")),
        "title": ctx.get("title"),
        "nextChapterUrl": ctx.get("nextChapterUrl"),
        "rssArticle": _to_json_safe(ctx.get("rssArticle")),
        "page": ctx.get("page"),
        "key": ctx.get("key"),
        "source_data": source_data,
        "_source_vars": source_vars,
        "_source_cache": dict(vars_map),
        "_cookies": _cookies,
        "_vars": dict(vars_map),
        "_updates": {},
        "_source_updates": {},
        "_events": {
            "logs": [],
            "toasts": [],
            "browserUrl": "",
            "browserTitle": "",
        },
        "extra": {},
        "code": "" # Will be populated
    }
    
    import json
    # Filter other bindings
    for k, v in ctx.items():
        if k not in run_ctx and k not in ("java", "cookie", "source"):
             try:
                 json.dumps(v)
                 run_ctx["extra"][k] = v
             except:
                 pass

    # Prepare user code with var declarations.
    # js_str already contains jsLib (prepended in eval_js), so don't add it again.
    # Skip injecting var declarations for variables already declared with let/const in
    # the user code — re-declaring them with var causes SyntaxError in strict contexts.
    import re as _re
    _let_const_decls = set(_re.findall(r'\b(?:let|const)\s+(\w+)\b', js_str))
    var_decls = [
        f"var {k} = ctx.extra.{k};"
        for k in run_ctx["extra"]
        if k not in _let_const_decls
    ]

    run_ctx["code"] = "\n".join(var_decls) + "\n" + js_str

    try:
        # Compile the wrapper
        compiled = _JS_RUNTIME.compile(_EXECJS_WRAPPER)
        # Call run
        raw_res = compiled.call("run", run_ctx)
        
        # Sync cookies back to store
        try:
             from .utils.cookie_store import cookie_store
             cookie_store.load_from_file('/tmp/legado_cookies.txt')
        except Exception:
             pass

        if isinstance(raw_res, dict) and "updates" in raw_res:
            updates = raw_res["updates"] or {}
            source_updates = raw_res.get("source_updates") or {}
            events = raw_res.get("events") or {}
            src = ctx.get("source")
            if src:
                if "source_var" in updates:
                    src.setVariable(updates["source_var"])
                if "login_info" in updates:
                    src.putLoginInfo(updates["login_info"])
                for k, v in source_updates.items():
                    src.put(k, v)
            java = ctx.get("java")
            if java:
                for k, v in updates.items():
                    if k not in ("source_var", "login_info"):
                        java.put(k, v)
                if hasattr(java, "logs") and isinstance(events.get("logs"), list):
                    java.logs.extend(str(item) for item in events.get("logs") or [])
                if hasattr(java, "toasts") and isinstance(events.get("toasts"), list):
                    java.toasts.extend(str(item) for item in events.get("toasts") or [])
                if hasattr(java, "browser_url") and events.get("browserUrl"):
                    java.browser_url = str(events.get("browserUrl") or "")
                if hasattr(java, "browser_title") and events.get("browserTitle") is not None:
                    java.browser_title = str(events.get("browserTitle") or "")
            return raw_res.get("result")
        return raw_res
    except Exception as e:
        print(f"ExecJS Error: {e}")
        return None
