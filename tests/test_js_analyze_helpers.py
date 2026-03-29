import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine import AnalyzeRule, Book, BookSource, LegadoEngine  # noqa: E402


class JsAnalyzeHelperTests(unittest.TestCase):
    def test_execjs_analyze_helpers_match_analyze_rule_behavior(self) -> None:
        engine = LegadoEngine()
        source = BookSource(bookSourceUrl="https://example.com", bookSourceName="demo")
        book = Book(bookUrl="https://example.com/book")
        analyze_rule = AnalyzeRule(book, source, engine=engine)
        analyze_rule.set_content(
            "<div class='item'><a href='/book-a'>One</a></div>"
            "<div class='item'><a href='/book-b'>Two</a></div>",
            base_url="https://example.com/base/",
        )
        analyze_rule.set_redirect_url("https://example.com/base/")
        result = analyze_rule.eval_js(
            """
var firstHref = java.getString("@CSS:.item a@href", null, true);
var names = java.getStringList("@CSS:.item a@text");
var firstElement = java.getElement("@CSS:.item");
var innerName = java.getString("@CSS:a@text", firstElement);
var count = java.getElements("@CSS:.item").length;
java.setContent("<div id='changed'>Changed</div>", "https://example.com/other/");
var changed = java.getString("@CSS:#changed@text");
firstHref + "|" + names.join(",") + "|" + innerName + "|" + count + "|" + changed;
""",
        )
        href, names, inner_name, count, changed = str(result).split("|")
        self.assertEqual(href, "https://example.com/book-a")
        self.assertEqual(names, "One,Two")
        self.assertEqual(inner_name, "One")
        self.assertEqual(count, "2")
        self.assertEqual(changed, "Changed")


if __name__ == "__main__":
    unittest.main()
