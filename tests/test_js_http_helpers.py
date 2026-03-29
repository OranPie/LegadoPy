import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine import AnalyzeUrl, BookSource  # noqa: E402
from legado_engine import LegadoEngine  # noqa: E402
from legado_engine.js_engine import JsExtensions, eval_js  # noqa: E402


class _HttpHelperHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/final")
            self.end_headers()
            return
        if self.path == "/final":
            payload = b"done"
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/meta-charset":
            payload = (
                "<html><head><meta charset='utf-8'></head><body>中文内容</body></html>".encode("utf-8")
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/needs-source-auth":
            auth = self.headers.get("Authorization", "")
            ua = self.headers.get("User-Agent", "")
            status = 200 if auth == "Bearer token" and ua == "LegadoPyTest/1.0" else 401
            payload = f"{auth}|{ua}".encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path.startswith("/needs-cookies"):
            cookies = self.headers.get("Cookie", "")
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            required = [value for value in query.get("require", []) if value]
            ok = all(token in cookies for token in required)
            payload = cookies.encode("utf-8")
            self.send_response(200 if ok else 401)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/post-redirect":
            self.send_response(302)
            self.send_header("Location", "/posted")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


class JsHttpHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _HttpHelperHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_java_post_exposes_redirect_location_header(self) -> None:
        engine = LegadoEngine()
        result = eval_js(
            f"java.post('{self.base_url}/post-redirect', 'x=1', {{}}).header('Location')",
            bindings={"engine": engine},
            java_obj=JsExtensions(engine=engine),
        )
        self.assertEqual(result, "/posted")

    def test_connect_raw_request_url_and_alias_helpers_work(self) -> None:
        engine = LegadoEngine()
        script = (
            f"var finalUrl = java.connect('{self.base_url}/redirect').raw().request().url();"
            "var encoded = java.encodeURI('a b');"
            "var hash = java.md5Encode('abc');"
            "finalUrl + '|' + encoded + '|' + hash;"
        )
        result = eval_js(script, bindings={"engine": engine}, java_obj=JsExtensions(engine=engine))
        final_url, encoded, digest = str(result).split("|")
        self.assertEqual(final_url, f"{self.base_url}/final")
        self.assertEqual(encoded, "a%20b")
        self.assertEqual(digest, "900150983cd24fb0d6963f7d28e17f72")

    def test_analyze_url_reuses_sessions_and_decodes_meta_charset(self) -> None:
        engine = LegadoEngine()
        first = AnalyzeUrl(f"{self.base_url}/final", engine=engine).get_str_response()
        second = AnalyzeUrl(f"{self.base_url}/meta-charset", engine=engine).get_str_response()

        self.assertEqual(first.body, "done")
        self.assertIn("中文内容", second.body)
        self.assertEqual(len(engine._http_sessions), 1)

    def test_java_ajax_applies_source_headers_and_login_header_by_default(self) -> None:
        engine = LegadoEngine()
        source = BookSource(
            bookSourceUrl="https://example.com/source",
            bookSourceName="headers",
            header='{"User-Agent":"LegadoPyTest/1.0"}',
        )
        script = (
            "source.putLoginHeader(JSON.stringify({Authorization: 'Bearer token'}));"
            f"java.connect('{self.base_url}/needs-source-auth').body().string();"
        )
        result = eval_js(
            script,
            bindings={"engine": engine, "source": source},
            java_obj=JsExtensions(engine=engine),
        )
        self.assertEqual(result, "Bearer token|LegadoPyTest/1.0")

    def test_cookie_set_cookie_preserves_multiple_cookie_pairs_for_plain_ajax(self) -> None:
        engine = LegadoEngine()
        script = (
            f"cookie.setCookie('{self.base_url}', 'qttoken=abc123; deviceId=xyz789');"
            f"java.connect('{self.base_url}/needs-cookies?require=qttoken=abc123&require=deviceId=xyz789').body().string();"
        )
        result = eval_js(script, bindings={"engine": engine}, java_obj=JsExtensions(engine=engine))
        self.assertIn("qttoken=abc123", str(result))
        self.assertIn("deviceId=xyz789", str(result))


if __name__ == "__main__":
    unittest.main()
