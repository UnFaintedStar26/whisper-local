# history_window.py
# Live, searchable transcript browser over `transcripts.jsonl`. Launched by
# `whisper-local --history`, the tray "Transcript history..." item (which spawns
# it as its own process), or the Start Menu "Transcript History" shortcut.
# The UI is history_ui.html rendered in a native window by pywebview (WebView2
# on Windows); the page polls `Api.poll` once a second for new dictations.

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Must match the AppUserModelID on the Start Menu shortcut
# (tools/install-history-shortcut.ps1) so the taskbar groups the window under
# "Transcript History" with our icon instead of "Python".
APP_ID = 'WhisperLocal.TranscriptHistory'
_HERE = Path(__file__).parent
_ICON_PATH = _HERE / 'platform' / 'windows' / 'assets' / 'whisperkey-icon.ico'
_HTML_PATH = _HERE / 'history_ui.html'


# Change marker for the journal: None when missing, else "mtime:size".
def _file_sig(path):
    try:
        st = os.stat(path)
        return f'{st.st_mtime_ns}:{st.st_size}'
    except OSError:
        return None


# Methods here are callable from the page as `pywebview.api.<name>`.
class Api:
    def __init__(self, path):
        self._path = path

    # Returns None when nothing changed since `sig`, else fresh newest-first entries.
    def poll(self, sig=''):
        from .transcript_log import load_transcripts
        current = _file_sig(self._path)
        if current == sig:
            return None
        return {'sig': current, 'entries': load_transcripts()}

    def copy(self, text):
        import pyperclip
        pyperclip.copy(text or '')
        return True

    # The user's recording hotkey, formatted like the rest of the app, so the empty
    # state can say exactly what to press. None if settings can't be read.
    def hotkey(self):
        try:
            from .config_manager import ConfigManager
            from .utils import beautify_hotkey
            hk = ConfigManager(quiet=True).get_hotkey_config()
            return {
                'keys': beautify_hotkey(hk.get('recording_hotkey', '')),
                'hold': hk.get('recording_mode') == 'push_to_talk',
            }
        except Exception as e:
            logger.warning(f"Could not read hotkey for history empty state: {e}")
            return None

    # Shift+Enter ("copy and close") and Esc on an empty search dismiss the window.
    def close(self):
        import webview
        webview.windows[0].destroy()  # ponytail: this process only ever opens one window


def _set_windows_app_identity():
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception as e:
        logger.debug(f"Could not set AppUserModelID: {e}")


# Background shown before the page paints, so dark mode doesn't flash white.
def _initial_background():
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as k:
                if winreg.QueryValueEx(k, 'AppsUseLightTheme')[0]:
                    return '#F6F5F2'
        except OSError:
            pass
    return '#131211'


# Blocks until the window is closed.
def show_history():
    try:
        import webview
    except ImportError:
        print("The transcript window needs pywebview:  pip install pywebview")
        logger.warning("pywebview not installed; cannot open history window")
        return

    from .transcript_log import transcript_log_path

    _set_windows_app_identity()
    webview.create_window(
        'Transcript History',
        html=_HTML_PATH.read_text(encoding='utf-8'),
        js_api=Api(transcript_log_path()),
        width=900, height=760, min_size=(520, 420),
        background_color=_initial_background(),
        text_select=True,
    )
    webview.start(icon=str(_ICON_PATH) if _ICON_PATH.exists() else None)
