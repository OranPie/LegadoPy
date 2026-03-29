import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine import LegadoEngine, RssSource, ReplaceRule, get_rss_article_content, get_rss_articles  # noqa: E402


def data_url(text: str) -> str:
    return "data:text/html;base64," + base64.b64encode(text.encode("utf-8")).decode("ascii")


class RssEngineTests(unittest.TestCase):
    def test_rss_article_list_and_detail(self) -> None:
        engine = LegadoEngine()
        engine.add_replace_rule(ReplaceRule(name="rss-title", pattern="Title", replacement="Headline", scopeTitle=True, scopeContent=False))
        engine.add_replace_rule(ReplaceRule(name="rss-content", pattern="foo", replacement="bar", scopeTitle=False, scopeContent=True))

        detail = data_url("<html><body><article><h1>Title A</h1><div class='content'>foo article body</div></article></body></html>")
        feed = data_url(
            f"<html><body><div class='item'><a class='title' href='{detail}'>Title A</a>"
            "<span class='date'>2026-03-29</span><p class='desc'>foo summary</p></div></body></html>"
        )
        source = RssSource(
            sourceUrl=feed,
            sourceName="Feed",
            ruleArticles="@CSS:.item",
            ruleTitle="@CSS:.title@text",
            ruleLink="@CSS:.title@href",
            rulePubDate="@CSS:.date@text",
            ruleDescription="@CSS:.desc@text",
            ruleContent="@CSS:.content@text",
        )

        articles = get_rss_articles(source, engine=engine)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Headline A")
        self.assertEqual(articles[0].pubDate, "2026-03-29")

        article = get_rss_article_content(source, articles[0], engine=engine)
        self.assertEqual(article.title, "Headline A")
        self.assertIn("bar article body", article.content)


if __name__ == "__main__":
    unittest.main()
