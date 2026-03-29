from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import queue
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Callable, Optional

from legado_engine import Book, BookChapter, ExploreKind, SearchBook
from legado_engine.source_login import SourceUiActionResult, UiRow

from .controller import ReaderController


class SourceAuthDialog(tk.Toplevel):
    def __init__(self, app: ReaderDesktopApp) -> None:
        super().__init__(app.root)
        self.app = app
        self.controller = app.controller
        self._rows = self.controller.get_source_auth_rows()
        self._action_rows = [row for row in self._rows if row.type == "button"]
        self._field_vars: dict[str, tk.StringVar] = {}
        self._last_open_url: Optional[str] = None
        self.status_var = tk.StringVar(value="Ready.")
        source = self.controller.session.source
        self.title(f"Source Login / Auth - {source.bookSourceName if source else 'Unknown Source'}")
        self.geometry("900x720")
        self.transient(app.root)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._build_ui()
        self._load_saved_form()
        self._set_detail(self.controller.describe_source_auth())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.lift()
        self.focus_force()

    def _build_ui(self) -> None:
        source = self.controller.session.source

        summary = ttk.Frame(self, padding=(12, 12, 12, 6))
        summary.grid(row=0, column=0, sticky="ew")
        summary.columnconfigure(0, weight=1)
        ttk.Label(
            summary,
            text=f"{source.bookSourceName}  [{source.bookSourceUrl}]",
            font=("", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")

        toolbar = ttk.Frame(self, padding=(12, 0, 12, 8))
        toolbar.grid(row=1, column=0, sticky="ew")
        ttk.Button(toolbar, text="Submit", command=self.submit_form).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Show Header", command=self.show_header).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="Clear Header", command=self.clear_header).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="Show Form", command=self.show_form).pack(side=tk.LEFT, padx=(8, 0))
        self.open_url_button = ttk.Button(toolbar, text="Open URL", command=self.open_last_url, state=tk.DISABLED)
        self.open_url_button.pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="Close", command=self.destroy).pack(side=tk.RIGHT, padx=(0, 8))

        body = ttk.Frame(self, padding=(12, 0, 12, 8))
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        form_shell = ttk.LabelFrame(body, text="Form", padding=8)
        form_shell.grid(row=0, column=0, sticky="ew")
        form_shell.columnconfigure(1, weight=1)
        row_index = 0
        for row in self._rows:
            if row.type not in {"text", "password"}:
                continue
            field_var = tk.StringVar()
            self._field_vars[row.name] = field_var
            ttk.Label(form_shell, text=row.name or "Field").grid(
                row=row_index,
                column=0,
                sticky="w",
                padx=(0, 10),
                pady=4,
            )
            ttk.Entry(
                form_shell,
                textvariable=field_var,
                show="*" if row.type == "password" else "",
            ).grid(row=row_index, column=1, sticky="ew", pady=4)
            row_index += 1
        if not self._field_vars:
            ttk.Label(
                form_shell,
                text="No editable login fields were defined for this source.",
            ).grid(row=0, column=0, sticky="w")

        if self._action_rows:
            actions_shell = ttk.LabelFrame(body, text="Actions", padding=8)
            actions_shell.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
            actions_shell.columnconfigure(0, weight=1)
            actions_shell.rowconfigure(0, weight=1)
            self.action_list = tk.Listbox(actions_shell, activestyle="dotbox", height=10)
            self.action_list.grid(row=0, column=0, sticky="nsew")
            for row in self._action_rows:
                self.action_list.insert(tk.END, row.name or "Action")
            self.action_list.bind("<Double-Button-1>", lambda _event: self.run_selected_action())
            action_bar = ttk.Frame(actions_shell)
            action_bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
            ttk.Button(action_bar, text="Run Selected Action", command=self.run_selected_action).pack(side=tk.LEFT)
            ttk.Label(
                action_bar,
                text=f"{len(self._action_rows)} source-defined actions",
            ).pack(side=tk.RIGHT)

        detail_shell = ttk.LabelFrame(body, text="Details", padding=8)
        detail_row = 2 if self._action_rows else 1
        detail_shell.grid(row=detail_row, column=0, sticky="nsew", pady=(8, 0))
        detail_shell.rowconfigure(0, weight=1)
        detail_shell.columnconfigure(0, weight=1)
        self.detail_text = ScrolledText(detail_shell, wrap=tk.WORD, height=20)
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        self.detail_text.configure(state=tk.DISABLED)
        body.rowconfigure(detail_row, weight=1)

        ttk.Label(
            self,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor="w",
            padding=(8, 4),
        ).grid(row=3, column=0, sticky="ew")

    def _load_saved_form(self) -> None:
        for name, value in self.controller.get_source_auth_form_data().items():
            if name in self._field_vars:
                self._field_vars[name].set(value)

    def collect_form_data(self) -> dict[str, str]:
        return {name: var.get() for name, var in self._field_vars.items()}

    def submit_form(self) -> None:
        self.app._run_task(
            "Submitting source authentication...",
            lambda: self.controller.submit_source_auth(self.collect_form_data()),
            self._apply_result,
            on_error=self._handle_error,
        )

    def run_action(self, row: UiRow) -> None:
        self.app._run_task(
            f"Running source action {row.name or 'action'}...",
            lambda: self.controller.run_source_auth_action(row.action or "", self.collect_form_data()),
            self._apply_result,
            on_error=self._handle_error,
        )

    def run_selected_action(self) -> None:
        if not self._action_rows:
            return
        selection = self.action_list.curselection()
        if not selection:
            self.status_var.set("Select an action first.")
            return
        self.run_action(self._action_rows[selection[0]])

    def show_form(self) -> None:
        self.status_var.set("Showing current form values.")
        self._set_detail(json_dump(self.collect_form_data()))

    def show_header(self) -> None:
        header = self.controller.get_source_login_header()
        self.status_var.set("Showing saved login header.")
        self._set_detail(header or "No saved login header.")

    def clear_header(self) -> None:
        if not messagebox.askyesno("Clear Header", "Remove the saved login header for this source?"):
            return
        self.controller.clear_source_login_header()
        self.app._refresh_source_views()
        self.status_var.set("Saved login header cleared.")
        self._set_detail(self.controller.describe_source_auth())

    def open_last_url(self) -> None:
        if self._last_open_url:
            webbrowser.open(self._last_open_url)

    def _apply_result(self, outcome: SourceUiActionResult) -> None:
        self._last_open_url = outcome.open_url or None
        self.open_url_button.configure(
            state=(tk.NORMAL if self._last_open_url else tk.DISABLED)
        )
        self.status_var.set(outcome.message or "Completed.")
        self._set_detail(outcome.detail_text() or self.controller.describe_source_auth())
        self._load_saved_form()
        self.app._refresh_source_views()

    def _handle_error(self, exc: Exception) -> None:
        self.status_var.set(f"Operation failed: {exc}")
        messagebox.showerror("Source Login / Auth", str(exc), parent=self)

    def _set_detail(self, text: str) -> None:
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        if getattr(self.app, "_auth_dialog", None) is self:
            self.app._auth_dialog = None
        self.destroy()


class SourceAuthPanel(ttk.Frame):
    def __init__(self, parent: Any, app: ReaderDesktopApp) -> None:
        super().__init__(parent, padding=8)
        self.app = app
        self.controller = app.controller
        self._rows: list[UiRow] = []
        self._action_rows: list[UiRow] = []
        self._field_vars: dict[str, tk.StringVar] = {}
        self._last_open_url: Optional[str] = None
        self.status_var = tk.StringVar(value="Load a source with login/auth support.")
        self.source_var = tk.StringVar(value="No source loaded")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.columnconfigure(0, weight=1)
        ttk.Label(top, textvariable=self.source_var, font=("", 10, "bold")).grid(row=0, column=0, sticky="w")

        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(toolbar, text="Submit", command=self.submit_form).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Run Selected Action", command=self.run_selected_action).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="Show Header", command=self.show_header).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="Clear Header", command=self.clear_header).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="Show Form", command=self.show_form).pack(side=tk.LEFT, padx=(8, 0))
        self.open_url_button = ttk.Button(toolbar, text="Open URL", command=self.open_last_url, state=tk.DISABLED)
        self.open_url_button.pack(side=tk.RIGHT)

        body = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        body.grid(row=2, column=0, sticky="nsew")

        left = ttk.Frame(body, padding=4)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        form_box = ttk.LabelFrame(left, text="Form", padding=8)
        form_box.grid(row=0, column=0, sticky="ew")
        form_box.columnconfigure(1, weight=1)
        self.form_frame = form_box

        actions_box = ttk.LabelFrame(left, text="Actions", padding=8)
        actions_box.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        actions_box.columnconfigure(0, weight=1)
        actions_box.rowconfigure(0, weight=1)
        self.action_list = tk.Listbox(actions_box, activestyle="dotbox")
        self.action_list.grid(row=0, column=0, sticky="nsew")
        self.action_list.bind("<Double-Button-1>", lambda _event: self.run_selected_action())

        right = ttk.LabelFrame(body, text="Details", padding=8)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.detail_text = ScrolledText(right, wrap=tk.WORD)
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        self.detail_text.configure(state=tk.DISABLED)

        body.add(left, weight=2)
        body.add(right, weight=3)

        ttk.Label(
            self,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor="w",
            padding=(8, 4),
        ).grid(row=3, column=0, sticky="ew", pady=(8, 0))

    def load_current_source(self) -> None:
        source = self.controller.session.source
        if source is None:
            self.source_var.set("No source loaded")
            self.status_var.set("Load a source first.")
            self._set_detail("")
            return
        self._rows = self.controller.get_source_auth_rows()
        self._action_rows = [row for row in self._rows if row.type == "button"]
        self._field_vars = {}
        for child in self.form_frame.winfo_children():
            child.destroy()
        row_index = 0
        for row in self._rows:
            if row.type not in {"text", "password"}:
                continue
            field_var = tk.StringVar()
            self._field_vars[row.name] = field_var
            ttk.Label(self.form_frame, text=row.name or "Field").grid(
                row=row_index, column=0, sticky="w", padx=(0, 10), pady=4
            )
            ttk.Entry(
                self.form_frame,
                textvariable=field_var,
                show="*" if row.type == "password" else "",
            ).grid(row=row_index, column=1, sticky="ew", pady=4)
            row_index += 1
        if not self._field_vars:
            ttk.Label(
                self.form_frame,
                text="No editable login fields were defined for this source.",
            ).grid(row=0, column=0, sticky="w")
        self.action_list.delete(0, tk.END)
        for row in self._action_rows:
            self.action_list.insert(tk.END, row.name or "Action")
        self._load_saved_form()
        self.source_var.set(f"{source.bookSourceName}  [{source.bookSourceUrl}]")
        self.status_var.set("Auth panel ready.")
        self._set_detail(self.controller.describe_source_auth())

    def _load_saved_form(self) -> None:
        for name, value in self.controller.get_source_auth_form_data().items():
            if name in self._field_vars:
                self._field_vars[name].set(value)

    def collect_form_data(self) -> dict[str, str]:
        return {name: var.get() for name, var in self._field_vars.items()}

    def submit_form(self) -> None:
        self.app._run_task(
            "Submitting source authentication...",
            lambda: self.controller.submit_source_auth(self.collect_form_data()),
            self._apply_result,
            on_error=self._handle_error,
        )

    def run_selected_action(self) -> None:
        if not self._action_rows:
            self.status_var.set("No source-defined actions.")
            return
        selection = self.action_list.curselection()
        if not selection:
            self.status_var.set("Select an action first.")
            return
        row = self._action_rows[selection[0]]
        self.app._run_task(
            f"Running source action {row.name or 'action'}...",
            lambda: self.controller.run_source_auth_action(row.action or "", self.collect_form_data()),
            self._apply_result,
            on_error=self._handle_error,
        )

    def show_form(self) -> None:
        self.status_var.set("Showing current form values.")
        self._set_detail(json_dump(self.collect_form_data()))

    def show_header(self) -> None:
        self.status_var.set("Showing saved login header.")
        header = self.controller.get_source_login_header()
        self._set_detail(header or "No saved login header.")

    def clear_header(self) -> None:
        if not messagebox.askyesno("Clear Header", "Remove the saved login header for this source?"):
            return
        self.controller.clear_source_login_header()
        self.app._refresh_source_views()
        self.load_current_source()
        self.status_var.set("Saved login header cleared.")

    def open_last_url(self) -> None:
        if self._last_open_url:
            webbrowser.open(self._last_open_url)

    def _apply_result(self, outcome: SourceUiActionResult) -> None:
        self._last_open_url = outcome.open_url or None
        self.open_url_button.configure(state=(tk.NORMAL if self._last_open_url else tk.DISABLED))
        self.status_var.set(outcome.message or "Completed.")
        self._set_detail(outcome.detail_text() or self.controller.describe_source_auth())
        self._load_saved_form()
        self.app._refresh_source_views()

    def _handle_error(self, exc: Exception) -> None:
        self.status_var.set(f"Operation failed: {exc}")
        messagebox.showerror("Source Login / Auth", str(exc), parent=self)

    def _set_detail(self, text: str) -> None:
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state=tk.DISABLED)


def json_dump(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


class ReaderDesktopApp:
    def __init__(self, controller: Optional[ReaderController] = None) -> None:
        self.controller = controller or ReaderController()
        self.root = tk.Tk()
        self.root.title("LegadoPy Desktop Reader")
        self.root.geometry("1500x920")
        self._task_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="legado-gui")
        self._last_saved_scroll_ratio: Optional[float] = None
        self._auth_dialog: Optional[SourceAuthDialog] = None
        self._build_ui()
        self._restore_source()
        self._refresh_bookshelf()
        self.root.after(100, self._poll_tasks)
        self.root.after(750, self._poll_reader_progress)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.status_var = tk.StringVar(value="Load a source JSON file to begin.")
        self.source_var = tk.StringVar(value="No source loaded")
        self.book_var = tk.StringVar(value="No book selected")
        self.progress_var = tk.StringVar(value="No reading progress yet")
        self.page_var = tk.StringVar(value="1")
        self.query_var = tk.StringVar()
        self.source_path_var = tk.StringVar(value="No source file")
        self.preload_var = tk.StringVar(value=str(self.controller.get_settings().get("preload_count", 2)))
        self.style_var = tk.StringVar(value=str(self.controller.get_settings().get("reader_style", "comfortable")))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=(10, 10, 10, 6))
        top.grid(row=0, column=0, sticky="ew")
        for col, weight in {1: 1, 7: 1, 12: 1}.items():
            top.columnconfigure(col, weight=weight)

        ttk.Button(top, text="Open Source", command=self.open_source_dialog).grid(row=0, column=0, padx=(0, 8))
        ttk.Label(top, textvariable=self.source_var).grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Button(top, text="Reload", command=self.reload_source).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(top, text="Resume", command=self.resume_current_book).grid(row=0, column=3, padx=(0, 14))
        ttk.Button(top, text="Categories", command=self.load_categories).grid(row=0, column=4, padx=(0, 10))
        self.auth_button = ttk.Button(top, text="Login/Auth", command=self.open_source_auth_dialog)
        self.auth_button.grid(row=0, column=5, padx=(0, 10))
        self.auth_button.configure(state=tk.DISABLED)
        ttk.Label(top, text="Query").grid(row=0, column=6, padx=(0, 6))
        query_entry = ttk.Entry(top, textvariable=self.query_var, width=26)
        query_entry.grid(row=0, column=7, padx=(0, 8))
        query_entry.bind("<Return>", lambda _event: self.trigger_search())
        ttk.Label(top, text="Page").grid(row=0, column=8, padx=(0, 6))
        ttk.Entry(top, textvariable=self.page_var, width=6).grid(row=0, column=9, sticky="w", padx=(0, 8))
        ttk.Button(top, text="Search", command=self.trigger_search).grid(row=0, column=10, padx=(0, 16))
        ttk.Label(top, text="Preload").grid(row=0, column=11, padx=(0, 6))
        preload = ttk.Spinbox(top, from_=0, to=10, width=5, textvariable=self.preload_var, command=self.apply_settings)
        preload.grid(row=0, column=12, padx=(0, 8))
        preload.bind("<Return>", lambda _event: self.apply_settings())
        ttk.Label(top, text="Style").grid(row=0, column=13, padx=(0, 6), sticky="e")
        style_box = ttk.Combobox(top, width=14, textvariable=self.style_var, state="readonly")
        style_box["values"] = ("comfortable", "compact", "focus")
        style_box.grid(row=0, column=14, sticky="w")
        style_box.bind("<<ComboboxSelected>>", lambda _event: self.apply_settings())

        meta = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        meta.grid(row=2, column=0, sticky="ew")
        meta.columnconfigure(1, weight=1)
        ttk.Label(meta, text="Book", font=("", 10, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(meta, textvariable=self.book_var).grid(row=0, column=1, sticky="w")
        ttk.Label(meta, text="Progress", font=("", 10, "bold")).grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Label(meta, textvariable=self.progress_var).grid(row=1, column=1, sticky="w")
        ttk.Label(meta, text="Source File", font=("", 10, "bold")).grid(row=2, column=0, sticky="w", padx=(0, 8))
        ttk.Label(meta, textvariable=self.source_path_var).grid(row=2, column=1, sticky="w")

        shell = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        shell.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(shell, padding=10)
        center = ttk.Frame(shell, padding=10)
        right = ttk.Frame(shell, padding=10)
        for panel in (left, center, right):
            panel.rowconfigure(0, weight=1)
            panel.columnconfigure(0, weight=1)

        shell.add(left, weight=3)
        shell.add(center, weight=3)
        shell.add(right, weight=6)

        self.sidebar_tabs = ttk.Notebook(left)
        self.sidebar_tabs.grid(row=0, column=0, sticky="nsew")

        results_tab = ttk.Frame(self.sidebar_tabs, padding=8)
        results_tab.rowconfigure(0, weight=1)
        results_tab.columnconfigure(0, weight=1)
        self.results_list = tk.Listbox(results_tab, activestyle="dotbox")
        self.results_list.grid(row=0, column=0, sticky="nsew")
        self.results_list.bind("<Double-Button-1>", lambda _event: self.open_selected_result())
        self.sidebar_tabs.add(results_tab, text="Search Results")

        categories_tab = ttk.Frame(self.sidebar_tabs, padding=8)
        categories_tab.rowconfigure(1, weight=1)
        categories_tab.columnconfigure(0, weight=1)
        categories_tab.columnconfigure(1, weight=1)
        category_actions = ttk.Frame(categories_tab)
        category_actions.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(category_actions, text="Load Categories", command=self.load_categories).pack(side=tk.LEFT)
        ttk.Button(category_actions, text="Open Category", command=self.open_selected_category).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(category_actions, text="Open Book", command=self.open_selected_explore_result).pack(side=tk.RIGHT)
        ttk.Label(categories_tab, text="Categories").grid(row=1, column=0, sticky="w")
        ttk.Label(categories_tab, text="Books").grid(row=1, column=1, sticky="w")
        self.category_list = tk.Listbox(categories_tab, activestyle="dotbox")
        self.category_list.grid(row=2, column=0, sticky="nsew", padx=(0, 6))
        self.category_list.bind("<Double-Button-1>", lambda _event: self.open_selected_category())
        self.explore_results_list = tk.Listbox(categories_tab, activestyle="dotbox")
        self.explore_results_list.grid(row=2, column=1, sticky="nsew", padx=(6, 0))
        self.explore_results_list.bind("<Double-Button-1>", lambda _event: self.open_selected_explore_result())
        categories_tab.rowconfigure(2, weight=1)
        self.sidebar_tabs.add(categories_tab, text="Categories")

        shelf_tab = ttk.Frame(self.sidebar_tabs, padding=8)
        shelf_tab.rowconfigure(0, weight=1)
        shelf_tab.columnconfigure(0, weight=1)
        self.bookshelf_tree = ttk.Treeview(
            shelf_tab,
            columns=("title", "author", "progress"),
            show="headings",
            selectmode="browse",
        )
        self.bookshelf_tree.heading("title", text="Title")
        self.bookshelf_tree.heading("author", text="Author")
        self.bookshelf_tree.heading("progress", text="Progress")
        self.bookshelf_tree.column("title", width=220, anchor="w")
        self.bookshelf_tree.column("author", width=120, anchor="w")
        self.bookshelf_tree.column("progress", width=180, anchor="w")
        self.bookshelf_tree.grid(row=0, column=0, sticky="nsew")
        self.bookshelf_tree.bind("<Double-1>", lambda _event: self.open_selected_bookshelf())
        shelf_actions = ttk.Frame(shelf_tab)
        shelf_actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(shelf_actions, text="Open", command=self.open_selected_bookshelf).pack(side=tk.LEFT)
        ttk.Button(shelf_actions, text="Remove", command=self.remove_selected_bookshelf).pack(side=tk.LEFT, padx=(8, 0))
        self.sidebar_tabs.add(shelf_tab, text="Bookshelf")

        self.center_tabs = ttk.Notebook(center)
        self.center_tabs.grid(row=0, column=0, sticky="nsew")

        info_tab = ttk.Frame(self.center_tabs, padding=8)
        info_tab.rowconfigure(0, weight=1)
        info_tab.columnconfigure(0, weight=1)
        self.info_text = ScrolledText(info_tab, wrap=tk.WORD, height=12)
        self.info_text.grid(row=0, column=0, sticky="nsew")
        self.info_text.configure(state=tk.DISABLED)
        self.center_tabs.add(info_tab, text="Book Info")

        chapters_tab = ttk.Frame(self.center_tabs, padding=8)
        chapters_tab.rowconfigure(0, weight=1)
        chapters_tab.columnconfigure(0, weight=1)
        self.chapter_list = tk.Listbox(chapters_tab, activestyle="dotbox")
        self.chapter_list.grid(row=0, column=0, sticky="nsew")
        self.chapter_list.bind("<Double-Button-1>", lambda _event: self.open_selected_chapter())
        chapter_actions = ttk.Frame(chapters_tab)
        chapter_actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(chapter_actions, text="Open Chapter", command=self.open_selected_chapter).pack(side=tk.LEFT)
        ttk.Button(chapter_actions, text="Resume Here", command=self.resume_current_book).pack(side=tk.LEFT, padx=(8, 0))
        self.center_tabs.add(chapters_tab, text="Chapters")

        source_tab = ttk.Frame(self.center_tabs, padding=8)
        source_tab.rowconfigure(0, weight=1)
        source_tab.columnconfigure(0, weight=1)
        self.source_text = ScrolledText(source_tab, wrap=tk.WORD, height=12)
        self.source_text.grid(row=0, column=0, sticky="nsew")
        self.source_text.configure(state=tk.DISABLED)
        self.center_tabs.add(source_tab, text="Source")

        auth_tab = ttk.Frame(self.center_tabs, padding=8)
        auth_tab.rowconfigure(0, weight=1)
        auth_tab.columnconfigure(0, weight=1)
        self.auth_panel = SourceAuthPanel(auth_tab, self)
        self.auth_panel.grid(row=0, column=0, sticky="nsew")
        self.center_tabs.add(auth_tab, text="Auth")
        self.auth_tab = auth_tab

        reader_shell = ttk.Frame(right)
        reader_shell.grid(row=0, column=0, sticky="nsew")
        reader_shell.rowconfigure(1, weight=1)
        reader_shell.columnconfigure(0, weight=1)

        nav = ttk.Frame(reader_shell)
        nav.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(nav, text="Previous Chapter", command=self.open_previous_chapter).pack(side=tk.LEFT)
        ttk.Button(nav, text="Next Chapter", command=self.open_next_chapter).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(nav, text="Refresh Chapters", command=self.refresh_chapters).pack(side=tk.RIGHT)

        self.content_text = ScrolledText(reader_shell, wrap=tk.WORD, font=("Georgia", 13), padx=18, pady=18)
        self.content_text.grid(row=1, column=0, sticky="nsew")
        self.content_text.configure(state=tk.DISABLED)

        status = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w", padding=(8, 4))
        status.grid(row=3, column=0, sticky="ew")

    def _restore_source(self) -> None:
        source = self.controller.state.get_current_source()
        if source is None:
            return
        self.controller.set_source(source)
        self._update_source_labels(source)
        self.status_var.set("Restored previously used source.")

    def _update_source_labels(self, source: Any) -> None:
        self.source_var.set(f"{source.bookSourceName}  [{source.bookSourceUrl}]")
        self.source_path_var.set(self.controller.session.source_path or "Loaded from state")
        self.auth_button.configure(
            state=(tk.NORMAL if self.controller.has_source_auth() else tk.DISABLED)
        )
        self._set_source_text(source)

    def run(self) -> None:
        self.root.mainloop()

    def _on_close(self) -> None:
        if self._auth_dialog is not None and self._auth_dialog.winfo_exists():
            self._auth_dialog.destroy()
            self._auth_dialog = None
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def _refresh_source_views(self) -> None:
        source = self.controller.session.source
        if source is None:
            self.auth_button.configure(state=tk.DISABLED)
            return
        self._update_source_labels(source)
        self._refresh_bookshelf()

    def open_source_auth_dialog(self) -> None:
        source = self.controller.session.source
        if source is None:
            messagebox.showinfo("Login / Auth", "Load a source first.")
            return
        if not self.controller.has_source_auth():
            messagebox.showinfo("Login / Auth", "The current source has no login or auth form.")
            return
        self.auth_panel.load_current_source()
        self.center_tabs.select(self.auth_tab)

    def open_source_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Source JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self._run_task(
            f"Loading source {Path(path).name}...",
            lambda: self.controller.load_source(path),
            self._after_source_loaded,
        )

    def reload_source(self) -> None:
        if not self.controller.session.source_path:
            messagebox.showinfo("Reload Source", "No source file path is recorded for the current source.")
            return
        self._run_task("Reloading source...", self.controller.reload_source, self._after_source_loaded)

    def trigger_search(self) -> None:
        query = self.query_var.get().strip()
        if not query:
            messagebox.showinfo("Search", "Enter a query first.")
            return
        try:
            page = max(1, int(self.page_var.get().strip() or "1"))
        except ValueError:
            messagebox.showerror("Search", "Page must be an integer.")
            return
        self._run_task(
            f"Searching for {query!r}...",
            lambda: self.controller.search(query, page=page),
            self._after_search,
        )

    def apply_settings(self) -> None:
        try:
            preload_count = max(0, int(self.preload_var.get().strip() or "0"))
        except ValueError:
            messagebox.showerror("Settings", "Preload count must be an integer.")
            return
        reader_style = self.style_var.get().strip() or "comfortable"
        self.controller.update_settings(preload_count=preload_count, reader_style=reader_style)
        self.status_var.set("Reader settings updated.")

    def load_categories(self) -> None:
        self._run_task(
            "Loading categories...",
            self.controller.load_explore_kinds,
            self._after_categories_loaded,
        )

    def open_selected_result(self) -> None:
        selection = self.results_list.curselection()
        if not selection:
            return
        result = self.controller.session.search_results[selection[0]]
        self._run_task(
            f"Loading book {result.name}...",
            lambda: self.controller.open_search_result(result),
            self._after_book_loaded,
        )

    def open_selected_category(self) -> None:
        selection = self.category_list.curselection()
        if not selection:
            return
        try:
            page = max(1, int(self.page_var.get().strip() or "1"))
        except ValueError:
            messagebox.showerror("Categories", "Page must be an integer.")
            return
        kind = self.controller.session.explore_kinds[selection[0]]
        self._run_task(
            f"Loading category {kind.title or '(untitled)'}...",
            lambda: self.controller.explore(kind, page=page),
            self._after_explore_results_loaded,
        )

    def open_selected_explore_result(self) -> None:
        selection = self.explore_results_list.curselection()
        if not selection:
            return
        result = self.controller.session.explore_results[selection[0]]
        self._run_task(
            f"Loading book {result.name}...",
            lambda: self.controller.open_explore_result(result),
            self._after_book_loaded,
        )

    def open_selected_bookshelf(self) -> None:
        item_id = self._selected_bookshelf_id()
        if not item_id:
            return
        self._run_task(
            "Opening bookshelf entry...",
            lambda: self.controller.open_bookshelf_entry(item_id),
            self._after_bookshelf_book_opened,
        )

    def remove_selected_bookshelf(self) -> None:
        item_id = self._selected_bookshelf_id()
        if not item_id:
            return
        self.controller.remove_bookshelf_entry(item_id)
        self._refresh_bookshelf()
        self.status_var.set("Bookshelf entry removed.")

    def open_selected_chapter(self) -> None:
        selection = self.chapter_list.curselection()
        if not selection:
            return
        chapter_index = selection[0]
        self._run_task(
            f"Fetching chapter {chapter_index + 1}...",
            lambda: self.controller.get_chapter_content(chapter_index),
            lambda text: self._after_chapter_loaded(chapter_index, text),
        )

    def open_previous_chapter(self) -> None:
        if not self.controller.can_go_previous():
            return
        target_index = int(self.controller.session.current_chapter_index) - 1
        self._run_task(
            "Loading previous chapter...",
            self.controller.go_previous,
            lambda text: self._after_chapter_loaded(target_index, text),
        )

    def open_next_chapter(self) -> None:
        if not self.controller.can_go_next():
            return
        target_index = int(self.controller.session.current_chapter_index) + 1
        self._run_task(
            "Loading next chapter...",
            self.controller.go_next,
            lambda text: self._after_chapter_loaded(target_index, text),
        )

    def refresh_chapters(self) -> None:
        if not self.controller.session.book:
            return
        self._run_task("Refreshing chapter list...", self.controller.load_chapters, self._after_chapters_loaded)

    def resume_current_book(self) -> None:
        if not self.controller.session.book:
            messagebox.showinfo("Resume", "No active book.")
            return
        self._run_task("Resuming current book...", self.controller.resume_current_book, self._after_resume_loaded)

    def _after_source_loaded(self, source: Any) -> None:
        self._update_source_labels(source)
        self.book_var.set("No book selected")
        self.progress_var.set("No reading progress yet")
        self._set_info_text("")
        self._set_content("")
        self.results_list.delete(0, tk.END)
        self.category_list.delete(0, tk.END)
        self.explore_results_list.delete(0, tk.END)
        self.chapter_list.delete(0, tk.END)
        self.status_var.set(f"Loaded source {source.bookSourceName}. Use Categories to load discover items.")
        self._refresh_bookshelf()

    def _after_search(self, results: list[SearchBook]) -> None:
        self.results_list.delete(0, tk.END)
        for item in results:
            title = item.name or "(untitled)"
            author = item.author or "Unknown author"
            self.results_list.insert(tk.END, f"{title}  |  {author}")
        self.sidebar_tabs.select(0)
        self.status_var.set(f"Loaded {len(results)} search result(s).")

    def _after_categories_loaded(self, kinds: list[ExploreKind]) -> None:
        self.category_list.delete(0, tk.END)
        self.explore_results_list.delete(0, tk.END)
        for item in kinds:
            label = item.title or "(untitled)"
            if item.url:
                self.category_list.insert(tk.END, label)
            else:
                self.category_list.insert(tk.END, f"{label}  [no url]")
        if kinds:
            self.sidebar_tabs.select(1)
            self.status_var.set(f"Loaded {len(kinds)} category item(s).")
        else:
            self.status_var.set("No categories available for this source.")

    def _after_explore_results_loaded(self, results: list[SearchBook]) -> None:
        self.explore_results_list.delete(0, tk.END)
        for item in results:
            title = item.name or "(untitled)"
            author = item.author or "Unknown author"
            self.explore_results_list.insert(tk.END, f"{title}  |  {author}")
        self.sidebar_tabs.select(1)
        kind = self.controller.session.active_explore_kind
        kind_name = kind.title if kind and kind.title else "category"
        self.status_var.set(f"Loaded {len(results)} book(s) for {kind_name}.")

    def _after_book_loaded(self, book: Book) -> None:
        self.book_var.set(f"{book.name or '(untitled)'}  by  {book.author or 'Unknown author'}")
        self.progress_var.set("Chapter list pending")
        self._set_info_text(self._format_book_info(book))
        self._refresh_bookshelf()
        self._run_task(
            f"Loading chapters for {book.name or 'book'}...",
            self.controller.load_chapters,
            self._after_chapters_loaded,
        )

    def _after_bookshelf_book_opened(self, book: Book) -> None:
        self._after_book_loaded(book)
        self.status_var.set("Bookshelf entry opened.")

    def _after_chapters_loaded(self, chapters: list[BookChapter]) -> None:
        self.chapter_list.delete(0, tk.END)
        for chapter in chapters:
            prefix = f"{chapter.index + 1:>4}. "
            self.chapter_list.insert(tk.END, f"{prefix}{chapter.title}")
        self.center_tabs.select(1)
        self._update_progress_label()
        self.status_var.set(f"Loaded {len(chapters)} chapter(s). Double-click one to read.")

    def _after_chapter_loaded(self, chapter_index: int, text: str) -> None:
        if 0 <= chapter_index < len(self.controller.session.chapters):
            self.chapter_list.selection_clear(0, tk.END)
            self.chapter_list.selection_set(chapter_index)
            self.chapter_list.activate(chapter_index)
            chapter = self.controller.session.chapters[chapter_index]
            book_name = self.controller.session.book.name if self.controller.session.book else "(untitled)"
            self.book_var.set(f"{book_name}  |  {chapter.title}")
        self._set_content(text)
        self._restore_reader_position(chapter_index)
        self._update_progress_label()
        self.status_var.set("Chapter rendered.")
        self._refresh_bookshelf()

    def _after_resume_loaded(self, text: str) -> None:
        chapter_index = int(self.controller.session.current_chapter_index or 0)
        self._after_chapter_loaded(chapter_index, text)

    def _selected_bookshelf_id(self) -> Optional[str]:
        selection = self.bookshelf_tree.selection()
        if not selection:
            return None
        return str(selection[0])

    def _refresh_bookshelf(self) -> None:
        for item in self.bookshelf_tree.get_children():
            self.bookshelf_tree.delete(item)
        for entry in self.controller.list_bookshelf_entries():
            book = entry.get("book") or {}
            progress = entry.get("progress") or {}
            progress_text = progress.get("chapter_title") or "Unread"
            self.bookshelf_tree.insert(
                "",
                tk.END,
                iid=str(entry.get("key")),
                values=(
                    book.get("name", "(untitled)"),
                    book.get("author", "Unknown author"),
                    progress_text,
                ),
            )

    def _update_progress_label(self) -> None:
        progress = self.controller.get_current_progress()
        if not progress:
            self.progress_var.set("No reading progress yet")
            return
        chapter_title = progress.get("chapter_title") or "Unknown chapter"
        chapter_index = int(progress.get("chapter_index", 0) or 0) + 1
        chapter_total = progress.get("chapter_total") or len(self.controller.session.chapters)
        self.progress_var.set(f"Chapter {chapter_index}/{chapter_total}: {chapter_title}")

    def _format_book_info(self, book: Book) -> str:
        return "\n".join(
            [
                f"Name: {book.name or '—'}",
                f"Author: {book.author or '—'}",
                f"Kind: {book.kind or '—'}",
                f"Words: {book.wordCount or '—'}",
                f"Latest: {book.latestChapterTitle or '—'}",
                f"Cover: {book.coverUrl or '—'}",
                f"Book URL: {book.bookUrl or '—'}",
                f"TOC URL: {book.tocUrl or '—'}",
                "",
                "Intro:",
                book.intro or "—",
            ]
        )

    def _set_source_text(self, source: Any) -> None:
        source_text = "\n".join(
            [
                f"Name: {source.bookSourceName}",
                f"URL: {source.bookSourceUrl}",
                f"Search URL: {source.searchUrl or '—'}",
                f"Explore URL: {source.exploreUrl or '—'}",
                f"Concurrent Rate: {source.concurrentRate or '0'}",
                f"Cookie Jar: {source.enabledCookieJar}",
                "",
                "Rules:",
                str(source.to_dict()),
            ]
        )
        self.source_text.configure(state=tk.NORMAL)
        self.source_text.delete("1.0", tk.END)
        self.source_text.insert("1.0", source_text)
        self.source_text.configure(state=tk.DISABLED)

    def _set_info_text(self, text: str) -> None:
        self.info_text.configure(state=tk.NORMAL)
        self.info_text.delete("1.0", tk.END)
        self.info_text.insert("1.0", text)
        self.info_text.configure(state=tk.DISABLED)

    def _set_content(self, text: str) -> None:
        self.content_text.configure(state=tk.NORMAL)
        self.content_text.delete("1.0", tk.END)
        self.content_text.insert("1.0", text)
        self.content_text.see("1.0")
        self.content_text.configure(state=tk.DISABLED)
        self._last_saved_scroll_ratio = None

    def _restore_reader_position(self, chapter_index: int) -> None:
        progress = self.controller.get_current_progress() or {}
        progress_index_raw = progress.get("chapter_index")
        progress_index = int(progress_index_raw) if progress_index_raw is not None else -1
        if progress_index != chapter_index:
            return
        scroll_ratio = max(0.0, min(1.0, float(progress.get("scroll_ratio", 0.0) or 0.0)))
        self.content_text.yview_moveto(scroll_ratio)
        self._last_saved_scroll_ratio = scroll_ratio

    def _run_task(
        self,
        status_text: str,
        func: Callable[[], Any],
        on_success: Callable[[Any], None],
        *,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        self.status_var.set(status_text)

        def worker() -> None:
            try:
                result = func()
            except Exception as exc:
                self._task_queue.put(("error", (on_error, exc)))
            else:
                self._task_queue.put(("success", (on_success, result)))

        self._executor.submit(worker)

    def _poll_tasks(self) -> None:
        while True:
            try:
                kind, payload = self._task_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "error":
                self.status_var.set("Operation failed.")
                callback, exc = payload
                if callback is not None:
                    callback(exc)
                else:
                    messagebox.showerror("LegadoPy Reader", str(exc))
            elif kind == "success":
                callback, result = payload
                callback(result)
        self.root.after(100, self._poll_tasks)

    def _poll_reader_progress(self) -> None:
        if self.controller.session.book and self.controller.get_current_chapter() is not None:
            first, _last = self.content_text.yview()
            if self._last_saved_scroll_ratio is None or abs(first - self._last_saved_scroll_ratio) >= 0.01:
                self.controller.update_current_scroll(first)
                self._last_saved_scroll_ratio = first
        self.root.after(750, self._poll_reader_progress)


def launch_gui() -> None:
    ReaderDesktopApp().run()
