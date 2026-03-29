"""
LegadoPy Qt6 Desktop Reader (PySide6).

3-panel layout:
  Left   – Search / Explore / Bookshelf tabs
  Centre – Book Info / Chapters / Source / Auth tabs
  Right  – Chapter content (QTextBrowser)
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
from PySide6.QtGui import QAction, QFont, QKeySequence, QTextCursor
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
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from legado_engine import Book, BookChapter, ExploreKind, SearchBook
from legado_engine.source_login import SourceUiActionResult, UiRow

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
        worker.signals.result.connect(self._apply_result)
        worker.signals.error.connect(lambda msg, _: self.status_changed.emit(f"Auth failed: {msg}"))
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
        worker.signals.result.connect(self._apply_result)
        worker.signals.error.connect(lambda msg, _: self.status_changed.emit(f"Action failed: {msg}"))
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
# Main window
# ---------------------------------------------------------------------------

class LegadoApp(QMainWindow):
    def __init__(self, controller: Optional[ReaderController] = None) -> None:
        super().__init__()
        self._controller = controller or ReaderController()
        self._dark_mode = True
        self._reader_font_size = 15
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(800)
        self._scroll_timer.timeout.connect(self._save_scroll_position)

        self.setWindowTitle("LegadoPy Reader")
        self.resize(1560, 940)
        self._build_ui()
        self._apply_theme()
        self._restore_source()

        QThreadPool.globalInstance().setMaxThreadCount(8)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Toolbar ──────────────────────────────────────────────────
        tb = QToolBar("Main", self)
        tb.setMovable(False)
        self.addToolBar(tb)

        self._btn_open_source = QPushButton("Open Source")
        self._btn_open_source.clicked.connect(self._open_source_dialog)
        tb.addWidget(self._btn_open_source)

        self._btn_reload = QPushButton("Reload")
        self._btn_reload.clicked.connect(self._reload_source)
        tb.addWidget(self._btn_reload)

        self._btn_resume = QPushButton("▶ Resume")
        self._btn_resume.clicked.connect(self._resume_book)
        tb.addWidget(self._btn_resume)

        self._btn_categories = QPushButton("Categories")
        self._btn_categories.clicked.connect(self._load_categories)
        tb.addWidget(self._btn_categories)

        self._btn_auth = QPushButton("Login / Auth")
        self._btn_auth.setEnabled(False)
        self._btn_auth.clicked.connect(self._open_auth_tab)
        tb.addWidget(self._btn_auth)

        tb.addSeparator()

        tb.addWidget(QLabel(" Search: "))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Enter query…")
        self._search_edit.setFixedWidth(220)
        self._search_edit.returnPressed.connect(self._trigger_search)
        tb.addWidget(self._search_edit)

        tb.addWidget(QLabel(" Page: "))
        self._page_spin = QSpinBox()
        self._page_spin.setRange(1, 9999)
        self._page_spin.setFixedWidth(64)
        tb.addWidget(self._page_spin)

        self._btn_search = QPushButton("Search")
        self._btn_search.clicked.connect(self._trigger_search)
        tb.addWidget(self._btn_search)

        tb.addSeparator()
        tb.addWidget(QLabel(" Preload: "))
        self._preload_spin = QSpinBox()
        self._preload_spin.setRange(0, 10)
        self._preload_spin.setValue(
            int(self._controller.get_settings().get("preload_count", 2) or 2)
        )
        self._preload_spin.setFixedWidth(56)
        self._preload_spin.valueChanged.connect(self._apply_settings)
        tb.addWidget(self._preload_spin)

        tb.addWidget(QLabel(" Font: "))
        self._font_spin = QSpinBox()
        self._font_spin.setRange(10, 28)
        self._font_spin.setValue(self._reader_font_size)
        self._font_spin.setFixedWidth(56)
        self._font_spin.valueChanged.connect(self._change_font_size)
        tb.addWidget(self._font_spin)

        self._btn_theme = QPushButton("☀ Light")
        self._btn_theme.setFixedWidth(80)
        self._btn_theme.clicked.connect(self._toggle_theme)
        tb.addWidget(self._btn_theme)

        # ── Source label ─────────────────────────────────────────────
        self._source_label = QLabel("No source loaded")
        self._source_label.setContentsMargins(8, 0, 0, 0)
        self._source_label.setStyleSheet("color: #89b4fa; font-weight: bold;")
        tb2 = QToolBar("Source info", self)
        tb2.setMovable(False)
        tb2.addWidget(self._source_label)
        self.addToolBarBreak()
        self.addToolBar(tb2)

        # ── Central splitter ─────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        # Left panel
        self._left_tabs = QTabWidget()
        splitter.addWidget(self._left_tabs)

        # Centre panel
        self._centre_tabs = QTabWidget()
        splitter.addWidget(self._centre_tabs)

        # Right panel
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 6, 6, 6)

        nav = QHBoxLayout()
        self._btn_prev = QPushButton("◀ Prev")
        self._btn_prev.clicked.connect(self._open_prev_chapter)
        self._btn_next = QPushButton("Next ▶")
        self._btn_next.clicked.connect(self._open_next_chapter)
        self._btn_refresh_ch = QPushButton("↺ Refresh Chapters")
        self._btn_refresh_ch.clicked.connect(self._refresh_chapters)
        self._chapter_label = QLabel()
        self._chapter_label.setAlignment(Qt.AlignCenter)
        self._chapter_label.setStyleSheet("color: #89b4fa; font-weight: bold;")
        nav.addWidget(self._btn_prev)
        nav.addWidget(self._btn_next)
        nav.addStretch()
        nav.addWidget(self._chapter_label)
        nav.addStretch()
        nav.addWidget(self._btn_refresh_ch)
        rv.addLayout(nav)

        self._reader = QTextBrowser()
        self._reader.setOpenExternalLinks(True)
        self._reader.verticalScrollBar().valueChanged.connect(self._on_scroll)
        rv.addWidget(self._reader, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 6)

        # ── Left tabs ────────────────────────────────────────────────
        # Search results
        search_w = QWidget()
        sv = QVBoxLayout(search_w)
        sv.setContentsMargins(6, 6, 6, 6)
        self._results_list = QListWidget()
        self._results_list.itemDoubleClicked.connect(self._open_selected_result)
        sv.addWidget(self._results_list)
        self._left_tabs.addTab(search_w, "Search")

        # Explore / Categories
        explore_w = QWidget()
        ev = QVBoxLayout(explore_w)
        ev.setContentsMargins(6, 6, 6, 6)
        ebtns = QHBoxLayout()
        self._btn_load_cats = QPushButton("Load Categories")
        self._btn_load_cats.clicked.connect(self._load_categories)
        self._btn_open_cat = QPushButton("Open Category")
        self._btn_open_cat.clicked.connect(self._open_selected_category)
        self._btn_open_explore = QPushButton("Open Book")
        self._btn_open_explore.clicked.connect(self._open_selected_explore)
        for b in (self._btn_load_cats, self._btn_open_cat, self._btn_open_explore):
            ebtns.addWidget(b)
        ebtns.addStretch()
        ev.addLayout(ebtns)
        explore_splitter = QSplitter(Qt.Vertical)
        self._category_list = QListWidget()
        self._category_list.itemDoubleClicked.connect(self._open_selected_category)
        self._explore_results = QListWidget()
        self._explore_results.itemDoubleClicked.connect(self._open_selected_explore)
        explore_splitter.addWidget(self._category_list)
        explore_splitter.addWidget(self._explore_results)
        ev.addWidget(explore_splitter, 1)
        self._left_tabs.addTab(explore_w, "Explore")

        # Bookshelf
        shelf_w = QWidget()
        shv = QVBoxLayout(shelf_w)
        shv.setContentsMargins(6, 6, 6, 6)
        self._bookshelf = QTreeWidget()
        self._bookshelf.setHeaderLabels(["Title", "Author", "Progress"])
        self._bookshelf.setColumnWidth(0, 200)
        self._bookshelf.setColumnWidth(1, 120)
        self._bookshelf.setRootIsDecorated(False)
        self._bookshelf.itemDoubleClicked.connect(self._open_selected_bookshelf)
        shv.addWidget(self._bookshelf, 1)
        shelf_btns = QHBoxLayout()
        self._btn_shelf_open = QPushButton("Open")
        self._btn_shelf_open.clicked.connect(self._open_selected_bookshelf)
        self._btn_shelf_remove = QPushButton("Remove")
        self._btn_shelf_remove.clicked.connect(self._remove_selected_bookshelf)
        shelf_btns.addWidget(self._btn_shelf_open)
        shelf_btns.addWidget(self._btn_shelf_remove)
        shelf_btns.addStretch()
        shv.addLayout(shelf_btns)
        self._left_tabs.addTab(shelf_w, "Bookshelf")

        # ── Centre tabs ──────────────────────────────────────────────
        # Book Info
        self._info_text = QTextEdit()
        self._info_text.setReadOnly(True)
        self._centre_tabs.addTab(self._info_text, "Book Info")

        # Chapters
        chapters_w = QWidget()
        chv = QVBoxLayout(chapters_w)
        chv.setContentsMargins(6, 6, 6, 6)
        self._chapter_list = QListWidget()
        self._chapter_list.itemDoubleClicked.connect(self._open_selected_chapter)
        chv.addWidget(self._chapter_list, 1)
        ch_btns = QHBoxLayout()
        self._btn_open_ch = QPushButton("Open Chapter")
        self._btn_open_ch.clicked.connect(self._open_selected_chapter)
        ch_btns.addWidget(self._btn_open_ch)
        ch_btns.addStretch()
        chv.addLayout(ch_btns)
        self._centre_tabs.addTab(chapters_w, "Chapters")

        # Source
        self._source_text = QTextEdit()
        self._source_text.setReadOnly(True)
        self._source_text.setFont(QFont("Courier New", 11))
        self._centre_tabs.addTab(self._source_text, "Source")

        # Auth
        self._auth_panel = AuthPanel(self, self._controller)
        self._auth_panel.status_changed.connect(self._set_status)
        self._centre_tabs.addTab(self._auth_panel, "Auth")

        # ── Status bar ───────────────────────────────────────────────
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Load a source JSON file to begin.")

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
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        qss = _DARK_QSS if self._dark_mode else _LIGHT_QSS
        QApplication.instance().setStyleSheet(qss)
        self._btn_theme.setText("☀ Light" if self._dark_mode else "🌙 Dark")
        self._reader_css = _READER_CSS_DARK if self._dark_mode else _READER_CSS_LIGHT
        self._source_label.setStyleSheet(
            "color: #89b4fa; font-weight: bold;"
            if self._dark_mode
            else "color: #1e66f5; font-weight: bold;"
        )
        # Refresh reader if content is loaded
        current = self._reader.toPlainText()
        if current:
            self._reader.setHtml(_text_to_html(current, self._reader_css))

    @Slot()
    def _toggle_theme(self) -> None:
        self._dark_mode = not self._dark_mode
        self._apply_theme()

    # ------------------------------------------------------------------
    # Source management
    # ------------------------------------------------------------------

    def _restore_source(self) -> None:
        source = self._controller.state.get_current_source()
        if source is None:
            return
        self._controller.set_source(source)
        self._update_source_ui(source)
        self._refresh_bookshelf()
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
        self._run_task("Reloading source…", self._controller.reload_source, self._after_source_loaded)

    @Slot()
    def _open_auth_tab(self) -> None:
        self._auth_panel.load_source()
        self._centre_tabs.setCurrentWidget(self._auth_panel)

    def _update_source_ui(self, source: Any) -> None:
        self._source_label.setText(f"{source.bookSourceName}  [{source.bookSourceUrl}]")
        self._btn_auth.setEnabled(self._controller.has_source_auth())
        # Fill Source tab
        info = "\n".join([
            f"Name: {source.bookSourceName}",
            f"URL:  {source.bookSourceUrl}",
            f"Search URL: {source.searchUrl or '—'}",
            f"Explore URL: {source.exploreUrl or '—'}",
            f"Concurrent Rate: {source.concurrentRate or '0'}",
            f"Cookie Jar: {source.enabledCookieJar}",
            "",
            json.dumps(source.to_dict(), ensure_ascii=False, indent=2),
        ])
        self._source_text.setPlainText(info)

    def _after_source_loaded(self, source: Any) -> None:
        self._update_source_ui(source)
        self._info_text.clear()
        self._reader.clear()
        self._chapter_label.clear()
        self._results_list.clear()
        self._category_list.clear()
        self._explore_results.clear()
        self._chapter_list.clear()
        self._refresh_bookshelf()
        self._set_status(f"Loaded source: {source.bookSourceName}.")

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @Slot()
    def _trigger_search(self) -> None:
        query = self._search_edit.text().strip()
        if not query:
            QMessageBox.information(self, "Search", "Enter a search query first.")
            return
        page = self._page_spin.value()
        self._run_task(
            f'Searching for "{query}"\u2026',
            lambda: self._controller.search(query, page=page),
            self._after_search,
        )

    def _after_search(self, results: List[SearchBook]) -> None:
        self._results_list.clear()
        for item in results:
            label = f"{item.name or '(untitled)'}  |  {item.author or 'Unknown author'}"
            self._results_list.addItem(label)
        self._left_tabs.setCurrentIndex(0)
        self._set_status(f"{len(results)} search result(s) found.")

    @Slot(QListWidgetItem)
    def _open_selected_result(self, _item: QListWidgetItem | None = None) -> None:
        row = self._results_list.currentRow()
        if row < 0:
            return
        result = self._controller.session.search_results[row]
        self._run_task(
            f'Loading "{result.name}"\u2026',
            lambda: self._controller.open_search_result(result),
            self._after_book_loaded,
        )

    # ------------------------------------------------------------------
    # Explore
    # ------------------------------------------------------------------

    @Slot()
    def _load_categories(self) -> None:
        self._run_task(
            "Loading categories…",
            self._controller.load_explore_kinds,
            self._after_categories_loaded,
        )

    def _after_categories_loaded(self, kinds: List[ExploreKind]) -> None:
        self._category_list.clear()
        self._explore_results.clear()
        for k in kinds:
            label = k.title or "(untitled)"
            if not k.url:
                label += "  [no url]"
            self._category_list.addItem(label)
        self._left_tabs.setCurrentIndex(1)
        self._set_status(f"{len(kinds)} categories loaded.")

    @Slot()
    def _open_selected_category(self) -> None:
        row = self._category_list.currentRow()
        if row < 0:
            return
        kind = self._controller.session.explore_kinds[row]
        page = self._page_spin.value()
        self._run_task(
            f'Loading "{kind.title or "(untitled)"}\u2026',
            lambda: self._controller.explore(kind, page=page),
            self._after_explore_results,
        )

    def _after_explore_results(self, results: List[SearchBook]) -> None:
        self._explore_results.clear()
        for item in results:
            label = f"{item.name or '(untitled)'}  |  {item.author or 'Unknown author'}"
            self._explore_results.addItem(label)
        kind = self._controller.session.active_explore_kind
        name = kind.title if kind and kind.title else "category"
        self._set_status(f'{len(results)} books in "{name}".')

    @Slot()
    def _open_selected_explore(self) -> None:
        row = self._explore_results.currentRow()
        if row < 0:
            return
        result = self._controller.session.explore_results[row]
        self._run_task(
            f'Loading "{result.name}"\u2026',
            lambda: self._controller.open_explore_result(result),
            self._after_book_loaded,
        )

    # ------------------------------------------------------------------
    # Bookshelf
    # ------------------------------------------------------------------

    def _refresh_bookshelf(self) -> None:
        self._bookshelf.clear()
        for entry in self._controller.list_bookshelf_entries():
            book = entry.get("book") or {}
            progress = entry.get("progress") or {}
            ch_title = progress.get("chapter_title") or "Unread"
            item = QTreeWidgetItem([
                book.get("name", "(untitled)"),
                book.get("author", "Unknown author"),
                ch_title,
            ])
            item.setData(0, Qt.UserRole, entry.get("key"))
            self._bookshelf.addTopLevelItem(item)

    @Slot(QTreeWidgetItem)
    def _open_selected_bookshelf(self, _item: QTreeWidgetItem | None = None) -> None:
        sel = self._bookshelf.currentItem()
        if not sel:
            return
        key = sel.data(0, Qt.UserRole)
        self._run_task(
            "Opening bookshelf entry…",
            lambda: self._controller.open_bookshelf_entry(str(key)),
            self._after_book_loaded,
        )

    @Slot()
    def _remove_selected_bookshelf(self) -> None:
        sel = self._bookshelf.currentItem()
        if not sel:
            return
        key = sel.data(0, Qt.UserRole)
        self._controller.remove_bookshelf_entry(str(key))
        self._refresh_bookshelf()
        self._set_status("Bookshelf entry removed.")

    # ------------------------------------------------------------------
    # Book / chapters
    # ------------------------------------------------------------------

    def _after_book_loaded(self, book: Book) -> None:
        info = "\n".join([
            f"Name:    {book.name or '—'}",
            f"Author:  {book.author or '—'}",
            f"Kind:    {book.kind or '—'}",
            f"Words:   {book.wordCount or '—'}",
            f"Latest:  {book.latestChapterTitle or '—'}",
            f"Cover:   {book.coverUrl or '—'}",
            f"Book URL:{book.bookUrl or '—'}",
            f"TOC URL: {book.tocUrl or '—'}",
            "",
            "Intro:",
            book.intro or "—",
        ])
        self._info_text.setPlainText(info)
        self._centre_tabs.setCurrentIndex(0)
        self._refresh_bookshelf()
        self._run_task(
            f'Loading chapters for "{book.name or "book"}"\u2026',
            self._controller.load_chapters,
            self._after_chapters_loaded,
        )

    def _after_chapters_loaded(self, chapters: List[BookChapter]) -> None:
        self._chapter_list.clear()
        for ch in chapters:
            self._chapter_list.addItem(f"{ch.index + 1:>4}. {ch.title}")
        self._centre_tabs.setCurrentIndex(1)
        self._set_status(f"{len(chapters)} chapter(s) loaded. Double-click to read.")

    @Slot()
    def _open_selected_chapter(self) -> None:
        row = self._chapter_list.currentRow()
        if row < 0:
            return
        self._run_task(
            f"Fetching chapter {row + 1}…",
            lambda: self._controller.get_chapter_content(row),
            lambda text: self._after_chapter_loaded(row, text),
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

    @Slot()
    def _refresh_chapters(self) -> None:
        if not self._controller.session.book:
            return
        self._run_task("Refreshing chapters…", self._controller.load_chapters, self._after_chapters_loaded)

    @Slot()
    def _resume_book(self) -> None:
        if not self._controller.session.book:
            QMessageBox.information(self, "Resume", "No active book.")
            return
        self._run_task(
            "Resuming current book…",
            self._controller.resume_current_book,
            lambda text: self._after_chapter_loaded(
                int(self._controller.session.current_chapter_index or 0), text
            ),
        )

    def _after_chapter_loaded(self, chapter_index: int, text: str) -> None:
        # Highlight chapter in list
        if 0 <= chapter_index < self._chapter_list.count():
            self._chapter_list.setCurrentRow(chapter_index)
            chapter = self._controller.session.chapters[chapter_index]
            self._chapter_label.setText(chapter.title)

        self._render_content(text)
        self._restore_scroll(chapter_index)
        self._refresh_bookshelf()
        self._set_status("Chapter rendered.")

    def _render_content(self, text: str) -> None:
        self._reader.setHtml(_text_to_html(text, self._reader_css))

    def _restore_scroll(self, chapter_index: int) -> None:
        progress = self._controller.get_current_progress() or {}
        prog_idx_raw = progress.get("chapter_index")
        prog_idx = int(prog_idx_raw) if prog_idx_raw is not None else -1
        if prog_idx != chapter_index:
            return
        scroll_ratio = float(progress.get("scroll_y", 0.0) or 0.0)
        if scroll_ratio > 0:
            bar = self._reader.verticalScrollBar()
            bar.setValue(int(bar.maximum() * scroll_ratio))

    # ------------------------------------------------------------------
    # Scroll persistence
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_scroll(self, _value: int) -> None:
        self._scroll_timer.start()

    @Slot()
    def _save_scroll_position(self) -> None:
        self._scroll_timer.stop()
        if not self._controller.session.book or self._controller.get_current_chapter() is None:
            return
        bar = self._reader.verticalScrollBar()
        maximum = bar.maximum()
        ratio = bar.value() / maximum if maximum > 0 else 0.0
        self._controller.update_current_scroll(ratio)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @Slot()
    def _apply_settings(self) -> None:
        self._controller.update_settings(preload_count=self._preload_spin.value())

    @Slot(int)
    def _change_font_size(self, size: int) -> None:
        self._reader_font_size = size
        global _READER_CSS_DARK, _READER_CSS_LIGHT
        for attr, bg, fg in (
            ("_READER_CSS_DARK", "#1e1e2e", "#cdd6f4"),
            ("_READER_CSS_LIGHT", "#fafafa", "#3c3c3c"),
        ):
            globals()[attr] = (
                f"body {{ background-color: {bg}; color: {fg};"
                f" font-family: 'Georgia', 'Noto Serif', serif;"
                f" font-size: {size}px; line-height: 1.8;"
                f" margin: 24px 48px; max-width: 800px; }}"
                f" p {{ margin: 0.6em 0; }}"
            )
        self._reader_css = _READER_CSS_DARK if self._dark_mode else _READER_CSS_LIGHT
        current = self._reader.toPlainText()
        if current:
            self._reader.setHtml(_text_to_html(current, self._reader_css))

    # ------------------------------------------------------------------
    # Task runner
    # ------------------------------------------------------------------

    def _run_task(self, status: str, fn, on_success) -> None:
        self._set_status(status)
        worker = Worker(fn)
        worker.signals.result.connect(on_success)
        worker.signals.error.connect(self._on_task_error)
        QThreadPool.globalInstance().start(worker)

    @Slot(str, object)
    def _on_task_error(self, message: str, exc: object) -> None:
        self._set_status(f"Error: {message}")
        QMessageBox.critical(self, "LegadoPy Reader", message)

    def _set_status(self, text: str) -> None:
        self._status_bar.showMessage(text)

    # ------------------------------------------------------------------
    # Reader CSS property (updated by font/theme changes)
    # ------------------------------------------------------------------

    @property
    def _reader_css(self) -> str:
        return self.__reader_css

    @_reader_css.setter
    def _reader_css(self, value: str) -> None:
        self.__reader_css = value

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)


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
