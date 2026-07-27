import unittest
from unittest.mock import patch

from sius_ingest.windows_console import (
    ENABLE_EXTENDED_FLAGS,
    ENABLE_QUICK_EDIT_MODE,
    FILE_TYPE_CHAR,
    disable_windows_quick_edit,
    protect_windows_console,
)


class FakeKernel32:
    def __init__(
        self,
        *,
        mode: int = ENABLE_QUICK_EDIT_MODE,
        file_type: int = FILE_TYPE_CHAR,
        get_mode_succeeds: bool = True,
        set_mode_succeeds: bool = True,
    ) -> None:
        self.mode = mode
        self.file_type = file_type
        self.get_mode_succeeds = get_mode_succeeds
        self.set_mode_succeeds = set_mode_succeeds
        self.set_modes: list[int] = []

    def GetStdHandle(self, handle_kind: int) -> int:
        return 123

    def GetFileType(self, handle: int) -> int:
        return self.file_type

    def GetConsoleMode(self, handle: int, mode_pointer: object) -> bool:
        mode_pointer._obj.value = self.mode  # type: ignore[attr-defined]
        return self.get_mode_succeeds

    def SetConsoleMode(self, handle: int, mode: int) -> bool:
        self.set_modes.append(mode)
        return self.set_mode_succeeds


class WindowsConsoleTests(unittest.TestCase):
    def test_quick_edit_is_cleared_without_changing_other_console_flags(self) -> None:
        existing_flag = 0x0002
        kernel32 = FakeKernel32(mode=ENABLE_QUICK_EDIT_MODE | existing_flag)

        result = disable_windows_quick_edit(kernel32)

        self.assertTrue(result)
        self.assertEqual(
            kernel32.set_modes,
            [ENABLE_EXTENDED_FLAGS | existing_flag],
        )

    def test_already_protected_console_does_not_need_an_api_write(self) -> None:
        kernel32 = FakeKernel32(mode=ENABLE_EXTENDED_FLAGS | 0x0002)

        result = disable_windows_quick_edit(kernel32)

        self.assertTrue(result)
        self.assertEqual(kernel32.set_modes, [])

    def test_redirected_input_is_not_treated_as_a_console_failure(self) -> None:
        kernel32 = FakeKernel32(file_type=0x0003)

        self.assertIsNone(disable_windows_quick_edit(kernel32))
        self.assertEqual(kernel32.set_modes, [])

    def test_console_api_failure_is_reported_without_raising(self) -> None:
        kernel32 = FakeKernel32(get_mode_succeeds=False)

        self.assertFalse(disable_windows_quick_edit(kernel32))

    def test_non_windows_process_does_not_load_windows_apis(self) -> None:
        with (
            patch("sius_ingest.windows_console.os.name", "posix"),
            patch("sius_ingest.windows_console._load_kernel32") as load_kernel32,
        ):
            result = disable_windows_quick_edit()

        self.assertIsNone(result)
        load_kernel32.assert_not_called()

    def test_windows_startup_reports_success_to_stderr(self) -> None:
        with (
            patch("sius_ingest.windows_console.os.name", "nt"),
            patch(
                "sius_ingest.windows_console.disable_windows_quick_edit",
                return_value=True,
            ),
            patch("builtins.print") as print_mock,
        ):
            protect_windows_console()

        self.assertIn("QuickEdit is disabled", print_mock.call_args.args[0])
        self.assertTrue(print_mock.call_args.kwargs["flush"])


if __name__ == "__main__":
    unittest.main()
