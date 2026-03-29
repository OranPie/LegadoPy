import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine import (  # noqa: E402
    Book,
    BookSource,
    ContentRule,
    RssArticle,
    RssSource,
    fetch_book_cover_bytes,
    fetch_content_image_bytes,
    fetch_rss_image_bytes,
)


def data_url_bytes(data: bytes, mime: str = "application/octet-stream") -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


class ImageDecodeTests(unittest.TestCase):
    def test_cover_decode_js_decodes_binary_payload(self) -> None:
        secret = b"secret-cover"
        encoded_payload = base64.b64encode(secret)
        cover_url = data_url_bytes(encoded_payload)
        source = BookSource(
            bookSourceUrl="https://example.com",
            bookSourceName="demo",
            coverDecodeJs="java.base64DecodeToByteArray(java.bytesToStr(result))",
        )
        book = Book(bookUrl="https://example.com/book", coverUrl=cover_url)

        cover_bytes = fetch_book_cover_bytes(source, book)

        self.assertEqual(cover_bytes, secret)

    def test_content_image_decode_js_rewrites_binary_payload(self) -> None:
        image_url = data_url_bytes(b"foo-image")
        source = BookSource(
            bookSourceUrl="https://example.com",
            bookSourceName="demo",
            ruleContent=ContentRule(
                imageDecode="var text = java.bytesToStr(result); java.strToBytes(text.replace('foo', 'bar'))"
            ),
        )
        book = Book(bookUrl="https://example.com/book")

        image_bytes = fetch_content_image_bytes(source, book, image_url)

        self.assertEqual(image_bytes, b"bar-image")

    def test_rss_cover_decode_js_decodes_binary_payload(self) -> None:
        secret = b"rss-image"
        image_url = data_url_bytes(base64.b64encode(secret))
        source = RssSource(
            sourceUrl="https://example.com/rss",
            sourceName="Feed",
            coverDecodeJs="java.base64DecodeToByteArray(java.bytesToStr(result))",
        )
        article = RssArticle(image=image_url)

        image_bytes = fetch_rss_image_bytes(source, article)

        self.assertEqual(image_bytes, secret)


if __name__ == "__main__":
    unittest.main()
