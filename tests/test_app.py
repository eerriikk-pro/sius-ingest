import unittest
from argparse import Namespace
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

from sius_ingest.app import (
    _effective_argv,
    _resolve_secret_key,
    _run_combined,
    build_parser,
)


class EffectiveArgumentsTests(unittest.TestCase):
    def test_empty_arguments_default_to_combined_collection_and_upload(self) -> None:
        self.assertEqual(_effective_argv([]), ["run"])

    def test_explicit_command_is_preserved(self) -> None:
        self.assertEqual(
            _effective_argv(["status", "--json"]),
            ["status", "--json"],
        )

    def test_process_arguments_are_used_when_not_injected(self) -> None:
        with patch("sys.argv", ["sius-ingest.exe"]):
            self.assertEqual(_effective_argv(None), ["run"])

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

    def test_normalizer_uses_remote_state_without_local_database_flags(self) -> None:
        args = build_parser().parse_args(["normalize"])

        self.assertEqual(args.projection_name, "default")
        self.assertEqual(args.page_size, 500)
        self.assertFalse(hasattr(args, "database"))
        self.assertFalse(hasattr(args, "watch"))

    def test_secret_key_can_be_read_from_masked_prompt(self) -> None:
        args = Namespace(prompt_secret_key=True, secret_key=None)
        with patch("sius_ingest.app.getpass", return_value=" sb_secret_test "):
            secret_key = _resolve_secret_key(args)

        self.assertEqual(secret_key, "sb_secret_test")

    def test_combined_mode_without_credentials_collects_locally(self) -> None:
        with TemporaryDirectory() as temp_directory:
            database = Path(temp_directory) / "sius.sqlite3"
            with patch.dict(
                environ,
                {
                    "SUPABASE_URL": "",
                    "SUPABASE_SECRET_KEY": "",
                    "SUPABASE_SERVICE_ROLE_KEY": "",
                },
            ):
                args = build_parser().parse_args(["run", "--database", str(database), "--once"])

            with (
                patch("sius_ingest.app._run_live", return_value=0) as run_live,
                patch("builtins.print") as print_mock,
            ):
                result = _run_combined(args)

        self.assertEqual(result, 0)
        run_live.assert_called_once_with(args)
        self.assertIn("Supabase upload disabled", print_mock.call_args.args[0])

    def test_combined_mode_runs_uploader_until_live_collection_stops(self) -> None:
        uploader_started = Event()
        uploader_stopped = Event()

        def background_uploader(
            args: Namespace,
            secret_key: str,
            stop_event: Event,
        ) -> None:
            self.assertEqual(secret_key, "sb_secret_test")
            uploader_started.set()
            if stop_event.wait(1):
                uploader_stopped.set()

        def live_collection(args: Namespace) -> int:
            self.assertTrue(uploader_started.wait(1))
            return 0

        with TemporaryDirectory() as temp_directory:
            database = Path(temp_directory) / "sius.sqlite3"
            with patch.dict(
                environ,
                {
                    "SUPABASE_URL": "https://example.supabase.co",
                    "SUPABASE_SECRET_KEY": "sb_secret_test",
                },
            ):
                args = build_parser().parse_args(["run", "--database", str(database), "--once"])

            with (
                patch(
                    "sius_ingest.app._run_background_uploader",
                    new=background_uploader,
                ),
                patch("sius_ingest.app._run_live", new=live_collection),
                patch("builtins.print"),
            ):
                result = _run_combined(args)

        self.assertEqual(result, 0)
        self.assertTrue(uploader_stopped.is_set())


if __name__ == "__main__":
    unittest.main()
