# foreground.py (Windows)
# Identifies the app that owns the focused window: exe name (stable key for
# per-app rules), full path, window title, and a human-readable app name taken
# from the exe's version resource (e.g. claude.exe -> "Claude Code").

import ctypes
import ctypes.wintypes as wt
import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_psapi = ctypes.windll.psapi

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010


def get_foreground_app() -> dict:
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return {}

        pid = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return {}

        handle = _kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid.value
        )
        if not handle:
            return {}

        try:
            buf = ctypes.create_unicode_buffer(520)
            _psapi.GetModuleFileNameExW(handle, None, buf, 520)
            exe_path = buf.value
        finally:
            _kernel32.CloseHandle(handle)

        title_len = _user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(title_len + 1)
        _user32.GetWindowTextW(hwnd, title_buf, title_len + 1)

        return {
            'exe': os.path.basename(exe_path).lower() if exe_path else '',
            'path': exe_path,
            'title': title_buf.value,
            'name': app_display_name(exe_path) if exe_path else '',
        }
    except Exception as e:
        logger.debug(f"Foreground app probe failed: {e}")
        return {}


# Picks the friendlier of the two version-info names. FileDescription is usually
# right ("Microsoft Word" where ProductName says "Microsoft Office"), but some
# exes append a role to it ("Windows Terminal Host"), in which case the shorter
# ProductName it starts with is the real name.
# ponytail: prefix heuristic; add a per-exe override map if an app still reads wrong.
def pick_display_name(description: str, product: str, exe_path: str) -> str:
    description, product = (description or '').strip(), (product or '').strip()
    if product and description.startswith(product):
        return product
    return description or product or os.path.splitext(os.path.basename(exe_path))[0]


# Cached per exe path: version resources don't change while an app is running.
@lru_cache(maxsize=64)
def app_display_name(exe_path: str) -> str:
    description = product = ''
    try:
        import win32api
        lang, codepage = win32api.GetFileVersionInfo(exe_path, r'\VarFileInfo\Translation')[0]
        prefix = rf'\StringFileInfo\{lang:04x}{codepage:04x}' + '\\'
        description = win32api.GetFileVersionInfo(exe_path, prefix + 'FileDescription') or ''
        product = win32api.GetFileVersionInfo(exe_path, prefix + 'ProductName') or ''
    except Exception as e:
        logger.debug(f"No version info for {exe_path}: {e}")
    return pick_display_name(description, product, exe_path)
