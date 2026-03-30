import sys
import unittest
from argparse import Namespace
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cli  # noqa: E402
from legado_engine import BookSource  # noqa: E402
from legado_engine.auth.login import SourceUiActionResult  # noqa: E402


class CliTests(unittest.TestCase):
    def test_parse_kv_fields(self) -> None:
        self.assertEqual(
            cli.parse_kv_fields(["用户名=demo", "密码=secret"]),
            {"用户名": "demo", "密码": "secret"},
        )

    def test_cmd_auth_submits_form_fields(self) -> None:
        source = BookSource(
            bookSourceUrl="https://example.com/source",
            bookSourceName="Demo",
            loginUrl="function login() { return 'ok'; }",
        )
        args = Namespace(
            source="source.json",
            field=["用户名=demo", "密码=secret"],
            action=None,
            show_header=False,
            clear_header=False,
        )
        outcome = SourceUiActionResult(message="authenticated")

        with patch("cli.load_source", return_value=source), patch(
            "cli.submit_source_form_detailed",
            return_value=outcome,
        ) as mock_submit, patch("cli.spinner", return_value=nullcontext()), patch("cli.console.print"):
            cli.cmd_auth(args)

        self.assertEqual(mock_submit.call_count, 1)
        submitted_form = mock_submit.call_args.args[1]
        self.assertEqual(submitted_form["用户名"], "demo")
        self.assertEqual(submitted_form["密码"], "secret")

    def test_build_parser_accepts_login_alias(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["login", "source.json"])
        self.assertEqual(args.command, "login")


if __name__ == "__main__":
    unittest.main()
