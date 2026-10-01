# history_window.py
# Live, searchable transcript browser over `transcripts.jsonl`. Launched by
# `whisper-local --history`, the tray "Transcript history..." item (which spawns
# it as its own process), or the Start Menu "Transcript History" shortcut.
# The UI is history_ui.html rendered in a native window by pywebview (WebView2
# on Windows); the page polls `Api.poll` once a second for new dictations.

import logging
import os
import sys
import threading
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
        # _close_permit is the one-shot that lets the page's own close past the
        # guard. The first title-bar click always asks the page to flush.
        self._close_permit = False
        self._close_attempts = 0
        self._in_closing = False
        self._seq = {}
        self._seq_lock = threading.Lock()

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

    # Same change-detection protocol as poll, over prompts.yaml. Raises on I/O
    # and on a file we cannot parse, so the page can say so instead of looking empty.
    def prompts_poll(self, sig=''):
        from .prompt_library import load_prompts, prompts_path
        current = _file_sig(prompts_path())
        if current == sig:
            return None
        return {'sig': current, 'prompts': [prompt.to_dict() for prompt in load_prompts()]}

    # Idempotent: a second capture of the same dictation returns the saved prompt.
    # The source key is built here from the transcript timestamp and text.
    def prompt_capture(self, timestamp, text):
        from .prompt_library import Capture, PromptRejected, capture_source, mutate
        if not isinstance(timestamp, str) or not isinstance(text, str):
            raise PromptRejected('capture needs text')
        result = mutate(Capture(capture_source(timestamp, text), text))
        return {'prompt': result.prompt.to_dict(), 'created': bool(result.changed)}

    # seq is per prompt id for this window. An older seq is dropped so a slow
    # save cannot overwrite a newer one. The response has no file signature.
    def prompt_save(self, raw, base_rev, seq):
        from .prompt_library import Conflict, PromptRejected, Wrote, mutate
        if isinstance(seq, bool) or not isinstance(seq, (int, float)):
            raise PromptRejected('seq must be an int')
        seq = int(seq)
        command = _save_command(raw, base_rev)
        with self._seq_lock:
            if command.id is not None:
                seen = self._seq.get(command.id)
                if seen is not None and seq < seen:
                    return {'status': 'stale'}
                self._seq[command.id] = seq
            result = mutate(command)
            if command.id is None and isinstance(result, Wrote) and result.prompt is not None:
                seen = self._seq.get(result.prompt.id, -1)
                if seq >= seen:
                    self._seq[result.prompt.id] = seq
        return _save_status(result)

    def prompt_delete(self, id, base_rev):
        from .prompt_library import Conflict, Delete, mutate
        if base_rev == '':
            base_rev = None
        result = mutate(Delete(id, base_rev))
        if isinstance(result, Conflict):
            return {
                'status': 'conflict',
                'kind': result.kind,
                'prompt': result.current.to_dict() if result.current else None,
            }
        if result.changed:
            return {'status': 'deleted'}
        return {'status': 'missing'}

    # False on the first title-bar close, so the page can flush. True after that,
    # and true once the page has called close().
    def allow_close(self) -> bool:
        if self._close_permit:
            return True
        self._close_attempts += 1
        return self._close_attempts >= 2

    # Shift+Enter and a successful flush call this. The permit lets destroy() finish.
    def close(self, force=False):
        self._close_permit = True
        if force:
            self._close_attempts = max(self._close_attempts, 2)
        # destroy() re-enters the closing handler. Setting the permit above is enough
        # while that handler is already on the stack.
        if self._in_closing:
            return True
        import webview
        webview.windows[0].destroy()  # ponytail: this process only ever opens one window
        return True


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


def _save_command(raw, base_rev):
    from .prompt_library import PromptRejected, Save
    if not isinstance(raw, dict):
        raise PromptRejected('save payload must be an object')

    def text(key):
        value = raw.get(key, '')
        if value is None:
            value = ''
        if not isinstance(value, str):
            raise PromptRejected(f'{key} must be a string')
        return value

    pid = raw.get('id')
    if pid == '':
        pid = None
    if pid is not None and not isinstance(pid, str):
        raise PromptRejected('id must be a string')
    created = raw.get('created')
    if created == '':
        created = None
    if created is not None and not isinstance(created, str):
        raise PromptRejected('created must be a string')
    if base_rev == '':
        base_rev = None
    if base_rev is not None and not isinstance(base_rev, str):
        raise PromptRejected('base_rev must be a string')
    return Save(
        id=pid,
        title=text('title'),
        purpose=text('purpose'),
        note=text('note'),
        body=text('body'),
        source=text('source'),
        base_rev=base_rev,
        created=created,
    )


def _save_status(result):
    from .prompt_library import Conflict
    if isinstance(result, Conflict):
        return {
            'status': 'conflict',
            'kind': result.kind,
            'prompt': result.current.to_dict() if result.current else None,
        }
    return {
        'status': 'saved' if result.changed else 'unchanged',
        'prompt': result.prompt.to_dict() if result.prompt else None,
    }


# 'close' when evaluate_js cannot reach the page. Otherwise the page decides.
def page_flush_outcome(evaluate) -> str:
    try:
        evaluate()
    except Exception:
        return 'close'
    return 'asked'


# evaluate_js from the UI thread deadlocks the WebView2 message pump.
def _ask_page_to_flush(window, api):
    outcome = page_flush_outcome(
        lambda: window.evaluate_js('window.__flushAndClose && window.__flushAndClose()')
    )
    if outcome != 'close':
        return
    logger.warning("Could not ask the history page to flush")
    try:
        api.close()
    except Exception as e:
        logger.warning(f"Could not close the history window: {e}")


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
    api = Api(transcript_log_path())
    window = webview.create_window(
        'Transcript History',
        html=_HTML_PATH.read_text(encoding='utf-8'),
        js_api=api,
        width=900, height=760, min_size=(520, 420),
        background_color=_initial_background(),
        text_select=True,
    )

    def on_closing():
        # The first title-bar close always asks the page to flush, then cancels.
        # The page closes immediately when nothing is dirty. The next close wins.
        api._in_closing = True
        try:
            if api.allow_close():
                return True
            threading.Thread(
                target=_ask_page_to_flush, args=(window, api), daemon=True,
            ).start()
            return False
        finally:
            api._in_closing = False

    window.events.closing += on_closing
    webview.start(icon=str(_ICON_PATH) if _ICON_PATH.exists() else None)
