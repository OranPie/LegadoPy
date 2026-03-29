import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine import Book, BookChapter, BookSource, ExploreKind, SearchBook  # noqa: E402
from legado_engine.source_login import SourceUiActionResult  # noqa: E402
from legado_gui import ReaderController, load_source_file  # noqa: E402
from reader_state import ReaderState  # noqa: E402


class GuiPackageTests(unittest.TestCase):
    def test_load_source_file_accepts_json_array(self) -> None:
        payload = [
            {
                "bookSourceUrl": "https://example.com",
                "bookSourceName": "Demo Source",
                "searchUrl": "https://example.com/search?q={{searchKey}}",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "source.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            source = load_source_file(path)
        self.assertEqual(source.bookSourceName, "Demo Source")
        self.assertEqual(source.bookSourceUrl, "https://example.com")

    def test_controller_uses_cached_chapter_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)
            source = BookSource(bookSourceUrl="https://example.com", bookSourceName="Demo")
            controller.set_source(source)
            controller.session.book = Book(bookUrl="https://example.com/book", name="Book")
            controller.session.chapters = [
                BookChapter(bookUrl="https://example.com/book", index=0, url="https://example.com/ch-1", title="Ch 1")
            ]
            chapter = controller.session.chapters[0]
            state.set_cached_content(source, controller.session.book, chapter, "cached body")

            with patch("legado_gui.controller.get_content", side_effect=AssertionError("should not fetch")):
                text = controller.get_chapter_content(0)

        self.assertEqual(text, "cached body")

    def test_controller_bookshelf_round_trip_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)
            source = BookSource(bookSourceUrl="https://example.com/source", bookSourceName="Demo")
            controller.set_source(source, source_path="/tmp/demo-source.json")
            book = Book(bookUrl="https://example.com/book", name="Book", author="Author")

            with patch("legado_gui.controller.get_book_info", return_value=book):
                controller.open_book(book)

            entries = controller.list_bookshelf_entries()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["book"]["name"], "Book")

            restored = controller.open_bookshelf_entry(entries[0]["key"])

            self.assertEqual(restored.name, "Book")
            self.assertIsNone(controller.session.source_path)
            self.assertEqual(controller.session.source.bookSourceUrl, "https://example.com/source")

            controller.remove_bookshelf_entry(entries[0]["key"])
            self.assertEqual(controller.list_bookshelf_entries(), [])

    def test_controller_loads_categories_and_explore_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)
            source = BookSource(bookSourceUrl="https://example.com/source", bookSourceName="Demo")
            controller.set_source(source)
            kinds = [ExploreKind(title="Hot", url="https://example.com/hot")]
            results = [
                SearchBook(
                    bookUrl="https://example.com/book-1",
                    name="Book 1",
                    author="Author 1",
                )
            ]

            with patch("legado_gui.controller.get_explore_kinds", return_value=kinds):
                loaded_kinds = controller.load_explore_kinds()
            with patch("legado_gui.controller.explore_book", return_value=results):
                loaded_results = controller.explore(kinds[0], page=2)

            self.assertEqual(loaded_kinds, kinds)
            self.assertEqual(controller.session.explore_kinds, kinds)
            self.assertEqual(loaded_results, results)
            self.assertEqual(controller.session.active_explore_kind, kinds[0])
            self.assertEqual(controller.session.explore_results, results)

    def test_controller_caches_search_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)
            source = BookSource(bookSourceUrl="https://example.com/source", bookSourceName="Demo")
            controller.set_source(source)
            results = [SearchBook(bookUrl="https://example.com/book", name="Book", author="Author")]

            with patch("legado_gui.controller.search_book", return_value=results) as mock_search:
                first = controller.search("demo", page=1)
                second = controller.search("demo", page=1)

            self.assertEqual(mock_search.call_count, 1)
            self.assertEqual(first[0].name, "Book")
            self.assertEqual(second[0].name, "Book")
            self.assertIsNot(first, second)

    def test_controller_caches_explore_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)
            source = BookSource(bookSourceUrl="https://example.com/source", bookSourceName="Demo")
            controller.set_source(source)
            kind = ExploreKind(title="Hot", url="https://example.com/hot")
            results = [SearchBook(bookUrl="https://example.com/book", name="Book", author="Author")]

            with patch("legado_gui.controller.explore_book", return_value=results) as mock_explore:
                first = controller.explore(kind, page=1)
                second = controller.explore(kind, page=1)

            self.assertEqual(mock_explore.call_count, 1)
            self.assertEqual(first[0].name, "Book")
            self.assertEqual(second[0].name, "Book")
            self.assertIsNot(first, second)

    def test_controller_opens_explore_result_via_book_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)
            source = BookSource(bookSourceUrl="https://example.com/source", bookSourceName="Demo")
            controller.set_source(source)
            result = SearchBook(bookUrl="https://example.com/book", name="Book", author="Author")
            hydrated = Book(bookUrl="https://example.com/book", name="Book", author="Author")

            with patch("legado_gui.controller.get_book_info", return_value=hydrated):
                opened = controller.open_explore_result(result)

            self.assertEqual(opened.name, "Book")
            self.assertEqual(controller.session.book, hydrated)

    def test_controller_caches_book_info_and_chapter_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)
            source = BookSource(bookSourceUrl="https://example.com/source", bookSourceName="Demo")
            controller.set_source(source)
            book = Book(bookUrl="https://example.com/book", name="Book", author="Author", tocUrl="https://example.com/toc")
            chapter = BookChapter(
                bookUrl="https://example.com/book",
                index=0,
                url="https://example.com/ch-1",
                title="Chapter 1",
            )

            with patch("legado_gui.controller.get_book_info", return_value=book) as mock_book_info:
                opened_first = controller.open_book(Book(bookUrl=book.bookUrl, name="Book", author="Author"))
                opened_second = controller.open_book(Book(bookUrl=book.bookUrl, name="Book", author="Author"))
            with patch("legado_gui.controller.get_chapter_list", return_value=[chapter]) as mock_chapters:
                chapters_first = controller.load_chapters()
                chapters_second = controller.load_chapters()

            self.assertEqual(mock_book_info.call_count, 1)
            self.assertEqual(mock_chapters.call_count, 1)
            self.assertEqual(opened_first.name, "Book")
            self.assertEqual(opened_second.name, "Book")
            self.assertEqual(chapters_first[0].title, "Chapter 1")
            self.assertEqual(chapters_second[0].title, "Chapter 1")

    def test_resume_current_book_preserves_saved_scroll_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)
            source = BookSource(bookSourceUrl="https://example.com/source", bookSourceName="Demo")
            book = Book(bookUrl="https://example.com/book", name="Book")
            chapter = BookChapter(
                bookUrl="https://example.com/book",
                index=0,
                url="https://example.com/ch-1",
                title="Chapter 1",
            )
            controller.set_source(source)
            controller.session.book = book
            controller.session.chapters = [chapter]
            state.remember_book(source, book)
            state.update_progress(
                source,
                book,
                chapter,
                scroll_y=0.45,
                max_scroll_y=1.0,
                total_chapters=1,
            )

            with patch("legado_gui.controller.get_content", return_value="chapter body"):
                text = controller.resume_current_book()

            self.assertEqual(text, "chapter body")
            progress = controller.get_current_progress()
            self.assertIsNotNone(progress)
            self.assertAlmostEqual(progress["scroll_ratio"], 0.45)
            self.assertEqual(progress["chapter_index"], 0)

    def test_update_current_scroll_updates_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)
            source = BookSource(bookSourceUrl="https://example.com/source", bookSourceName="Demo")
            book = Book(bookUrl="https://example.com/book", name="Book")
            chapter = BookChapter(
                bookUrl="https://example.com/book",
                index=0,
                url="https://example.com/ch-1",
                title="Chapter 1",
            )
            controller.set_source(source)
            controller.session.book = book
            controller.session.chapters = [chapter]
            state.remember_book(source, book)

            with patch("legado_gui.controller.get_content", return_value="chapter body"):
                controller.get_chapter_content(0)
            progress = controller.update_current_scroll(1.5)

            self.assertIsNotNone(progress)
            self.assertEqual(progress["chapter_index"], 0)
            self.assertEqual(progress["max_scroll_y"], 1.0)
            self.assertAlmostEqual(progress["scroll_ratio"], 1.0)

    def test_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)

            controller.update_settings(preload_count=5, reader_style="focus")

            self.assertEqual(
                controller.get_settings(),
                {"reader_style": "focus", "preload_count": 5},
            )

    def test_controller_exposes_source_auth_rows_and_saved_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)
            source = BookSource(
                bookSourceUrl="https://example.com/source",
                bookSourceName="Demo",
                loginUrl="function login() { return 'ok'; }",
            )
            source.putLoginInfo(json.dumps({"邮箱": "demo@example.com"}, ensure_ascii=False))
            controller.set_source(source)

            rows = controller.get_source_auth_rows()
            form_data = controller.get_source_auth_form_data()

            self.assertTrue(controller.has_source_auth())
            self.assertEqual([row.name for row in rows], ["邮箱", "密码", "密钥", "自定义服务器(可不填)"])
            self.assertEqual(form_data["邮箱"], "demo@example.com")

    def test_controller_submit_source_auth_persists_current_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ReaderState(Path(tmpdir))
            controller = ReaderController(state=state)
            source = BookSource(
                bookSourceUrl="https://example.com/source",
                bookSourceName="Demo",
                loginUrl="function login() { return 'ok'; }",
            )
            controller.set_source(source)
            outcome = SourceUiActionResult(message="authenticated")

            with patch("legado_gui.controller.submit_source_form_detailed", return_value=outcome) as mock_submit:
                result = controller.submit_source_auth({"邮箱": "demo@example.com", "密码": "secret"})

            saved = state.get_current_source()
            self.assertEqual(result.message, "authenticated")
            self.assertEqual(mock_submit.call_count, 1)
            self.assertIsNotNone(saved)
            self.assertEqual(saved.bookSourceUrl, "https://example.com/source")


if __name__ == "__main__":
    unittest.main()
