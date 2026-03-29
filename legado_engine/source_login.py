"""
Helpers for Legado source-defined structured UI schemas.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .engine import resolve_engine
from .js_engine import JsExtensions, eval_js
from .models.book_source import BookSource


@dataclass
class UiRow:
    name: str = ""
    type: str = "text"
    action: Optional[str] = None
    style: Optional[Dict[str, Any]] = None


@dataclass
class SourceUiActionResult:
    raw_result: Any = None
    message: str = ""
    open_url: Optional[str] = None
    open_title: str = ""
    html_content: Optional[str] = None
    toasts: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)

    def detail_text(self) -> str:
        chunks: List[str] = []
        if self.message:
            chunks.append(self.message)
        if self.open_url:
            chunks.append(f"Open URL: {self.open_url}")
        if self.toasts:
            chunks.append("Messages:\n" + "\n".join(self.toasts))
        if self.logs:
            chunks.append("Logs:\n" + "\n".join(self.logs))
        if self.raw_result not in (None, "", self.message):
            if isinstance(self.raw_result, (dict, list)):
                chunks.append("Result:\n" + json.dumps(self.raw_result, ensure_ascii=False, indent=2))
            else:
                chunks.append(f"Result:\n{self.raw_result}")
        return "\n\n".join(part for part in chunks if part).strip()


LoginRow = UiRow


class _SourceUiJsExtensions(JsExtensions):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.logs: List[str] = []
        self.toasts: List[str] = []
        self.browser_url: Optional[str] = None
        self.browser_title: str = ""
        self._allow_browser_capture = True

    def log(self, msg: str) -> None:
        self.logs.append(str(msg))

    def longToast(self, msg: str) -> None:  # noqa: N802
        self.toasts.append(str(msg))

    def toast(self, msg: str) -> None:
        self.toasts.append(str(msg))

    def startBrowser(self, url: str, title: str = "") -> None:  # noqa: N802
        self.browser_url = str(url)
        self.browser_title = str(title or "")

    def startBrowserAwait(self, url: str, title: str = "") -> Any:  # noqa: N802
        self.browser_url = str(url)
        self.browser_title = str(title or "")
        return super().startBrowserAwait(url, title)


def parse_ui_rows(ui_text: str) -> List[UiRow]:
    if not ui_text:
        return []
    raw: Any = None
    try:
        raw = json.loads(ui_text)
    except Exception:
        fixed = re.sub(r",\s*([}\]])", r"\1", ui_text)
        try:
            raw = json.loads(fixed)
        except Exception:
            try:
                raw = eval_js(f"({ui_text})", java_obj=JsExtensions())
            except Exception:
                return []
    if not isinstance(raw, list):
        return []
    rows: List[UiRow] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rows.append(UiRow(
            name=str(item.get("name") or ""),
            type=str(item.get("type") or "text"),
            action=item.get("action"),
            style=item.get("style") if isinstance(item.get("style"), dict) else None,
        ))
    return rows


def parse_source_ui(book_source: BookSource) -> List[UiRow]:
    return parse_ui_rows(book_source.loginUi or "")


def parse_login_ui(book_source: BookSource) -> List[LoginRow]:
    return parse_source_ui(book_source)


def get_login_form_data(book_source: BookSource) -> Dict[str, str]:
    info = book_source.getLoginInfoMap()
    return {str(k): "" if v is None else str(v) for k, v in info.items()}


def get_source_form_data(book_source: BookSource) -> Dict[str, str]:
    return get_login_form_data(book_source)


def _looks_like_html(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.lstrip().lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html") or (
        stripped.startswith("<") and "</" in stripped
    )


def _result_message(raw_result: Any, default: str) -> str:
    if raw_result is None:
        return default
    if isinstance(raw_result, str):
        text = raw_result.strip()
        return text or default
    if isinstance(raw_result, (dict, list)):
        return default
    return str(raw_result)


def _finalize_action_result(
    raw_result: Any,
    java: _SourceUiJsExtensions,
    default_message: str,
) -> SourceUiActionResult:
    open_url = java.browser_url
    html_content: Optional[str] = None
    if isinstance(raw_result, str):
        candidate = raw_result.strip()
        if candidate.startswith(("http://", "https://", "data:")) and not open_url:
            open_url = candidate
        elif _looks_like_html(candidate):
            html_content = candidate
    return SourceUiActionResult(
        raw_result=raw_result,
        message=_result_message(raw_result, default_message),
        open_url=open_url,
        open_title=java.browser_title,
        html_content=html_content,
        toasts=list(java.toasts),
        logs=list(java.logs),
    )


def submit_login_detailed(
    book_source: BookSource,
    form_data: Dict[str, str],
    engine=None,
) -> SourceUiActionResult:
    if not book_source.loginUrl:
        raise ValueError("当前书源未定义 loginUrl。")
    book_source.putLoginInfo(json.dumps(form_data, ensure_ascii=False))
    login_js = f"{book_source.loginUrl}\nlogin(true);"
    engine = resolve_engine(engine)
    java = _SourceUiJsExtensions(engine=engine)
    raw_result = eval_js(
        login_js,
        result=form_data,
        bindings={"source": book_source, "engine": engine},
        java_obj=java,
    )
    return _finalize_action_result(raw_result, java, "认证已提交。")


def submit_login(book_source: BookSource, form_data: Dict[str, str], engine=None) -> None:
    submit_login_detailed(book_source, form_data, engine=engine)


def submit_source_form(book_source: BookSource, form_data: Dict[str, str], engine=None) -> None:
    submit_login(book_source, form_data, engine=engine)


def submit_source_form_detailed(
    book_source: BookSource,
    form_data: Dict[str, str],
    engine=None,
) -> SourceUiActionResult:
    return submit_login_detailed(book_source, form_data, engine=engine)


def run_login_button_action(
    book_source: BookSource,
    action: str,
    form_data: Dict[str, str],
    engine=None,
) -> Optional[str]:
    result = execute_login_button_action(book_source, action, form_data, engine=engine)
    if result.open_url:
        return "opened_url"
    return result.raw_result


def execute_login_button_action(
    book_source: BookSource,
    action: str,
    form_data: Dict[str, str],
    engine=None,
) -> SourceUiActionResult:
    if not action:
        return SourceUiActionResult(message="未定义动作。")
    if action.startswith(("http://", "https://", "data:")):
        return SourceUiActionResult(
            raw_result=action,
            message="准备打开链接。",
            open_url=action,
        )
    if not book_source.loginUrl:
        raise ValueError("当前书源未定义 loginUrl。")

    login_js = f"{book_source.loginUrl}\n{action}"
    engine = resolve_engine(engine)
    java = _SourceUiJsExtensions(engine=engine)
    raw_result = eval_js(
        login_js,
        result=form_data,
        bindings={"source": book_source, "engine": engine},
        java_obj=java,
    )
    return _finalize_action_result(raw_result, java, "操作完成。")


def run_source_ui_action(
    book_source: BookSource,
    action: str,
    form_data: Dict[str, str],
    engine=None,
) -> Optional[str]:
    return run_login_button_action(book_source, action, form_data, engine=engine)


def execute_source_ui_action(
    book_source: BookSource,
    action: str,
    form_data: Dict[str, str],
    engine=None,
) -> SourceUiActionResult:
    return execute_login_button_action(book_source, action, form_data, engine=engine)
