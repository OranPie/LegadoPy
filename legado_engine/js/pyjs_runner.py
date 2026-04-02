"""PyJS (pure-Python) backend for JavaScript evaluation."""
from __future__ import annotations

import base64
import re
from typing import Any, Dict, Optional

from ..engine import resolve_engine
from ..exceptions import UnsupportedHeadlessOperation

# ---------------------------------------------------------------------------
# Lazy import of pyjs — only loaded when this backend is actually selected.
# ---------------------------------------------------------------------------
_pyjs = None


def _ensure_pyjs():
    global _pyjs
    if _pyjs is None:
        import pyjs as _p
        _pyjs = _p
    return _pyjs


# ---------------------------------------------------------------------------
# Convert between Python objects and PyJS JsValue
# ---------------------------------------------------------------------------

def _py_to_jsval(value: Any) -> Any:
    """Convert a Python value to a PyJS JsValue."""
    pyjs = _ensure_pyjs()
    JsValue = pyjs.JsValue
    UNDEFINED = pyjs.UNDEFINED

    if value is None:
        return UNDEFINED
    if isinstance(value, JsValue):
        return value
    if isinstance(value, bool):
        return pyjs.JS_TRUE if value else pyjs.JS_FALSE
    if isinstance(value, (int, float)):
        return JsValue("number", float(value))
    if isinstance(value, str):
        return JsValue("string", value)
    if isinstance(value, (bytes, bytearray)):
        # Expose as an array of numbers (same as Node's Buffer behavior)
        items = [JsValue("number", float(b)) for b in value]
        return JsValue("array", items)
    if isinstance(value, list):
        return JsValue("array", [_py_to_jsval(item) for item in value])
    if isinstance(value, dict):
        obj = {}
        for k, v in value.items():
            obj[str(k)] = _py_to_jsval(v)
        return JsValue("object", obj)
    # Handle dataclasses (JsURL, etc.)
    import dataclasses
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        obj = {}
        for k, v in dataclasses.asdict(value).items():
            obj[str(k)] = _py_to_jsval(v)
        return JsValue("object", obj)
    # Handle objects with to_dict
    if hasattr(value, "to_dict"):
        return _py_to_jsval(value.to_dict())
    # Fallback: stringify
    return JsValue("string", str(value))


def _jsval_to_py(value: Any) -> Any:
    """Convert a PyJS JsValue back to a plain Python value."""
    pyjs = _ensure_pyjs()
    JsValue = pyjs.JsValue
    UNDEFINED = pyjs.UNDEFINED

    if value is None or value is UNDEFINED:
        return None
    if not isinstance(value, JsValue):
        return value
    t = value.type
    if t == "string":
        return value.value
    if t == "number":
        v = value.value
        if isinstance(v, float) and v == int(v) and abs(v) < 2**53:
            return int(v)
        return v
    if t == "boolean":
        return value.value
    if t in ("null", "undefined"):
        return None
    if t == "array":
        return [_jsval_to_py(item) for item in (value.value or [])]
    if t == "object":
        d = value.value
        if isinstance(d, dict):
            return {k: _jsval_to_py(v) for k, v in d.items()}
        return d
    return value


# ---------------------------------------------------------------------------
# Bridge: expose a Python object's methods as a PyJS JsValue "object"
# with intrinsic callable methods.
# ---------------------------------------------------------------------------

def _wrap_py_method(py_callable, method_name: str) -> Any:
    """Wrap a Python callable as a PyJS intrinsic function."""
    pyjs = _ensure_pyjs()
    JsValue = pyjs.JsValue

    def _bridge(this_val, args, interp):
        py_args = [_jsval_to_py(a) for a in args]
        try:
            result = py_callable(*py_args)
        except UnsupportedHeadlessOperation:
            raise
        except Exception as exc:
            # Re-raise as JS error
            raise
        return _py_to_jsval(result)

    return JsValue("intrinsic", {"fn": _bridge, "name": method_name})


def _make_response_jsval(resp_obj: Any) -> Any:
    """Convert a LegadoPy StrResponse/CompatResponse to a PyJS JsValue object."""
    pyjs = _ensure_pyjs()
    JsValue = pyjs.JsValue
    UNDEFINED = pyjs.UNDEFINED

    if resp_obj is None:
        return UNDEFINED

    # Extract fields from various response types
    body_text = ""
    status_code = 0
    headers_map = {}
    message_text = ""
    url_str = ""
    request_url = ""

    # Handle StrResponse (from AnalyzeUrl.get_str_response)
    if hasattr(resp_obj, "body") and isinstance(getattr(resp_obj, "body", None), str):
        body_text = resp_obj.body or ""
        status_code = getattr(resp_obj, "status_code", 200)
        headers_map = getattr(resp_obj, "headers", {}) or {}
        url_str = getattr(resp_obj, "url", "")
        request_url = url_str
    # Handle _CompatResponse (from JsExtensions._request_compat)
    elif hasattr(resp_obj, "body") and callable(resp_obj.body):
        body_obj = resp_obj.body()
        if hasattr(body_obj, "string") and callable(body_obj.string):
            body_text = str(body_obj.string())
        else:
            body_text = str(body_obj)
        if hasattr(resp_obj, "code"):
            code_fn = resp_obj.code
            status_code = int(code_fn() if callable(code_fn) else code_fn)
        if hasattr(resp_obj, "headers"):
            headers_fn = resp_obj.headers
            h = headers_fn() if callable(headers_fn) else headers_fn
            if hasattr(h, "to_dict"):
                headers_map = h.to_dict()
            elif isinstance(h, dict):
                headers_map = h
        if hasattr(resp_obj, "message"):
            msg_fn = resp_obj.message
            message_text = str(msg_fn() if callable(msg_fn) else msg_fn)
        url_str = getattr(resp_obj, "_url", "")
        request_url = getattr(resp_obj, "_request_url", url_str)
    # Handle dict-serialized responses
    elif isinstance(resp_obj, dict):
        body_text = resp_obj.get("bodyText", resp_obj.get("body", ""))
        status_code = resp_obj.get("statusCode", resp_obj.get("status_code", 0))
        headers_map = resp_obj.get("headersMap", resp_obj.get("headers", {}))
        url_str = resp_obj.get("url", "")
        request_url = resp_obj.get("requestUrl", url_str)
    else:
        body_text = str(resp_obj)
        url_str = ""
        request_url = ""

    def body_bridge(this, args, interp):
        body_val = JsValue("string", body_text)
        return JsValue("object", {
            "string": JsValue("intrinsic", {
                "fn": lambda t, a, i: JsValue("string", body_text),
                "name": "string",
            }),
            "toString": JsValue("intrinsic", {
                "fn": lambda t, a, i: JsValue("string", body_text),
                "name": "toString",
            }),
            "valueOf": JsValue("intrinsic", {
                "fn": lambda t, a, i: JsValue("string", body_text),
                "name": "valueOf",
            }),
        })

    def code_bridge(this, args, interp):
        return JsValue("number", float(status_code))

    def header_bridge(this, args, interp):
        name = _jsval_to_py(args[0]) if args else ""
        lookup = str(name or "").lower()
        for k, v in headers_map.items():
            if k.lower() == lookup:
                return JsValue("string", str(v))
        return pyjs.UNDEFINED

    def headers_bridge(this, args, interp):
        headers_obj = {}
        for k, v in headers_map.items():
            headers_obj[str(k)] = JsValue("string", str(v))
        headers_obj["get"] = JsValue("intrinsic", {
            "fn": header_bridge,
            "name": "get",
        })
        return JsValue("object", headers_obj)

    def message_bridge(this, args, interp):
        return JsValue("string", message_text)

    def raw_bridge(this, args, interp):
        def request_bridge(t, a, i):
            def url_bridge(t2, a2, i2):
                return JsValue("string", request_url)
            return JsValue("object", {
                "url": JsValue("intrinsic", {"fn": url_bridge, "name": "url"}),
            })
        return JsValue("object", {
            "request": JsValue("intrinsic", {"fn": request_bridge, "name": "request"}),
        })

    def tostring_bridge(this, args, interp):
        return JsValue("string", body_text)

    return JsValue("object", {
        "body": JsValue("intrinsic", {"fn": body_bridge, "name": "body"}),
        "code": JsValue("intrinsic", {"fn": code_bridge, "name": "code"}),
        "header": JsValue("intrinsic", {"fn": header_bridge, "name": "header"}),
        "headers": JsValue("intrinsic", {"fn": headers_bridge, "name": "headers"}),
        "message": JsValue("intrinsic", {"fn": message_bridge, "name": "message"}),
        "raw": JsValue("intrinsic", {"fn": raw_bridge, "name": "raw"}),
        "toString": JsValue("intrinsic", {"fn": tostring_bridge, "name": "toString"}),
    })


def _build_java_bridge(java_obj: Any) -> Any:
    """
    Build a PyJS JsValue 'object' that mirrors the `java` bridge.
    Each method on JsExtensions becomes an intrinsic callable.
    """
    pyjs = _ensure_pyjs()
    JsValue = pyjs.JsValue
    UNDEFINED = pyjs.UNDEFINED

    if java_obj is None:
        return UNDEFINED

    # Methods that return response objects need special wrapping
    _RESPONSE_METHODS = {"connect", "get", "head", "post"}
    # Methods that may raise UnsupportedHeadlessOperation
    _UNSUPPORTED_METHODS = {
        "startBrowser", "startBrowserAwait", "webView",
        "webViewGetSource", "webViewGetOverrideUrl",
        "getVerificationCode", "startBrowserDp", "showReadingBrowser",
    }

    obj_dict: Dict[str, Any] = {}

    # Enumerate all public methods on the JsExtensions object
    for name in dir(java_obj):
        if name.startswith("_"):
            continue
        attr = getattr(java_obj, name, None)
        if not callable(attr):
            # Expose as property
            obj_dict[name] = _py_to_jsval(attr)
            continue

        method_name = name

        if method_name in _UNSUPPORTED_METHODS:
            def _make_unsupported(mn):
                def _fn(this, args, interp):
                    detail = _jsval_to_py(args[0]) if args else ""
                    raise UnsupportedHeadlessOperation(mn, str(detail or ""))
                return JsValue("intrinsic", {"fn": _fn, "name": mn})
            obj_dict[method_name] = _make_unsupported(method_name)
            continue

        if method_name in _RESPONSE_METHODS:
            def _make_response_method(bound_method, mn):
                def _fn(this, args, interp):
                    py_args = [_jsval_to_py(a) for a in args]
                    try:
                        result = bound_method(*py_args)
                    except UnsupportedHeadlessOperation:
                        raise
                    except Exception:
                        return UNDEFINED
                    return _make_response_jsval(result)
                return JsValue("intrinsic", {"fn": _fn, "name": mn})
            obj_dict[method_name] = _make_response_method(attr, method_name)
            continue

        # Regular method
        def _make_method(bound_method, mn):
            def _fn(this, args, interp):
                py_args = [_jsval_to_py(a) for a in args]
                try:
                    result = bound_method(*py_args)
                except UnsupportedHeadlessOperation:
                    raise
                except Exception:
                    return UNDEFINED
                return _py_to_jsval(result)
            return JsValue("intrinsic", {"fn": _fn, "name": mn})
        obj_dict[method_name] = _make_method(attr, method_name)

    # Add AnalyzeRule bridge methods if available
    analyze_rule = getattr(java_obj, "_analyze_rule", None)
    if analyze_rule is not None:
        def _make_get_string(ar):
            def _fn(this, args, interp):
                rule = _jsval_to_py(args[0]) if len(args) > 0 else None
                m_content = _jsval_to_py(args[1]) if len(args) > 1 else None
                is_url = bool(_jsval_to_py(args[2])) if len(args) > 2 else False
                return _py_to_jsval(ar.get_string(rule, m_content, is_url))
            return JsValue("intrinsic", {"fn": _fn, "name": "getString"})

        def _make_get_string_list(ar):
            def _fn(this, args, interp):
                rule = _jsval_to_py(args[0]) if len(args) > 0 else None
                m_content = _jsval_to_py(args[1]) if len(args) > 1 else None
                is_url = bool(_jsval_to_py(args[2])) if len(args) > 2 else False
                result = ar.get_string_list(rule, m_content, is_url)
                return _py_to_jsval(result or [])
            return JsValue("intrinsic", {"fn": _fn, "name": "getStringList"})

        def _make_get_element(ar):
            def _fn(this, args, interp):
                rule = _jsval_to_py(args[0]) if args else ""
                result = ar.get_element(str(rule))
                if result is None:
                    return UNDEFINED
                # get_element may return a list; take first item (matches execjs bridge)
                if isinstance(result, list):
                    result = result[0] if result else None
                if result is None:
                    return UNDEFINED
                return _py_to_jsval(str(result))
            return JsValue("intrinsic", {"fn": _fn, "name": "getElement"})

        def _make_get_elements(ar):
            def _fn(this, args, interp):
                rule = _jsval_to_py(args[0]) if args else ""
                result = ar.get_elements(str(rule))
                return _py_to_jsval([str(el) for el in (result or [])])
            return JsValue("intrinsic", {"fn": _fn, "name": "getElements"})

        def _make_set_content(ar):
            def _fn(this, args, interp):
                content = _jsval_to_py(args[0]) if len(args) > 0 else ""
                base_url = _jsval_to_py(args[1]) if len(args) > 1 else None
                ar.set_content(content, base_url)
                return UNDEFINED
            return JsValue("intrinsic", {"fn": _fn, "name": "setContent"})

        obj_dict["getString"] = _make_get_string(analyze_rule)
        obj_dict["getStringList"] = _make_get_string_list(analyze_rule)
        obj_dict["getElement"] = _make_get_element(analyze_rule)
        obj_dict["getElements"] = _make_get_elements(analyze_rule)
        obj_dict["setContent"] = _make_set_content(analyze_rule)

    return JsValue("object", obj_dict)


def _build_source_jsval(source_obj: Any) -> Any:
    """Convert a BookSource Python object to a PyJS JsValue object."""
    pyjs = _ensure_pyjs()
    JsValue = pyjs.JsValue
    UNDEFINED = pyjs.UNDEFINED

    if source_obj is None:
        return UNDEFINED

    obj = {}

    # Expose key string attributes
    for attr in (
        "bookSourceUrl", "bookSourceName", "bookSourceType",
        "bookSourceGroup", "bookSourceComment", "loginUrl",
        "header", "jsLib",
    ):
        val = getattr(source_obj, attr, None)
        obj[attr] = JsValue("string", str(val)) if val is not None else UNDEFINED

    # Expose variable methods
    if hasattr(source_obj, "getVariable"):
        def _get_var(this, args, interp):
            return JsValue("string", str(source_obj.getVariable() or ""))
        obj["getVariable"] = JsValue("intrinsic", {"fn": _get_var, "name": "getVariable"})

    if hasattr(source_obj, "setVariable"):
        def _set_var(this, args, interp):
            val = _jsval_to_py(args[0]) if args else ""
            source_obj.setVariable(str(val or ""))
            return UNDEFINED
        obj["setVariable"] = JsValue("intrinsic", {"fn": _set_var, "name": "setVariable"})

    if hasattr(source_obj, "put"):
        def _put(this, args, interp):
            k = _jsval_to_py(args[0]) if len(args) > 0 else ""
            v = _jsval_to_py(args[1]) if len(args) > 1 else ""
            source_obj.put(str(k), str(v or ""))
            return UNDEFINED
        obj["put"] = JsValue("intrinsic", {"fn": _put, "name": "put"})

    if hasattr(source_obj, "get"):
        def _get(this, args, interp):
            k = _jsval_to_py(args[0]) if args else ""
            return JsValue("string", str(source_obj.get(str(k)) or ""))
        obj["get"] = JsValue("intrinsic", {"fn": _get, "name": "get"})

    if hasattr(source_obj, "getLoginInfo"):
        def _get_login(this, args, interp):
            return _py_to_jsval(source_obj.getLoginInfo())
        obj["getLoginInfo"] = JsValue("intrinsic", {"fn": _get_login, "name": "getLoginInfo"})

    if hasattr(source_obj, "putLoginInfo"):
        def _put_login(this, args, interp):
            val = _jsval_to_py(args[0]) if args else ""
            source_obj.putLoginInfo(str(val or ""))
            return UNDEFINED
        obj["putLoginInfo"] = JsValue("intrinsic", {"fn": _put_login, "name": "putLoginInfo"})

    if hasattr(source_obj, "getLoginHeader"):
        def _get_login_header(this, args, interp):
            return _py_to_jsval(source_obj.getLoginHeader())
        obj["getLoginHeader"] = JsValue("intrinsic", {"fn": _get_login_header, "name": "getLoginHeader"})

    if hasattr(source_obj, "putLoginHeader"):
        def _put_login_header(this, args, interp):
            val = _jsval_to_py(args[0]) if args else ""
            source_obj.putLoginHeader(str(val or ""))
            return UNDEFINED
        obj["putLoginHeader"] = JsValue("intrinsic", {"fn": _put_login_header, "name": "putLoginHeader"})

    return JsValue("object", obj)


def _build_cookie_jsval(cookie_obj: Any) -> Any:
    """Convert a JsCookie Python object to a PyJS JsValue object."""
    pyjs = _ensure_pyjs()
    JsValue = pyjs.JsValue
    UNDEFINED = pyjs.UNDEFINED

    if cookie_obj is None:
        return UNDEFINED

    obj = {}
    for method_name in ("getCookie", "setCookie", "replaceCookie", "removeCookie"):
        attr = getattr(cookie_obj, method_name, None)
        if attr and callable(attr):
            obj[method_name] = _wrap_py_method(attr, method_name)

    return JsValue("object", obj)


def _build_book_jsval(book_obj: Any) -> Any:
    """Convert a Book/SearchBook Python object to a PyJS JsValue object."""
    pyjs = _ensure_pyjs()
    JsValue = pyjs.JsValue
    UNDEFINED = pyjs.UNDEFINED

    if book_obj is None:
        return UNDEFINED

    # Start with serialized data
    obj = {}
    if hasattr(book_obj, "to_dict"):
        for k, v in book_obj.to_dict().items():
            obj[str(k)] = _py_to_jsval(v)
    else:
        import dataclasses
        if dataclasses.is_dataclass(book_obj):
            for k, v in dataclasses.asdict(book_obj).items():
                obj[str(k)] = _py_to_jsval(v)

    # Expose RuleData variable methods if present
    for method_name in ("getVariable", "setVariable", "put", "get",
                        "get_variable_map"):
        attr = getattr(book_obj, method_name, None)
        if attr and callable(attr):
            obj[method_name] = _wrap_py_method(attr, method_name)

    # Expose Book-specific methods
    if hasattr(book_obj, "set_use_replace_rule"):
        def _set_replace(this, args, interp):
            val = _jsval_to_py(args[0]) if args else False
            book_obj.set_use_replace_rule(bool(val))
            return UNDEFINED
        obj["setUseReplaceRule"] = JsValue("intrinsic", {
            "fn": _set_replace, "name": "setUseReplaceRule",
        })

    if hasattr(book_obj, "get_use_replace_rule"):
        def _get_replace(this, args, interp):
            return pyjs.JS_TRUE if book_obj.get_use_replace_rule() else pyjs.JS_FALSE
        obj["getUseReplaceRule"] = JsValue("intrinsic", {
            "fn": _get_replace, "name": "getUseReplaceRule",
        })

    return JsValue("object", obj)


def _build_chapter_jsval(chapter_obj: Any) -> Any:
    """Convert a BookChapter Python object to a PyJS JsValue."""
    return _build_book_jsval(chapter_obj)


def _build_cache_jsval(cache_obj: Any) -> Any:
    """Expose the engine cache as a JS object with get/put/remove/clear."""
    pyjs = _ensure_pyjs()
    JsValue = pyjs.JsValue
    UNDEFINED = pyjs.UNDEFINED

    if cache_obj is None:
        return UNDEFINED

    def _get(this, args, interp):
        key = _jsval_to_py(args[0]) if args else ""
        default = _jsval_to_py(args[1]) if len(args) > 1 else ""
        return _py_to_jsval(cache_obj.get(str(key), default))

    def _put(this, args, interp):
        key = _jsval_to_py(args[0]) if len(args) > 0 else ""
        val = _jsval_to_py(args[1]) if len(args) > 1 else ""
        cache_obj.put(str(key), val)
        return UNDEFINED

    def _remove(this, args, interp):
        key = _jsval_to_py(args[0]) if args else ""
        cache_obj.remove(str(key))
        return UNDEFINED

    def _clear(this, args, interp):
        cache_obj.clear()
        return UNDEFINED

    return JsValue("object", {
        "get": JsValue("intrinsic", {"fn": _get, "name": "get"}),
        "put": JsValue("intrinsic", {"fn": _put, "name": "put"}),
        "remove": JsValue("intrinsic", {"fn": _remove, "name": "remove"}),
        "clear": JsValue("intrinsic", {"fn": _clear, "name": "clear"}),
    })


# ---------------------------------------------------------------------------
# Crypto polyfill — mirrors the legacy Crypto object from execjs_runner.
# ---------------------------------------------------------------------------

def _build_crypto_global() -> Any:
    """Build a Crypto global with HMAC, MD5, SHA1, SHA256, and util helpers."""
    import hashlib
    import hmac as _hmac

    pyjs = _ensure_pyjs()
    JsValue = pyjs.JsValue
    UNDEFINED = pyjs.UNDEFINED

    def _to_bytes(val: Any) -> bytes:
        if isinstance(val, bytes):
            return val
        if isinstance(val, list):
            return bytes(int(b) & 0xFF for b in val)
        return str(val or "").encode("utf-8")

    def _digest_fn(algo_name: str):
        def _fn(this, args, interp):
            message = _jsval_to_py(args[0]) if args else ""
            opts = _jsval_to_py(args[1]) if len(args) > 1 else {}
            msg_bytes = _to_bytes(message)
            h = hashlib.new(algo_name, msg_bytes)
            as_bytes = isinstance(opts, dict) and opts.get("asBytes")
            if as_bytes:
                return _py_to_jsval(list(h.digest()))
            return JsValue("string", h.hexdigest())
        return JsValue("intrinsic", {"fn": _fn, "name": algo_name.upper()})

    def _hmac_fn(this, args, interp):
        # Crypto.HMAC(hashFn, message, key, opts)
        # hashFn is a JsValue function (Crypto.SHA1 etc.), but we get the algo from it
        hash_fn = args[0] if len(args) > 0 else None
        message = _jsval_to_py(args[1]) if len(args) > 1 else ""
        key = _jsval_to_py(args[2]) if len(args) > 2 else ""
        opts = _jsval_to_py(args[3]) if len(args) > 3 else {}

        # Determine algorithm from the hash function name
        algo = "sha1"
        if hash_fn and hasattr(hash_fn, "value") and isinstance(hash_fn.value, dict):
            fn_name = (hash_fn.value.get("name") or "").upper()
            if "SHA256" in fn_name:
                algo = "sha256"
            elif "SHA1" in fn_name:
                algo = "sha1"
            elif "MD5" in fn_name:
                algo = "md5"

        key_bytes = _to_bytes(key)
        msg_bytes = _to_bytes(message)
        mac = _hmac.new(key_bytes, msg_bytes, algo)

        as_bytes = isinstance(opts, dict) and opts.get("asBytes")
        if as_bytes:
            return _py_to_jsval(list(mac.digest()))
        return JsValue("string", mac.hexdigest())

    # util helpers
    def _bytes_to_hex(this, args, interp):
        data = _jsval_to_py(args[0]) if args else []
        return JsValue("string", _to_bytes(data).hex())

    def _hex_to_bytes(this, args, interp):
        hex_str = _jsval_to_py(args[0]) if args else ""
        return _py_to_jsval(list(bytes.fromhex(str(hex_str or ""))))

    def _bytes_to_base64(this, args, interp):
        data = _jsval_to_py(args[0]) if args else []
        return JsValue("string", base64.b64encode(_to_bytes(data)).decode())

    def _base64_to_bytes(this, args, interp):
        text = _jsval_to_py(args[0]) if args else ""
        return _py_to_jsval(list(base64.b64decode(str(text or ""))))

    def _random_bytes(this, args, interp):
        import os
        n = int(_jsval_to_py(args[0]) or 0) if args else 0
        return _py_to_jsval(list(os.urandom(max(0, n))))

    util_obj = JsValue("object", {
        "bytesToHex": JsValue("intrinsic", {"fn": _bytes_to_hex, "name": "bytesToHex"}),
        "hexToBytes": JsValue("intrinsic", {"fn": _hex_to_bytes, "name": "hexToBytes"}),
        "bytesToBase64": JsValue("intrinsic", {"fn": _bytes_to_base64, "name": "bytesToBase64"}),
        "base64ToBytes": JsValue("intrinsic", {"fn": _base64_to_bytes, "name": "base64ToBytes"}),
        "randomBytes": JsValue("intrinsic", {"fn": _random_bytes, "name": "randomBytes"}),
    })

    return JsValue("object", {
        "MD5": _digest_fn("md5"),
        "SHA1": _digest_fn("sha1"),
        "SHA256": _digest_fn("sha256"),
        "HMAC": JsValue("intrinsic", {"fn": _hmac_fn, "name": "HMAC"}),
        "util": util_obj,
    })


# ---------------------------------------------------------------------------
# Main entry point: _run_pyjs
# ---------------------------------------------------------------------------

def _run_pyjs(js_str: str, ctx: Dict[str, Any]) -> Any:
    """
    Execute JavaScript using the PyJS pure-Python interpreter.

    This is a drop-in replacement for _run_execjs() and _run_js2py().
    """
    pyjs = _ensure_pyjs()
    JsValue = pyjs.JsValue
    UNDEFINED = pyjs.UNDEFINED
    Interpreter = pyjs.Interpreter

    interp = Interpreter()

    # ---- Inject standard Legado bindings into the global scope ----
    java_obj = ctx.get("java")
    source_obj = ctx.get("source")
    cookie_obj = ctx.get("cookie")
    engine = resolve_engine(ctx.get("engine"))

    # java bridge
    interp.genv.declare("java", _build_java_bridge(java_obj), "var")

    # source
    interp.genv.declare("source", _build_source_jsval(source_obj), "var")

    # cookie — ensure a working cookie object is always available
    cookie_obj = ctx.get("cookie")
    if cookie_obj is None:
        from ..analyze.analyze_url import JsCookie
        cookie_obj = JsCookie(engine.cookie_store)
    interp.genv.declare("cookie", _build_cookie_jsval(cookie_obj), "var")

    # cache
    interp.genv.declare("cache", _build_cache_jsval(ctx.get("cache")), "var")

    # Scalar bindings
    for name in ("result", "baseUrl", "url", "key", "title",
                 "nextChapterUrl", "src", "speakText", "speakSpeed"):
        val = ctx.get(name)
        interp.genv.declare(name, _py_to_jsval(val), "var")

    # Numeric bindings
    page = ctx.get("page", 1)
    interp.genv.declare("page", JsValue("number", float(page or 1)), "var")

    # Complex object bindings
    interp.genv.declare("book", _build_book_jsval(ctx.get("book")), "var")
    interp.genv.declare("chapter", _build_chapter_jsval(ctx.get("chapter")), "var")
    interp.genv.declare("rssArticle", _build_book_jsval(ctx.get("rssArticle")), "var")

    # Crypto polyfill (legacy CryptoJS-compatible interface)
    interp.genv.declare("Crypto", _build_crypto_global(), "var")
    interp.genv.declare("LegacyCrypto", _build_crypto_global(), "var")

    # Any extra bindings
    _let_const_decls = set(re.findall(r'\b(?:let|const)\s+(\w+)\b', js_str))
    for k, v in ctx.items():
        if k in ("java", "cookie", "source", "cache", "engine",
                 "result", "baseUrl", "url", "key", "title",
                 "nextChapterUrl", "src", "speakText", "speakSpeed",
                 "page", "book", "chapter", "rssArticle"):
            continue
        if k in _let_const_decls:
            continue
        try:
            interp.genv.declare(k, _py_to_jsval(v), "var")
        except Exception:
            pass

    # ---- Execute ----
    try:
        interp.run(js_str)
    except UnsupportedHeadlessOperation:
        raise
    except Exception as exc:
        detail = str(exc)
        if "Unsupported headless operation:" in detail:
            operation = detail.split("Unsupported headless operation:", 1)[1].strip()
            raise UnsupportedHeadlessOperation(operation)
        raise

    # ---- Extract result ----
    # PyJS's _last_value captures the last ExpressionStatement value
    result = interp._last_value

    # Sync logs / toasts from java bridge back to the Java object
    if java_obj is not None:
        # Logs and toasts are accumulated on the Python java_obj directly
        # since our bridge calls java_obj methods which mutate it in-place.
        pass

    return _jsval_to_py(result)
