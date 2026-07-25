import unittest
from unittest.mock import patch

from sius_ingest.app import _effective_argv


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


if __name__ == "__main__":
    unittest.main()
