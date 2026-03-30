"""JS engine subpackage – executes JavaScript snippets in a sandboxed environment."""
from .eval import eval_js
from .extensions import JsExtensions

__all__ = ["eval_js", "JsExtensions"]
