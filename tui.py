#!/usr/bin/env python3
"""
legado-tui – Comprehensive Terminal UI reader for the Legado Python engine.

Launch:
    python3 tui.py [source.json]

Navigation:
    q / Ctrl+C    Quit
    Escape        Go back / close modal
    Enter         Select / open
    r             Reload / refresh
    /             Focus search / filter
    Tab           Cycle focus

Bookshelf:
    s  Search       e  Discover     l  Load source
    a  Auth/UI      t  Settings     Delete  Remove book

Reader:
    n / p         Next / previous chapter
    /             Find in chapter
    Ctrl+Home/End Scroll to top / bottom
    t             Reader settings / theme
    j             Jump to chapter
"""
from __future__ import annotations

import json
import sys
import textwrap
import warnings
import base64
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests
from rich.text import Text

warnings.filterwarnings("ignore", category=UserWarning, module='requests')

sys.path.insert(0, str(Path(__file__).resolve().parent))

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import (
    Container, Horizontal, Vertical,
    ScrollableContainer, VerticalScroll,
)
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label,
    ListItem, ListView, LoadingIndicator, Markdown,
    ProgressBar, Rule, Static, Switch,
)
from textual.reactive import reactive

import legado_engine as le
from legado_engine import (
    BookSource, Book, BookChapter,
    ExploreKind, search_book, get_book_info, get_chapter_list, get_content,
    explore_book, get_explore_kinds,
    SourceUiActionResult, parse_source_ui, get_source_form_data,
    submit_source_form_detailed, execute_source_ui_action,
)
from legado_engine.analyze.analyze_url import AnalyzeUrl
from reader_state import ReaderState


# ─── Reader Themes ───────────────────────────────────────────────────────────
# Each theme defines colors for the reader view.  The CSS class `.reader-theme-<key>`
# is applied to the reader scroll container; the APP_CSS block generates the
# rules automatically.

READER_THEMES: Dict[str, Dict[str, str]] = {
    "day": {
        "label": "日间",
        "icon": "☀",
        "bg": "#f5f5f0",
        "fg": "#2e2e2e",
        "title": "#1a6b50",
        "accent": "#4a90d9",
        "dim": "#888888",
        "border": "#d0d0c8",
    },
    "night": {
        "label": "夜间",
        "icon": "🌙",
        "bg": "#1e1e2e",
        "fg": "#cdd6f4",
        "title": "#89b4fa",
        "accent": "#f38ba8",
        "dim": "#6c7086",
        "border": "#313244",
    },
    "ink": {
        "label": "墨水",
        "icon": "🖋",
        "bg": "#e8e8e8",
        "fg": "#1a1a1a",
        "title": "#333333",
        "accent": "#555555",
        "dim": "#777777",
        "border": "#bbbbbb",
    },
    "eyecare": {
        "label": "护眼",
        "icon": "🌿",
        "bg": "#c7edcc",
        "fg": "#2d4a32",
        "title": "#1b5e20",
        "accent": "#388e3c",
        "dim": "#5a7a5e",
        "border": "#98c49e",
    },
    "parchment": {
        "label": "羊皮纸",
        "icon": "📜",
        "bg": "#f4e8c1",
        "fg": "#5b4636",
        "title": "#8b4513",
        "accent": "#a0522d",
        "dim": "#8b7d6b",
        "border": "#d4c4a0",
    },
}

# ─── Reader layout presets ───────────────────────────────────────────────────

READER_STYLE_PRESETS: Dict[str, Dict[str, int]] = {
    "compact":     {"width": 66, "gap": 1, "padding": 2},
    "comfortable": {"width": 82, "gap": 2, "padding": 4},
    "immersive":   {"width": 98, "gap": 3, "padding": 6},
}

READER_STYLE_LABELS: Dict[str, str] = {
    "compact":     "紧凑",
    "comfortable": "舒适",
    "immersive":   "沉浸",
}

# ─── Bookshelf sort modes ────────────────────────────────────────────────────

SHELF_SORT_MODES: List[Tuple[str, str]] = [
    ("updated",  "最近阅读"),
    ("name",     "书名"),
    ("author",   "作者"),
    ("progress", "进度"),
    ("added",    "添加时间"),
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def zh_bool(value: Any) -> str:
    """Return 是/否 for boolean display."""
    return "是" if value else "否"


def format_time_short(ts: int) -> str:
    """Format unix timestamp to short date string."""
    if ts <= 0:
        return ""
    dt = datetime.fromtimestamp(ts)
    now = datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    if dt.year == now.year:
        return dt.strftime("%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d")


def format_progress(entry: Dict[str, Any]) -> str:
    """Format bookshelf entry progress for display."""
    progress = entry.get("progress") or {}
    if progress.get("chapter_index") is None:
        return "未读"
    chapter_num = int(progress.get("chapter_index", 0)) + 1
    chapter_total = progress.get("chapter_total")
    scroll_ratio = float(progress.get("scroll_ratio", 0.0) or 0.0)
    pct = f"{int(scroll_ratio * 100)}%"
    if chapter_total:
        return f"第{chapter_num}/{chapter_total}章 {pct}"
    return f"第{chapter_num}章 {pct}"


def format_progress_short(entry: Dict[str, Any]) -> str:
    """Ultra-compact progress string for tight layouts."""
    progress = entry.get("progress") or {}
    if progress.get("chapter_index") is None:
        return "—"
    idx = int(progress.get("chapter_index", 0)) + 1
    total = progress.get("chapter_total")
    if total:
        return f"{idx}/{total}"
    return f"Ch.{idx}"


def parse_book_sources(raw: str) -> List[BookSource]:
    """Parse one or more BookSource objects from a JSON string."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return [BookSource.from_dict(parsed)]
    if isinstance(parsed, list):
        sources: List[BookSource] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                source = BookSource.from_dict(item)
            except Exception:
                continue
            if source.bookSourceUrl and source.bookSourceName:
                sources.append(source)
        return sources
    try:
        return [BookSource.from_json(raw)]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# MODAL SCREENS
# ═══════════════════════════════════════════════════════════════════════════════

class SourcePickerScreen(ModalScreen):
    """Choose one source from a JSON array with search and group display."""

    BINDINGS = [
        Binding("escape", "dismiss", "取消"),
        Binding("/", "focus_filter", "筛选"),
    ]

    def __init__(self, sources: List[BookSource], title: str = "选择书源") -> None:
        super().__init__()
        self._all_sources = sources
        self._filtered_sources = list(sources)
        self._title = title

    def compose(self) -> ComposeResult:
        with Container(id="source-picker-modal"):
            yield Label(f"📚 {self._title}", id="source-picker-title")
            yield Input(placeholder="🔍 输入名称、分组或网址筛选…", id="source-picker-filter")
            yield DataTable(id="source-picker-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="source-picker-buttons"):
                yield Button("打开", variant="primary", id="btn-source-picker-open")
                yield Button("取消", variant="default", id="btn-source-picker-cancel")

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#source-picker-table", DataTable)
        table.add_columns("#", "名称", "分组", "搜索", "发现", "URL")
        self._apply_filter("")

    def action_focus_filter(self) -> None:
        self.query_one("#source-picker-filter", Input).focus()

    def _apply_filter(self, query: str) -> None:
        q = query.lower().strip()
        if not q:
            self._filtered_sources = list(self._all_sources)
        else:
            self._filtered_sources = [
                s for s in self._all_sources
                if q in f"{s.bookSourceName} {s.bookSourceGroup or ''} {s.bookSourceUrl}".lower()
            ]
        table: DataTable = self.query_one("#source-picker-table", DataTable)
        table.clear()
        for idx, source in enumerate(self._filtered_sources, 1):
            table.add_row(
                str(idx),
                source.bookSourceName or "",
                source.bookSourceGroup or "—",
                "✓" if source.searchUrl else "✗",
                "✓" if source.exploreUrl else "✗",
                source.bookSourceUrl or "",
                key=str(idx - 1),
            )

    def _selected_source(self) -> Optional[BookSource]:
        table: DataTable = self.query_one("#source-picker-table", DataTable)
        row = table.cursor_row
        if row < 0 or row >= len(self._filtered_sources):
            return None
        return self._filtered_sources[row]

    @on(Button.Pressed, "#btn-source-picker-cancel")
    def picker_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-source-picker-open")
    def picker_open(self) -> None:
        source = self._selected_source()
        if source is None:
            self.app.warn("请先选择一个书源。")
            return
        self.dismiss(source)

    @on(Input.Changed, "#source-picker-filter")
    def picker_filter_changed(self, event: Input.Changed) -> None:
        self._apply_filter(event.value)

    @on(DataTable.RowSelected, "#source-picker-table")
    def picker_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        if 0 <= idx < len(self._filtered_sources):
            self.dismiss(self._filtered_sources[idx])


class SourceLoaderScreen(ModalScreen):
    """Modal that lets the user load a BookSource from file or URL."""

    BINDINGS = [Binding("escape", "dismiss", "取消")]

    def compose(self) -> ComposeResult:
        with Container(id="source-loader"):
            yield Label("📂 加载书源", id="loader-title")
            yield Static(
                "[dim]支持本地 JSON 文件路径或远程 URL\n"
                "单个书源或书源数组均可[/dim]",
                id="loader-hint",
            )
            yield Input(
                placeholder="文件路径或 https://… URL",
                id="source-path",
            )
            with Horizontal(id="loader-btns"):
                yield Button("加载", variant="primary", id="btn-load")
                yield Button("取消", id="btn-cancel")
            yield Label("", id="loader-error")

    @on(Button.Pressed, "#btn-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-load")
    def load(self) -> None:
        self._do_load()

    @on(Input.Submitted, "#source-path")
    def submitted(self) -> None:
        self._do_load()

    def _do_load(self) -> None:
        path = self.query_one("#source-path", Input).value.strip()
        if not path:
            self.query_one("#loader-error", Label).update("[red]请输入文件路径或 URL。[/red]")
            return
        is_web = path.lower().startswith(("http://", "https://"))
        p = Path(path).expanduser()
        if not is_web and not p.exists():
            self.query_one("#loader-error", Label).update(f"[red]文件不存在：{p}[/red]")
            return

        raw = ""
        try:
            if is_web:
                resp = requests.get(path, timeout=15)
                resp.raise_for_status()
                raw = resp.text
            else:
                raw = p.read_text(encoding="utf-8")
            sources = parse_book_sources(raw)
        except Exception as exc:
            self.query_one("#loader-error", Label).update(f"[red]加载失败：{exc}[/red]")
            return
        if not sources:
            self.query_one("#loader-error", Label).update("[red]未发现有效书源数据。[/red]")
            return
        if len(sources) == 1:
            self.dismiss(sources[0])
            return
        self.app.push_screen(
            SourcePickerScreen(sources, title=f"选择书源（共 {len(sources)} 个）"),
            self._on_source_picked,
        )

    def _on_source_picked(self, source: Optional[BookSource]) -> None:
        if source is not None:
            self.dismiss(source)


class AlertDialogScreen(ModalScreen):
    """Generic alert / confirm dialog with icon support."""

    BINDINGS = [
        Binding("escape", "dismiss", "关闭"),
        Binding("enter", "confirm", "确定"),
    ]

    def __init__(
        self,
        title: str,
        message: str,
        confirm_label: str = "确定",
        cancel_label: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._confirm_label = confirm_label
        self._cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Container(id="alert-modal"):
            yield Label(self._title, id="alert-title")
            yield Rule(line_style="heavy")
            yield Static(self._message, id="alert-message")
            with Horizontal(id="alert-buttons"):
                yield Button(self._confirm_label, variant="primary", id="btn-alert-confirm")
                if self._cancel_label:
                    yield Button(self._cancel_label, id="btn-alert-cancel")

    def action_confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-alert-confirm")
    def alert_confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-alert-cancel")
    def alert_cancel(self) -> None:
        self.dismiss(False)


class TextPromptScreen(ModalScreen):
    """Small text-input modal for reader search and quick commands."""

    BINDINGS = [Binding("escape", "dismiss", "取消")]

    def __init__(self, title: str, placeholder: str = "", value: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._value = value

    def compose(self) -> ComposeResult:
        with Container(id="prompt-modal"):
            yield Label(self._title, id="prompt-title")
            yield Input(value=self._value, placeholder=self._placeholder, id="prompt-input")
            with Horizontal(id="prompt-buttons"):
                yield Button("应用", variant="primary", id="btn-prompt-apply")
                yield Button("清空", id="btn-prompt-clear")
                yield Button("取消", id="btn-prompt-cancel")

    @on(Button.Pressed, "#btn-prompt-cancel")
    def prompt_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-prompt-clear")
    def prompt_clear(self) -> None:
        self.dismiss("")

    @on(Button.Pressed, "#btn-prompt-apply")
    def prompt_apply(self) -> None:
        self.dismiss(self.query_one("#prompt-input", Input).value.strip())

    @on(Input.Submitted, "#prompt-input")
    def prompt_submit(self) -> None:
        self.dismiss(self.query_one("#prompt-input", Input).value.strip())


class StructuredFormScreen(ModalScreen):
    """Unified renderer for structured source-driven forms (auth, login, etc.)."""

    BINDINGS = [Binding("escape", "dismiss", "关闭")]

    def __init__(
        self,
        title: str,
        rows: List[Any],
        initial_data: Optional[dict[str, str]] = None,
        submit_label: str = "提交",
    ) -> None:
        super().__init__()
        self._title = title
        self._rows = rows
        self._form_data = initial_data or {}
        self._submit_label = submit_label

    def on_mount(self) -> None:
        detail = self.describe_form()
        if detail:
            self._set_detail(detail)

    @staticmethod
    def _row_name(row: Any) -> str:
        return row.name if hasattr(row, "name") else str(row.get("name", ""))

    @staticmethod
    def _row_type(row: Any) -> str:
        return row.type if hasattr(row, "type") else str(row.get("type", "text"))

    @staticmethod
    def _row_action(row: Any) -> Optional[str]:
        return row.action if hasattr(row, "action") else row.get("action")

    @staticmethod
    def _row_style(row: Any) -> Dict[str, Any]:
        style = row.style if hasattr(row, "style") else row.get("style")
        return style if isinstance(style, dict) else {}

    def _button_width_class(self, row: Any) -> str:
        basis = self._row_style(row).get("layout_flexBasisPercent")
        try:
            basis_val = float(basis)
        except (TypeError, ValueError):
            basis_val = -1.0
        if 0 < basis_val <= 0.36:
            return "schema-btn-third"
        if 0 < basis_val <= 0.5:
            return "schema-btn-half"
        return "schema-btn-full"

    def _button_variant(self, row: Any) -> str:
        name = self._row_name(row).lower()
        action = (self._row_action(row) or "").lower()
        if "login" in action or "登录" in name:
            return "primary"
        if "logout" in action or "退出" in name or "清除" in name:
            return "error"
        if "register" in action or "注册" in name or action.startswith(("http://", "https://")):
            return "success"
        return "default"

    def toolbar_buttons(self) -> List[tuple[str, str, str]]:
        return []

    def describe_form(self) -> str:
        return ""

    def handle_toolbar_action(self, action_id: str) -> Any:
        raise NotImplementedError

    def create_preview_screen(self, outcome: SourceUiActionResult) -> Optional[Screen]:
        if not (outcome.open_url or outcome.html_content):
            return None
        return WebPreviewScreen(
            title=outcome.open_title or "书源页面",
            url=outcome.open_url,
            html_content=outcome.html_content,
        )

    def compose(self) -> ComposeResult:
        with Container(id="schema-modal"):
            yield Label(self._title, id="schema-title")
            toolbar = self.toolbar_buttons()
            if toolbar:
                with Horizontal(id="schema-tools"):
                    for action_id, label, variant in toolbar:
                        yield Button(
                            label,
                            id=f"schema-tool-{action_id}",
                            variant=variant,
                            classes="schema-tool-btn",
                        )
            with VerticalScroll(id="schema-scroll"):
                with Vertical(id="schema-form"):
                    button_buffer: List[tuple[int, Any]] = []

                    def flush_buttons() -> ComposeResult:
                        nonlocal button_buffer
                        while button_buffer:
                            first_idx, first_row = button_buffer[0]
                            width_class = self._button_width_class(first_row)
                            if width_class == "schema-btn-third":
                                take = 3
                            elif width_class == "schema-btn-half":
                                take = 2
                            else:
                                take = 1
                            row_items = button_buffer[:take]
                            button_buffer = button_buffer[take:]
                            with Horizontal(classes="schema-button-row"):
                                for idx2, row2 in row_items:
                                    yield Button(
                                        self._row_name(row2) or "操作",
                                        id=f"schema-action-{idx2}",
                                        variant=self._button_variant(row2),
                                        classes=f"schema-action-btn {self._button_width_class(row2)}",
                                    )

                    for idx, row in enumerate(self._rows):
                        row_type = self._row_type(row)
                        row_name = self._row_name(row)
                        if row_type in ("text", "password"):
                            yield from flush_buttons()
                            yield Label(row_name, classes="schema-field-label")
                            yield Input(
                                value=self._form_data.get(row_name, ""),
                                placeholder=f"请输入 {row_name}",
                                id=f"schema-field-{idx}",
                                password=(row_type == "password"),
                                classes="schema-field-input",
                            )
                        elif row_type == "button":
                            button_buffer.append((idx, row))
                    yield from flush_buttons()
            with Horizontal(id="schema-buttons"):
                yield Button(self._submit_label, variant="primary", id="btn-schema-submit")
                yield Button("关闭", id="btn-schema-close")
            yield Label("", id="schema-status")
            yield Static("", id="schema-detail")

    def collect_form_data(self) -> dict[str, str]:
        data = dict(self._form_data)
        for idx, row in enumerate(self._rows):
            row_type = self._row_type(row)
            row_name = self._row_name(row)
            if row_type in ("text", "password"):
                data[row_name] = self.query_one(f"#schema-field-{idx}", Input).value
        self._form_data = data
        return data

    def submit_form(self, form_data: dict[str, str]) -> str:
        raise NotImplementedError

    def run_row_action(self, action: str, form_data: dict[str, str]) -> str:
        raise NotImplementedError

    @on(Button.Pressed, "#btn-schema-close")
    def schema_close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-schema-submit")
    def schema_submit(self) -> None:
        self._run_submit()

    @work(thread=True)
    def _run_submit(self) -> None:
        try:
            outcome = self.submit_form(self.collect_form_data())
            self.app.call_from_thread(self._apply_action_result, outcome)
        except Exception as e:
            self.app.call_from_thread(self._set_status, f"[red]{e}[/red]")
            self.app.call_from_thread(self._set_detail, "")

    @on(Button.Pressed)
    def schema_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("schema-tool-"):
            action_id = btn_id.removeprefix("schema-tool-")
            try:
                outcome = self.handle_toolbar_action(action_id)
                self._apply_action_result(outcome)
            except Exception as e:
                self._set_status(f"[red]{e}[/red]")
            return
        if not btn_id.startswith("schema-action-"):
            return
        idx = int(btn_id.rsplit("-", 1)[1])
        action = self._row_action(self._rows[idx]) or ""
        self._run_action(action)

    @work(thread=True)
    def _run_action(self, action: str) -> None:
        try:
            outcome = self.run_row_action(action, self.collect_form_data())
            self.app.call_from_thread(self._apply_action_result, outcome)
        except Exception as e:
            self.app.call_from_thread(self._set_status, f"[red]{e}[/red]")
            self.app.call_from_thread(self._set_detail, "")

    def _set_status(self, text: str) -> None:
        self.query_one("#schema-status", Label).update(text)

    def _set_detail(self, text: str) -> None:
        self.query_one("#schema-detail", Static).update(text)

    def _apply_action_result(self, outcome: Any) -> None:
        if isinstance(outcome, SourceUiActionResult):
            message = outcome.message or "操作完成。"
            self._set_status(f"[green]{message}[/green]")
            self._set_detail(outcome.detail_text())
            preview_screen = self.create_preview_screen(outcome)
            if preview_screen is not None:
                self.app.push_screen(preview_screen)
            return
        self._set_status(f"[green]{outcome}[/green]")
        self._set_detail("")


class SourceUiScreen(StructuredFormScreen):
    """Source-defined structured UI rendered through the unified form UI."""

    def __init__(self, source: BookSource) -> None:
        self._source = source
        rows = parse_source_ui(source)
        initial_data = get_source_form_data(source)
        if not rows and source.loginUrl:
            rows = [
                {"name": "邮箱", "type": "text"},
                {"name": "密码", "type": "password"},
                {"name": "密钥", "type": "text"},
                {"name": "自定义服务器(可不填)", "type": "text"},
            ]
        super().__init__(
            title=f"🔐 认证与功能：{source.bookSourceName}",
            rows=rows,
            initial_data=initial_data,
            submit_label="认证",
        )

    def toolbar_buttons(self) -> List[tuple[str, str, str]]:
        return [
            ("show-header", "登录请求头", "default"),
            ("clear-header", "清空请求头", "warning"),
            ("show-form", "当前表单", "default"),
        ]

    def describe_form(self) -> str:
        info = [
            f"书源：{self._source.bookSourceName}",
            f"源地址：{self._source.bookSourceUrl}",
            f"认证脚本：{zh_bool(self._source.loginUrl)}",
            f"已存请求头：{zh_bool(self._source.getLoginHeader())}",
            f"已存字段数：{len(self._source.getLoginInfoMap())}",
        ]
        return "\n".join(info)

    def handle_toolbar_action(self, action_id: str) -> Any:
        if action_id == "show-header":
            header = self._source.getLoginHeader().strip()
            return SourceUiActionResult(
                message="已读取登录请求头。",
                raw_result=header or "当前没有保存登录请求头。",
            )
        if action_id == "clear-header":
            self.app.confirm(
                "清空登录请求头",
                "确认清空当前书源保存的登录请求头吗？",
                self._on_clear_header_confirmed,
            )
            return SourceUiActionResult(
                message="请确认是否清空登录请求头。",
                raw_result=self.describe_form(),
            )
        if action_id == "show-form":
            data = self.collect_form_data()
            return SourceUiActionResult(
                message="当前表单内容。",
                raw_result=data,
            )
        return SourceUiActionResult(message=f"未知操作：{action_id}")

    def _on_clear_header_confirmed(self, confirmed: Optional[bool]) -> None:
        if not confirmed:
            return
        self._source.removeLoginHeader()
        self.app.set_source(self._source, persist=True, notify=False)
        self._apply_action_result(
            SourceUiActionResult(
                message="已清空登录请求头。",
                raw_result=self.describe_form(),
            )
        )

    def create_preview_screen(self, outcome: SourceUiActionResult) -> Optional[Screen]:
        if not (outcome.open_url or outcome.html_content):
            return None
        return WebPreviewScreen(
            title=outcome.open_title or self._source.bookSourceName,
            url=outcome.open_url,
            html_content=outcome.html_content,
            source=self._source,
        )

    def submit_form(self, form_data: dict[str, str]) -> SourceUiActionResult:
        outcome = submit_source_form_detailed(self._source, form_data)
        self.app.set_source(self._source, persist=True, notify=False)
        return outcome

    def run_row_action(self, action: str, form_data: dict[str, str]) -> SourceUiActionResult:
        outcome = execute_source_ui_action(self._source, action, form_data)
        self.app.set_source(self._source, persist=True, notify=False)
        return outcome


class WebPreviewScreen(Screen):
    """Source-aware in-app page preview with text/raw/info view modes."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "返回"),
        Binding("r", "reload", "刷新"),
        Binding("o", "open_external", "浏览器"),
        Binding("v", "cycle_view", "切换视图"),
        Binding("t", "show_text", "正文"),
        Binding("h", "show_raw", "源码"),
        Binding("i", "show_info", "信息"),
    ]

    def __init__(
        self,
        title: str,
        url: Optional[str] = None,
        html_content: Optional[str] = None,
        source: Optional[BookSource] = None,
    ) -> None:
        super().__init__()
        self._title = title or "页面预览"
        self._url = url
        self._html_content = html_content
        self._source = source
        self._view_mode = "text"
        self._render_text = ""
        self._raw_content = ""
        self._resolved_url = url or ""
        self._request_method = "GET"
        self._request_headers: Dict[str, str] = {}
        self._request_body = ""
        self._response_status = 0
        self._response_headers: Dict[str, str] = {}
        self._page_title = title or ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            with Horizontal(id="web-preview-top"):
                yield Label("", id="web-preview-meta")
            with Horizontal(id="web-preview-actions"):
                yield Button("正文", id="btn-web-preview-text", variant="primary")
                yield Button("源码", id="btn-web-preview-raw")
                yield Button("信息", id="btn-web-preview-info")
                yield Button("外部浏览器", id="btn-web-preview-open")
            yield LoadingIndicator(id="web-preview-loading")
            yield ScrollableContainer(Static("", id="web-preview-content"), id="web-preview-scroll")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self._title
        self._update_header()
        self.query_one("#web-preview-loading").display = True
        self._load_preview()

    def _update_header(self) -> None:
        parts = []
        if self._source:
            parts.append(f"[cyan]{self._source.bookSourceName}[/cyan]")
        parts.append(f"[bold]{self._page_title or self._title}[/bold]")
        if self._resolved_url or self._url:
            parts.append(f"[dim]{self._resolved_url or self._url}[/dim]")
        self.query_one("#web-preview-meta", Label).update("  ".join(parts))
        open_url = self._resolved_url or self._url or ""
        self.query_one("#btn-web-preview-open", Button).disabled = not bool(
            open_url and open_url.startswith(("http://", "https://"))
        )
        self._refresh_mode_buttons()

    def _refresh_mode_buttons(self) -> None:
        self.query_one("#btn-web-preview-text", Button).variant = (
            "primary" if self._view_mode == "text" else "default"
        )
        self.query_one("#btn-web-preview-raw", Button).variant = (
            "primary" if self._view_mode == "raw" else "default"
        )
        self.query_one("#btn-web-preview-info", Button).variant = (
            "primary" if self._view_mode == "info" else "default"
        )

    def action_reload(self) -> None:
        self.query_one("#web-preview-loading").display = True
        self._load_preview()

    def action_cycle_view(self) -> None:
        order = ["text", "raw", "info"]
        idx = order.index(self._view_mode) if self._view_mode in order else 0
        self._set_view_mode(order[(idx + 1) % len(order)])

    def action_show_text(self) -> None:
        self._set_view_mode("text")

    def action_show_raw(self) -> None:
        self._set_view_mode("raw")

    def action_show_info(self) -> None:
        self._set_view_mode("info")

    def _set_view_mode(self, mode: str) -> None:
        self._view_mode = mode
        self._refresh_mode_buttons()
        self._render_active_view()

    def action_open_external(self) -> None:
        open_url = self._resolved_url or self._url or ""
        if not open_url or not open_url.startswith(("http://", "https://")):
            self.app.warn("当前预览没有可打开的外部链接。")
            return
        import webbrowser
        webbrowser.open(open_url)
        self.app.info("已使用外部浏览器打开。")

    @work(thread=True)
    def _load_preview(self) -> None:
        try:
            payload = self._load_preview_payload()
        except Exception as exc:
            payload = {
                "text": f"预览失败：{exc}",
                "raw": f"预览失败：{exc}",
                "info": f"预览失败：{exc}",
                "resolved_url": self._url or "",
                "title": self._title,
                "status": 0,
                "request_method": self._request_method,
                "request_headers": self._request_headers,
                "request_body": self._request_body,
                "response_headers": {},
            }
        self.app.call_from_thread(self._apply_preview_payload, payload)

    def _apply_preview_payload(self, payload: Dict[str, Any]) -> None:
        self._render_text = str(payload.get("text") or "")
        self._raw_content = str(payload.get("raw") or "")
        self._resolved_url = str(payload.get("resolved_url") or self._url or "")
        self._page_title = str(payload.get("title") or self._title)
        self._response_status = int(payload.get("status") or 0)
        self._request_method = str(payload.get("request_method") or "GET")
        self._request_headers = dict(payload.get("request_headers") or {})
        self._request_body = str(payload.get("request_body") or "")
        self._response_headers = dict(payload.get("response_headers") or {})
        self.query_one("#web-preview-loading").display = False
        self._update_header()
        self._render_active_view()

    def _render_active_view(self) -> None:
        if self._view_mode == "raw":
            content = self._raw_content or self._render_text or "没有源码内容。"
        elif self._view_mode == "info":
            content = self._render_info_text()
        else:
            content = self._render_text or "没有可读内容。"
        self.query_one("#web-preview-content", Static).update(content)
        self.query_one("#web-preview-scroll", ScrollableContainer).scroll_home(animate=False)

    @staticmethod
    def _extract_title(html_text: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        title = re.sub(r"\s+", " ", match.group(1)).strip()
        return title

    @classmethod
    def _html_to_text(cls, html_text: str) -> str:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_text, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            body = soup.get_text("\n", strip=True)
            return f"{title}\n\n{body}".strip()
        except Exception:
            return html_text

    @staticmethod
    def _decode_data_url(url: str) -> tuple[str, str]:
        try:
            header, payload = url.split(",", 1)
            if ";base64" in header:
                decoded = base64.b64decode(payload).decode("utf-8", errors="replace")
            else:
                from urllib.parse import unquote
                decoded = unquote(payload)
            return header, decoded
        except Exception:
            return "", url[:2000]

    @staticmethod
    def _looks_like_html(text: str) -> bool:
        stripped = text.lstrip().lower()
        return stripped.startswith("<!doctype html") or stripped.startswith("<html") or (
            stripped.startswith("<") and "</" in stripped
        )

    def _load_preview_payload(self) -> Dict[str, Any]:
        resolved_url = self._url or ""
        raw = self._html_content or ""
        response_headers: Dict[str, str] = {}
        request_headers: Dict[str, str] = {}
        request_body = ""
        request_method = "GET"
        status = 200 if self._html_content else 0

        if self._html_content:
            if not resolved_url:
                resolved_url = "inline://html"
        elif self._url:
            if self._url.startswith("data:"):
                header, decoded = self._decode_data_url(self._url)
                raw = decoded
                status = 200
                response_headers = {"content-type": header.partition(":")[2] or "text/plain"}
            elif self._source:
                analyze = AnalyzeUrl(self._url, source=self._source)
                request_method = analyze.get_method()
                request_headers = dict(analyze.header_map)
                request_body = analyze.get_body() or ""
                response = analyze.get_str_response()
                resolved_url = response.url or analyze.url
                raw = response.body or ""
                status = response.status_code
                response_headers = dict(response.headers or {})
            else:
                response = requests.get(self._url, timeout=20)
                response.raise_for_status()
                resolved_url = str(response.url)
                raw = response.text
                status = response.status_code
                response_headers = dict(response.headers)
        else:
            raw = "没有可预览的内容。"

        content_type = str(response_headers.get("content-type", ""))
        is_html = "html" in content_type.lower() or self._looks_like_html(raw)
        text = self._html_to_text(raw) if is_html else raw
        title = self._extract_title(raw) if is_html else ""
        if not title:
            title = self._title
        return {
            "text": text,
            "raw": raw,
            "resolved_url": resolved_url,
            "title": title,
            "status": status,
            "request_method": request_method,
            "request_headers": request_headers,
            "request_body": request_body,
            "response_headers": response_headers,
        }

    def _render_info_text(self) -> str:
        info = [
            f"标题：{self._page_title or self._title}",
            f"书源：{self._source.bookSourceName if self._source else '无'}",
            f"请求方式：{self._request_method}",
            f"状态码：{self._response_status or '无'}",
            f"链接：{self._resolved_url or self._url or '无'}",
        ]
        if self._request_headers:
            info.append("")
            info.append("请求头：")
            info.append(json.dumps(self._request_headers, ensure_ascii=False, indent=2))
        if self._request_body:
            info.append("")
            info.append("请求体：")
            info.append(self._request_body)
        if self._response_headers:
            info.append("")
            info.append("响应头：")
            info.append(json.dumps(self._response_headers, ensure_ascii=False, indent=2))
        return "\n".join(info).strip()

    @on(Button.Pressed, "#btn-web-preview-open")
    def web_preview_open_pressed(self) -> None:
        self.action_open_external()

    @on(Button.Pressed, "#btn-web-preview-text")
    def web_preview_text_pressed(self) -> None:
        self.action_show_text()

    @on(Button.Pressed, "#btn-web-preview-raw")
    def web_preview_raw_pressed(self) -> None:
        self.action_show_raw()

    @on(Button.Pressed, "#btn-web-preview-info")
    def web_preview_info_pressed(self) -> None:
        self.action_show_info()


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS & THEME SCREENS
# ═══════════════════════════════════════════════════════════════════════════════

class ReaderSettingsScreen(ModalScreen):
    """Comprehensive reader settings: theme, layout, preload, cache management."""

    BINDINGS = [Binding("escape", "dismiss", "关闭")]

    def __init__(self) -> None:
        super().__init__()
        self._reader_style = "comfortable"
        self._reader_theme = "night"

    def compose(self) -> ComposeResult:
        settings = self.app.reader_state.get_settings()
        self._reader_style = str(settings.get("reader_style", self._reader_style))
        self._reader_theme = str(settings.get("reader_theme", self._reader_theme))
        preload_count = int(settings.get("preload_count", 2))
        with Container(id="reader-settings-modal"):
            yield Label("⚙ 阅读设置", id="reader-settings-title")

            # ── Theme section ──
            yield Label("🎨 阅读主题", classes="settings-section")
            with Horizontal(id="reader-theme-buttons"):
                for theme_key, theme in READER_THEMES.items():
                    yield Button(
                        f"{theme['icon']} {theme['label']}",
                        id=f"reader-theme-{theme_key}",
                        variant="primary" if theme_key == self._reader_theme else "default",
                        classes="theme-btn",
                    )

            # ── Layout section ──
            yield Label("📐 排版样式", classes="settings-section")
            with Horizontal(id="reader-style-buttons"):
                for style_name in READER_STYLE_PRESETS:
                    yield Button(
                        READER_STYLE_LABELS.get(style_name, style_name),
                        id=f"reader-style-{style_name}",
                        variant="primary" if style_name == self._reader_style else "default",
                    )

            # ── Preload section ──
            yield Label("⏳ 预加载后续章节数", classes="settings-section")
            yield Input(value=str(preload_count), id="reader-preload-count")

            # ── Stats section ──
            yield Label("📊 阅读统计", classes="settings-section")
            yield Static("", id="reader-stats-info")

            # ── Actions ──
            with Horizontal(id="reader-settings-buttons"):
                yield Button("保存", variant="primary", id="btn-reader-settings-save")
                yield Button("清空缓存", variant="warning", id="btn-reader-settings-clear-cache")
                yield Button("关闭", id="btn-reader-settings-close")
            yield Label("", id="reader-settings-status")

    def on_mount(self) -> None:
        self._update_stats()

    def _update_stats(self) -> None:
        entries = self.app.reader_state.list_bookshelf()
        total_books = len(entries)
        reading = sum(1 for e in entries if (e.get("progress") or {}).get("chapter_index") is not None)
        cache_count = len(list(self.app.reader_state.cache_dir.glob("*.txt")))
        stats = (
            f"  书架藏书：{total_books} 本\n"
            f"  正在阅读：{reading} 本\n"
            f"  缓存章节：{cache_count} 个"
        )
        try:
            self.query_one("#reader-stats-info", Static).update(stats)
        except Exception:
            pass

    def _refresh_style_buttons(self) -> None:
        for style_name in READER_STYLE_PRESETS:
            button = self.query_one(f"#reader-style-{style_name}", Button)
            button.variant = "primary" if style_name == self._reader_style else "default"

    def _refresh_theme_buttons(self) -> None:
        for theme_key in READER_THEMES:
            button = self.query_one(f"#reader-theme-{theme_key}", Button)
            button.variant = "primary" if theme_key == self._reader_theme else "default"

    @on(Button.Pressed)
    def settings_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""

        if button_id.startswith("reader-theme-"):
            self._reader_theme = button_id.removeprefix("reader-theme-")
            self._refresh_theme_buttons()
            return

        if button_id.startswith("reader-style-"):
            self._reader_style = button_id.removeprefix("reader-style-")
            self._refresh_style_buttons()
            return

        if button_id == "btn-reader-settings-close":
            self.dismiss(None)
            return

        if button_id == "btn-reader-settings-clear-cache":
            self.app.confirm(
                "清空章节缓存",
                "确认清空所有章节缓存吗？此操作不会删除书架记录。",
                self._on_clear_cache_confirmed,
            )
            return

        if button_id == "btn-reader-settings-save":
            self._save_settings()

    def _save_settings(self) -> None:
        preload_raw = self.query_one("#reader-preload-count", Input).value.strip() or "0"
        try:
            preload_count = max(0, min(6, int(preload_raw)))
        except ValueError:
            self.query_one("#reader-settings-status", Label).update(
                "[red]预加载数量必须是 0–6 的数字。[/red]"
            )
            return
        self.app.reader_state.update_settings(
            reader_style=self._reader_style,
            reader_theme=self._reader_theme,
            preload_count=preload_count,
        )
        self.app.refresh_reader_views()
        self.query_one("#reader-settings-status", Label).update(
            "[green]✓ 阅读设置已保存。[/green]"
        )

    def _on_clear_cache_confirmed(self, confirmed: Optional[bool]) -> None:
        if not confirmed:
            return
        self.app.reader_state.clear_cache()
        self._update_stats()
        self.query_one("#reader-settings-status", Label).update(
            "[green]✓ 章节缓存已清空。[/green]"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BOOKSHELF SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

class BookshelfScreen(Screen):
    """Persistent bookshelf with sorting, filtering, reading stats, and continue-reading."""

    BINDINGS = [
        Binding("/", "focus_filter", "筛选"),
        Binding("s", "open_search", "搜索"),
        Binding("e", "open_discover", "发现"),
        Binding("a", "open_source_ui", "认证"),
        Binding("t", "open_reader_settings", "设置"),
        Binding("l", "load_source", "加载书源"),
        Binding("delete", "remove_selected", "移除"),
        Binding("o", "cycle_sort", "排序"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._entries: List[Dict[str, Any]] = []
        self._filtered_entries: List[Dict[str, Any]] = []
        self._sort_mode = "updated"

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            # ── Toolbar ──
            with Horizontal(id="shelf-actions"):
                yield Button("🔍 搜索", variant="primary", id="btn-shelf-search")
                yield Button("🧭 发现", id="btn-shelf-discover")
                yield Button("🔐 认证", id="btn-shelf-source-ui")
                yield Button("⚙ 设置", id="btn-shelf-settings")
                yield Button("📂 书源", id="btn-shelf-load")
                yield Button("🗑 移除", variant="error", id="btn-shelf-remove")

            # ── Source & stats bar ──
            yield Label("", id="shelf-source-label")

            # ── Filter & sort ──
            with Horizontal(id="shelf-filter-bar"):
                yield Input(placeholder="🔍 筛选书名、作者…", id="shelf-filter")
                yield Button("排序", id="btn-shelf-sort", classes="shelf-sort-btn")
                yield Label("", id="shelf-count")

            # ── Book table ──
            yield DataTable(id="shelf-table", cursor_type="row", zebra_stripes=True)

            # ── Stats footer ──
            yield Label("", id="shelf-stats")
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#shelf-table", DataTable)
        table.add_columns("#", "书名", "作者", "书源", "进度", "更新时间")
        self._update_source_label()
        self._load_entries()

    def on_show(self) -> None:
        if self.is_mounted:
            self._update_source_label()
            self._load_entries()

    def _update_source_label(self) -> None:
        src = self.app.source
        if src:
            has_search = "✓" if src.searchUrl else "✗"
            has_explore = "✓" if src.exploreUrl else "✗"
            label = (
                f"[bold]📚 书架[/bold]  "
                f"[dim]当前书源：[/dim][cyan]{src.bookSourceName}[/cyan]  "
                f"[dim]搜索{has_search} 发现{has_explore}[/dim]"
            )
        else:
            label = "[bold]📚 书架[/bold]  [dim]尚未加载书源 — 按 [bold]l[/bold] 加载[/dim]"
        self.query_one("#shelf-source-label", Label).update(label)
        self.query_one("#btn-shelf-discover", Button).disabled = not bool(src and src.exploreUrl)
        self.query_one("#btn-shelf-source-ui", Button).disabled = not bool(
            src and (src.loginUi or src.loginUrl)
        )

    def _sort_entries(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self._sort_mode == "name":
            return sorted(entries, key=lambda e: (e.get("book") or {}).get("name", ""))
        elif self._sort_mode == "author":
            return sorted(entries, key=lambda e: (e.get("book") or {}).get("author", ""))
        elif self._sort_mode == "progress":
            def progress_key(e: Dict[str, Any]) -> float:
                p = e.get("progress") or {}
                idx = p.get("chapter_index")
                total = p.get("chapter_total")
                if idx is None:
                    return -1.0
                if total and total > 0:
                    return (idx + 1) / total
                return float(idx)
            return sorted(entries, key=progress_key, reverse=True)
        elif self._sort_mode == "added":
            return sorted(entries, key=lambda e: e.get("added_at", 0), reverse=True)
        else:  # "updated" — default
            return sorted(entries, key=lambda e: e.get("updated_at", 0), reverse=True)

    def _load_entries(self) -> None:
        self._entries = self.app.reader_state.list_bookshelf()
        self._apply_filter(self.query_one("#shelf-filter", Input).value if self.is_mounted else "")

    def _apply_filter(self, query: str) -> None:
        q = query.lower().strip()
        if not q:
            filtered = list(self._entries)
        else:
            filtered = [
                entry for entry in self._entries
                if q in json.dumps(entry, ensure_ascii=False).lower()
            ]
        self._filtered_entries = self._sort_entries(filtered)
        table: DataTable = self.query_one("#shelf-table", DataTable)
        table.clear()
        for idx, entry in enumerate(self._filtered_entries, 1):
            book = entry.get("book") or {}
            source = entry.get("source") or {}
            table.add_row(
                str(idx),
                str(book.get("name") or "未命名"),
                str(book.get("author") or "—"),
                str(source.get("bookSourceName") or "—"),
                format_progress(entry),
                format_time_short(int(entry.get("updated_at", 0) or 0)),
                key=str(idx - 1),
            )

        # Update counts
        total = len(self._entries)
        shown = len(self._filtered_entries)
        reading = sum(
            1 for e in self._entries
            if (e.get("progress") or {}).get("chapter_index") is not None
        )
        count_text = f"[dim]{shown} 本[/dim]" if shown == total else f"[dim]{shown}/{total} 本[/dim]"
        self.query_one("#shelf-count", Label).update(count_text)

        sort_label = dict(SHELF_SORT_MODES).get(self._sort_mode, self._sort_mode)
        self.query_one("#btn-shelf-sort", Button).label = f"↕ {sort_label}"

        # Stats footer
        stats = f"[dim]藏书 {total} · 在读 {reading}[/dim]"
        self.query_one("#shelf-stats", Label).update(stats)

    def _selected_entry(self) -> Optional[Dict[str, Any]]:
        table: DataTable = self.query_one("#shelf-table", DataTable)
        if table.cursor_row < 0 or table.cursor_row >= len(self._filtered_entries):
            return None
        return self._filtered_entries[table.cursor_row]

    def action_focus_filter(self) -> None:
        self.query_one("#shelf-filter", Input).focus()

    def action_open_search(self) -> None:
        self.app.open_search()

    def action_open_discover(self) -> None:
        self.app.open_discover(self.app.source)

    def action_open_source_ui(self) -> None:
        self.app.open_source_ui(self.app.source)

    def action_open_reader_settings(self) -> None:
        self.app.open_reader_settings()

    def action_load_source(self) -> None:
        self.app.open_source_loader()

    def action_cycle_sort(self) -> None:
        keys = [k for k, _ in SHELF_SORT_MODES]
        current_idx = keys.index(self._sort_mode) if self._sort_mode in keys else 0
        self._sort_mode = keys[(current_idx + 1) % len(keys)]
        self._apply_filter(self.query_one("#shelf-filter", Input).value if self.is_mounted else "")
        self.app.info(f"排序：{dict(SHELF_SORT_MODES)[self._sort_mode]}")

    def action_remove_selected(self) -> None:
        entry = self._selected_entry()
        if not entry:
            self.app.warn("请先选择一本书。")
            return
        book = entry.get("book") or {}
        self.app.confirm(
            "移出书架",
            f"确认将《{book.get('name') or '未命名'}》移出书架吗？",
            lambda confirmed: self._remove_entry_confirmed(entry, confirmed),
        )

    def _remove_entry_confirmed(self, entry: Dict[str, Any], confirmed: Optional[bool]) -> None:
        if not confirmed:
            return
        self.app.reader_state.remove_book(entry["key"])
        self._load_entries()
        self.app.info("已从书架移除。")

    def _resume_entry(self, entry: Dict[str, Any]) -> None:
        source = self.app.reader_state.restore_source(entry)
        book = self.app.reader_state.restore_book(entry)
        self.app.set_source(source)
        self._update_source_label()
        self.app.push_screen(
            BookScreen(
                book=book,
                source=source,
                resume_progress=entry.get("progress") or None,
                auto_open=bool(entry.get("progress")),
            )
        )

    @on(Button.Pressed, "#btn-shelf-search")
    def shelf_search_pressed(self) -> None:
        self.action_open_search()

    @on(Button.Pressed, "#btn-shelf-discover")
    def shelf_discover_pressed(self) -> None:
        self.action_open_discover()

    @on(Button.Pressed, "#btn-shelf-source-ui")
    def shelf_source_ui_pressed(self) -> None:
        self.action_open_source_ui()

    @on(Button.Pressed, "#btn-shelf-settings")
    def shelf_settings_pressed(self) -> None:
        self.action_open_reader_settings()

    @on(Button.Pressed, "#btn-shelf-load")
    def shelf_load_pressed(self) -> None:
        self.action_load_source()

    @on(Button.Pressed, "#btn-shelf-remove")
    def shelf_remove_pressed(self) -> None:
        self.action_remove_selected()

    @on(Button.Pressed, "#btn-shelf-sort")
    def shelf_sort_pressed(self) -> None:
        self.action_cycle_sort()

    @on(Input.Changed, "#shelf-filter")
    def shelf_filter_changed(self, event: Input.Changed) -> None:
        self._apply_filter(event.value)

    @on(DataTable.RowSelected, "#shelf-table")
    def shelf_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        if 0 <= idx < len(self._filtered_entries):
            self._resume_entry(self._filtered_entries[idx])



# ═══════════════════════════════════════════════════════════════════════════════
# SEARCH & DISCOVER SCREENS
# ═══════════════════════════════════════════════════════════════════════════════

class SearchScreen(Screen):
    """Search screen with results table and quick access to other features."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "返回"),
        Binding("/",      "focus_search", "聚焦搜索"),
        Binding("r",      "refresh_results", "刷新"),
        Binding("b",      "open_bookshelf", "书架"),
        Binding("t",      "open_reader_settings", "设置"),
        Binding("a",      "open_source_ui", "认证"),
        Binding("e",      "open_discover", "发现"),
    ]

    source: reactive[Optional[BookSource]] = reactive(None)
    results: reactive[list] = reactive([])

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            with Horizontal(id="search-bar"):
                yield Button("📚", id="btn-bookshelf", classes="icon-btn")
                yield Input(placeholder="🔍 输入书名、作者或关键词…", id="search-input")
                yield Button("搜索", variant="primary", id="btn-search")
                yield Button("🔐", id="btn-source-ui", classes="icon-btn")
                yield Button("🧭", id="btn-discover", classes="icon-btn")
                yield Button("⚙", id="btn-reader-settings", classes="icon-btn")
                yield Button("📂", id="btn-load-source", classes="icon-btn")
            yield Label("", id="source-label")
            yield DataTable(id="results-table", cursor_type="row", zebra_stripes=True)
            yield LoadingIndicator(id="search-loading")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#search-loading").display = False
        self.query_one("#btn-source-ui", Button).disabled = True
        self.query_one("#btn-discover", Button).disabled = True
        tbl: DataTable = self.query_one("#results-table", DataTable)
        tbl.add_columns("#", "书名", "作者", "分类", "最新章节", "URL")
        self.source = self.app.source
        self._update_source_label()

    def on_show(self) -> None:
        self.source = self.app.source
        self._update_source_label()

    def _update_source_label(self) -> None:
        src = self.source
        if src:
            self.query_one("#source-label", Label).update(
                f"[dim]书源：[/dim][bold cyan]{src.bookSourceName}[/bold cyan]  "
                f"[dim]{src.bookSourceUrl}[/dim]"
            )
        else:
            self.query_one("#source-label", Label).update(
                "[dim]书源：未加载 — 按 📂 加载书源[/dim]"
            )
        self.query_one("#btn-source-ui", Button).disabled = not bool(
            src and (src.loginUi or src.loginUrl)
        )
        self.query_one("#btn-discover", Button).disabled = not bool(src and src.exploreUrl)

    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def action_refresh_results(self) -> None:
        self._do_search()

    def action_open_bookshelf(self) -> None:
        self.app.open_bookshelf()

    def action_open_reader_settings(self) -> None:
        self.app.open_reader_settings()

    def action_open_source_ui(self) -> None:
        self.app.open_source_ui(self.source)

    def action_open_discover(self) -> None:
        self.app.open_discover(self.source)

    @on(Button.Pressed, "#btn-load-source")
    def load_source(self) -> None:
        self.app.open_source_loader()

    @on(Button.Pressed, "#btn-search")
    def search_pressed(self) -> None:
        self._do_search()

    @on(Button.Pressed, "#btn-discover")
    def discover_pressed(self) -> None:
        self.action_open_discover()

    @on(Button.Pressed, "#btn-bookshelf")
    def bookshelf_pressed(self) -> None:
        self.action_open_bookshelf()

    @on(Button.Pressed, "#btn-source-ui")
    def source_ui_pressed(self) -> None:
        self.action_open_source_ui()

    @on(Button.Pressed, "#btn-reader-settings")
    def reader_settings_pressed(self) -> None:
        self.action_open_reader_settings()

    @on(Input.Submitted, "#search-input")
    def search_submitted(self) -> None:
        self._do_search()

    def _do_search(self) -> None:
        if not self.source:
            self.app.warn("请先加载书源。")
            return
        query = self.query_one("#search-input", Input).value.strip()
        if not query:
            return
        self._run_search(query)

    @work(thread=True)
    def _run_search(self, query: str) -> None:
        self.app.call_from_thread(
            lambda: setattr(self.query_one("#search-loading"), "display", True)
        )
        try:
            results = search_book(self.source, query)
        except Exception as e:
            self.app.call_from_thread(self.app.error, f"搜索失败：{e}")
            results = []
        finally:
            self.app.call_from_thread(
                lambda: setattr(self.query_one("#search-loading"), "display", False)
            )
        self.app.call_from_thread(self._populate_results, results)

    def _populate_results(self, results: list) -> None:
        self.results = results
        tbl: DataTable = self.query_one("#results-table", DataTable)
        tbl.clear()
        for i, r in enumerate(results, 1):
            tbl.add_row(
                str(i),
                r.name or "",
                r.author or "",
                r.kind or "",
                (r.latestChapterTitle or "")[:40],
                r.bookUrl or "",
                key=str(i - 1),
            )

    @on(DataTable.RowSelected, "#results-table")
    def row_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        if 0 <= idx < len(self.results):
            book = self.results[idx].to_book() if hasattr(self.results[idx], "to_book") else None
            if book is None:
                book = Book()
                book.bookUrl = self.results[idx].bookUrl
                book.name = self.results[idx].name
                book.author = self.results[idx].author
                book.origin = self.source.bookSourceUrl
                book.infoHtml = getattr(self.results[idx], "infoHtml", None)
            self.app.push_screen(BookScreen(book=book, source=self.source))


class ExploreKindsScreen(Screen):
    """Shows discover categories/function buttons for the current source."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "返回"),
        Binding("r",      "reload",         "刷新"),
        Binding("a",      "open_source_ui", "认证"),
        Binding("/",      "focus_filter",   "筛选"),
    ]

    def __init__(self, source: BookSource) -> None:
        super().__init__()
        self._source = source
        self._kinds: List[ExploreKind] = []
        self._filtered_kinds: List[ExploreKind] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            with Horizontal(id="discover-top"):
                yield Label("", id="discover-label")
                yield Button("🔐 认证", id="btn-discover-source-ui")
            with Horizontal(id="discover-filter-bar"):
                yield Input(placeholder="🔍 筛选分类…", id="discover-filter")
                yield Label("", id="discover-count")
            yield LoadingIndicator(id="discover-loading")
            yield DataTable(id="discover-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#discover-label", Label).update(
            f"[bold]🧭 发现[/bold]  [dim]{self._source.bookSourceName}[/dim]"
        )
        table: DataTable = self.query_one("#discover-table", DataTable)
        table.add_columns("#", "名称", "类型", "URL")
        self.query_one("#btn-discover-source-ui", Button).disabled = not bool(
            self._source.loginUi or self._source.loginUrl
        )
        self.query_one("#discover-loading").display = True
        self._load_kinds()

    def action_open_source_ui(self) -> None:
        self.app.open_source_ui(self._source)

    def action_reload(self) -> None:
        self.query_one("#discover-loading").display = True
        self._load_kinds()

    def action_focus_filter(self) -> None:
        self.query_one("#discover-filter", Input).focus()

    @work(thread=True)
    def _load_kinds(self) -> None:
        try:
            kinds = get_explore_kinds(self._source)
        except Exception as e:
            self.app.call_from_thread(self.app.error, f"发现页加载失败：{e}")
            kinds = []
        self._kinds = kinds
        self.app.call_from_thread(self._populate_kinds, kinds)

    def _populate_kinds(self, kinds: List[ExploreKind]) -> None:
        self.query_one("#discover-loading").display = False
        self._filtered_kinds = list(kinds)
        self._render_kinds_table()

    def _render_kinds_table(self) -> None:
        table: DataTable = self.query_one("#discover-table", DataTable)
        table.clear()
        for i, kind in enumerate(self._filtered_kinds, 1):
            kind_type = "📂 分类" if kind.url else "🏷 标签"
            table.add_row(
                str(i),
                kind.title or "",
                kind_type,
                kind.url or "—",
                key=str(i - 1),
            )
        self.query_one("#discover-count", Label).update(
            f"[dim]{len(self._filtered_kinds)} 项[/dim]"
        )

    @on(Input.Changed, "#discover-filter")
    def discover_filter_changed(self, event: Input.Changed) -> None:
        q = event.value.lower().strip()
        if not q:
            self._filtered_kinds = list(self._kinds)
        else:
            self._filtered_kinds = [
                k for k in self._kinds
                if q in (k.title or "").lower() or q in (k.url or "").lower()
            ]
        self._render_kinds_table()

    @on(DataTable.RowSelected, "#discover-table")
    def discover_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        if 0 <= idx < len(self._filtered_kinds):
            kind = self._filtered_kinds[idx]
            if not kind.url:
                self.app.info("该项只是分组标签，无法打开。")
                return
            self.app.push_screen(ExploreResultsScreen(
                source=self._source,
                title=kind.title or "发现",
                url=kind.url,
            ))

    @on(Button.Pressed, "#btn-discover-source-ui")
    def discover_source_ui_pressed(self) -> None:
        self.action_open_source_ui()


class ExploreResultsScreen(Screen):
    """Shows books for one discover category with pagination."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "返回"),
        Binding("r",      "reload",         "刷新"),
        Binding("n",      "next_page",      "下一页"),
        Binding("p",      "prev_page",      "上一页"),
    ]

    def __init__(self, source: BookSource, title: str, url: str, page: int = 1) -> None:
        super().__init__()
        self._source = source
        self._title = title
        self._url = url
        self._page = page
        self._results: List = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            with Horizontal(id="explore-top"):
                yield Button("← 上一页", id="btn-explore-prev")
                yield Label("", id="explore-page-label")
                yield Button("下一页 →", variant="primary", id="btn-explore-next")
            yield LoadingIndicator(id="explore-loading")
            yield DataTable(id="explore-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self._title
        table: DataTable = self.query_one("#explore-table", DataTable)
        table.add_columns("#", "书名", "作者", "分类", "最新章节", "URL")
        self.query_one("#explore-loading").display = True
        self._update_page_label()
        self._load_results()

    def _update_page_label(self) -> None:
        self.query_one("#explore-page-label", Label).update(
            f"[bold]{self._title}[/bold]  [dim]第 {self._page} 页[/dim]"
        )
        self.query_one("#btn-explore-prev", Button).disabled = self._page <= 1

    def action_reload(self) -> None:
        self.query_one("#explore-loading").display = True
        self._load_results()

    def action_next_page(self) -> None:
        self._page += 1
        self.query_one("#explore-loading").display = True
        self._update_page_label()
        self._load_results()

    def action_prev_page(self) -> None:
        if self._page <= 1:
            return
        self._page -= 1
        self.query_one("#explore-loading").display = True
        self._update_page_label()
        self._load_results()

    @work(thread=True)
    def _load_results(self) -> None:
        try:
            results = explore_book(self._source, self._url, page=self._page)
        except Exception as e:
            self.app.call_from_thread(self.app.error, f"分类加载失败：{e}")
            results = []
        self._results = results
        self.app.call_from_thread(self._populate_results, results)

    def _populate_results(self, results: list) -> None:
        self.query_one("#explore-loading").display = False
        table: DataTable = self.query_one("#explore-table", DataTable)
        table.clear()
        for i, r in enumerate(results, 1):
            table.add_row(
                str(i),
                r.name or "",
                r.author or "",
                r.kind or "",
                (r.latestChapterTitle or "")[:40],
                r.bookUrl or "",
                key=str(i - 1),
            )

    @on(Button.Pressed, "#btn-explore-next")
    def explore_next_pressed(self) -> None:
        self.action_next_page()

    @on(Button.Pressed, "#btn-explore-prev")
    def explore_prev_pressed(self) -> None:
        self.action_prev_page()

    @on(DataTable.RowSelected, "#explore-table")
    def explore_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        if 0 <= idx < len(self._results):
            result = self._results[idx]
            book = result.to_book() if hasattr(result, "to_book") else None
            if book is None:
                book = Book()
                book.bookUrl = result.bookUrl
                book.name = result.name
                book.author = result.author
                book.origin = self._source.bookSourceUrl
                book.infoHtml = getattr(result, "infoHtml", None)
            self.app.push_screen(BookScreen(book=book, source=self._source))



# ═══════════════════════════════════════════════════════════════════════════════
# BOOK INFO & CHAPTER LIST SCREENS
# ═══════════════════════════════════════════════════════════════════════════════

class BookInfoScreen(Screen):
    """Shows book metadata with rich display, bookmark, and chapter-list access."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "返回"),
        Binding("b",      "open_bookshelf", "书架"),
        Binding("c",      "open_chapters",  "目录"),
        Binding("r",      "reload",         "刷新"),
        Binding("f",      "save_to_shelf",  "收藏"),
    ]

    def __init__(self, book: Book, source: BookSource) -> None:
        super().__init__()
        self._book = book
        self._source = source

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield LoadingIndicator(id="info-loading")
            yield ScrollableContainer(
                Static("", id="info-content"),
                id="info-scroll",
            )
            with Horizontal(id="info-btns"):
                yield Button("⭐ 加入书架", id="btn-save-shelf")
                yield Button("📖 章节目录", variant="primary", id="btn-chapters")
                yield Button("← 返回", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#info-loading").display = True
        self._load_info()

    def action_reload(self) -> None:
        self._book.tocUrl = ""
        self._book.infoHtml = None
        self.query_one("#info-loading").display = True
        self._load_info()

    @work(thread=True)
    def _load_info(self) -> None:
        try:
            book = get_book_info(self._source, self._book, can_rename=True)
            self._book = book
        except Exception as e:
            self.app.call_from_thread(self.app.error, f"书籍详情加载失败：{e}")
        finally:
            self.app.call_from_thread(self._render_info)

    def _render_info(self) -> None:
        self.query_one("#info-loading").display = False
        b = self._book
        self.sub_title = b.name or "书籍详情"

        # Build a rich Text renderable
        renderable = Text()
        renderable.append(f"  {b.name or '未命名'}\n", style="bold cyan")
        renderable.append("  " + "─" * 40 + "\n\n", style="dim")

        fields = [
            ("作者", b.author, "green"),
            ("分类", b.kind, "yellow"),
            ("字数", b.wordCount, ""),
            ("最新", b.latestChapterTitle, ""),
        ]
        for label, value, style in fields:
            renderable.append(f"  {label}：", style="bold")
            renderable.append(f"{value or '—'}\n", style=style)

        renderable.append("\n")
        renderable.append("  简介\n", style="bold underline")
        renderable.append("  " + "─" * 40 + "\n", style="dim")
        intro = (b.intro or "暂无简介").strip()
        for para in intro.split("\n"):
            wrapped = textwrap.fill(para.strip(), width=72, initial_indent="  ", subsequent_indent="  ")
            renderable.append(wrapped + "\n\n", style="")

        renderable.append("  " + "─" * 40 + "\n", style="dim")
        renderable.append("  详情：", style="bold dim")
        renderable.append(f"{b.bookUrl}\n", style="blue dim")
        renderable.append("  目录：", style="bold dim")
        renderable.append(f"{b.tocUrl or '—'}\n", style="blue dim")

        # Check if already on shelf
        entry = self.app.reader_state.get_bookshelf_entry(self._source, b)
        if entry:
            progress = format_progress(entry)
            renderable.append(f"\n  [已在书架] 进度：{progress}\n", style="green")

        self.query_one("#info-content", Static).update(renderable)

    def action_open_chapters(self) -> None:
        self.action_save_to_shelf()
        self.app.push_screen(ChapterListScreen(book=self._book, source=self._source))

    def action_open_bookshelf(self) -> None:
        self.app.open_bookshelf()

    def action_save_to_shelf(self) -> None:
        self.app.reader_state.remember_book(self._source, self._book)
        self.app.info("⭐ 已加入书架。")

    @on(Button.Pressed, "#btn-chapters")
    def chapters_pressed(self) -> None:
        self.action_open_chapters()

    @on(Button.Pressed, "#btn-save-shelf")
    def save_shelf_pressed(self) -> None:
        self.action_save_to_shelf()

    @on(Button.Pressed, "#btn-back")
    def back_pressed(self) -> None:
        self.app.pop_screen()


class ChapterListScreen(Screen):
    """Chapter list with filter, jump-to-chapter, and resume-reading support."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "返回"),
        Binding("b",      "open_bookshelf", "书架"),
        Binding("t",      "open_reader_settings", "设置"),
        Binding("r",      "reload",         "刷新"),
        Binding("/",      "focus_filter",   "筛选"),
        Binding("j",      "jump_to_chapter", "跳转"),
        Binding("g",      "goto_last_read", "继续阅读"),
    ]

    def __init__(
        self,
        book: Book,
        source: BookSource,
        resume_progress: Optional[Dict[str, Any]] = None,
        auto_open: bool = False,
    ) -> None:
        super().__init__()
        self._book = book
        self._source = source
        self._chapters: List[BookChapter] = []
        self._filtered: List[BookChapter] = []
        self._resume_progress = resume_progress or {}
        self._auto_open = auto_open
        self._auto_opened = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            # ── Book info bar ──
            yield Label("", id="ch-book-info")

            # ── Filter + actions ──
            with Horizontal(id="chapters-top"):
                yield Input(placeholder="🔍 筛选章节…", id="chapter-filter")
                yield Button("跳转", id="btn-ch-jump")
                yield Button("继续", variant="primary", id="btn-ch-resume")
                yield Label("", id="chapter-count")

            with Horizontal(id="ch-loading", classes="chapter-loading-row"):
                yield ProgressBar(id="ch-progress", show_eta=False)
                yield Label("", id="ch-progress-label")
            yield DataTable(id="ch-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self._book.name or "目录"
        self.query_one("#ch-book-info", Label).update(
            f"[bold]📖 {self._book.name or '未命名'}[/bold]  "
            f"[dim]{self._book.author or ''}[/dim]"
        )
        tbl: DataTable = self.query_one("#ch-table", DataTable)
        tbl.add_columns("#", "章节", "VIP", "URL")
        self.query_one("#ch-loading").display = True
        self._load_chapters()

    def action_reload(self) -> None:
        self._book.tocHtml = None
        self.query_one("#ch-loading").display = True
        self._load_chapters()

    def action_focus_filter(self) -> None:
        self.query_one("#chapter-filter", Input).focus()

    def action_open_bookshelf(self) -> None:
        self.app.open_bookshelf()

    def action_open_reader_settings(self) -> None:
        self.app.open_reader_settings()

    def action_jump_to_chapter(self) -> None:
        self.app.push_screen(
            TextPromptScreen(
                "跳转到章节",
                placeholder=f"输入章节号 (1-{len(self._chapters)})",
            ),
            self._on_jump_to_chapter,
        )

    def _on_jump_to_chapter(self, value: Optional[str]) -> None:
        if value is None or not value.strip():
            return
        try:
            num = int(value.strip())
        except ValueError:
            self.app.warn("请输入有效的章节数字。")
            return
        idx = num - 1
        ch = next((c for c in self._chapters if c.index == idx), None)
        if ch is None:
            self.app.warn(f"章节 {num} 不存在。")
            return
        self._open_reader(ch)

    def action_goto_last_read(self) -> None:
        if not self._chapters:
            return
        progress = self._resume_progress
        target = None
        chapter_url = progress.get("chapter_url")
        chapter_index = progress.get("chapter_index")
        if chapter_url:
            target = next((c for c in self._chapters if c.url == chapter_url), None)
        if target is None and chapter_index is not None:
            target = next((c for c in self._chapters if c.index == chapter_index), None)
        if target:
            self._open_reader(target)
        else:
            self.app.info("没有找到上次阅读位置。")

    @work(thread=True)
    def _load_chapters(self) -> None:
        def _on_progress(done: int, total: int) -> None:
            self.app.call_from_thread(self._update_ch_progress, done, total)

        def _on_batch(batch: list) -> None:
            self.app.call_from_thread(self._append_chapter_batch, batch)

        try:
            chapters = get_chapter_list(
                self._source, self._book,
                progress_fn=_on_progress,
                chapter_batch_fn=_on_batch,
            )
        except Exception as e:
            self.app.call_from_thread(self.app.error, f"目录加载失败：{e}")
            chapters = []
        self._chapters = chapters
        self.app.call_from_thread(self._populate, chapters)

    def _append_chapter_batch(self, batch: list) -> None:
        """Stream-append a page-worth of chapters while loading is in progress."""
        tbl: DataTable = self.query_one("#ch-table", DataTable)
        for ch in batch:
            row_num = tbl.row_count + 1
            tbl.add_row(str(row_num), ch.title or "", "★" if ch.isVip else "", ch.url or "")

    def _populate(self, chapters: List[BookChapter]) -> None:
        self.query_one("#ch-loading").display = False
        self._filtered = chapters
        self._book.totalChapterNum = len(chapters)
        tbl: DataTable = self.query_one("#ch-table", DataTable)
        tbl.clear()

        # Determine which chapter is the last-read one
        progress = self._resume_progress
        last_read_index = progress.get("chapter_index")

        for ch in chapters:
            marker = "→" if ch.index == last_read_index else ""
            tbl.add_row(
                str(ch.index + 1),
                f"{marker} {ch.title}" if marker else (ch.title or ""),
                "★" if ch.isVip else "",
                ch.url or "",
                key=str(ch.index),
            )

        self.query_one("#chapter-count", Label).update(
            f"[dim]{len(chapters)} 章[/dim]"
        )

        # Show/hide resume button
        has_progress = bool(progress.get("chapter_index") is not None)
        self.query_one("#btn-ch-resume", Button).disabled = not has_progress

        if self._auto_open and not self._auto_opened and chapters:
            self._auto_opened = True
            target = None
            chapter_url = progress.get("chapter_url")
            chapter_index = progress.get("chapter_index")
            if chapter_url:
                target = next((c for c in chapters if c.url == chapter_url), None)
            if target is None and chapter_index is not None:
                target = next((c for c in chapters if c.index == chapter_index), None)
            if target is None:
                target = chapters[0]
            self._open_reader(target)

    @on(Input.Changed, "#chapter-filter")
    def filter_changed(self, event: Input.Changed) -> None:
        q = event.value.lower()
        filtered = (
            [c for c in self._chapters if q in (c.title or "").lower()]
            if q else self._chapters
        )
        self._filtered = filtered
        tbl: DataTable = self.query_one("#ch-table", DataTable)
        tbl.clear()
        for ch in filtered:
            tbl.add_row(
                str(ch.index + 1),
                ch.title or "",
                "★" if ch.isVip else "",
                ch.url or "",
                key=str(ch.index),
            )
        self.query_one("#chapter-count", Label).update(
            f"[dim]{len(filtered)} 章[/dim]"
        )

    @on(DataTable.RowSelected, "#ch-table")
    def chapter_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        ch = next((c for c in self._chapters if c.index == idx), None)
        if ch:
            self._open_reader(ch)

    @on(Button.Pressed, "#btn-ch-jump")
    def jump_pressed(self) -> None:
        self.action_jump_to_chapter()

    @on(Button.Pressed, "#btn-ch-resume")
    def resume_pressed(self) -> None:
        self.action_goto_last_read()

    def _open_reader(self, chapter: BookChapter) -> None:
        progress = self._resume_progress or {}
        initial_scroll_ratio = 0.0
        if (
            progress.get("chapter_index") == chapter.index
            or (progress.get("chapter_url") and progress.get("chapter_url") == chapter.url)
        ):
            initial_scroll_ratio = float(progress.get("scroll_ratio", 0.0) or 0.0)
        self._book.durChapterIndex = chapter.index
        self._book.durChapterTitle = chapter.title
        self.app.push_screen(
            ReaderScreen(
                book=self._book,
                chapter=chapter,
                chapters=self._chapters,
                source=self._source,
                initial_scroll_ratio=initial_scroll_ratio,
            )
        )


class BookScreen(Screen):
    """Combined book info + chapter list in a two-column layout."""

    BINDINGS = [
        Binding("escape", "app.pop_screen",       "返回"),
        Binding("b",      "open_bookshelf",       "书架"),
        Binding("t",      "open_reader_settings", "设置"),
        Binding("r",      "reload",               "刷新"),
        Binding("/",      "focus_filter",         "筛选章节"),
        Binding("j",      "jump_to_chapter",      "跳转"),
        Binding("g",      "goto_last_read",       "继续阅读"),
        Binding("f",      "save_to_shelf",        "收藏"),
    ]

    def __init__(
        self,
        book: Book,
        source: BookSource,
        resume_progress: Optional[Dict[str, Any]] = None,
        auto_open: bool = False,
    ) -> None:
        super().__init__()
        self._book = book
        self._source = source
        self._chapters: List[BookChapter] = []
        self._filtered: List[BookChapter] = []
        self._resume_progress = resume_progress or {}
        self._auto_open = auto_open
        self._auto_opened = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="book-screen-body"):
            # Left column: book info
            with Vertical(id="book-info-col"):
                yield LoadingIndicator(id="info-loading")
                yield ScrollableContainer(
                    Static("", id="info-content"),
                    id="info-scroll",
                )
                with Horizontal(id="info-actions"):
                    yield Button("⭐ 收藏", id="btn-save-shelf")
                    yield Button("继续阅读", variant="primary", id="btn-resume")
                    yield Button("← 返回", id="btn-back")
            # Right column: chapter list
            with Vertical(id="book-chapter-col"):
                with Horizontal(id="chapters-top"):
                    yield Input(placeholder="🔍 筛选章节…", id="chapter-filter")
                    yield Button("跳转", id="btn-ch-jump")
                    yield Label("", id="chapter-count")
                with Horizontal(id="ch-loading", classes="chapter-loading-row"):
                    yield ProgressBar(id="ch-progress", show_eta=False)
                    yield Label("", id="ch-progress-label")
                yield DataTable(id="ch-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self._book.name or "书籍详情"
        self.query_one("#info-loading").display = True
        self.query_one("#ch-loading").display = True
        tbl: DataTable = self.query_one("#ch-table", DataTable)
        tbl.add_columns("#", "章节", "VIP", "URL")
        self._load_info()
        self._load_chapters()

    def action_reload(self) -> None:
        self._book.tocUrl = ""
        self._book.infoHtml = None
        self._book.tocHtml = None
        self.query_one("#info-loading").display = True
        self.query_one("#ch-loading").display = True
        self._load_info()
        self._load_chapters()

    def action_focus_filter(self) -> None:
        self.query_one("#chapter-filter", Input).focus()

    def action_open_bookshelf(self) -> None:
        self.app.open_bookshelf()

    def action_open_reader_settings(self) -> None:
        self.app.open_reader_settings()

    def action_save_to_shelf(self) -> None:
        self.app.reader_state.remember_book(self._source, self._book)
        self.app.info("⭐ 已加入书架。")

    def action_jump_to_chapter(self) -> None:
        self.app.push_screen(
            TextPromptScreen(
                "跳转到章节",
                placeholder=f"输入章节号 (1-{len(self._chapters)})",
            ),
            self._on_jump_to_chapter,
        )

    def _on_jump_to_chapter(self, value: Optional[str]) -> None:
        if value is None or not value.strip():
            return
        try:
            num = int(value.strip())
        except ValueError:
            self.app.warn("请输入有效的章节数字。")
            return
        idx = num - 1
        ch = next((c for c in self._chapters if c.index == idx), None)
        if ch is None:
            self.app.warn(f"章节 {num} 不存在。")
            return
        self._open_reader(ch)

    def action_goto_last_read(self) -> None:
        if not self._chapters:
            return
        progress = self._resume_progress
        target = None
        chapter_url = progress.get("chapter_url")
        chapter_index = progress.get("chapter_index")
        if chapter_url:
            target = next((c for c in self._chapters if c.url == chapter_url), None)
        if target is None and chapter_index is not None:
            target = next((c for c in self._chapters if c.index == chapter_index), None)
        if target:
            self._open_reader(target)
        else:
            self.app.info("没有找到上次阅读位置。")

    @work(thread=True)
    def _load_info(self) -> None:
        try:
            book = get_book_info(self._source, self._book, can_rename=True)
            self._book = book
        except Exception as e:
            self.app.call_from_thread(self.app.error, f"书籍详情加载失败：{e}")
        finally:
            self.app.call_from_thread(self._render_info)

    def _render_info(self) -> None:
        self.query_one("#info-loading").display = False
        b = self._book
        self.sub_title = b.name or "书籍详情"

        renderable = Text()
        renderable.append(f"  {b.name or '未命名'}\n", style="bold cyan")
        renderable.append("  " + "─" * 40 + "\n\n", style="dim")

        fields = [
            ("作者", b.author, "green"),
            ("分类", b.kind, "yellow"),
            ("字数", b.wordCount, ""),
            ("最新", b.latestChapterTitle, ""),
        ]
        for label, value, style in fields:
            renderable.append(f"  {label}：", style="bold")
            renderable.append(f"{value or '—'}\n", style=style)

        renderable.append("\n")
        renderable.append("  简介\n", style="bold underline")
        renderable.append("  " + "─" * 40 + "\n", style="dim")
        intro = (b.intro or "暂无简介").strip()
        for para in intro.split("\n"):
            wrapped = textwrap.fill(para.strip(), width=72, initial_indent="  ", subsequent_indent="  ")
            renderable.append(wrapped + "\n\n", style="")

        renderable.append("  " + "─" * 40 + "\n", style="dim")
        renderable.append("  详情：", style="bold dim")
        renderable.append(f"{b.bookUrl}\n", style="blue dim")
        renderable.append("  目录：", style="bold dim")
        renderable.append(f"{b.tocUrl or '—'}\n", style="blue dim")

        entry = self.app.reader_state.get_bookshelf_entry(self._source, b)
        if entry:
            progress = format_progress(entry)
            renderable.append(f"\n  [已在书架] 进度：{progress}\n", style="green")

        self.query_one("#info-content", Static).update(renderable)

    @work(thread=True)
    def _load_chapters(self) -> None:
        def _on_progress(done: int, total: int) -> None:
            self.app.call_from_thread(self._update_ch_progress, done, total)

        def _on_batch(batch: list) -> None:
            self.app.call_from_thread(self._append_chapter_batch, batch)

        try:
            chapters = get_chapter_list(
                self._source, self._book,
                progress_fn=_on_progress,
                chapter_batch_fn=_on_batch,
            )
        except Exception as e:
            self.app.call_from_thread(self.app.error, f"目录加载失败：{e}")
            chapters = []
        self._chapters = chapters
        self.app.call_from_thread(self._populate, chapters)

    def _append_chapter_batch(self, batch: list) -> None:
        """Stream-append a page-worth of chapters while loading is in progress."""
        tbl: DataTable = self.query_one("#ch-table", DataTable)
        for ch in batch:
            row_num = tbl.row_count + 1
            tbl.add_row(str(row_num), ch.title or "", "★" if ch.isVip else "", ch.url or "")

    def _update_ch_progress(self, done: int, total: int) -> None:
        try:
            self.query_one("#ch-progress", ProgressBar).update(progress=done, total=total)
            self.query_one("#ch-progress-label", Label).update(f"  {done}/{total}")
        except Exception:
            pass

    def _populate(self, chapters: List[BookChapter]) -> None:
        self.query_one("#ch-loading").display = False
        self._filtered = chapters
        self._book.totalChapterNum = len(chapters)
        tbl: DataTable = self.query_one("#ch-table", DataTable)
        tbl.clear()

        progress = self._resume_progress
        last_read_index = progress.get("chapter_index")

        for ch in chapters:
            marker = "→" if ch.index == last_read_index else ""
            tbl.add_row(
                str(ch.index + 1),
                f"{marker} {ch.title}" if marker else (ch.title or ""),
                "★" if ch.isVip else "",
                ch.url or "",
                key=str(ch.index),
            )

        self.query_one("#chapter-count", Label).update(
            f"[dim]{len(chapters)} 章[/dim]"
        )

        has_progress = bool(progress.get("chapter_index") is not None)
        self.query_one("#btn-resume", Button).disabled = not has_progress

        if self._auto_open and not self._auto_opened and chapters:
            self._auto_opened = True
            target = None
            chapter_url = progress.get("chapter_url")
            chapter_index = progress.get("chapter_index")
            if chapter_url:
                target = next((c for c in chapters if c.url == chapter_url), None)
            if target is None and chapter_index is not None:
                target = next((c for c in chapters if c.index == chapter_index), None)
            if target is None:
                target = chapters[0]
            self._open_reader(target)

    @on(Input.Changed, "#chapter-filter")
    def filter_changed(self, event: Input.Changed) -> None:
        q = event.value.lower()
        filtered = (
            [c for c in self._chapters if q in (c.title or "").lower()]
            if q else self._chapters
        )
        self._filtered = filtered
        tbl: DataTable = self.query_one("#ch-table", DataTable)
        tbl.clear()
        for ch in filtered:
            tbl.add_row(
                str(ch.index + 1),
                ch.title or "",
                "★" if ch.isVip else "",
                ch.url or "",
                key=str(ch.index),
            )
        self.query_one("#chapter-count", Label).update(
            f"[dim]{len(filtered)} 章[/dim]"
        )

    @on(DataTable.RowSelected, "#ch-table")
    def chapter_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        ch = next((c for c in self._chapters if c.index == idx), None)
        if ch:
            self._open_reader(ch)

    @on(Button.Pressed, "#btn-ch-jump")
    def jump_pressed(self) -> None:
        self.action_jump_to_chapter()

    @on(Button.Pressed, "#btn-resume")
    def resume_pressed(self) -> None:
        self.action_goto_last_read()

    @on(Button.Pressed, "#btn-save-shelf")
    def save_shelf_pressed(self) -> None:
        self.action_save_to_shelf()

    @on(Button.Pressed, "#btn-back")
    def back_pressed(self) -> None:
        self.app.pop_screen()

    def _open_reader(self, chapter: BookChapter) -> None:
        progress = self._resume_progress or {}
        initial_scroll_ratio = 0.0
        if (
            progress.get("chapter_index") == chapter.index
            or (progress.get("chapter_url") and progress.get("chapter_url") == chapter.url)
        ):
            initial_scroll_ratio = float(progress.get("scroll_ratio", 0.0) or 0.0)
        self._book.durChapterIndex = chapter.index
        self._book.durChapterTitle = chapter.title
        self.app.push_screen(
            ReaderScreen(
                book=self._book,
                chapter=chapter,
                chapters=self._chapters,
                source=self._source,
                initial_scroll_ratio=initial_scroll_ratio,
            )
        )


# ═══════════════════════════════════════════════════════════════════════════════
# READER SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

class ReaderScreen(Screen):
    """Full-screen chapter reader with themes, caching, progress, and navigation."""

    BINDINGS = [
        Binding("escape",    "app.pop_screen",      "返回"),
        Binding("b",         "open_bookshelf",      "书架"),
        Binding("t",         "open_reader_settings", "设置"),
        Binding("/",         "find_text",           "查找"),
        Binding("n",         "next_chapter",        "下一章"),
        Binding("p",         "prev_chapter",        "上一章"),
        Binding("r",         "reload",              "刷新"),
        Binding("j",         "jump_to_chapter",     "跳转"),
        Binding("ctrl+end",  "scroll_bottom",       "末尾"),
        Binding("ctrl+home", "scroll_top",          "顶部"),
        Binding("d",         "cycle_theme",         "主题"),
    ]

    def __init__(
        self,
        book: Book,
        chapter: BookChapter,
        chapters: List[BookChapter],
        source: BookSource,
        initial_scroll_ratio: float = 0.0,
    ) -> None:
        super().__init__()
        self._book = book
        self._chapter = chapter
        self._chapters = chapters
        self._source = source
        self._initial_scroll_ratio = initial_scroll_ratio
        self._restore_scroll_ratio = initial_scroll_ratio
        self._current_text = ""
        self._search_query = ""
        self._progress_timer = None

    @property
    def _current_idx(self) -> int:
        return self._chapter.index

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield LoadingIndicator(id="reader-loading")

            # ── Reading area with theme-aware container ──
            yield ScrollableContainer(
                Static("", id="reader-text"),
                id="reader-scroll",
            )

            # ── Navigation bar ──
            with Horizontal(id="reader-nav"):
                yield Button("← 上一章", id="btn-prev")
                yield Button("🔍", id="btn-find", classes="icon-btn")
                yield Label("", id="nav-label")
                yield Button("🎨", id="btn-theme", classes="icon-btn")
                yield Button("⚙", id="btn-style", classes="icon-btn")
                yield Button("下一章 →", variant="primary", id="btn-next")

            # ── Progress indicator ──
            with Horizontal(id="reader-progress-bar"):
                yield Label("", id="reader-progress-label")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self._chapter.title or ""
        self._book.totalChapterNum = len(self._chapters)
        self._book.durChapterIndex = self._chapter.index
        self._book.durChapterTitle = self._chapter.title
        self.app.reader_state.remember_book(self._source, self._book)

        # Apply current theme
        self._apply_theme_class()

        self.query_one("#reader-loading").display = True
        self._update_nav()
        self._load_content()
        self._progress_timer = self.set_interval(2.5, self._autosave_progress)

    def on_unmount(self) -> None:
        self._autosave_progress()

    def _get_current_theme(self) -> str:
        settings = self.app.reader_state.get_settings()
        return str(settings.get("reader_theme", "night"))

    def _apply_theme_class(self) -> None:
        """Apply the CSS theme class to the reader scroll container."""
        scroll = self.query_one("#reader-scroll", ScrollableContainer)
        # Remove all existing theme classes
        for theme_key in READER_THEMES:
            scroll.remove_class(f"reader-theme-{theme_key}")
        # Apply current theme
        theme_key = self._get_current_theme()
        scroll.add_class(f"reader-theme-{theme_key}")

    def _update_nav(self) -> None:
        idx = self._current_idx
        total = len(self._chapters)
        search_note = f"  [yellow]/{self._search_query}[/yellow]" if self._search_query else ""

        # Chapter progress percentage
        if total > 0:
            chapter_pct = int(((idx + 1) / total) * 100)
        else:
            chapter_pct = 0

        # Theme indicator
        theme = READER_THEMES.get(self._get_current_theme(), {})
        theme_icon = theme.get("icon", "")

        self.query_one("#nav-label", Label).update(
            f"[dim]{idx + 1}/{total}[/dim]  "
            f"[bold]{self._chapter.title or '—'}[/bold]"
            f"{search_note}"
        )
        self.query_one("#btn-prev").disabled = (idx == 0)
        self.query_one("#btn-next").disabled = (idx >= total - 1)

        # Progress bar label
        self.query_one("#reader-progress-label", Label).update(
            f"[dim]{theme_icon} {self._book.name or ''} · "
            f"第{idx + 1}章 · 全书{chapter_pct}%[/dim]"
        )

    def action_reload(self) -> None:
        self._restore_scroll_ratio = 0.0
        self.query_one("#reader-loading").display = True
        self._load_content(force_refresh=True)

    def action_open_bookshelf(self) -> None:
        self.app.open_bookshelf()

    def action_open_reader_settings(self) -> None:
        self.app.open_reader_settings()

    def action_find_text(self) -> None:
        self.app.push_screen(
            TextPromptScreen(
                "🔍 章节内查找",
                placeholder="输入关键词…",
                value=self._search_query,
            ),
            self._on_find_text,
        )

    def _on_find_text(self, value: Optional[str]) -> None:
        if value is None:
            return
        self._search_query = value.strip()
        self._update_nav()
        self._render_current_text()
        self.set_timer(0.05, self._scroll_to_search_result)

    def action_jump_to_chapter(self) -> None:
        total = len(self._chapters)
        self.app.push_screen(
            TextPromptScreen(
                "跳转到章节",
                placeholder=f"输入章节号 (1-{total})",
                value=str(self._current_idx + 1),
            ),
            self._on_jump_to_chapter,
        )

    def _on_jump_to_chapter(self, value: Optional[str]) -> None:
        if value is None or not value.strip():
            return
        try:
            num = int(value.strip())
        except ValueError:
            self.app.warn("请输入有效的章节数字。")
            return
        idx = num - 1
        ch = next((c for c in self._chapters if c.index == idx), None)
        if ch is None:
            self.app.warn(f"章节 {num} 不存在。")
            return
        self._switch_to_chapter(ch)

    def action_cycle_theme(self) -> None:
        """Cycle through reader themes."""
        theme_keys = list(READER_THEMES.keys())
        current = self._get_current_theme()
        idx = theme_keys.index(current) if current in theme_keys else 0
        next_theme = theme_keys[(idx + 1) % len(theme_keys)]
        self.app.reader_state.update_settings(reader_theme=next_theme)
        self._apply_theme_class()
        self._update_nav()
        theme_info = READER_THEMES[next_theme]
        self.app.info(f"{theme_info['icon']} 主题：{theme_info['label']}")

    @work(thread=True)
    def _load_content(self, force_refresh: bool = False) -> None:
        idx = self._current_idx
        next_ch = next((c for c in self._chapters if c.index == idx + 1), None)
        try:
            text = None if force_refresh else self.app.reader_state.get_cached_content(
                self._source, self._book, self._chapter
            )
            if text is None:
                text = get_content(self._source, self._book, self._chapter, next_ch)
                self.app.reader_state.set_cached_content(
                    self._source, self._book, self._chapter, text
                )
        except Exception as e:
            text = f"*加载失败：{e}*"
        preload_count = int(self.app.reader_state.get_settings().get("preload_count", 2))
        self.app.reader_state.preload_chapters(
            self._source, self._book, self._chapters, idx, preload_count,
        )
        self.app.call_from_thread(self._display_content, text)

    def _display_content(self, text: str) -> None:
        self._current_text = text or ""
        self.query_one("#reader-loading").display = False
        self._render_current_text()
        self.set_timer(0.05, self._restore_scroll_position)
        self._autosave_progress()

    def _render_current_text(self) -> None:
        settings = self.app.reader_state.get_settings()
        preset_name = str(settings.get("reader_style", "comfortable"))
        preset = READER_STYLE_PRESETS.get(preset_name, READER_STYLE_PRESETS["comfortable"])
        width = preset["width"]
        gap = preset["gap"]
        padding = " " * preset["padding"]

        # Build renderable
        renderable = Text()

        # Chapter title
        renderable.append(
            f"\n{padding}{self._chapter.title or '未命名章节'}\n",
            style="bold",
        )
        renderable.append(f"{padding}{'─' * min(40, width - preset['padding'] * 2)}\n\n", style="dim")

        if not self._current_text.strip():
            renderable.append(f"{padding}暂无正文。\n", style="dim italic")
        else:
            # Parse paragraphs: split on double newlines, then on single newlines
            raw_text = self._current_text.replace("\r\n", "\n")
            paragraphs = []
            for chunk in raw_text.split("\n\n"):
                chunk = chunk.strip()
                if chunk:
                    paragraphs.append(" ".join(chunk.split()))
            if not paragraphs:
                for line in raw_text.split("\n"):
                    line = line.strip()
                    if line:
                        paragraphs.append(line)

            for paragraph in paragraphs:
                wrapped = textwrap.fill(
                    paragraph,
                    width=width,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                block = Text(
                    "\n".join(f"{padding}{line}" for line in wrapped.splitlines()),
                )
                if self._search_query:
                    block.highlight_words(
                        [self._search_query],
                        style="black on yellow",
                        case_sensitive=False,
                    )
                renderable.append_text(block)
                renderable.append("\n" * (gap + 1))

        # End-of-chapter marker
        renderable.append(f"\n{padding}{'─' * min(40, width - preset['padding'] * 2)}\n", style="dim")
        idx = self._current_idx
        total = len(self._chapters)
        if idx < total - 1:
            next_ch = next((c for c in self._chapters if c.index == idx + 1), None)
            next_title = next_ch.title if next_ch else ""
            renderable.append(f"{padding}下一章：{next_title}\n", style="dim italic")
        else:
            renderable.append(f"{padding}— 全书完 —\n", style="bold dim")
        renderable.append("\n")

        self.query_one("#reader-text", Static).update(renderable)

    def _restore_scroll_position(self) -> None:
        scroll = self.query_one("#reader-scroll", ScrollableContainer)
        ratio = max(0.0, min(1.0, float(self._restore_scroll_ratio or 0.0)))
        if ratio > 0 and getattr(scroll, "max_scroll_y", 0) > 0:
            scroll.scroll_to(y=scroll.max_scroll_y * ratio, animate=False)
        else:
            scroll.scroll_home(animate=False)

    def _scroll_to_search_result(self) -> None:
        if not self._search_query:
            return
        scroll = self.query_one("#reader-scroll", ScrollableContainer)
        scroll.scroll_home(animate=False)

    def _autosave_progress(self) -> None:
        try:
            scroll = self.query_one("#reader-scroll", ScrollableContainer)
        except Exception:
            return
        self.app.reader_state.update_progress(
            self._source,
            self._book,
            self._chapter,
            scroll_y=float(getattr(scroll, "scroll_y", 0.0) or 0.0),
            max_scroll_y=float(getattr(scroll, "max_scroll_y", 0.0) or 0.0),
            total_chapters=len(self._chapters),
        )

    def _switch_to_chapter(self, ch: BookChapter) -> None:
        self._autosave_progress()
        self._chapter = ch
        self._restore_scroll_ratio = 0.0
        self.sub_title = ch.title or ""
        self._book.durChapterIndex = ch.index
        self._book.durChapterTitle = ch.title
        self.query_one("#reader-loading").display = True
        self._apply_theme_class()
        self._update_nav()
        self._load_content()

    def action_next_chapter(self) -> None:
        ch = next((c for c in self._chapters if c.index == self._current_idx + 1), None)
        if ch:
            self._switch_to_chapter(ch)

    def action_prev_chapter(self) -> None:
        ch = next((c for c in self._chapters if c.index == self._current_idx - 1), None)
        if ch:
            self._switch_to_chapter(ch)

    @on(Button.Pressed, "#btn-next")
    def next_pressed(self) -> None:
        self.action_next_chapter()

    @on(Button.Pressed, "#btn-prev")
    def prev_pressed(self) -> None:
        self.action_prev_chapter()

    @on(Button.Pressed, "#btn-find")
    def find_pressed(self) -> None:
        self.action_find_text()

    @on(Button.Pressed, "#btn-style")
    def style_pressed(self) -> None:
        self.action_open_reader_settings()

    @on(Button.Pressed, "#btn-theme")
    def theme_pressed(self) -> None:
        self.action_cycle_theme()

    def action_scroll_top(self) -> None:
        self.query_one("#reader-scroll").scroll_home(animate=True)

    def action_scroll_bottom(self) -> None:
        self.query_one("#reader-scroll").scroll_end(animate=True)

    def apply_reader_settings(self) -> None:
        self._apply_theme_class()
        self._update_nav()
        if self._current_text:
            self._render_current_text()



# ═══════════════════════════════════════════════════════════════════════════════
# APP CSS
# ═══════════════════════════════════════════════════════════════════════════════

def _build_theme_css() -> str:
    """Generate CSS rules for each reader theme."""
    rules = []
    for key, theme in READER_THEMES.items():
        rules.append(f"""
.reader-theme-{key} {{
    background: {theme['bg']};
    color: {theme['fg']};
    border: none;
}}
.reader-theme-{key} #reader-text {{
    color: {theme['fg']};
}}""")
    return "\n".join(rules)


APP_CSS = """
/* ─── Global ─────────────────────────────────────────────────────────── */
Screen {
    background: $surface;
}

/* ─── Modal Alignment ────────────────────────────────────────────────── */
SourceLoaderScreen,
StructuredFormScreen,
TextPromptScreen,
ReaderSettingsScreen,
SourcePickerScreen,
AlertDialogScreen {
    align: center middle;
}

/* ─── Source Loader ──────────────────────────────────────────────────── */
#source-loader {
    width: 64;
    height: auto;
    border: tall $primary;
    background: $panel;
    padding: 1 2;
    margin: 4 0;
}
#loader-title {
    text-align: center;
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}
#loader-hint {
    text-align: center;
    margin-bottom: 1;
}
#loader-btns {
    margin-top: 1;
    align: center middle;
    height: 3;
}
#loader-error {
    margin-top: 1;
    text-align: center;
}

/* ─── Alert Dialog ───────────────────────────────────────────────────── */
#alert-modal {
    width: 72;
    height: auto;
    border: tall $warning;
    background: $panel;
    padding: 1 2;
}
#alert-title {
    text-style: bold;
    text-align: center;
    margin-bottom: 1;
}
#alert-message {
    padding: 0 0 1 0;
}
#alert-buttons {
    height: 3;
    align: center middle;
}
#alert-buttons Button {
    margin: 0 1;
}

/* ─── Source Picker ──────────────────────────────────────────────────── */
#source-picker-modal {
    width: 120;
    height: 80%;
    border: tall $primary;
    background: $panel;
    padding: 1 2;
}
#source-picker-title {
    text-style: bold;
    text-align: center;
    margin-bottom: 1;
    color: $text;
}
#source-picker-filter {
    margin-bottom: 1;
}
#source-picker-table {
    height: 1fr;
    border: tall $primary-darken-2;
}
#source-picker-buttons {
    height: 3;
    align: center middle;
    margin-top: 1;
}
#source-picker-buttons Button {
    margin: 0 1;
}

/* ─── Structured Form / Schema ───────────────────────────────────────── */
#schema-modal {
    width: 84;
    height: 80%;
    border: tall $primary;
    background: $panel;
    padding: 1 2;
}
#schema-title {
    text-align: center;
    text-style: bold;
    margin-bottom: 1;
}
#schema-tools {
    height: 3;
    align: left middle;
    margin-bottom: 1;
}
.schema-tool-btn {
    margin-right: 1;
}
#schema-scroll {
    height: 1fr;
}
#schema-form {
    padding-right: 1;
}
#schema-form Input {
    margin-bottom: 1;
}
#schema-form Button {
    margin-bottom: 1;
}
.schema-field-label {
    margin-top: 1;
    text-style: bold;
}
.schema-field-input {
    margin-bottom: 1;
}
.schema-button-row {
    height: auto;
    margin-bottom: 1;
}
.schema-action-btn {
    margin-right: 1;
}
.schema-btn-full {
    width: 1fr;
}
.schema-btn-half {
    width: 1fr;
}
.schema-btn-third {
    width: 1fr;
}
#schema-buttons {
    margin-top: 1;
    align: center middle;
    height: 3;
}
#schema-buttons Button {
    margin: 0 1;
}
#schema-status {
    margin-top: 1;
    text-align: center;
}
#schema-detail {
    height: 8;
    margin-top: 1;
    border: round $panel-darken-1;
    padding: 1;
}

/* ─── Web Preview ────────────────────────────────────────────────────── */
#web-preview-top {
    height: 3;
    align: left middle;
    padding: 0 1;
}
#web-preview-meta {
    width: 1fr;
}
#web-preview-actions {
    height: 3;
    align: left middle;
    padding: 0 1;
}
#web-preview-actions Button {
    margin-right: 1;
}
#web-preview-loading {
    height: 1;
}
#web-preview-scroll {
    height: 1fr;
    padding: 1 2;
}
#web-preview-content {
    padding: 1 0 2 0;
}

/* ─── Text Prompt ────────────────────────────────────────────────────── */
#prompt-modal {
    width: 64;
    height: auto;
    border: tall $accent;
    background: $panel;
    padding: 1 2;
}
#prompt-title {
    text-style: bold;
    text-align: center;
    margin-bottom: 1;
}
#prompt-buttons {
    height: 3;
    align: center middle;
    margin-top: 1;
}
#prompt-buttons Button {
    margin: 0 1;
}

/* ─── Reader Settings ────────────────────────────────────────────────── */
#reader-settings-modal {
    width: 80;
    height: auto;
    max-height: 90%;
    border: tall $success;
    background: $panel;
    padding: 1 2;
}
#reader-settings-title {
    text-style: bold;
    text-align: center;
    margin-bottom: 1;
    color: $text;
}
.settings-section {
    margin-top: 1;
    margin-bottom: 1;
    text-style: bold;
    color: $accent;
}
#reader-theme-buttons {
    height: 3;
    align: center middle;
}
.theme-btn {
    margin-right: 1;
    min-width: 10;
}
#reader-style-buttons {
    height: 3;
    align: center middle;
}
#reader-style-buttons Button {
    margin-right: 1;
}
#reader-stats-info {
    margin: 1 0;
    padding: 1;
    border: round $panel-darken-1;
}
#reader-settings-buttons {
    height: 3;
    align: center middle;
    margin-top: 1;
}
#reader-settings-buttons Button {
    margin: 0 1;
}
#reader-settings-status {
    margin-top: 1;
    text-align: center;
}

/* ─── Bookshelf ──────────────────────────────────────────────────────── */
#shelf-actions {
    height: 3;
    padding: 0 1;
    align: left middle;
}
#shelf-actions Button {
    margin-right: 1;
}
#shelf-source-label {
    padding: 0 1;
    height: 2;
}
#shelf-filter-bar {
    height: 3;
    padding: 0 1;
    align: left middle;
}
#shelf-filter {
    width: 1fr;
}
.shelf-sort-btn {
    margin-left: 1;
    min-width: 14;
}
#shelf-count {
    margin-left: 1;
    min-width: 8;
}
#shelf-table {
    height: 1fr;
    border: tall $primary-darken-2;
}
#shelf-stats {
    height: 1;
    padding: 0 1;
    text-align: center;
}

/* ─── Search ─────────────────────────────────────────────────────────── */
#search-bar {
    height: 3;
    padding: 0 1;
    align: left middle;
}
#search-bar Input {
    width: 1fr;
}
#search-bar Button {
    margin-left: 1;
}
.icon-btn {
    min-width: 4;
    max-width: 5;
}
#source-label {
    padding: 0 1;
    height: 1;
}
#results-table {
    height: 1fr;
    border: tall $primary-darken-2;
}
#search-loading {
    height: 1;
}

/* ─── Book Info ──────────────────────────────────────────────────────── */
#info-scroll {
    height: 1fr;
    padding: 0 2;
}
#info-content {
    padding: 1 0;
}
#info-loading {
    height: 1;
}
#info-btns {
    height: 3;
    align: center middle;
    padding: 0 2;
}
#info-btns Button {
    margin: 0 1;
}

/* ─── Chapter List ───────────────────────────────────────────────────── */
#ch-book-info {
    height: 2;
    padding: 0 1;
}
#chapters-top {
    height: 3;
    padding: 0 1;
    align: left middle;
}
#chapters-top Input {
    width: 1fr;
}
#chapters-top Button {
    margin-left: 1;
}
#chapter-count {
    margin-left: 1;
}
#ch-table {
    height: 1fr;
    border: tall $primary-darken-2;
}
#ch-loading {
    height: 1;
    align: left middle;
}
.chapter-loading-row > ProgressBar {
    width: 1fr;
}
.chapter-loading-row > Label {
    width: auto;
    padding: 0 1;
    color: $text-muted;
}

/* ─── Discover ───────────────────────────────────────────────────────── */
#discover-label {
    padding: 0 1;
    height: 1;
    width: 1fr;
}
#discover-top {
    height: 3;
    align: center middle;
    padding: 0 1;
}
#discover-top Button {
    margin-left: 1;
}
#discover-filter-bar {
    height: 3;
    padding: 0 1;
    align: left middle;
}
#discover-filter-bar Input {
    width: 1fr;
}
#discover-count {
    margin-left: 1;
}
#discover-table {
    height: 1fr;
    border: tall $primary-darken-2;
}
#discover-loading {
    height: 1;
}

/* ─── Explore Results ────────────────────────────────────────────────── */
#explore-top {
    height: 3;
    align: center middle;
    padding: 0 2;
}
#explore-top Button {
    margin: 0 1;
}
#explore-page-label {
    width: 1fr;
    text-align: center;
}
#explore-table {
    height: 1fr;
    border: tall $primary-darken-2;
}
#explore-loading {
    height: 1;
}

/* ─── Reader ─────────────────────────────────────────────────────────── */
#reader-scroll {
    height: 1fr;
    padding: 1 3;
}
#reader-text {
    padding: 1 0 2 0;
}
#reader-loading {
    height: 1;
}
#reader-nav {
    height: 3;
    align: center middle;
    padding: 0 2;
}
#reader-nav Button {
    margin: 0 1;
}
#reader-nav .icon-btn {
    min-width: 4;
}
#nav-label {
    min-width: 30;
    text-align: center;
}
#reader-progress-bar {
    height: 1;
    padding: 0 2;
    align: center middle;
}
#reader-progress-label {
    text-align: center;
    width: 1fr;
}

/* ─── BookScreen two-column layout ──────────────────────────────────── */
BookScreen #book-screen-body {
    height: 1fr;
}
BookScreen #book-info-col {
    width: 2fr;
    height: 100%;
    border-right: solid $panel-lighten-1;
    padding-right: 1;
}
BookScreen #book-chapter-col {
    width: 3fr;
    height: 100%;
    padding-left: 1;
}
BookScreen #info-actions {
    height: 3;
    padding: 0 1;
}
BookScreen #chapters-top {
    height: 3;
    padding: 0 1;
}
BookScreen #info-scroll {
    height: 1fr;
}
""" + _build_theme_css()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════════════════════

class LegadoApp(App):
    """Legado TUI – comprehensive book source browser and reader."""

    TITLE = "Legado 阅读器"
    CSS = APP_CSS

    BINDINGS = [
        Binding("q",      "quit",  "退出"),
        Binding("ctrl+c", "quit",  "退出", show=False),
    ]

    def __init__(self, source: Optional[BookSource] = None) -> None:
        super().__init__()
        self.reader_state = ReaderState()
        self.source: Optional[BookSource] = source or self.reader_state.get_current_source()

    def info(self, message: str) -> None:
        self.notify(message, severity="information")

    def warn(self, message: str) -> None:
        self.notify(message, severity="warning")

    def error(self, message: str) -> None:
        self.notify(message, severity="error")

    def alert(self, title: str, message: str) -> None:
        self.push_screen(AlertDialogScreen(title=title, message=message))

    def confirm(self, title: str, message: str, callback) -> None:
        self.push_screen(
            AlertDialogScreen(
                title=title,
                message=message,
                confirm_label="确定",
                cancel_label="取消",
            ),
            callback,
        )

    def open_source_ui(self, source: Optional[BookSource]) -> bool:
        if not source:
            self.warn("请先加载书源。")
            return False
        if not (source.loginUi or source.loginUrl):
            self.warn("当前书源没有可用的认证/功能表单。")
            return False
        self.push_screen(SourceUiScreen(source=source))
        return True

    def open_discover(self, source: Optional[BookSource]) -> bool:
        if not source:
            self.warn("请先加载书源。")
            return False
        if not source.exploreUrl:
            self.warn("当前书源没有发现分类。")
            return False
        self.push_screen(ExploreKindsScreen(source=source))
        return True

    def on_mount(self) -> None:
        self.push_screen(BookshelfScreen())
        if self.source:
            self.set_source(self.source, persist=True, notify=True)

    def set_source(
        self,
        source: Optional[BookSource],
        *,
        persist: bool = True,
        notify: bool = False,
    ) -> None:
        self.source = source
        if source is None:
            if persist:
                self.reader_state.clear_current_source()
        else:
            if persist:
                self.reader_state.set_current_source(source)
        for screen in self.screen_stack:
            if isinstance(screen, SearchScreen):
                screen.source = source
                if screen.is_mounted:
                    screen._update_source_label()
            elif isinstance(screen, BookshelfScreen):
                if screen.is_mounted:
                    screen._update_source_label()
        if notify:
            if source is None:
                self.info("已清除当前书源。")
            else:
                self.info(f"✓ 已加载书源：{source.bookSourceName}")

    def open_bookshelf(self) -> None:
        while len(self.screen_stack) > 1:
            self.pop_screen()

    def open_search(self) -> None:
        if isinstance(self.screen, SearchScreen):
            return
        self.open_bookshelf()
        self.push_screen(SearchScreen())

    def open_reader_settings(self) -> None:
        self.push_screen(ReaderSettingsScreen())

    def open_source_loader(self) -> None:
        self.push_screen(SourceLoaderScreen(), self._on_source_loaded)

    def _on_source_loaded(self, src: Optional[BookSource]) -> None:
        if src is not None:
            self.set_source(src, persist=True, notify=True)

    def refresh_reader_views(self) -> None:
        for screen in self.screen_stack:
            if hasattr(screen, "apply_reader_settings"):
                try:
                    screen.apply_reader_settings()
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog="legado-tui",
        description="Legado TUI — 交互式书源浏览与阅读器",
    )
    parser.add_argument(
        "source", nargs="?", default=None,
        help="可选：启动时预加载的书源 JSON 路径",
    )
    args = parser.parse_args()

    src: Optional[BookSource] = None
    if args.source:
        raw = Path(args.source).expanduser().read_text(encoding="utf-8")
        sources = parse_book_sources(raw)
        if sources:
            src = sources[0]

    LegadoApp(source=src).run()


if __name__ == "__main__":
    main()
