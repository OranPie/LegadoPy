import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine import LegadoEngine  # noqa: E402
from legado_engine.js_engine import JsExtensions, eval_js  # noqa: E402


class JsMiscHelperTests(unittest.TestCase):
    def test_to_url_and_html_format_helpers_work(self) -> None:
        engine = LegadoEngine()
        result = eval_js(
            """
var info = java.toURL('/book?id=1&name=test', 'https://example.com/base/index.html');
var html = java.htmlFormat('<div><img src="/cover.jpg"></div>');
info.origin + '|' + info.pathname + '|' + info.searchParams.id + '|' + html;
""",
            bindings={"engine": engine, "baseUrl": "https://example.com/base/index.html"},
            java_obj=JsExtensions(base_url="https://example.com/base/index.html", engine=engine),
        )
        origin, pathname, query_id, html = str(result).split("|", 3)
        self.assertEqual(origin, "https://example.com")
        self.assertEqual(pathname, "/book")
        self.assertEqual(query_id, "1")
        self.assertIn('src="https://example.com/cover.jpg"', html)

    def test_log_type_records_type_name(self) -> None:
        engine = LegadoEngine()
        java = JsExtensions(engine=engine)
        eval_js("java.logType({a: 1})", bindings={"engine": engine}, java_obj=java)
        self.assertTrue(java.logs)

    def test_legacy_crypto_util_and_hmac_helpers_work(self) -> None:
        engine = LegadoEngine()
        result = eval_js(
            """
var mac = Crypto.HMAC(Crypto.SHA1, 'message', 'secret', {asBytes: true});
Crypto.util.bytesToBase64(mac) + '|' + Crypto.util.bytesToHex(Crypto.util.base64ToBytes('AQID'));
""",
            bindings={"engine": engine},
            java_obj=JsExtensions(engine=engine),
        )
        mac_b64, hex_value = str(result).split("|")
        self.assertEqual(mac_b64, "DK9kn+7klT2Hv5A6wRdsReAo3xY=")
        self.assertEqual(hex_value, "010203")


if __name__ == "__main__":
    unittest.main()
