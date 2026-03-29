#!/usr/bin/env python3
"""
legado-cli – Command-line interface for the Legado Python engine.

Commands:
  search    Search books in a source
  info      Fetch book metadata
  chapters  List table of contents
  content   Fetch chapter content
  explore   Browse explore/discovery pages
  categories List discover/category buttons from a source
  sources   List / validate book sources from a JSON array file

Usage examples:
  python cli.py search  source.json "斗破苍穹"
  python cli.py info    source.json "https://book.qidian.com/info/1234"
  python cli.py chapters source.json "https://book.qidian.com/info/1234"
  python cli.py content  source.json "https://chapter.url"
  python cli.py explore    source.json "https://explore.url"
  python cli.py categories source.json
  python cli.py sources    sources_array.json
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path
from typing import List, Optional

# Allow running as a script from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

import legado_engine as le
from legado_engine import (
    BookSource, Book, BookChapter,
    search_book, get_book_info, get_chapter_list, get_content, explore_book,
    get_explore_kinds,
)

console = Console()


# ─── helpers ─────────────────────────────────────────────────────────────────

def load_source(path: str) -> BookSource:
    raw = Path(path).read_text(encoding="utf-8")
    try:
        return BookSource.from_json(raw)
    except Exception:
        # Maybe it's a JSON array – take the first item
        arr = json.loads(raw)
        if isinstance(arr, list) and arr:
            return BookSource.from_dict(arr[0])
        raise


def spinner(msg: str):
    return Progress(
        SpinnerColumn(),
        TextColumn(f"[cyan]{msg}[/cyan]"),
        transient=True,
        console=console,
    )


# ─── commands ────────────────────────────────────────────────────────────────

def cmd_search(args):
    src = load_source(args.source)
    console.print(f"[bold]Source:[/bold] {src.bookSourceName}  [dim]{src.bookSourceUrl}[/dim]")

    with spinner(f"Searching for '{args.query}' (page {args.page})…"):
        results = search_book(src, args.query, page=args.page)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    t = Table(title=f"Search: {args.query!r}", box=box.ROUNDED, show_lines=False)
    t.add_column("#", style="dim", width=3)
    t.add_column("Name", style="bold green", min_width=20)
    t.add_column("Author", style="cyan", min_width=12)
    t.add_column("Kind", style="dim")
    t.add_column("Latest Chapter", style="dim", max_width=30)
    t.add_column("URL", style="blue dim", overflow="fold")

    for i, r in enumerate(results, 1):
        t.add_row(
            str(i),
            r.name or "",
            r.author or "",
            r.kind or "",
            (r.latestChapterTitle or "")[:40],
            r.bookUrl or "",
        )
    console.print(t)


def cmd_info(args):
    src = load_source(args.source)
    book = Book()
    book.bookUrl = args.url
    book.origin = src.bookSourceUrl

    with spinner(f"Fetching book info from {args.url}…"):
        book = get_book_info(src, book, can_rename=True)

    console.print(Panel(
        Text.assemble(
            ("Name:     ", "bold"), (book.name or "—", "green"), "\n",
            ("Author:   ", "bold"), (book.author or "—", "cyan"), "\n",
            ("Kind:     ", "bold"), (book.kind or "—", ""), "\n",
            ("Words:    ", "bold"), (book.wordCount or "—", ""), "\n",
            ("Latest:   ", "bold"), (book.latestChapterTitle or "—", ""), "\n",
            ("Cover:    ", "bold"), (book.coverUrl or "—", "blue"), "\n",
            ("TOC URL:  ", "bold"), (book.tocUrl or "—", "blue"), "\n",
            ("Intro:\n", "bold"),
            (textwrap.fill(book.intro or "—", width=70), "dim"),
        ),
        title=f"[bold]{book.name}[/bold]",
        border_style="green",
    ))


def cmd_chapters(args):
    src = load_source(args.source)
    book = Book()
    book.bookUrl = args.url
    book.origin = src.bookSourceUrl

    with spinner("Fetching book info…"):
        book = get_book_info(src, book)

    with spinner(f"Fetching chapter list for '{book.name}'…"):
        chapters = get_chapter_list(src, book)

    t = Table(
        title=f"Chapters: {book.name} ({len(chapters)} total)",
        box=box.SIMPLE_HEAVY, show_lines=False,
    )
    t.add_column("#", style="dim", width=5)
    t.add_column("Title", style="bold", min_width=30)
    t.add_column("VIP", width=3)
    t.add_column("URL", style="blue dim", overflow="fold")

    # Show a window around --start / --end
    start = max(0, args.start - 1) if args.start else 0
    end = min(len(chapters), args.end) if args.end else len(chapters)
    for ch in chapters[start:end]:
        t.add_row(
            str(ch.index + 1),
            ch.title or "",
            "✓" if ch.isVip else "",
            ch.url or "",
        )
    console.print(t)
    if args.end and args.end < len(chapters):
        console.print(f"[dim]… {len(chapters) - args.end} more chapters[/dim]")


def cmd_content(args):
    src = load_source(args.source)

    book = Book()
    book.origin = src.bookSourceUrl

    # Build a minimal chapter
    ch = BookChapter()
    ch.url = args.url
    ch.title = args.title or args.url
    ch.bookUrl = args.book_url or args.url

    with spinner(f"Fetching content: {ch.title}…"):
        text = get_content(src, book, ch)

    if args.raw:
        console.print(text)
    else:
        lines = text.splitlines()
        wrapped = "\n".join(
            textwrap.fill(ln, width=console.width - 4) if ln.strip() else ""
            for ln in lines
        )
        console.print(Panel(
            wrapped,
            title=f"[bold]{ch.title}[/bold]",
            border_style="cyan",
            padding=(1, 2),
        ))


def cmd_explore(args):
    src = load_source(args.source)
    console.print(f"[bold]Source:[/bold] {src.bookSourceName}")

    with spinner(f"Exploring {args.url}…"):
        results = explore_book(src, args.url, page=args.page)

    if not results:
        console.print("[yellow]No results.[/yellow]")
        return

    t = Table(title=f"Explore: {args.url}", box=box.ROUNDED)
    t.add_column("#", style="dim", width=3)
    t.add_column("Name", style="bold green", min_width=20)
    t.add_column("Author", style="cyan", min_width=12)
    t.add_column("Kind", style="dim")
    t.add_column("URL", style="blue dim", overflow="fold")

    for i, r in enumerate(results, 1):
        t.add_row(str(i), r.name or "", r.author or "", r.kind or "", r.bookUrl or "")
    console.print(t)


def cmd_categories(args):
    src = load_source(args.source)
    console.print(f"[bold]Source:[/bold] {src.bookSourceName}")

    with spinner("Loading discover/category buttons…"):
        kinds = get_explore_kinds(src)

    if not kinds:
        console.print("[yellow]No categories or function buttons found.[/yellow]")
        return

    t = Table(title=f"Discover: {src.bookSourceName}", box=box.ROUNDED)
    t.add_column("#", style="dim", width=3)
    t.add_column("Title", style="bold green", min_width=20)
    t.add_column("URL", style="blue dim", overflow="fold")
    t.add_column("Styled", width=6)

    for i, kind in enumerate(kinds, 1):
        t.add_row(
            str(i),
            kind.title or "",
            kind.url or "",
            "✓" if kind.style else "",
        )
    console.print(t)


def cmd_sources(args):
    raw = Path(args.file).read_text(encoding="utf-8")
    data = json.loads(raw)
    items = data if isinstance(data, list) else [data]

    t = Table(title=f"Book Sources ({len(items)})", box=box.ROUNDED)
    t.add_column("#", style="dim", width=4)
    t.add_column("Name", style="bold", min_width=20)
    t.add_column("URL", style="blue", min_width=25)
    t.add_column("Type", width=5)
    t.add_column("Search", width=6)
    t.add_column("Explore", width=7)
    t.add_column("Enabled", width=7)

    for i, item in enumerate(items, 1):
        src = BookSource.from_dict(item)
        t.add_row(
            str(i),
            src.bookSourceName or "",
            src.bookSourceUrl or "",
            str(src.bookSourceType or 0),
            "✓" if src.searchUrl else "✗",
            "✓" if src.exploreUrl else "✗",
            "✗" if src.enabled is False else "✓",
        )
    console.print(t)


# ─── argument parser ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="legado-cli",
        description="Legado book-scraping engine – command line interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # search
    ps = sub.add_parser("search", help="Search books")
    ps.add_argument("source", help="Path to BookSource JSON file")
    ps.add_argument("query", help="Search keyword")
    ps.add_argument("--page", type=int, default=1, metavar="N")

    # info
    pi = sub.add_parser("info", help="Fetch book metadata")
    pi.add_argument("source", help="Path to BookSource JSON file")
    pi.add_argument("url", help="Book detail URL")

    # chapters
    pc = sub.add_parser("chapters", help="List table of contents")
    pc.add_argument("source", help="Path to BookSource JSON file")
    pc.add_argument("url", help="Book URL (detail page)")
    pc.add_argument("--start", type=int, default=None, metavar="N")
    pc.add_argument("--end",   type=int, default=50,  metavar="N")

    # content
    pct = sub.add_parser("content", help="Fetch chapter content")
    pct.add_argument("source",    help="Path to BookSource JSON file")
    pct.add_argument("url",       help="Chapter URL")
    pct.add_argument("--title",   default=None)
    pct.add_argument("--book-url", dest="book_url", default=None)
    pct.add_argument("--raw",     action="store_true", help="Print raw text")

    # explore
    pe = sub.add_parser("explore", help="Browse discover/explore page")
    pe.add_argument("source", help="Path to BookSource JSON file")
    pe.add_argument("url", help="Explore URL (or one from discover categories)")
    pe.add_argument("--page", type=int, default=1, metavar="N")

    # categories
    pcat = sub.add_parser("categories", help="List discover/category buttons")
    pcat.add_argument("source", help="Path to BookSource JSON file")

    # sources
    psr = sub.add_parser("sources", help="List sources from a JSON array file")
    psr.add_argument("file", help="Path to sources JSON array file")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    dispatch = {
        "search":   cmd_search,
        "info":     cmd_info,
        "chapters": cmd_chapters,
        "content":  cmd_content,
        "explore":    cmd_explore,
        "categories": cmd_categories,
        "sources":    cmd_sources,
    }
    try:
        dispatch[args.command](args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print_exception(show_locals=False)
        sys.exit(1)


if __name__ == "__main__":
    main()
