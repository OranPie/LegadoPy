#!/usr/bin/env python3
"""
demo.py – Quick demonstration of legado_engine.

Usage:
    python3 examples/demo.py                        # uses bundled test source
    python3 examples/demo.py <source.json> <query>  # uses your source JSON
"""
import sys
import json
import textwrap
from pathlib import Path

# Add project root to path when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import legado_engine as le
from legado_engine import BookSource, search_book, get_book_info, get_chapter_list, get_content

# ─── Minimal test source (fanqienovel public search) ─────────────────────────
SAMPLE_SOURCE_JSON = r"""
{
  "bookSourceUrl": "https://fanqienovel.com",
  "bookSourceName": "番茄小说 (demo)",
  "bookSourceType": 0,
  "searchUrl": "https://fanqienovel.com/api/author/search/search_book/v1/?query={{searchKey}}&page_count=10&page_index={{searchPage}}",
  "ruleSearch": {
    "bookList": "$.data.search_book_data[*]",
    "name": "$.book_name",
    "author": "$.author",
    "coverUrl": "$.thumb_url",
    "intro": "$.abstract",
    "bookUrl": "https://fanqienovel.com/page/{{$.item_id}}"
  },
  "ruleBookInfo": {
    "name": "$.data.book_info.book_name",
    "author": "$.data.book_info.author",
    "coverUrl": "$.data.book_info.thumb_url",
    "intro": "$.data.book_info.abstract",
    "tocUrl": "https://fanqienovel.com/api/reader/directory/detail?book_id={{book_id}}"
  }
}
"""


def demo_parse_source():
    """Demonstrate source parsing without network calls."""
    print("=" * 60)
    print("1. Parse BookSource from JSON")
    print("=" * 60)
    source = BookSource.from_json(SAMPLE_SOURCE_JSON)
    print(f"  Source URL : {source.bookSourceUrl}")
    print(f"  Source Name: {source.bookSourceName}")
    print(f"  Search URL : {source.searchUrl}")
    sr = source.get_search_rule()
    print(f"  BookList   : {sr.bookList}")
    print(f"  Name rule  : {sr.name}")
    print()


def demo_rule_parsing():
    """Demonstrate AnalyzeRule on a static HTML snippet."""
    print("=" * 60)
    print("2. AnalyzeRule – CSS selector on static HTML")
    print("=" * 60)
    from legado_engine import AnalyzeRule, Book

    html = """
    <html><body>
      <div class="book-list">
        <div class="item">
          <a class="title" href="/book/1">修真聊天群</a>
          <span class="author">圣骑士的传说</span>
        </div>
        <div class="item">
          <a class="title" href="/book/2">我的治愈系游戏</a>
          <span class="author">月色星辰</span>
        </div>
      </div>
    </body></html>
    """
    book = Book()
    ar = AnalyzeRule(book)
    ar.set_content(html).set_base_url("https://example.com")

    # Legado rule syntax: selector@attr  (no attr = element node, need @text for text)
    titles  = ar.get_string_list("@CSS:.item .title@text")
    authors = ar.get_string_list("@CSS:.item .author@text")
    urls    = ar.get_string_list("@CSS:.item .title@href", is_url=True)

    print(f"  Titles  : {titles}")
    print(f"  Authors : {authors}")
    print(f"  URLs    : {urls}")
    print()


def demo_jsonpath():
    """Demonstrate JSON parsing via AnalyzeRule."""
    print("=" * 60)
    print("3. AnalyzeRule – JSONPath on API response")
    print("=" * 60)
    from legado_engine import AnalyzeRule, Book

    data = json.dumps({
        "code": 0,
        "data": {
            "list": [
                {"name": "书名甲", "author": "作者A", "url": "https://x.com/1"},
                {"name": "书名乙", "author": "作者B", "url": "https://x.com/2"},
            ]
        }
    })
    book = Book()
    ar = AnalyzeRule(book)
    ar.set_content(data).set_base_url("https://x.com")

    names   = ar.get_string_list("$.data.list[*].name")
    authors = ar.get_string_list("$.data.list[*].author")
    print(f"  Names  : {names}")
    print(f"  Authors: {authors}")
    print()


def demo_live_search(source_json_path: str, query: str):
    """Live search using a provided source JSON file."""
    print("=" * 60)
    print(f"4. Live search: query='{query}'")
    print("=" * 60)
    with open(source_json_path) as f:
        raw = f.read()
    source = BookSource.from_json(raw)
    print(f"  Source: {source.bookSourceName}")
    try:
        results = search_book(source, query)
        for i, r in enumerate(results[:5], 1):
            print(f"  [{i}] {r.name} – {r.author}")
            print(f"       {r.bookUrl}")
    except Exception as e:
        print(f"  Error: {e}")
    print()


if __name__ == "__main__":
    demo_parse_source()
    demo_rule_parsing()
    demo_jsonpath()

    if len(sys.argv) >= 3:
        demo_live_search(sys.argv[1], sys.argv[2])
    else:
        print("Tip: pass <source.json> <query> for a live search demo.")
