"""Best-effort protection against Windows console input pausing collection."""

import ctypes
import os
import sys
from typing import Any

STD_INPUT_HANDLE = -10
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
FILE_TYPE_CHAR = 0x0002
ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080


def protect_windows_console() -> None:
    """Disable QuickEdit when this process owns an interactive Windows console."""

    if os.name != "nt":
        return

    result = disable_windows_quick_edit()
    if result is True:
        print(
            "Windows console protection enabled: QuickEdit is disabled.",
            file=sys.stderr,
            flush=True,
        )
    elif result is False:
        print(
            "Warning: Windows QuickEdit could not be disabled. Avoid clicking or "
            "selecting text in this window because it may pause collection.",
            file=sys.stderr,
            flush=True,
        )


def disable_windows_quick_edit(kernel32: Any | None = None) -> bool | None:
    """Return True on success, False on failure, or None without a console."""

    if kernel32 is None:
        if os.name != "nt":
            return None
        try:
            kernel32 = _load_kernel32()
        except (AttributeError, OSError):
            return False

    return _disable_quick_edit_mode(kernel32)


def _load_kernel32() -> Any:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.argtypes = [ctypes.c_uint32]
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    kernel32.GetFileType.argtypes = [ctypes.c_void_p]
    kernel32.GetFileType.restype = ctypes.c_uint32
    kernel32.GetConsoleMode.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel32.GetConsoleMode.restype = ctypes.c_int
    kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.SetConsoleMode.restype = ctypes.c_int
    return kernel32


def _disable_quick_edit_mode(kernel32: Any) -> bool | None:
    input_handle = kernel32.GetStdHandle(ctypes.c_uint32(STD_INPUT_HANDLE).value)
    if input_handle in (None, 0, INVALID_HANDLE_VALUE):
        return None
    if kernel32.GetFileType(input_handle) != FILE_TYPE_CHAR:
        return None

    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(input_handle, ctypes.byref(mode)):
        return False

    protected_mode = (mode.value | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT_MODE
    if protected_mode == mode.value:
        return True
    return bool(kernel32.SetConsoleMode(input_handle, protected_mode))
