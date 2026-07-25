import unittest
from argparse import Namespace
from os import environ
from unittest.mock import patch

from sius_ingest.app import _effective_argv, _resolve_secret_key, build_parser


class EffectiveArgumentsTests(unittest.TestCase):
    def test_empty_arguments_default_to_live_collection(self) -> None:
        self.assertEqual(_effective_argv([]), ["live"])

    def test_explicit_command_is_preserved(self) -> None:
        self.assertEqual(
            _effective_argv(["status", "--json"]),
            ["status", "--json"],
        )

    def test_process_arguments_are_used_when_not_injected(self) -> None:
        with patch("sys.argv", ["sius-ingest.exe"]):
            self.assertEqual(_effective_argv(None), ["live"])

        with patch("sys.argv", ["sius-ingest.exe", "--help"]):
            self.assertEqual(_effective_argv(None), ["--help"])

    def test_upload_prefers_current_secret_key_environment_variable(self) -> None:
        with patch.dict(
            environ,
            {
                "SUPABASE_SECRET_KEY": "sb_secret_current",
                "SUPABASE_SERVICE_ROLE_KEY": "eyJlegacy",
            },
        ):
            args = build_parser().parse_args(["upload"])

        self.assertEqual(args.secret_key, "sb_secret_current")

    def test_secret_key_can_be_read_from_masked_prompt(self) -> None:
        args = Namespace(prompt_secret_key=True, secret_key=None)
        with patch("sius_ingest.app.getpass", return_value=" sb_secret_test "):
            secret_key = _resolve_secret_key(args)

        self.assertEqual(secret_key, "sb_secret_test")


if __name__ == "__main__":
    unittest.main()
