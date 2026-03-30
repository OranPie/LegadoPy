import base64
import dataclasses
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine import (  # noqa: E402
    AnalyzeUrl,
    Book,
    BookChapter,
    BookSource,
    ContentRule,
    LegadoEngine,
    ReplaceRule,
    UnsupportedHeadlessOperation,
    get_book_info,
    get_content,
)
from legado_engine.js import JsExtensions, eval_js  # noqa: E402


def data_url(text: str) -> str:
    return "data:text/html;base64," + base64.b64encode(text.encode("utf-8")).decode("ascii")


class HeadlessCoreTests(unittest.TestCase):
    def test_book_and_search_models_keep_ui_string_fields_defined(self) -> None:
        book = Book()
        search = book.to_search_book()

        self.assertEqual(book.kind, "")
        self.assertEqual(book.intro, "")
        self.assertEqual(book.coverUrl, "")
        self.assertEqual(book.latestChapterTitle, "")
        self.assertEqual(search.kind, "")
        self.assertEqual(search.intro, "")
        self.assertEqual(search.coverUrl, "")
        self.assertEqual(search.latestChapterTitle, "")
        self.assertEqual(dataclasses.asdict(search)["kind"], "")

    def test_get_book_info_skips_inline_marker_payload(self) -> None:
        source = BookSource(
            bookSourceUrl="https://example.com/source",
            bookSourceName="Demo Source",
        )
        marker_payload = {
            "book_id": "123",
            "sources": "Demo",
            "tab": "小说",
            "url": "",
        }
        book = Book(
            bookUrl="data:;base64," + base64.b64encode(
                json.dumps(marker_payload, ensure_ascii=False).encode("utf-8")
            ).decode("ascii") + ',{"type":"qingtian"}',
            name="Inline Marker Book",
            author="Author",
            kind="连载中,测试",
            intro="search intro",
            latestChapterTitle="search latest",
        )

        with patch("legado_engine.web_book.web_book.analyze_book_info", side_effect=AssertionError("should skip detail analysis")):
            hydrated = get_book_info(source, book)

        self.assertIs(hydrated, book)
        self.assertEqual(hydrated.name, "Inline Marker Book")
        self.assertEqual(hydrated.author, "Author")
        self.assertEqual(hydrated.latestChapterTitle, "search latest")
        self.assertEqual(hydrated.tocUrl, hydrated.bookUrl)

    def test_cache_persists_across_js_calls(self) -> None:
        engine = LegadoEngine()
        java = JsExtensions(engine=engine)
        self.assertEqual(eval_js("cache.put('token', 'abc'); cache.get('token')", bindings={"engine": engine}, java_obj=java), "abc")
        self.assertEqual(eval_js("cache.get('token')", bindings={"engine": engine}, java_obj=java), "abc")

    def test_book_can_disable_replace_rules_via_js(self) -> None:
        engine = LegadoEngine()
        book = Book(name="demo")
        java = JsExtensions(engine=engine)
        eval_js("book.setUseReplaceRule(false)", bindings={"book": book, "engine": engine}, java_obj=java)
        self.assertFalse(book.get_use_replace_rule())

    def test_unsupported_browser_operations_raise(self) -> None:
        engine = LegadoEngine()
        with self.assertRaises(UnsupportedHeadlessOperation):
            eval_js("java.startBrowser('https://example.com')", bindings={"engine": engine}, java_obj=JsExtensions(engine=engine))

    def test_android_id_is_available_in_headless_mode(self) -> None:
        engine = LegadoEngine()
        java = JsExtensions(engine=engine)

        android_id = eval_js("java.androidId()", bindings={"engine": engine}, java_obj=java)
        device_id = eval_js("java.deviceID()", bindings={"engine": engine}, java_obj=java)

        self.assertEqual(android_id, engine.android_id)
        self.assertEqual(device_id, engine.device_id)
        self.assertTrue(android_id)
        self.assertTrue(device_id)

    def test_analyze_url_rejects_webview_requests(self) -> None:
        analyze_url = AnalyzeUrl("https://example.com, {\"webView\": true}", engine=LegadoEngine())
        with self.assertRaises(UnsupportedHeadlessOperation):
            analyze_url.get_str_response()

    def test_content_pipeline_applies_title_and_content_rules(self) -> None:
        engine = LegadoEngine()
        engine.add_replace_rule(ReplaceRule(name="title", pattern="Chapter", replacement="Ch", scopeTitle=True, scopeContent=False))
        engine.add_replace_rule(ReplaceRule(name="content", pattern="foo", replacement="bar", scopeTitle=False, scopeContent=True))

        page_two = data_url("<html><body><div id='content'>foo two</div></body></html>")
        page_one = data_url(
            f"<html><body><h1>Chapter 1</h1><div id='content'>foo one</div>"
            f"<a id='next' href='{page_two}'>next</a></body></html>"
        )
        source = BookSource(
            bookSourceUrl="https://example.com",
            bookSourceName="demo",
            ruleContent=ContentRule(
                content="@CSS:#content@text",
                title="@CSS:h1@text",
                nextContentUrl="@CSS:#next@href",
            ),
        )
        book = Book(bookUrl="https://example.com/book", origin="https://example.com")
        chapter = BookChapter(bookUrl=book.bookUrl, index=0, url=page_one, title="orig")

        content = get_content(source, book, chapter, engine=engine)

        self.assertEqual(chapter.title, "Ch 1")
        self.assertIn("bar one", content)
        self.assertIn("bar two", content)


if __name__ == "__main__":
    unittest.main()
