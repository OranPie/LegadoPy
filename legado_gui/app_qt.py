"""
LegadoPy Qt6 Desktop Reader (PySide6).

Sidebar + 3-Stage layout:
  Sidebar  – Source info & Bookshelf
  Stage 0  – Discovery (Search + Explore)
  Stage 1  – Book (Info card + Chapter list)
  Stage 2  – Reading (QTextBrowser)
"""
from __future__ import annotations

import json
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTextBrowser,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from legado_engine import Book, BookChapter, ExploreKind, SearchBook
from legado_engine.auth.login import SourceUiActionResult, UiRow

from .controller import ReaderController
from .workers import Worker, submit


# ---------------------------------------------------------------------------
# Theme stylesheets
# ---------------------------------------------------------------------------

_DARK_QSS = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "SF Pro Display", "Helvetica Neue", sans-serif;
    font-size: 13px;
}
QSplitter::handle { background: #313244; width: 3px; height: 3px; }
QTabWidget::pane { border: 1px solid #313244; border-radius: 4px; }
QTabBar::tab {
    background: #181825; color: #a6adc8;
    padding: 6px 14px; margin-right: 2px;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
}
QTabBar::tab:selected { background: #1e1e2e; color: #89b4fa; border-bottom: 2px solid #89b4fa; }
QTabBar::tab:hover:!selected { background: #252538; }
QListWidget, QTreeWidget, QTextEdit, QTextBrowser {
    background-color: #181825; color: #cdd6f4;
    border: 1px solid #313244; border-radius: 4px;
    selection-background-color: #89b4fa; selection-color: #1e1e2e;
}
QListWidget::item:hover { background: #252538; }
QTreeWidget::item:hover { background: #252538; }
QLineEdit, QSpinBox, QComboBox {
    background: #181825; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 4px;
    padding: 4px 8px; min-height: 26px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #89b4fa; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background: #181825; color: #cdd6f4; selection-background-color: #89b4fa; }
QPushButton {
    background: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 4px;
    padding: 5px 14px; min-height: 26px;
}
QPushButton:hover { background: #45475a; border-color: #89b4fa; }
QPushButton:pressed { background: #89b4fa; color: #1e1e2e; }
QPushButton:disabled { background: #1e1e2e; color: #585b70; border-color: #313244; }
QToolBar { background: #181825; border-bottom: 1px solid #313244; spacing: 6px; padding: 4px; }
QStatusBar { background: #181825; color: #a6adc8; border-top: 1px solid #313244; }
QScrollBar:vertical {
    background: #181825; width: 10px; margin: 0;
}
QScrollBar::handle:vertical { background: #45475a; border-radius: 5px; min-height: 20px; }
QScrollBar::handle:vertical:hover { background: #585b70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #181825; height: 10px; margin: 0;
}
QScrollBar::handle:horizontal { background: #45475a; border-radius: 5px; min-width: 20px; }
QScrollBar::handle:horizontal:hover { background: #585b70; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QLabel { color: #cdd6f4; }
QGroupBox {
    color: #89b4fa; border: 1px solid #313244;
    border-radius: 4px; margin-top: 8px; padding-top: 4px;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
"""

_LIGHT_QSS = """
QMainWindow, QWidget {
    background-color: #eff1f5;
    color: #4c4f69;
    font-family: "Segoe UI", "SF Pro Display", "Helvetica Neue", sans-serif;
    font-size: 13px;
}
QSplitter::handle { background: #bcc0cc; width: 3px; height: 3px; }
QTabWidget::pane { border: 1px solid #bcc0cc; border-radius: 4px; }
QTabBar::tab {
    background: #e6e9ef; color: #6c6f85;
    padding: 6px 14px; margin-right: 2px;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
}
QTabBar::tab:selected { background: #eff1f5; color: #1e66f5; border-bottom: 2px solid #1e66f5; }
QTabBar::tab:hover:!selected { background: #dce0e8; }
QListWidget, QTreeWidget, QTextEdit, QTextBrowser {
    background-color: #ffffff; color: #4c4f69;
    border: 1px solid #bcc0cc; border-radius: 4px;
    selection-background-color: #1e66f5; selection-color: #ffffff;
}
QLineEdit, QSpinBox, QComboBox {
    background: #ffffff; color: #4c4f69;
    border: 1px solid #9ca0b0; border-radius: 4px;
    padding: 4px 8px; min-height: 26px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #1e66f5; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background: #ffffff; color: #4c4f69; }
QPushButton {
    background: #e6e9ef; color: #4c4f69;
    border: 1px solid #9ca0b0; border-radius: 4px;
    padding: 5px 14px; min-height: 26px;
}
QPushButton:hover { background: #dce0e8; border-color: #1e66f5; }
QPushButton:pressed { background: #1e66f5; color: #ffffff; }
QPushButton:disabled { background: #eff1f5; color: #9ca0b0; }
QToolBar { background: #e6e9ef; border-bottom: 1px solid #bcc0cc; spacing: 6px; padding: 4px; }
QStatusBar { background: #e6e9ef; color: #6c6f85; border-top: 1px solid #bcc0cc; }
QScrollBar:vertical { background: #e6e9ef; width: 10px; }
QScrollBar::handle:vertical { background: #9ca0b0; border-radius: 5px; min-height: 20px; }
QScrollBar::handle:vertical:hover { background: #7c7f93; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #e6e9ef; height: 10px; }
QScrollBar::handle:horizontal { background: #9ca0b0; border-radius: 5px; min-width: 20px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QGroupBox { color: #1e66f5; border: 1px solid #bcc0cc; border-radius: 4px; margin-top: 8px; padding-top: 4px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
"""

_READER_CSS_DARK = """
body {
    background-color: #1e1e2e; color: #cdd6f4;
    font-family: "Georgia", "Noto Serif", serif;
    font-size: 15px; line-height: 1.8;
    margin: 24px 48px; max-width: 800px;
}
p { margin: 0.6em 0; }
"""

_READER_CSS_LIGHT = """
body {
    background-color: #fafafa; color: #3c3c3c;
    font-family: "Georgia", "Noto Serif", serif;
    font-size: 15px; line-height: 1.8;
    margin: 24px 48px; max-width: 800px;
}
p { margin: 0.6em 0; }
"""


def _text_to_html(text: str, css: str) -> str:
    """Wrap plain-text chapter content in minimal HTML with the given CSS."""
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n\n", "</p><p>")
        .replace("\n", "<br>")
    )
    return (
        f"<html><head><style>{css}</style></head>"
        f"<body><p>{escaped}</p></body></html>"
    )


# ---------------------------------------------------------------------------
# Auth panel widget
# ---------------------------------------------------------------------------

class AuthPanel(QWidget):
    status_changed = Signal(str)

    def __init__(self, parent: QWidget, controller: ReaderController) -> None:
        super().__init__(parent)
        self._controller = controller
        self._field_widgets: Dict[str, QLineEdit] = {}
        self._action_rows: List[UiRow] = []
        self._last_open_url: Optional[str] = None
        self._active_workers: set = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        self._source_label = QLabel("No source loaded")
        self._source_label.setStyleSheet("font-weight: bold;")
        root.addWidget(self._source_label)

        # Toolbar
        tb = QHBoxLayout()
        self._btn_submit = QPushButton("Submit")
        self._btn_submit.clicked.connect(self._submit)
        self._btn_run = QPushButton("Run Action")
        self._btn_run.clicked.connect(self._run_action)
        self._btn_show_header = QPushButton("Show Header")
        self._btn_show_header.clicked.connect(self._show_header)
        self._btn_clear_header = QPushButton("Clear Header")
        self._btn_clear_header.clicked.connect(self._clear_header)
        self._btn_open_url = QPushButton("Open URL")
        self._btn_open_url.setEnabled(False)
        self._btn_open_url.clicked.connect(self._open_url)
        for btn in (self._btn_submit, self._btn_run, self._btn_show_header,
                    self._btn_clear_header, self._btn_open_url):
            tb.addWidget(btn)
        tb.addStretch()
        root.addLayout(tb)

        # Body splitter
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        self._form_group = QGroupBox("Form")
        self._form_layout = QFormLayout()
        self._form_group.setLayout(self._form_layout)
        lv.addWidget(self._form_group)

        act_group = QGroupBox("Actions")
        ag_layout = QVBoxLayout(act_group)
        self._action_list = QListWidget()
        self._action_list.itemDoubleClicked.connect(lambda _: self._run_action())
        ag_layout.addWidget(self._action_list)
        lv.addWidget(act_group, 1)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)

        splitter.addWidget(left)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

    def load_source(self) -> None:
        source = self._controller.session.source
        if source is None:
            self._source_label.setText("No source loaded")
            return
        rows = self._controller.get_source_auth_rows()
        self._action_rows = [r for r in rows if r.type == "button"]

        # Rebuild form
        while self._form_layout.rowCount():
            self._form_layout.removeRow(0)
        self._field_widgets.clear()

        for row in rows:
            if row.type not in ("text", "password"):
                continue
            edit = QLineEdit()
            if row.type == "password":
                edit.setEchoMode(QLineEdit.Password)
            self._field_widgets[row.name] = edit
            self._form_layout.addRow(row.name or "Field", edit)

        if not self._field_widgets:
            self._form_layout.addRow(QLabel("No editable login fields for this source."))

        # Load saved values
        for name, value in self._controller.get_source_auth_form_data().items():
            if name in self._field_widgets:
                self._field_widgets[name].setText(value)

        self._action_list.clear()
        for row in self._action_rows:
            self._action_list.addItem(row.name or "Action")

        self._source_label.setText(f"{source.bookSourceName}  [{source.bookSourceUrl}]")
        self._detail.setPlainText(self._controller.describe_source_auth())

    def _form_data(self) -> Dict[str, str]:
        return {name: w.text() for name, w in self._field_widgets.items()}

    @Slot()
    def _submit(self) -> None:
        self.status_changed.emit("Submitting source authentication…")
        worker = Worker(lambda: self._controller.submit_source_auth(self._form_data()))
        self._active_workers.add(worker)
        worker.signals.result.connect(self._apply_result)
        worker.signals.result.connect(lambda _: self._active_workers.discard(worker))
        worker.signals.error.connect(lambda msg, _: self.status_changed.emit(f"Auth failed: {msg}"))
        worker.signals.error.connect(lambda *_: self._active_workers.discard(worker))
        QThreadPool.globalInstance().start(worker)

    @Slot()
    def _run_action(self) -> None:
        if not self._action_rows:
            return
        sel = self._action_list.currentRow()
        if sel < 0:
            return
        row = self._action_rows[sel]
        self.status_changed.emit(f"Running action: {row.name or 'action'}…")
        worker = Worker(
            lambda: self._controller.run_source_auth_action(row.action or "", self._form_data())
        )
        self._active_workers.add(worker)
        worker.signals.result.connect(self._apply_result)
        worker.signals.result.connect(lambda _: self._active_workers.discard(worker))
        worker.signals.error.connect(lambda msg, _: self.status_changed.emit(f"Action failed: {msg}"))
        worker.signals.error.connect(lambda *_: self._active_workers.discard(worker))
        QThreadPool.globalInstance().start(worker)

    @Slot(object)
    def _apply_result(self, outcome: SourceUiActionResult) -> None:
        self._last_open_url = outcome.open_url or None
        self._btn_open_url.setEnabled(bool(self._last_open_url))
        detail = outcome.detail_text() or self._controller.describe_source_auth()
        self._detail.setPlainText(detail)
        self.status_changed.emit(outcome.message or "Auth completed.")
        for name, value in self._controller.get_source_auth_form_data().items():
            if name in self._field_widgets:
                self._field_widgets[name].setText(value)

    @Slot()
    def _show_header(self) -> None:
        header = self._controller.get_source_login_header()
        self._detail.setPlainText(header or "No saved login header.")
        self.status_changed.emit("Showing saved login header.")

    @Slot()
    def _clear_header(self) -> None:
        reply = QMessageBox.question(
            self, "Clear Header",
            "Remove the saved login header for this source?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._controller.clear_source_login_header()
        self.load_source()
        self.status_changed.emit("Saved login header cleared.")

    @Slot()
    def _open_url(self) -> None:
        if self._last_open_url:
            webbrowser.open(self._last_open_url)


# ---------------------------------------------------------------------------
# Sidebar widget (240 px fixed, Source + Bookshelf groups)
# ---------------------------------------------------------------------------

class SidebarWidget(QWidget):
    load_source_requested = Signal()
    reload_source_requested = Signal()
    auth_requested = Signal()
    book_selected = Signal(str)       # bookshelf key
    resume_requested = Signal(str)    # bookshelf key
    remove_requested = Signal(str)    # bookshelf key

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(240)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Source group ──────────────────────────────────────────────
        source_group = QGroupBox("Source")
        sg = QVBoxLayout(source_group)
        sg.setSpacing(4)

        self._source_name = QLabel("No source loaded")
        self._source_name.setStyleSheet("font-weight: bold;")
        self._source_name.setWordWrap(True)
        sg.addWidget(self._source_name)

        self._source_url = QLabel("")
        self._source_url.setWordWrap(True)
        self._source_url.setMaximumHeight(34)
        self._source_url.setStyleSheet("font-size: 11px;")
        sg.addWidget(self._source_url)

        self._source_caps = QLabel("")
        self._source_caps.setStyleSheet("font-size: 11px;")
        sg.addWidget(self._source_caps)

        self._btn_load = QPushButton("📂 Load Source")
        self._btn_load.clicked.connect(self.load_source_requested)
        sg.addWidget(self._btn_load)

        self._btn_reload = QPushButton("🔄 Reload")
        self._btn_reload.setEnabled(False)
        self._btn_reload.clicked.connect(self.reload_source_requested)
        sg.addWidget(self._btn_reload)

        self._btn_auth = QPushButton("🔐 Auth")
        self._btn_auth.setVisible(False)
        self._btn_auth.clicked.connect(self.auth_requested)
        sg.addWidget(self._btn_auth)

        root.addWidget(source_group)

        # ── Bookshelf group ───────────────────────────────────────────
        shelf_group = QGroupBox("Bookshelf")
        sh = QVBoxLayout(shelf_group)
        sh.setSpacing(4)

        self._shelf_list = QListWidget()
        self._shelf_list.itemDoubleClicked.connect(self._on_shelf_double_clicked)
        sh.addWidget(self._shelf_list, 1)

        shelf_btns = QHBoxLayout()
        self._btn_resume = QPushButton("▶ Resume")
        self._btn_resume.clicked.connect(self._on_resume)
        shelf_btns.addWidget(self._btn_resume, 1)
        self._btn_remove = QPushButton("🗑")
        self._btn_remove.setFixedWidth(36)
        self._btn_remove.clicked.connect(self._on_remove)
        shelf_btns.addWidget(self._btn_remove)
        sh.addLayout(shelf_btns)

        root.addWidget(shelf_group, 1)

    def update_source(self, source: Any) -> None:
        self._source_name.setText(source.bookSourceName or "(unnamed)")
        self._source_url.setText(source.bookSourceUrl or "")
        caps = []
        if getattr(source, "searchUrl", None):
            caps.append("🔍 Search")
        if getattr(source, "exploreUrl", None):
            caps.append("🧭 Explore")
        self._source_caps.setText("  ".join(caps) if caps else "")
        self._btn_reload.setEnabled(True)
        has_auth = bool(
            getattr(source, "loginUi", None) or getattr(source, "loginUrl", None)
        )
        self._btn_auth.setVisible(has_auth)

    def clear_source(self) -> None:
        self._source_name.setText("No source loaded")
        self._source_url.setText("")
        self._source_caps.setText("")
        self._btn_reload.setEnabled(False)
        self._btn_auth.setVisible(False)

    def refresh_bookshelf(self, entries: List[Dict[str, Any]]) -> None:
        self._shelf_list.clear()
        for entry in entries:
            book = entry.get("book") or {}
            progress = entry.get("progress") or {}
            name = book.get("name", "(untitled)")
            ch_idx = progress.get("chapter_index")
            total_ch = progress.get("total_chapters")
            ch_title = progress.get("chapter_title") or "Unread"
            if ch_idx is not None and total_ch:
                pct = int(int(ch_idx) * 100 / max(1, int(total_ch)))
                line2 = f"{pct}% · {ch_title}"
            else:
                line2 = ch_title
            item = QListWidgetItem(f"{name}\n{line2}")
            item.setData(Qt.UserRole, entry.get("key"))
            self._shelf_list.addItem(item)

    def _get_selected_key(self) -> Optional[str]:
        item = self._shelf_list.currentItem()
        return str(item.data(Qt.UserRole)) if item else None

    @Slot(QListWidgetItem)
    def _on_shelf_double_clicked(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.UserRole)
        if key:
            self.book_selected.emit(str(key))

    @Slot()
    def _on_resume(self) -> None:
        key = self._get_selected_key()
        if key:
            self.resume_requested.emit(key)

    @Slot()
    def _on_remove(self) -> None:
        key = self._get_selected_key()
        if key:
            self.remove_requested.emit(key)


# ---------------------------------------------------------------------------
# Discovery page — Stage 0
# ---------------------------------------------------------------------------

class DiscoveryPage(QWidget):
    book_selected = Signal(object)            # emits SearchBook
    explore_category_requested = Signal(object)  # emits ExploreKind

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Search / Explore row ──────────────────────────────────────
        search_row = QHBoxLayout()

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search books…")
        self._search_edit.returnPressed.connect(lambda: self._btn_search.click())
        search_row.addWidget(self._search_edit, 1)

        self._page_spin = QSpinBox()
        self._page_spin.setRange(1, 9999)
        self._page_spin.setFixedWidth(64)
        search_row.addWidget(self._page_spin)

        self._btn_search = QPushButton("🔍 Search")
        search_row.addWidget(self._btn_search)

        self._btn_explore = QPushButton("🧭 Explore")
        search_row.addWidget(self._btn_explore)

        root.addLayout(search_row)

        # ── Sub-stack ─────────────────────────────────────────────────
        self._sub_stack = QStackedWidget()
        root.addWidget(self._sub_stack, 1)

        # Sub-page 0: Search results
        search_page = QWidget()
        sp_layout = QVBoxLayout(search_page)
        sp_layout.setContentsMargins(0, 0, 0, 0)
        self._results_list = QListWidget()
        self._results_list.itemDoubleClicked.connect(self._on_result_activated)
        sp_layout.addWidget(self._results_list)
        self._sub_stack.addWidget(search_page)

        # Sub-page 1: Explore (categories + results)
        explore_page = QWidget()
        ep_layout = QVBoxLayout(explore_page)
        ep_layout.setContentsMargins(0, 0, 0, 0)
        explore_splitter = QSplitter(Qt.Vertical)
        self._category_list = QListWidget()
        self._category_list.itemDoubleClicked.connect(self._on_category_activated)
        self._explore_results = QListWidget()
        self._explore_results.itemDoubleClicked.connect(self._on_explore_result_activated)
        explore_splitter.addWidget(self._category_list)
        explore_splitter.addWidget(self._explore_results)
        ep_layout.addWidget(explore_splitter)
        self._sub_stack.addWidget(explore_page)

        # Internal data for index lookups
        self._search_results: List[SearchBook] = []
        self._explore_kinds: List[ExploreKind] = []
        self._explore_items: List[SearchBook] = []

    def show_search_results(self, items: List[SearchBook]) -> None:
        self._search_results = items
        self._results_list.clear()
        for item in items:
            self._results_list.addItem(
                f"{item.name or '(untitled)'}  —  {item.author or 'Unknown'}"
            )
        self._sub_stack.setCurrentIndex(0)

    def show_categories(self, kinds: List[ExploreKind]) -> None:
        self._explore_kinds = kinds
        self._category_list.clear()
        for k in kinds:
            label = k.title or "(untitled)"
            if not k.url:
                label += "  [no url]"
            self._category_list.addItem(label)
        self._explore_results.clear()
        self._sub_stack.setCurrentIndex(1)

    def show_explore_results(self, items: List[SearchBook]) -> None:
        self._explore_items = items
        self._explore_results.clear()
        for item in items:
            self._explore_results.addItem(
                f"{item.name or '(untitled)'}  —  {item.author or 'Unknown'}"
            )

    @Slot(QListWidgetItem)
    def _on_result_activated(self, _item: QListWidgetItem) -> None:
        row = self._results_list.currentRow()
        if 0 <= row < len(self._search_results):
            self.book_selected.emit(self._search_results[row])

    @Slot(QListWidgetItem)
    def _on_category_activated(self, _item: QListWidgetItem) -> None:
        row = self._category_list.currentRow()
        if 0 <= row < len(self._explore_kinds):
            self.explore_category_requested.emit(self._explore_kinds[row])

    @Slot(QListWidgetItem)
    def _on_explore_result_activated(self, _item: QListWidgetItem) -> None:
        row = self._explore_results.currentRow()
        if 0 <= row < len(self._explore_items):
            self.book_selected.emit(self._explore_items[row])


# ---------------------------------------------------------------------------
# Book page — Stage 1
# ---------------------------------------------------------------------------

class BookPage(QWidget):
    chapter_selected = Signal(int)
    resume_requested = Signal()
    refresh_toc_requested = Signal()
    back_requested = Signal()
    add_to_shelf_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Info card (fixed height ~130 px) ─────────────────────────
        self._info_card = QFrame()
        self._info_card.setFrameShape(QFrame.StyledPanel)
        self._info_card.setFixedHeight(130)
        card = QVBoxLayout(self._info_card)
        card.setContentsMargins(12, 8, 12, 8)
        card.setSpacing(4)

        title_row = QHBoxLayout()
        self._title_label = QLabel("—")
        self._title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        title_row.addWidget(self._title_label, 1)
        self._author_label = QLabel("—")
        self._author_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        title_row.addWidget(self._author_label)
        card.addLayout(title_row)

        self._meta_label = QLabel("—")
        self._meta_label.setStyleSheet("font-size: 11px;")
        card.addWidget(self._meta_label)

        self._intro_label = QLabel("—")
        self._intro_label.setWordWrap(True)
        self._intro_label.setMaximumHeight(44)
        card.addWidget(self._intro_label, 1)

        root.addWidget(self._info_card)

        # ── Action row ────────────────────────────────────────────────
        action_row = QHBoxLayout()

        self._btn_resume_ch = QPushButton("▶ Resume")
        self._btn_resume_ch.setEnabled(False)
        self._btn_resume_ch.clicked.connect(self.resume_requested)
        action_row.addWidget(self._btn_resume_ch)

        self._btn_shelf = QPushButton("⭐ Bookshelf")
        self._btn_shelf.clicked.connect(self.add_to_shelf_requested)
        action_row.addWidget(self._btn_shelf)

        self._btn_refresh_toc = QPushButton("↺ Refresh TOC")
        self._btn_refresh_toc.clicked.connect(self.refresh_toc_requested)
        action_row.addWidget(self._btn_refresh_toc)

        self._btn_back = QPushButton("← Back")
        self._btn_back.clicked.connect(self.back_requested)
        action_row.addWidget(self._btn_back)

        action_row.addStretch()
        root.addLayout(action_row)

        # ── Chapter list ──────────────────────────────────────────────
        self._chapter_list = QListWidget()
        self._chapter_list.itemDoubleClicked.connect(self._on_chapter_activated)
        root.addWidget(self._chapter_list, 1)

    def set_book(self, book: Book, progress: Optional[Dict[str, Any]]) -> None:
        self._title_label.setText(book.name or "—")
        self._author_label.setText(book.author or "—")

        meta_parts = []
        if book.kind:
            meta_parts.append(book.kind)
        if book.wordCount:
            meta_parts.append(str(book.wordCount))
        if book.latestChapterTitle:
            meta_parts.append(f"Latest: {book.latestChapterTitle}")
        self._meta_label.setText(" · ".join(meta_parts) if meta_parts else "—")

        intro = book.intro or ""
        self._intro_label.setText((intro[:117] + "…") if len(intro) > 120 else (intro or "—"))

        has_progress = bool(progress and progress.get("chapter_index") is not None)
        self._btn_resume_ch.setEnabled(has_progress)

    def set_chapters(self, chapters: List[BookChapter]) -> None:
        self._chapter_list.clear()
        for ch in chapters:
            self._chapter_list.addItem(f"{ch.index + 1:>4}. {ch.title}")

    def set_chapters_loading(self) -> None:
        self._chapter_list.clear()
        self._chapter_list.addItem("Loading chapters…")
        self._btn_refresh_toc.setEnabled(False)

    def highlight_chapter(self, index: int) -> None:
        if 0 <= index < self._chapter_list.count():
            self._chapter_list.setCurrentRow(index)

    @Slot(QListWidgetItem)
    def _on_chapter_activated(self, _item: QListWidgetItem) -> None:
        row = self._chapter_list.currentRow()
        if row >= 0:
            self.chapter_selected.emit(row)


# ---------------------------------------------------------------------------
# Reader page — Stage 2
# ---------------------------------------------------------------------------

class ReaderPage(QWidget):
    prev_requested = Signal()
    next_requested = Signal()
    toc_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Nav bar ───────────────────────────────────────────────────
        nav_bar = QHBoxLayout()
        nav_bar.setContentsMargins(8, 4, 8, 4)

        self._btn_prev = QPushButton("← Prev")
        self._btn_prev.clicked.connect(self.prev_requested)
        nav_bar.addWidget(self._btn_prev)

        self._btn_toc = QPushButton("≡ TOC")
        self._btn_toc.clicked.connect(self.toc_requested)
        nav_bar.addWidget(self._btn_toc)

        self._chapter_label = QLabel()
        self._chapter_label.setAlignment(Qt.AlignCenter)
        self._chapter_label.setStyleSheet("font-weight: bold;")
        nav_bar.addWidget(self._chapter_label, 1)

        self._btn_next = QPushButton("Next →")
        self._btn_next.clicked.connect(self.next_requested)
        nav_bar.addWidget(self._btn_next)

        root.addLayout(nav_bar)

        sep_top = QFrame()
        sep_top.setFrameShape(QFrame.HLine)
        root.addWidget(sep_top)

        # ── Reader ────────────────────────────────────────────────────
        self._reader = QTextBrowser()
        self._reader.setOpenExternalLinks(True)
        root.addWidget(self._reader, 1)

        sep_bot = QFrame()
        sep_bot.setFrameShape(QFrame.HLine)
        root.addWidget(sep_bot)

        # ── Progress bar ──────────────────────────────────────────────
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(8, 4, 8, 4)
        self._progress_label = QLabel("📖 —")
        progress_row.addWidget(self._progress_label)
        progress_row.addStretch()
        root.addLayout(progress_row)

    def set_content(
        self,
        html: str,
        chapter: BookChapter,
        total: int,
        book_name: str,
        progress_pct: int,
    ) -> None:
        self._reader.setHtml(html)
        self._chapter_label.setText(chapter.title or "")
        ch_num = chapter.index + 1
        self._progress_label.setText(
            f"📖 {book_name} · Ch {ch_num}/{total} · {progress_pct}%"
        )

    def reload_html(self, html: str) -> None:
        """Re-render HTML preserving scroll position (for theme/font refresh)."""
        ratio = self.get_scroll_ratio()
        self._reader.setHtml(html)
        QTimer.singleShot(50, lambda: self.restore_scroll(ratio))

    def restore_scroll(self, ratio: float) -> None:
        if ratio > 0:
            bar = self._reader.verticalScrollBar()
            bar.setValue(int(bar.maximum() * ratio))

    def get_scroll_ratio(self) -> float:
        bar = self._reader.verticalScrollBar()
        maximum = bar.maximum()
        return bar.value() / maximum if maximum > 0 else 0.0

    @property
    def scroll_bar(self):
        return self._reader.verticalScrollBar()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

_STAGE_LABELS = ["Discovery", "Discovery › Book", "Discovery › Book › Reading"]


class LegadoApp(QMainWindow):
    def __init__(self, controller: Optional[ReaderController] = None) -> None:
        super().__init__()
        self._controller = controller or ReaderController()
        self._dark_mode = True
        self._reader_font_size = 15
        self._reader_css: str = _READER_CSS_DARK
        self._last_chapter_text: str = ""
        # Keep strong Python references to in-flight Worker objects so their
        # _Signals QObject is not GC'd before the queued cross-thread signal
        # reaches the main thread (GC before delivery → segfault).
        self._active_workers: set = set()
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(800)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._save_scroll_position)

        self.setWindowTitle("LegadoPy Reader")
        self.resize(1400, 860)
        self._build_ui()
        self._apply_theme()
        self._restore_source()

        QThreadPool.globalInstance().setMaxThreadCount(8)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Single toolbar ───────────────────────────────────────────
        tb = QToolBar("Main", self)
        tb.setMovable(False)
        self.addToolBar(tb)

        self._breadcrumb = QLabel("Discovery")
        self._breadcrumb.setContentsMargins(4, 0, 8, 0)
        tb.addWidget(self._breadcrumb)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        self._btn_font_minus = QPushButton("−")
        self._btn_font_minus.setFixedWidth(28)
        self._btn_font_minus.clicked.connect(lambda: self._change_font_size(-1))
        tb.addWidget(self._btn_font_minus)

        self._font_label = QLabel(f"Aa {self._reader_font_size}")
        self._font_label.setFixedWidth(44)
        self._font_label.setAlignment(Qt.AlignCenter)
        tb.addWidget(self._font_label)

        self._btn_font_plus = QPushButton("+")
        self._btn_font_plus.setFixedWidth(28)
        self._btn_font_plus.clicked.connect(lambda: self._change_font_size(1))
        tb.addWidget(self._btn_font_plus)

        tb.addSeparator()

        self._btn_theme = QPushButton("🌙 Dark")
        self._btn_theme.setFixedWidth(90)
        self._btn_theme.clicked.connect(self._toggle_theme)
        tb.addWidget(self._btn_theme)

        # ── Central layout: sidebar + stage stack ────────────────────
        central = QWidget()
        central.setContentsMargins(0, 0, 0, 0)
        main_h = QHBoxLayout(central)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)
        self.setCentralWidget(central)

        self._sidebar = SidebarWidget()
        main_h.addWidget(self._sidebar)

        self._stage_stack = QStackedWidget()
        main_h.addWidget(self._stage_stack, 1)

        # Stage 0 — Discovery
        self._discovery = DiscoveryPage()
        self._stage_stack.addWidget(self._discovery)

        # Stage 1 — Book
        self._book_page = BookPage()
        self._stage_stack.addWidget(self._book_page)

        # Stage 2 — Reading
        self._reader_page = ReaderPage()
        self._stage_stack.addWidget(self._reader_page)

        # ── Status bar ───────────────────────────────────────────────
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Load a source file to begin.")

        # ── Wire up sidebar signals ───────────────────────────────────
        self._sidebar.load_source_requested.connect(self._open_source_dialog)
        self._sidebar.reload_source_requested.connect(self._reload_source)
        self._sidebar.auth_requested.connect(self._open_auth_dialog)
        self._sidebar.book_selected.connect(self._open_bookshelf_entry)
        self._sidebar.resume_requested.connect(self._resume_bookshelf_entry)
        self._sidebar.remove_requested.connect(self._remove_bookshelf_entry)

        # ── Wire up discovery signals ─────────────────────────────────
        self._discovery._btn_search.clicked.connect(self._trigger_search)
        self._discovery._btn_explore.clicked.connect(self._load_categories)
        self._discovery.book_selected.connect(self._open_search_result)
        self._discovery.explore_category_requested.connect(self._load_explore_category)

        # ── Wire up book page signals ─────────────────────────────────
        self._book_page.chapter_selected.connect(self._open_chapter)
        self._book_page.resume_requested.connect(self._resume_current_book)
        self._book_page.refresh_toc_requested.connect(self._refresh_toc)
        self._book_page.back_requested.connect(lambda: self._show_stage(0))
        self._book_page.add_to_shelf_requested.connect(self._add_to_shelf)

        # ── Wire up reader page signals ───────────────────────────────
        self._reader_page.prev_requested.connect(self._open_prev_chapter)
        self._reader_page.next_requested.connect(self._open_next_chapter)
        self._reader_page.toc_requested.connect(lambda: self._show_stage(1))
        self._reader_page.scroll_bar.valueChanged.connect(self._on_scroll)

        # ── Keyboard shortcuts ───────────────────────────────────────
        for key, fn in (
            (Qt.Key_Left, self._open_prev_chapter),
            (Qt.Key_Right, self._open_next_chapter),
        ):
            act = QAction(self)
            act.setShortcut(key)
            act.triggered.connect(fn)
            self.addAction(act)

    # ------------------------------------------------------------------
    # Stage navigation
    # ------------------------------------------------------------------

    def _show_stage(self, index: int) -> None:
        self._stage_stack.setCurrentIndex(index)
        self._breadcrumb.setText(_STAGE_LABELS[index])

    # ------------------------------------------------------------------
    # Theme & font
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        qss = _DARK_QSS if self._dark_mode else _LIGHT_QSS
        QApplication.instance().setStyleSheet(qss)
        self._btn_theme.setText("☀ Light" if self._dark_mode else "🌙 Dark")
        self._reader_css = _READER_CSS_DARK if self._dark_mode else _READER_CSS_LIGHT
        if self._last_chapter_text:
            self._reader_page.reload_html(
                _text_to_html(self._last_chapter_text, self._reader_css)
            )

    @Slot()
    def _toggle_theme(self) -> None:
        self._dark_mode = not self._dark_mode
        self._apply_theme()

    def _change_font_size(self, delta: int) -> None:
        self._reader_font_size = max(10, min(28, self._reader_font_size + delta))
        self._font_label.setText(f"Aa {self._reader_font_size}")
        size = self._reader_font_size
        global _READER_CSS_DARK, _READER_CSS_LIGHT
        _READER_CSS_DARK = (
            f"body {{ background-color: #1e1e2e; color: #cdd6f4;"
            f" font-family: 'Georgia', 'Noto Serif', serif;"
            f" font-size: {size}px; line-height: 1.8;"
            f" margin: 24px 48px; max-width: 800px; }}"
            f" p {{ margin: 0.6em 0; }}"
        )
        _READER_CSS_LIGHT = (
            f"body {{ background-color: #fafafa; color: #3c3c3c;"
            f" font-family: 'Georgia', 'Noto Serif', serif;"
            f" font-size: {size}px; line-height: 1.8;"
            f" margin: 24px 48px; max-width: 800px; }}"
            f" p {{ margin: 0.6em 0; }}"
        )
        self._reader_css = _READER_CSS_DARK if self._dark_mode else _READER_CSS_LIGHT
        if self._last_chapter_text:
            self._reader_page.reload_html(
                _text_to_html(self._last_chapter_text, self._reader_css)
            )

    # ------------------------------------------------------------------
    # Source management
    # ------------------------------------------------------------------

    def _restore_source(self) -> None:
        source = self._controller.state.get_current_source()
        if source is None:
            return
        self._controller.set_source(source)
        self._sidebar.update_source(source)
        self._sidebar.refresh_bookshelf(self._controller.list_bookshelf_entries())
        self._set_status("Restored previously used source.")

    @Slot()
    def _open_source_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Source JSON", "", "JSON files (*.json);;All files (*.*)"
        )
        if not path:
            return
        self._run_task(
            f"Loading {Path(path).name}…",
            lambda: self._controller.load_source(path),
            self._after_source_loaded,
        )

    @Slot()
    def _reload_source(self) -> None:
        if not self._controller.session.source_path:
            QMessageBox.information(self, "Reload", "No source file path recorded.")
            return
        self._run_task(
            "Reloading source…",
            self._controller.reload_source,
            self._after_source_loaded,
        )

    @Slot()
    def _open_auth_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Source Authentication")
        dlg.resize(680, 500)
        layout = QVBoxLayout(dlg)
        auth_panel = AuthPanel(dlg, self._controller)
        auth_panel.status_changed.connect(self._set_status)
        layout.addWidget(auth_panel, 1)
        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(dlg.reject)
        layout.addWidget(btn_box)
        auth_panel.load_source()
        dlg.exec()

    def _after_source_loaded(self, source: Any) -> None:
        self._sidebar.update_source(source)
        self._sidebar.refresh_bookshelf(self._controller.list_bookshelf_entries())
        self._last_chapter_text = ""
        self._set_status(f"Loaded: {source.bookSourceName}.")

    # ------------------------------------------------------------------
    # Discovery: search
    # ------------------------------------------------------------------

    @Slot()
    def _trigger_search(self) -> None:
        query = self._discovery._search_edit.text().strip()
        if not query:
            QMessageBox.information(self, "Search", "Enter a search query first.")
            return
        page = self._discovery._page_spin.value()
        self._run_task(
            f'Searching for "{query}"…',
            lambda: self._controller.search(query, page=page),
            self._after_search,
        )

    def _after_search(self, results: List[SearchBook]) -> None:
        self._discovery.show_search_results(results)
        self._set_status(f"{len(results)} result(s) found.")

    # ------------------------------------------------------------------
    # Discovery: explore
    # ------------------------------------------------------------------

    @Slot()
    def _load_categories(self) -> None:
        self._run_task(
            "Loading categories…",
            self._controller.load_explore_kinds,
            self._after_categories_loaded,
        )

    def _after_categories_loaded(self, kinds: List[ExploreKind]) -> None:
        self._discovery.show_categories(kinds)
        self._set_status(f"{len(kinds)} categories loaded.")

    @Slot(object)
    def _load_explore_category(self, kind: ExploreKind) -> None:
        page = self._discovery._page_spin.value()
        self._run_task(
            f'Loading "{kind.title or "(untitled)"}"…',
            lambda: self._controller.explore(kind, page=page),
            self._after_explore_results,
        )

    def _after_explore_results(self, results: List[SearchBook]) -> None:
        self._discovery.show_explore_results(results)
        kind = self._controller.session.active_explore_kind
        name = kind.title if kind and kind.title else "category"
        self._set_status(f'{len(results)} books in "{name}".')

    # ------------------------------------------------------------------
    # Opening a book (from search/explore result or bookshelf)
    # ------------------------------------------------------------------

    @Slot(object)
    def _open_search_result(self, result: SearchBook) -> None:
        self._run_task(
            f'Loading "{result.name}"…',
            lambda: self._controller.open_search_result(result),
            self._after_book_loaded,
        )

    @Slot(str)
    def _open_bookshelf_entry(self, key: str) -> None:
        self._run_task(
            "Opening bookshelf entry…",
            lambda: self._controller.open_bookshelf_entry(key),
            self._after_book_loaded,
        )

    @Slot(str)
    def _resume_bookshelf_entry(self, key: str) -> None:
        self._set_status("Loading book…")
        worker = Worker(lambda: self._controller.open_bookshelf_entry(key))
        self._active_workers.add(worker)
        worker.signals.result.connect(self._after_book_loaded_for_resume)
        worker.signals.result.connect(lambda _: self._active_workers.discard(worker))
        worker.signals.error.connect(self._on_task_error)
        worker.signals.error.connect(lambda *_: self._active_workers.discard(worker))
        QThreadPool.globalInstance().start(worker)

    @Slot(object)
    def _after_book_loaded_for_resume(self, book: Book) -> None:
        self._run_task(
            "Resuming…",
            self._controller.resume_current_book,
            lambda text: self._after_chapter_loaded(
                int(self._controller.session.current_chapter_index or 0), text
            ),
        )

    @Slot(str)
    def _remove_bookshelf_entry(self, key: str) -> None:
        self._controller.remove_bookshelf_entry(key)
        self._sidebar.refresh_bookshelf(self._controller.list_bookshelf_entries())
        self._set_status("Bookshelf entry removed.")

    def _after_book_loaded(self, book: Book) -> None:
        if self._controller.session.source:
            self._sidebar.update_source(self._controller.session.source)
        progress = self._controller.get_current_progress()
        self._book_page.set_book(book, progress)
        self._book_page.set_chapters_loading()
        self._show_stage(1)
        self._sidebar.refresh_bookshelf(self._controller.list_bookshelf_entries())
        self._run_task(
            f'Loading chapters for "{book.name or "book"}"…',
            self._controller.load_chapters,
            self._after_chapters_loaded,
        )

    def _after_chapters_loaded(self, chapters: List[BookChapter]) -> None:
        self._book_page.set_chapters(chapters)
        book = self._controller.session.book
        if book is not None:
            self._book_page.set_book(book, self._controller.get_current_progress())
        self._set_status(f"{len(chapters)} chapter(s) loaded. Double-click to read.")

    # ------------------------------------------------------------------
    # Chapter navigation
    # ------------------------------------------------------------------

    @Slot(int)
    def _open_chapter(self, idx: int) -> None:
        self._run_task(
            f"Fetching chapter {idx + 1}…",
            lambda: self._controller.get_chapter_content(idx),
            lambda text: self._after_chapter_loaded(idx, text),
        )

    @Slot()
    def _resume_current_book(self) -> None:
        if not self._controller.session.book:
            QMessageBox.information(self, "Resume", "No active book.")
            return
        self._run_task(
            "Resuming…",
            self._controller.resume_current_book,
            lambda text: self._after_chapter_loaded(
                int(self._controller.session.current_chapter_index or 0), text
            ),
        )

    @Slot()
    def _refresh_toc(self) -> None:
        if not self._controller.session.book:
            return
        self._book_page.set_chapters_loading()
        self._run_task(
            "Refreshing TOC…",
            self._controller.load_chapters,
            self._after_chapters_loaded,
        )

    @Slot()
    def _open_prev_chapter(self) -> None:
        if not self._controller.can_go_previous():
            return
        target = int(self._controller.session.current_chapter_index) - 1
        self._run_task(
            "Loading previous chapter…",
            self._controller.go_previous,
            lambda text: self._after_chapter_loaded(target, text),
        )

    @Slot()
    def _open_next_chapter(self) -> None:
        if not self._controller.can_go_next():
            return
        target = int(self._controller.session.current_chapter_index) + 1
        self._run_task(
            "Loading next chapter…",
            self._controller.go_next,
            lambda text: self._after_chapter_loaded(target, text),
        )

    def _after_chapter_loaded(self, chapter_index: int, text: str) -> None:
        chapters = self._controller.session.chapters
        if not (0 <= chapter_index < len(chapters)):
            return
        chapter = chapters[chapter_index]
        total = len(chapters)
        book_name = (
            self._controller.session.book.name
            if self._controller.session.book
            else "—"
        )
        progress_pct = int(chapter_index * 100 / total) if total > 0 else 0

        self._last_chapter_text = text
        html = _text_to_html(text, self._reader_css)
        self._reader_page.set_content(html, chapter, total, book_name, progress_pct)
        self._book_page.highlight_chapter(chapter_index)
        self._show_stage(2)

        # Restore saved scroll position (delayed so layout is settled)
        progress = self._controller.get_current_progress() or {}
        prog_idx_raw = progress.get("chapter_index")
        prog_idx = int(prog_idx_raw) if prog_idx_raw is not None else -1
        if prog_idx == chapter_index:
            scroll_ratio = float(progress.get("scroll_y", 0.0) or 0.0)
            if scroll_ratio > 0:
                QTimer.singleShot(
                    50, lambda: self._reader_page.restore_scroll(scroll_ratio)
                )

        self._sidebar.refresh_bookshelf(self._controller.list_bookshelf_entries())
        self._set_status(f"Ch {chapter_index + 1}/{total}: {chapter.title}")

    # ------------------------------------------------------------------
    # Bookshelf (add)
    # ------------------------------------------------------------------

    @Slot()
    def _add_to_shelf(self) -> None:
        self._sidebar.refresh_bookshelf(self._controller.list_bookshelf_entries())
        self._set_status("Book is on your shelf.")

    # ------------------------------------------------------------------
    # Scroll persistence
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_scroll(self, _value: int) -> None:
        self._scroll_timer.start()

    @Slot()
    def _save_scroll_position(self) -> None:
        if not self._controller.session.book or self._controller.get_current_chapter() is None:
            return
        bar = self._reader_page.scroll_bar
        maximum = bar.maximum()
        ratio = bar.value() / maximum if maximum > 0 else 0.0
        self._controller.update_current_scroll(ratio)

    # ------------------------------------------------------------------
    # Task runner
    # ------------------------------------------------------------------

    def _run_task(self, status: str, fn, on_success) -> None:
        self._set_status(status)
        worker = Worker(fn)
        self._active_workers.add(worker)
        worker.signals.result.connect(on_success)
        worker.signals.result.connect(lambda _: self._active_workers.discard(worker))
        worker.signals.error.connect(self._on_task_error)
        worker.signals.error.connect(lambda *_: self._active_workers.discard(worker))
        QThreadPool.globalInstance().start(worker)

    def closeEvent(self, event) -> None:
        # Give in-flight workers up to 2 s to finish so their _Signals objects
        # aren't destroyed mid-emission (would segfault on the worker thread).
        QThreadPool.globalInstance().waitForDone(2000)
        self._active_workers.clear()
        super().closeEvent(event)

    @Slot(str, object)
    def _on_task_error(self, message: str, exc: object) -> None:
        self._set_status(f"Error: {message}")
        QMessageBox.critical(self, "LegadoPy Reader", message)

    def _set_status(self, text: str) -> None:
        self._status_bar.showMessage(text)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def launch_gui() -> None:
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LegadoPy Reader")
    window = LegadoApp()
    window.show()
    sys.exit(app.exec())
