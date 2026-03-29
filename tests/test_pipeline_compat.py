import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine import AnalyzeUrl, BookSource, LegadoEngine  # noqa: E402
from legado_engine.pipeline import run_login_check  # noqa: E402


class _CompatHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.startswith("/login-check"):
            body = {"statusCode": 200, "name": "ok"} if self.headers.get("Authorization") == "Bearer token" else {"statusCode": 301}
            payload = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        payload = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        return


class PipelineCompatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _CompatHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_login_check_js_can_refresh_response(self) -> None:
        engine = LegadoEngine()
        source = BookSource(
            bookSourceUrl=self.base_url,
            bookSourceName="compat",
            loginCheckJs="""
var strRes = result;
var payload = JSON.parse(result.body());
if (payload.statusCode == 301) {
    source.putLoginHeader(JSON.stringify({Authorization: "Bearer token"}));
    strRes = java.connect(url, source.getLoginHeader());
}
strRes
""",
        )
        analyze_url = AnalyzeUrl(f"{self.base_url}/login-check", source=source, engine=engine)
        initial = analyze_url.get_str_response()
        checked = run_login_check(analyze_url, source, initial)

        self.assertEqual(json.loads(checked.body)["statusCode"], 200)
        self.assertEqual(json.loads(source.getLoginHeader())["Authorization"], "Bearer token")

    def test_concurrent_rate_limits_repeat_requests(self) -> None:
        engine = LegadoEngine()
        source = BookSource(
            bookSourceUrl=self.base_url,
            bookSourceName="compat",
            concurrentRate="1000",
        )

        AnalyzeUrl(f"{self.base_url}/rate", source=source, engine=engine).get_str_response()
        with patch("legado_engine.engine.time.sleep") as mock_sleep:
            AnalyzeUrl(f"{self.base_url}/rate", source=source, engine=engine).get_str_response()

        self.assertTrue(mock_sleep.called)


if __name__ == "__main__":
    unittest.main()
