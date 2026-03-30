import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine import LegadoEngine  # noqa: E402
from legado_engine.js import JsExtensions, eval_js  # noqa: E402


class _ScriptCacheHandler(BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self) -> None:
        type(self).hits += 1
        payload = b"remote-script-body"
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        return


class JsScriptCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _ScriptCacheHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_import_script_reads_local_file(self) -> None:
        engine = LegadoEngine()
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "sample.js"
            script_path.write_text("local-script-body", encoding="utf-8")
            result = eval_js(
                f"java.importScript('{script_path}')",
                bindings={"engine": engine},
                java_obj=JsExtensions(engine=engine),
            )
        self.assertEqual(result, "local-script-body")

    def test_cache_file_persists_across_js_calls(self) -> None:
        engine = LegadoEngine()
        _ScriptCacheHandler.hits = 0
        url = f"{self.base_url}/script.js"

        first = eval_js(
            f"java.cacheFile('{url}', 60)",
            bindings={"engine": engine},
            java_obj=JsExtensions(engine=engine),
        )
        second = eval_js(
            f"java.cacheFile('{url}', 60)",
            bindings={"engine": engine},
            java_obj=JsExtensions(engine=engine),
        )

        self.assertEqual(first, "remote-script-body")
        self.assertEqual(second, "remote-script-body")
        self.assertEqual(_ScriptCacheHandler.hits, 1)


if __name__ == "__main__":
    unittest.main()
