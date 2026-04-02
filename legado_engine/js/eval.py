"""eval_js entry point and JS runtime selection."""
from __future__ import annotations
import threading
from typing import Any, Dict, Optional

from ..engine import resolve_engine
from ..exceptions import UnsupportedHeadlessOperation

# ---------------------------------------------------------------------------
# Select JS runtime
# ---------------------------------------------------------------------------
# These are defined before importing execjs_runner to resolve the circular
# dependency: execjs_runner imports _JS_RUNTIME/_EXECJS_CONTEXT from here,
# and they must be defined by the time that import is resolved.

_JS_RUNTIME = None
_JS_ENGINE = "none"
_EXECJS_CONTEXT = threading.local()

# Try execjs (Node.js) first for better ES6+ support
try:
    import execjs  # type: ignore[import]
    _JS_RUNTIME = execjs.get()
    _JS_ENGINE = "execjs"
except Exception:
    # Try PyJS (pure-Python ES2015+ interpreter)
    try:
        import pyjs  # type: ignore[import]
        _JS_ENGINE = "pyjs"
    except ImportError:
        # Fallback to js2py (ES5 only)
        try:
            import js2py  # type: ignore[import]
            _JS_ENGINE = "js2py"
        except ImportError:
            pass

# Import after runtime state is initialised so execjs_runner can safely read
# _JS_RUNTIME/_EXECJS_CONTEXT from the partially-loaded module.
from .extensions import JsExtensions  # noqa: E402
from .execjs_runner import _run_execjs  # noqa: E402
from .pyjs_runner import _run_pyjs  # noqa: E402

# Cache for jsLib+script concatenation, keyed by (source identity, script)
_jslib_cache: dict[tuple[int, str], str] = {}


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
    engine = (
        (bindings.get("engine") if bindings else None)
        or getattr(java_obj, "engine", None)
    )
    engine = resolve_engine(engine)
    if source and hasattr(source, "jsLib") and source.jsLib:
        cache_key = (id(source), js_str)
        cached = _jslib_cache.get(cache_key)
        if cached is None:
            cached = f"{source.jsLib}\n\n{js_str}"
            _jslib_cache[cache_key] = cached
        js_str = cached

    ctx: Dict[str, Any] = {
        "result": result,
        "baseUrl": "",
        "url": "",
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
        "cache": engine.cache,
        "engine": engine,
        "java": java_obj or JsExtensions(engine=engine),
    }
    if bindings:
        ctx.update(bindings)

    return _run_js(js_str, ctx)


def _run_js(js_str: str, ctx: Dict[str, Any]) -> Any:
    if _JS_ENGINE == "js2py":
        return _run_js2py(js_str, ctx)
    if _JS_ENGINE == "pyjs":
        return _run_pyjs(js_str, ctx)
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
        if isinstance(e, UnsupportedHeadlessOperation):
            raise
        try:
            return js2py.eval_js(js_str)
        except Exception as e2:
            if isinstance(e2, UnsupportedHeadlessOperation):
                raise
            if "Unsupported headless operation:" in str(e) or "Unsupported headless operation:" in str(e2):
                detail = str(e2 if "Unsupported headless operation:" in str(e2) else e)
                operation = detail.split("Unsupported headless operation:", 1)[1].strip()
                raise UnsupportedHeadlessOperation(operation)
            print(f"JS Engine Error: {e} | Fallback Error: {e2}")
            return None
