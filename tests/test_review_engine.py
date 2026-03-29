import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine import (  # noqa: E402
    Book,
    BookChapter,
    BookSource,
    ReplaceRule,
    ReviewRule,
    LegadoEngine,
    get_reviews,
)


def data_url(text: str) -> str:
    return "data:text/html;base64," + base64.b64encode(text.encode("utf-8")).decode("ascii")


class ReviewEngineTests(unittest.TestCase):
    def test_get_reviews_fetches_and_parses_review_entries(self) -> None:
        quote_url = data_url("<html><body>quote</body></html>")
        reviews_url = data_url(
            "<html><body>"
            f"<div class='review'><img src='/avatar-a.jpg'><p class='content'>foo one</p><span class='time'>2026-03-29</span><a class='quote' href='{quote_url}'>q</a></div>"
            "<div class='review'><img src='/avatar-b.jpg'><p class='content'>foo two</p><span class='time'>2026-03-30</span></div>"
            "</body></html>"
        )
        engine = LegadoEngine()
        engine.add_replace_rule(ReplaceRule(name="review-content", pattern="foo", replacement="bar", scopeTitle=False, scopeContent=True))
        source = BookSource(
            bookSourceUrl="https://example.com",
            bookSourceName="demo",
            ruleReview=ReviewRule(
                reviewUrl=reviews_url,
                avatarRule="@CSS:.review img@src",
                contentRule="@CSS:.review .content@text",
                postTimeRule="@CSS:.review .time@text",
                reviewQuoteUrl="@CSS:.review .quote@href",
            ),
        )
        book = Book(bookUrl="https://example.com/book", origin=source.bookSourceUrl)
        chapter = BookChapter(bookUrl=book.bookUrl, index=0, url="https://example.com/chapter-1", title="c1")

        reviews = get_reviews(source, book, chapter, engine=engine)

        self.assertEqual(len(reviews), 2)
        self.assertEqual(reviews[0].avatar, "https://example.com/avatar-a.jpg")
        self.assertEqual(reviews[0].content, "bar one")
        self.assertEqual(reviews[0].postTime, "2026-03-29")
        self.assertEqual(reviews[0].quoteUrl, quote_url)
        self.assertEqual(reviews[1].avatar, "https://example.com/avatar-b.jpg")
        self.assertEqual(reviews[1].content, "bar two")
        self.assertEqual(reviews[1].postTime, "2026-03-30")
        self.assertEqual(reviews[1].quoteUrl, "")


if __name__ == "__main__":
    unittest.main()
