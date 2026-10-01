import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


class HotkeyParsingTests(unittest.TestCase):
    def test_parse_hotkey_splits_on_plus(self):
        from whisper_key.utils import parse_hotkey
        self.assertEqual(parse_hotkey("ctrl+a"), ["ctrl", "a"])
        self.assertEqual(parse_hotkey("Ctrl+Shift+F1"), ["ctrl", "shift", "f1"])

    def test_parse_hotkey_handles_empty(self):
        from whisper_key.utils import parse_hotkey
        self.assertEqual(parse_hotkey(""), [])
        self.assertEqual(parse_hotkey(None), [])

    def test_beautify_hotkey_uppercases(self):
        from whisper_key.utils import beautify_hotkey
        self.assertEqual(beautify_hotkey("ctrl+a"), "CTRL+A")
        self.assertEqual(beautify_hotkey(""), "")


class VersionMetadataTests(unittest.TestCase):
    def test_pyproject_has_local_name(self):
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        self.assertEqual(data["project"]["name"], "whisper-local")
        self.assertIn("whisper-local", data["project"]["scripts"])
        self.assertIn("wl", data["project"]["scripts"])

    def test_no_orphan_update_checker(self):
        self.assertFalse((ROOT / "src" / "whisper_key" / "update_checker.py").exists())

    def test_main_does_not_import_update_checker(self):
        main_src = (ROOT / "src" / "whisper_key" / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("update_checker", main_src)
        self.assertNotIn("check_for_updates", main_src)


class VoiceCommandsDefaultsTests(unittest.TestCase):
    def test_no_registry_writes_in_defaults(self):
        defaults = (ROOT / "src" / "whisper_key" / "commands.defaults.yaml").read_text(encoding="utf-8")
        self.assertNotIn("reg add", defaults.lower())


class WhisperBackendTests(unittest.TestCase):
    def test_default_backend_is_faster_whisper(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "config.defaults.yaml"
        with open(path, encoding="utf-8") as f:
            cfg = YAML().load(f)
        self.assertEqual(cfg["whisper"].get("backend"), "faster_whisper")

    def test_whisper_cpp_module_imports_lazily(self):
        # Import the module — the heavy pywhispercpp import is lazy inside __init__
        from whisper_key import whisper_engine_cpp
        self.assertTrue(hasattr(whisper_engine_cpp, 'WhisperEngineCpp'))

    def test_optional_dep_declared(self):
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        extras = data.get("project", {}).get("optional-dependencies", {})
        self.assertIn("whispercpp", extras)
        self.assertTrue(any("pywhispercpp" in d for d in extras["whispercpp"]))


class InstanceManagerTests(unittest.TestCase):
    def test_exposes_cleanup_pid_file(self):
        src = (ROOT / "src" / "whisper_key" / "instance_manager.py").read_text(encoding="utf-8")
        self.assertIn("def cleanup_pid_file", src)
        self.assertIn("os.kill", src)
        self.assertIn("_wait_for_lock", src)

    def test_main_calls_cleanup_pid_file(self):
        main_src = (ROOT / "src" / "whisper_key" / "main.py").read_text(encoding="utf-8")
        self.assertIn("cleanup_pid_file(instance_name)", main_src)


class TextPostprocessTests(unittest.TestCase):
    def test_strip_filler_words(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'strip_filler_words': True}
        self.assertEqual(postprocess("um, hello like world", cfg), "hello world")

    def test_capitalize_first(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'capitalize_first': True}
        self.assertEqual(postprocess("hello world", cfg), "Hello world")

    def test_ensure_punctuation(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'ensure_punctuation': True}
        self.assertEqual(postprocess("hello world", cfg), "hello world.")
        self.assertEqual(postprocess("hello world.", cfg), "hello world.")

    def test_postprocess_passthrough_when_empty(self):
        from whisper_key.text_postprocess import postprocess
        self.assertEqual(postprocess("hello", {}), "hello")
        self.assertEqual(postprocess("", {'capitalize_first': True}), "")

    def test_strip_trailing_period(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'strip_trailing_period': True}
        self.assertEqual(postprocess("hello world.", cfg), "hello world")
        self.assertEqual(postprocess("done.\n", cfg), "done\n")
        self.assertEqual(postprocess("e.g..", cfg), "e.g..")  # don't touch ellipsis-like
        self.assertEqual(postprocess("no period here", cfg), "no period here")

    def test_inline_formatting_basics(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'inline_formatting': True}
        self.assertEqual(postprocess("hello comma world period", cfg), "hello, world.")
        self.assertEqual(postprocess("what time is it question mark", cfg), "what time is it?")

    def test_inline_formatting_custom_replaces_defaults(self):
        # Custom list replaces the English defaults (non-English use case).
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_replacements': [
                {'phrase': 'przecinek', 'replacement': ','},
                {'phrase': 'strzałka', 'replacement': '→'},
            ],
        }
        self.assertEqual(postprocess("tekst przecinek dalej", cfg), "tekst, dalej")
        self.assertEqual(postprocess("a strzałka b", cfg), "a → b")
        # English defaults are NOT active in replace mode.
        self.assertEqual(postprocess("hello comma world", cfg), "hello comma world")

    def test_inline_formatting_extend_keeps_defaults(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_extend': True,
            'inline_formatting_replacements': [{'phrase': 'arrow', 'replacement': '→'}],
        }
        # both the English default AND the custom phrase apply
        self.assertEqual(postprocess("hello comma arrow there", cfg), "hello, → there")

    def test_absorb_cleans_whisper_prosody_punctuation(self):
        # Whisper adds its own commas/periods around spoken cue words; absorb should
        # eat them so the output isn't polluted (Discussion #1 bug report).
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_absorb_punctuation': True,
            'inline_formatting_replacements': [
                {'phrase': 'comma', 'replacement': ', '},
                {'phrase': 'arrow', 'replacement': ' → '},
            ],
        }
        whisper_out = "Hello, comma, and welcome, arrow. Common greeting."
        self.assertEqual(postprocess(whisper_out, cfg),
                         "Hello, and welcome → Common greeting.")

    def test_absorb_off_leaves_prosody_artifacts(self):
        # Documents that WITHOUT absorb the artifacts remain (opt-in, no regression).
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_replacements': [{'phrase': 'comma', 'replacement': ','}],
        }
        self.assertIn(",,", postprocess("a, comma, b", cfg))

    def test_absorb_with_builtins_does_not_glue_or_eat_breaks(self):
        # SEC #4: absorb + built-in English cue words must keep spacing and newlines.
        from whisper_key.text_postprocess import postprocess
        cfg = {'inline_formatting': True, 'inline_formatting_absorb_punctuation': True}
        self.assertEqual(postprocess("Hello, comma, world.", cfg), "Hello, world.")
        # "new paragraph" break must survive a following cue's absorb
        out = postprocess("first new paragraph second period", cfg)
        self.assertIn("\n\n", out)

    def test_absorb_respects_word_boundary(self):
        # "comma" must not fire inside "commander"/"Common".
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_absorb_punctuation': True,
            'inline_formatting_replacements': [{'phrase': 'comma', 'replacement': ', '}],
        }
        out = postprocess("the commander said comma done", cfg)
        self.assertIn("commander", out)
        self.assertNotIn("commaander", out)

    def test_inline_formatting_replacement_is_literal(self):
        # A replacement containing regex-special chars must be inserted literally.
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_replacements': [{'phrase': 'backref', 'replacement': r'\1\g<0>'}],
        }
        self.assertEqual(postprocess("x backref y", cfg), r"x \1\g<0> y")

    def test_ollama_polish_handles_curly_braces_in_text(self):
        from whisper_key.text_postprocess import _ollama_polish
        cfg = {'enabled': True, 'endpoint': 'http://127.0.0.1:0', 'timeout': 0.1,
               'prompt': 'Polish:\n\n{text}'}
        result = _ollama_polish("config = {a: 1, b: 2}", cfg)
        self.assertEqual(result, '')

    def test_ollama_polish_handles_curly_braces_in_prompt(self):
        from whisper_key.text_postprocess import _ollama_polish
        cfg = {'enabled': True, 'endpoint': 'http://127.0.0.1:0', 'timeout': 0.1,
               'prompt': 'Format: {format_var} not a placeholder. {text}'}
        result = _ollama_polish("hi", cfg)
        self.assertEqual(result, '')


class AppRulesShapeTests(unittest.TestCase):
    def test_defaults_yaml_is_valid(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "app_rules.defaults.yaml"
        self.assertTrue(path.exists())
        with open(path, encoding="utf-8") as f:
            data = YAML().load(f)
        self.assertIn('rules', data)
        self.assertIsInstance(data['rules'], list)
        for rule in data['rules']:
            self.assertIn('match', rule)


class AppRulesFormattingTests(unittest.TestCase):
    def test_formatting_overrides_extracts_only_format_keys(self):
        from whisper_key.app_rules import formatting_overrides
        rule = {
            'match': ['code.exe'],
            'auto_paste': False,          # delivery key, not a formatting key
            'capitalize_first': False,
            'ensure_punctuation': False,
        }
        self.assertEqual(
            formatting_overrides(rule),
            {'capitalize_first': False, 'ensure_punctuation': False},
        )

    def test_formatting_overrides_empty_and_none(self):
        from whisper_key.app_rules import formatting_overrides
        self.assertEqual(formatting_overrides(None), {})
        self.assertEqual(formatting_overrides({'match': ['x'], 'auto_send': True}), {})

    def test_merge_overrides_global_postprocess(self):
        # Simulate the pipeline merge: rule formatting overrides global config.
        from whisper_key.app_rules import formatting_overrides
        global_cfg = {'capitalize_first': True, 'ensure_punctuation': True, 'inline_formatting': True}
        rule = {'capitalize_first': False, 'ensure_punctuation': False}
        merged = {**global_cfg, **formatting_overrides(rule)}
        self.assertFalse(merged['capitalize_first'])
        self.assertFalse(merged['ensure_punctuation'])
        self.assertTrue(merged['inline_formatting'])  # untouched key inherited


class TransformsShapeTests(unittest.TestCase):
    def test_defaults_yaml_is_valid(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "transforms.defaults.yaml"
        self.assertTrue(path.exists())
        with open(path, encoding="utf-8") as f:
            data = YAML().load(f)
        self.assertIn('transforms', data)
        for t in data['transforms']:
            self.assertIn('name', t)
            self.assertIn('prompt', t)

    def test_transforms_manager_loads(self):
        from whisper_key.transforms import TransformsManager
        tm = TransformsManager()
        names = [t.get('name') for t in tm.list_transforms()]
        self.assertIn('polish', names)
        self.assertIn('prompt-engineer', names)


class StreakComputationTests(unittest.TestCase):
    def test_streak_basic(self):
        import datetime
        from whisper_key.stats import _compute_streaks
        today = datetime.date(2026, 5, 18)
        active = {
            '2026-05-18', '2026-05-17', '2026-05-16',
            '2026-05-10', '2026-05-09',
        }
        current, longest = _compute_streaks(active, today)
        self.assertEqual(current, 3)
        self.assertEqual(longest, 3)

    def test_streak_breaks_yesterday(self):
        import datetime
        from whisper_key.stats import _compute_streaks
        today = datetime.date(2026, 5, 18)
        active = {'2026-05-10'}
        current, longest = _compute_streaks(active, today)
        self.assertEqual(current, 0)
        self.assertEqual(longest, 1)


class ProfilesShapeTests(unittest.TestCase):
    def test_defaults_yaml_is_valid(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "profiles.defaults.yaml"
        self.assertTrue(path.exists())
        with open(path, encoding="utf-8") as f:
            data = YAML().load(f)
        self.assertIn('profiles', data)
        self.assertIn('dictation', data['profiles'])


class UtilsTests(unittest.TestCase):
    def test_resolve_asset_path_relative(self):
        from whisper_key.utils import resolve_asset_path
        result = resolve_asset_path("config.defaults.yaml")
        self.assertTrue(result.endswith("config.defaults.yaml"))

    def test_resolve_asset_path_absolute_passthrough(self):
        from whisper_key.utils import resolve_asset_path
        absolute = os.path.abspath(__file__)
        self.assertEqual(resolve_asset_path(absolute), absolute)


class NoiseSuppresionTests(unittest.TestCase):
    def test_passthrough_without_noisereduce(self):
        import sys
        import unittest.mock as mock
        import numpy as np
        sys.modules.pop('whisper_key.noise_suppression', None)
        import importlib
        with mock.patch.dict(sys.modules, {'noisereduce': None}):
            import whisper_key.noise_suppression as ns_mod
            importlib.reload(ns_mod)
            audio = np.zeros(16000, dtype=np.float32)
            result = ns_mod.apply_noise_reduction(audio, 16000, 0.75)
            np.testing.assert_array_equal(result, audio)

    def test_config_in_defaults(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "config.defaults.yaml"
        with open(path, encoding="utf-8") as f:
            cfg = YAML().load(f)
        ns = cfg["audio"]["noise_suppression"]
        self.assertFalse(ns["enabled"])
        self.assertAlmostEqual(float(ns["strength"]), 0.75, places=2)


class UpdateCheckTests(unittest.TestCase):
    def test_is_newer_basic(self):
        from whisper_key.update_check import _is_newer
        self.assertTrue(_is_newer("1.0.0", "0.9.0"))
        self.assertFalse(_is_newer("0.9.0", "1.0.0"))
        self.assertFalse(_is_newer("0.9.0", "0.9.0"))

    def test_no_network_when_disabled(self):
        import unittest.mock as mock
        from whisper_key.update_check import maybe_check_for_update
        with mock.patch('whisper_key.update_check._check_in_background') as m:
            maybe_check_for_update(lambda _: None, {'enabled': False})
            m.assert_not_called()

    def test_update_check_in_config_defaults(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "config.defaults.yaml"
        with open(path, encoding="utf-8") as f:
            cfg = YAML().load(f)
        self.assertIn("update_check", cfg)
        self.assertFalse(cfg["update_check"]["enabled"])


class TranscriptLogTests(unittest.TestCase):
    def test_record_and_load(self):
        import tempfile
        import unittest.mock as mock
        from whisper_key import transcript_log
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch('whisper_key.transcript_log.get_user_app_data_path', return_value=tmpdir):
                transcript_log.record_transcript("Hello world", app="test.exe", duration_s=1.5, app_name="Test App")
                entries = transcript_log.load_transcripts()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["text"], "Hello world")
        self.assertEqual(entries[0]["app"], "test.exe")
        self.assertEqual(entries[0]["app_name"], "Test App")

    @unittest.skipUnless(sys.platform == 'win32', 'Windows version-info naming')
    def test_app_display_name_prefers_real_product_name(self):
        from whisper_key.platform.windows.foreground import pick_display_name
        self.assertEqual(pick_display_name('Windows Terminal Host', 'Windows Terminal', ''), 'Windows Terminal')
        self.assertEqual(pick_display_name('Microsoft Word', 'Microsoft Office', ''), 'Microsoft Word')
        self.assertEqual(pick_display_name('', '', 'tool.exe'), 'tool')

    def test_empty_text_not_logged(self):
        import tempfile
        import unittest.mock as mock
        from whisper_key import transcript_log
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch('whisper_key.transcript_log.get_user_app_data_path', return_value=tmpdir):
                transcript_log.record_transcript("", app="test.exe")
                entries = transcript_log.load_transcripts()
        self.assertEqual(len(entries), 0)

    def test_unreadable_journal_raises_instead_of_looking_empty(self):
        import tempfile
        import unittest.mock as mock
        from whisper_key import transcript_log
        from whisper_key.history_window import Api
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch('whisper_key.transcript_log.get_user_app_data_path', return_value=tmpdir):
                transcript_log.record_transcript("Hello world", app="test.exe")
                api = Api(transcript_log.transcript_log_path())
                with mock.patch('builtins.open', side_effect=PermissionError('locked')):
                    with self.assertRaises(PermissionError):
                        api.poll('')
                # Malformed lines are still skipped, not fatal.
                with open(transcript_log.transcript_log_path(), 'a', encoding='utf-8') as f:
                    f.write('{not json\n')
                self.assertEqual([e['text'] for e in transcript_log.load_transcripts()], ["Hello world"])


class SettingsUiModuleTests(unittest.TestCase):
    def test_module_importable(self):
        from whisper_key import settings_ui
        self.assertTrue(hasattr(settings_ui, 'run_settings_window'))


class OnboardingBannerTests(unittest.TestCase):
    # UX #4b: the first-launch banner must reflect the user's ACTUAL configured
    # hotkeys (and notify message), not hardcoded Windows defaults.
    def test_banner_uses_supplied_hotkeys(self):
        import io
        import contextlib
        import unittest.mock as mock
        from whisper_key import onboarding_tutorial
        seen = {}

        def fake_notify(msg):
            seen['notify'] = msg

        buf = io.StringIO()
        with mock.patch.object(onboarding_tutorial, 'mark_complete', lambda: None):
            with contextlib.redirect_stdout(buf):
                onboarding_tutorial.show_console_welcome(
                    hotkeys={'record': 'F9', 'rephrase': 'F10', 'command': 'F11',
                             'cancel': 'F12', 'pause': 'F8'},
                    notify=fake_notify,
                )
        out = buf.getvalue()
        self.assertIn('F9', out)
        self.assertIn('F10', out)
        self.assertNotIn('Ctrl+Win', out)  # no leaked default
        self.assertEqual(seen.get('notify'), 'Welcome! Hold F9 to start dictating.')


class PostprocessHotReloadTests(unittest.TestCase):
    # UX #1/#3: editing postprocess in user_settings.yaml applies on next dictation
    # (get_postprocess_config) without an app restart.
    def test_postprocess_reloads_on_file_change(self):
        import os
        import tempfile
        import unittest.mock as mock
        from ruamel.yaml import YAML
        # Import the submodule object so patch.object resolves it without relying
        # on it already being an attribute of the package (string-target patches
        # fail under a fresh `unittest` run where nothing imported it first).
        # config_manager pulls `.platform`, which eagerly imports the OS-specific
        # backend (win32api / AppKit) — absent in the lean CI env, so skip there.
        try:
            from whisper_key import config_manager as cm_mod
        except Exception:
            self.skipTest("config_manager not importable on this platform")
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(cm_mod, 'get_user_app_data_path', return_value=d):
                cm = cm_mod.ConfigManager(quiet=True)
                self.assertFalse(cm.get_postprocess_config().get('strip_filler_words'))
                sp = os.path.join(d, 'user_settings.yaml')
                base = cm._postprocess_mtime or os.path.getmtime(sp)
                with open(sp, 'w', encoding='utf-8') as f:
                    YAML().dump({'postprocess': {'strip_filler_words': True}}, f)
                os.utime(sp, (base + 10, base + 10))  # guarantee a newer mtime
                self.assertTrue(cm.get_postprocess_config().get('strip_filler_words'))


class SettingsResetTests(unittest.TestCase):
    # SEC #1: "Reset to defaults" promises hotwords survive — verify they do.
    def test_reset_preserves_hotwords(self):
        import tempfile, os
        from ruamel.yaml import YAML
        from whisper_key.settings_ui import reset_settings_preserving_hotwords
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'user_settings.yaml')
            with open(path, 'w', encoding='utf-8') as f:
                YAML().dump({'whisper': {'model': 'small', 'hotwords': ['Kubernetes', 'drajb']},
                             'clipboard': {'auto_paste': False}}, f)
            preserved = reset_settings_preserving_hotwords(path)
            self.assertEqual(preserved, ['Kubernetes', 'drajb'])
            with open(path, encoding='utf-8') as f:
                after = YAML().load(f)
            # hotwords kept, everything else gone (back to defaults)
            self.assertEqual(list(after['whisper']['hotwords']), ['Kubernetes', 'drajb'])
            self.assertNotIn('clipboard', after)
            self.assertNotIn('model', after['whisper'])

    def test_reset_with_no_hotwords_removes_file(self):
        import tempfile, os
        from ruamel.yaml import YAML
        from whisper_key.settings_ui import reset_settings_preserving_hotwords
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'user_settings.yaml')
            with open(path, 'w', encoding='utf-8') as f:
                YAML().dump({'clipboard': {'auto_paste': False}}, f)
            self.assertEqual(reset_settings_preserving_hotwords(path), [])
            self.assertFalse(os.path.exists(path))  # clean wipe when nothing to keep


class HistoryWindowModuleTests(unittest.TestCase):
    def test_module_importable(self):
        from whisper_key import history_window
        self.assertTrue(hasattr(history_window, 'show_history'))

    def test_poll_returns_data_only_when_journal_changes(self):
        import tempfile
        import unittest.mock as mock
        from whisper_key import transcript_log
        from whisper_key.history_window import Api
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch('whisper_key.transcript_log.get_user_app_data_path', return_value=tmpdir):
                api = Api(transcript_log.transcript_log_path())
                first = api.poll('')
                self.assertEqual(first['entries'], [])
                self.assertIsNone(api.poll(first['sig']))
                transcript_log.record_transcript("Hello world", app="test.exe")
                second = api.poll(first['sig'])
                self.assertEqual([e['text'] for e in second['entries']], ["Hello world"])
                self.assertIsNone(api.poll(second['sig']))

    def test_ui_page_packaged(self):
        from whisper_key import history_window
        self.assertTrue(history_window._HTML_PATH.exists())


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_workflow_exists(self):
        self.assertTrue((ROOT / ".github" / "workflows" / "release.yml").exists())

    def test_release_workflow_triggers_on_tag(self):
        with open(ROOT / ".github" / "workflows" / "release.yml", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("tags:", content)
        self.assertIn("v*", content)
        self.assertIn("pypa/gh-action-pypi-publish", content)


class PyprojectOptionalDepsTests(unittest.TestCase):
    def test_noise_optional_dep(self):
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        extras = data.get("project", {}).get("optional-dependencies", {})
        self.assertIn("noise", extras)
        self.assertTrue(any("noisereduce" in d for d in extras["noise"]))


class SelftestModuleTests(unittest.TestCase):
    def test_module_importable(self):
        from whisper_key import selftest
        self.assertTrue(hasattr(selftest, 'run_selftest'))

    def test_report_helper(self):
        import io
        import sys
        from whisper_key.selftest import _report
        failures = []
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            _report(True, "looks good", failures, "fake")
            _report(False, ("uh oh", "fix-me"), failures, "fake-2")
        finally:
            sys.stdout = old_stdout
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][0], "fake-2")


class FirstRunTests(unittest.TestCase):
    def test_flag_file_lifecycle(self):
        import tempfile
        import unittest.mock as mock
        from whisper_key import first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch('whisper_key.first_run.get_user_app_data_path', return_value=tmpdir):
                self.assertTrue(first_run.is_first_run())
                first_run.mark_first_run_complete()
                self.assertFalse(first_run.is_first_run())

    def test_show_welcome_module_importable(self):
        from whisper_key import first_run
        self.assertTrue(hasattr(first_run, 'show_welcome_window'))


class CheatSheetTests(unittest.TestCase):
    def test_module_importable(self):
        from whisper_key import cheat_sheet
        self.assertTrue(hasattr(cheat_sheet, 'show_cheat_sheet'))


class BundleLogsTests(unittest.TestCase):
    def test_redaction_replaces_usernames(self):
        from whisper_key.bundle_logs import _redact
        sample = "Path: C:\\Users\\rohit\\AppData\\Roaming and email me at test@example.com"
        red = _redact(sample)
        self.assertNotIn("rohit", red.lower())
        self.assertNotIn("test@example.com", red)
        self.assertIn("<USER>", red)
        self.assertIn("<EMAIL>", red)

    def test_redaction_macos_linux_paths(self):
        from whisper_key.bundle_logs import _redact
        self.assertIn("<USER>", _redact("/Users/alice/.whisperkey/"))
        self.assertIn("<USER>", _redact("/home/bob/log.txt"))

    def test_bundle_creates_zip(self):
        import io
        import sys
        import tempfile
        import unittest.mock as mock
        import zipfile
        from whisper_key import bundle_logs

        with tempfile.TemporaryDirectory() as appdata:
            with tempfile.TemporaryDirectory() as out:
                output = f"{out}/bundle.zip"
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()
                try:
                    with mock.patch('whisper_key.bundle_logs.get_user_app_data_path', return_value=appdata), \
                         mock.patch('whisper_key.bundle_logs._capture_doctor', return_value='[doctor mocked]'):
                        rc = bundle_logs.bundle_logs(output)
                finally:
                    sys.stdout = old_stdout
                self.assertEqual(rc, 0)
                with zipfile.ZipFile(output) as zf:
                    names = zf.namelist()
                self.assertIn('about.txt', names)
                self.assertIn('doctor.txt', names)


class LocalServerTests(unittest.TestCase):
    def test_module_importable(self):
        from whisper_key import local_server
        self.assertTrue(hasattr(local_server, 'run_server'))
        self.assertEqual(local_server.DEFAULT_PORT, 7777)

    def test_decode_wav_fallback(self):
        import io
        import wave
        import numpy as np
        from whisper_key.local_server import _decode_wav_fallback

        with io.BytesIO() as buf:
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                samples = (np.sin(2 * np.pi * 440 * np.arange(16000) / 16000) * 32767).astype(np.int16)
                wf.writeframes(samples.tobytes())
            wav_bytes = buf.getvalue()

        decoded = _decode_wav_fallback(wav_bytes)
        self.assertEqual(decoded.dtype, np.float32)
        self.assertEqual(len(decoded), 16000)
        self.assertGreater(float(np.max(np.abs(decoded))), 0.5)


class MainCliFlagsTests(unittest.TestCase):
    def test_main_registers_new_flags(self):
        main_src = (ROOT / "src" / "whisper_key" / "main.py").read_text(encoding="utf-8")
        for flag in ('--selftest', '--cheat-sheet', '--bundle-logs', '--serve'):
            self.assertIn(flag, main_src, f"main.py should register {flag}")


class TroubleshootingDocTests(unittest.TestCase):
    def test_docs_exist(self):
        self.assertTrue((ROOT / "docs" / "troubleshooting.md").exists())
        self.assertTrue((ROOT / "docs" / "faq.md").exists())


class VersionBumpTests(unittest.TestCase):
    def test_pyproject_version(self):
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        version = data["project"]["version"]
        major, minor = version.split('.')[:2]
        self.assertGreaterEqual((int(major), int(minor)), (0, 10))

    def test_citation_matches_pyproject(self):
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as f:
            pyproject_version = tomllib.load(f)["project"]["version"]
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        self.assertIn(f"version: {pyproject_version}", citation,
                      "CITATION.cff version must match pyproject.toml")


class _FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler for parser tests."""
    def __init__(self, body: bytes, boundary: str, content_length=None):
        import io
        self.headers = {
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Content-Length': str(content_length if content_length is not None else len(body)),
        }
        self.rfile = io.BytesIO(body)


def _build_multipart(boundary: str, file_bytes: bytes) -> bytes:
    b = boundary.encode()
    return (
        b'--' + b + b'\r\n'
        b'Content-Disposition: form-data; name="file"; filename="a.wav"\r\n'
        b'Content-Type: application/octet-stream\r\n\r\n'
        + file_bytes + b'\r\n'
        b'--' + b + b'--\r\n'
    )


class LocalServerSecurityTests(unittest.TestCase):
    # SRV-1: binary audio ending in 0x2D ('-') must NOT be truncated.
    def test_parse_multipart_preserves_trailing_dashes(self):
        from whisper_key.local_server import _parse_multipart
        audio = b'\x00\x01\x02\x2d\x2d\x2d'  # ends in three dashes
        body = _build_multipart('BoUnDaRy123', audio)
        fields = _parse_multipart(_FakeHandler(body, 'BoUnDaRy123'))
        self.assertEqual(fields['file']['data'], audio)

    # SRV-2: oversized Content-Length is rejected before the body is read.
    def test_oversized_content_length_rejected(self):
        from whisper_key import local_server
        huge = local_server.MAX_UPLOAD_BYTES + 1
        handler = _FakeHandler(b'x', 'B', content_length=huge)
        with self.assertRaises(ValueError):
            local_server._parse_multipart(handler)

    # SEC #3: negative Content-Length must be rejected (read(-1) would drain socket).
    def test_negative_content_length_rejected(self):
        from whisper_key import local_server
        handler = _FakeHandler(b'x', 'B', content_length=-1)
        with self.assertRaises(ValueError):
            local_server._parse_multipart(handler)


class BundleRedactionTests(unittest.TestCase):
    # SEC #2: URL credentials + secret query params masked in ALL bundled files
    # (this is what protects doctor.txt, not just user_settings.yaml).
    def test_redact_masks_url_credentials_and_tokens(self):
        from whisper_key.bundle_logs import _redact
        out = _redact("Ollama post-edit: http://user:s3cret@ollama.host:11434 reachable")
        self.assertNotIn("s3cret", out)
        self.assertIn("<REDACTED>@", out)
        out2 = _redact("GET https://api.example.com/x?token=abc123&z=1")
        self.assertNotIn("abc123", out2)
        self.assertIn("<REDACTED>", out2)

    # PRIV-1: sensitive config fields are masked in user_settings.yaml.
    def test_redact_yaml_masks_sensitive_fields(self):
        from whisper_key.bundle_logs import _redact_yaml
        sample = (
            "whisper:\n"
            "  hotwords: [SecretName, CodeWord]\n"
            "  initial_prompt: my private context\n"
            "postprocess:\n"
            "  ollama:\n"
            "    endpoint: http://user:pass@host:11434\n"
        )
        out = _redact_yaml(sample)
        self.assertNotIn('SecretName', out)
        self.assertNotIn('CodeWord', out)
        self.assertNotIn('private context', out)
        self.assertNotIn('user:pass', out)
        self.assertIn('<REDACTED>', out)

    def test_redact_yaml_masks_block_hotwords(self):
        from whisper_key.bundle_logs import _redact_yaml
        sample = "whisper:\n  hotwords:\n    - Alpha\n    - Bravo\n  model: tiny\n"
        out = _redact_yaml(sample)
        self.assertNotIn('Alpha', out)
        self.assertNotIn('Bravo', out)
        self.assertIn('model: tiny', out)  # non-sensitive keys untouched


class VoiceCommandQuotingTests(unittest.TestCase):
    # VC-1: clipboard content is shell-quoted when expanded into a run: command.
    def test_shell_safe_quotes_clipboard(self):
        try:
            from whisper_key.voice_commands import VoiceCommandManager
        except Exception:
            self.skipTest("voice_commands not importable on this platform")
        import shlex
        import unittest.mock as mock
        vc = VoiceCommandManager.__new__(VoiceCommandManager)
        with mock.patch('whisper_key.voice_commands.pyperclip.paste', return_value='; rm -rf ~'):
            safe = vc._expand_template('echo ${clipboard}', shell_safe=True)
            raw = vc._expand_template('echo ${clipboard}', shell_safe=False)
        self.assertEqual(safe, 'echo ' + shlex.quote('; rm -rf ~'))
        self.assertEqual(raw, 'echo ; rm -rf ~')


class AutostartTests(unittest.TestCase):
    def test_module_and_api(self):
        from whisper_key import autostart
        for fn in ('is_supported', 'is_enabled', 'enable', 'disable', 'toggle'):
            self.assertTrue(callable(getattr(autostart, fn, None)), f"missing {fn}")

    def test_is_supported_matches_platform(self):
        import sys
        from whisper_key import autostart
        self.assertEqual(autostart.is_supported(), sys.platform in ('win32', 'darwin'))

    def test_launch_command_nonempty(self):
        from whisper_key import autostart
        cmd = autostart._launch_command()
        self.assertIsInstance(cmd, list)
        self.assertTrue(cmd and cmd[0])

    def test_macos_plist_roundtrip(self):
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from whisper_key import autostart
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'agent.plist'
            with mock.patch('whisper_key.autostart._mac_plist_path', return_value=p):
                self.assertFalse(autostart._mac_is_enabled())
                autostart._mac_enable()
                self.assertTrue(autostart._mac_is_enabled())
                content = p.read_text(encoding='utf-8')
                self.assertIn('RunAtLoad', content)
                self.assertIn('com.drajb.whisper-local', content)
                autostart._mac_disable()
                self.assertFalse(autostart._mac_is_enabled())

    def test_main_registers_autostart_flags(self):
        main_src = (ROOT / "src" / "whisper_key" / "main.py").read_text(encoding="utf-8")
        self.assertIn('--enable-autostart', main_src)
        self.assertIn('--disable-autostart', main_src)


class DefaultsTests(unittest.TestCase):
    def test_default_model_and_recording_mode(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "config.defaults.yaml"
        with open(path, encoding="utf-8") as f:
            cfg = YAML().load(f)
        self.assertEqual(cfg["whisper"]["model"], "base")
        self.assertEqual(cfg["hotkey"]["recording_mode"], "push_to_talk")

    def test_profiles_no_tiny_downgrade(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "profiles.defaults.yaml"
        with open(path, encoding="utf-8") as f:
            data = YAML().load(f)
        for name, prof in data["profiles"].items():
            model = (prof.get("overrides", {}).get("whisper") or {}).get("model")
            self.assertNotEqual(model, "tiny", f"profile '{name}' still pins tiny")

    def test_export_covers_all_user_files(self):
        # backup/restore must include every user-editable config file.
        from whisper_key.settings_io import EXPORTABLE_FILES
        for f in ("user_settings.yaml", "commands.yaml", "profiles.yaml",
                  "app_rules.yaml", "transforms.yaml"):
            self.assertIn(f, EXPORTABLE_FILES)


class ReviewFixTests(unittest.TestCase):
    # update_check must not crash on a "-dev" suffixed local version.
    def test_is_newer_handles_dev_suffix(self):
        from whisper_key.update_check import _is_newer
        self.assertTrue(_is_newer("0.12.0", "0.11.0-dev"))
        self.assertFalse(_is_newer("0.11.0", "0.11.0-dev"))   # same core, not newer
        self.assertFalse(_is_newer("1.2", "1.2.0"))           # padded equal
        self.assertTrue(_is_newer("v1.3.0", "1.2.9"))         # leading v tolerated

    # settings_ui._coerce must keep free-text settings as strings even when numeric-looking.
    def test_coerce_is_type_aware(self):
        from whisper_key.settings_ui import _coerce
        sentinel = object()  # not a BooleanVar
        self.assertEqual(_coerce(sentinel, "2024", "whisper.initial_prompt"), "2024")
        self.assertEqual(_coerce(sentinel, "3", "postprocess.ollama.model"), "3")
        self.assertEqual(_coerce(sentinel, "5", "whisper.beam_size"), 5)
        self.assertAlmostEqual(_coerce(sentinel, "0.75", "audio.noise_suppression.strength"), 0.75)

    # autostart.toggle returns the achieved state (macOS path, temp plist).
    def test_autostart_toggle_returns_state(self):
        import sys
        if sys.platform != "darwin":
            self.skipTest("toggle round-trip exercised via macOS plist path only")
        import tempfile, unittest.mock as mock
        from pathlib import Path
        from whisper_key import autostart
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("whisper_key.autostart._mac_plist_path", return_value=Path(d) / "a.plist"):
                self.assertTrue(autostart.toggle())
                self.assertFalse(autostart.toggle())


class StreamingDeliveryDecisionTests(unittest.TestCase):
    def _cfg(self, on=True):
        return {'deliver_to_cursor': on}

    def test_off_by_default(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertFalse(decide_stream_delivery({}, True, True, True, None))

    def test_all_conditions_met(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertTrue(decide_stream_delivery(self._cfg(), True, True, True, None))

    def test_requires_streaming_available(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertFalse(decide_stream_delivery(self._cfg(), False, True, True, None))

    def test_requires_auto_paste(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertFalse(decide_stream_delivery(self._cfg(), True, False, True, None))

    def test_requires_textable_foreground(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertFalse(decide_stream_delivery(self._cfg(), True, True, False, None))

    def test_respects_app_rule_suppress_and_copyonly(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertFalse(decide_stream_delivery(self._cfg(), True, True, True, {'suppress': True}))
        self.assertFalse(decide_stream_delivery(self._cfg(), True, True, True, {'auto_paste': False}))
        # a rule that doesn't touch delivery is fine
        self.assertTrue(decide_stream_delivery(self._cfg(), True, True, True, {'initial_prompt': 'x'}))


class StreamingDeliveryWorkerTests(unittest.TestCase):
    def test_segments_delivered_in_order_and_recorded(self):
        from whisper_key.streaming_delivery import StreamingDelivery
        delivered = []
        sd = StreamingDelivery(deliver_fn=delivered.append)
        sd.start()
        sd.submit_final("hello")
        sd.submit_final("world")
        full = sd.stop()
        self.assertEqual(delivered, ["hello ", "world "])
        self.assertEqual(full, "hello world")
        self.assertTrue(sd.submitted_any)

    def test_blank_segments_ignored(self):
        from whisper_key.streaming_delivery import StreamingDelivery
        delivered = []
        sd = StreamingDelivery(deliver_fn=delivered.append)
        sd.start()
        sd.submit_final("   ")
        sd.submit_final("")
        self.assertEqual(sd.stop(), "")
        self.assertEqual(delivered, [])
        self.assertFalse(sd.submitted_any)

    def test_stop_is_idempotent(self):
        from whisper_key.streaming_delivery import StreamingDelivery
        sd = StreamingDelivery(deliver_fn=lambda s: None)
        sd.start()
        sd.submit_final("x")
        self.assertEqual(sd.stop(), "x")
        self.assertEqual(sd.stop(), "x")  # second stop returns same, no error

    def test_deliver_fn_exception_does_not_crash_and_flags_failure(self):
        from whisper_key.streaming_delivery import StreamingDelivery
        def boom(_):
            raise RuntimeError("boom")
        sd = StreamingDelivery(deliver_fn=boom)
        sd.start()
        sd.submit_final("x")
        # stop() must still return cleanly even though delivery raised
        self.assertEqual(sd.stop(), "")
        self.assertTrue(sd.had_failure)

    def test_no_failure_flag_on_clean_delivery(self):
        from whisper_key.streaming_delivery import StreamingDelivery
        sd = StreamingDelivery(deliver_fn=lambda s: None)
        sd.start()
        sd.submit_final("ok")
        sd.stop()
        self.assertFalse(sd.had_failure)

    def test_submit_after_stop_is_ignored(self):
        # Closes the submit/stop race: a late segment after stop is dropped, not enqueued.
        from whisper_key.streaming_delivery import StreamingDelivery
        delivered = []
        sd = StreamingDelivery(deliver_fn=delivered.append)
        sd.start()
        sd.submit_final("a")
        sd.stop()
        sd.submit_final("late")
        self.assertEqual(delivered, ["a "])


class PromptLibraryTests(unittest.TestCase):
    # The library imports the path helper by name, so the patch target is the module.
    def _isolated(self):
        import tempfile
        import unittest.mock as mock
        from whisper_key import prompt_library as pl
        tmp = tempfile.TemporaryDirectory()
        patch = mock.patch('whisper_key.prompt_library.get_user_app_data_path', return_value=tmp.name)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(tmp.cleanup)
        return pl

    def test_capture_is_idempotent_and_keeps_edited_body(self):
        pl = self._isolated()
        first = pl.mutate(pl.Capture('dictation-key', 'original body'))
        self.assertTrue(first.changed)
        self.assertEqual(first.prompt.body, 'original body')
        edited = pl.mutate(pl.Save(
            id=first.prompt.id, title='Kept title', purpose='Bug fix', note='a note',
            body='edited body', source='dictation-key', base_rev=first.prompt.rev,
        ))
        self.assertTrue(edited.changed)
        again = pl.mutate(pl.Capture('dictation-key', 'original body'))
        self.assertFalse(again.changed)
        self.assertEqual(again.prompt.body, 'edited body')
        self.assertEqual(again.prompt.id, first.prompt.id)
        loaded = pl.load_prompts()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].body, 'edited body')

    def test_save_load_keeps_body_byte_identical(self):
        pl = self._isolated()
        bodies = [
            '  leading',
            'trailing  ',
            '\nblank first line',
            '# not a comment',
            'key: value',
            '---',
            '\n  leading\ntrailing  \n# hash\nkey: value\n---\n',
        ]
        saved = []
        for body in bodies:
            result = pl.mutate(pl.Save(
                id=None, title='Title', purpose='Notes', note='keep',
                body=body, source='', base_rev=None,
            ))
            self.assertTrue(result.changed)
            saved.append(result.prompt.id)
        loaded = {prompt.id: prompt.body for prompt in pl.load_prompts()}
        self.assertEqual(len(loaded), len(bodies))
        for pid, body in zip(saved, bodies):
            self.assertEqual(loaded[pid], body)

    def test_hand_edit_changes_rev_and_survives_stale_save(self):
        pl = self._isolated()
        first = pl.mutate(pl.Save(
            id=None, title='Keep me', purpose='Bug fix', note='n',
            body='alpha-unique-body-token', source='', base_rev=None,
        ))
        path = pl.prompts_path()
        original = path.read_text(encoding='utf-8')
        self.assertIn('alpha-unique-body-token', original)
        path.write_text(original.replace('alpha-unique-body-token', 'beta-hand-edit-token'), encoding='utf-8')
        loaded = pl.load_prompts()
        self.assertEqual(loaded[0].body, 'beta-hand-edit-token')
        self.assertNotEqual(loaded[0].rev, first.prompt.rev)
        before = path.read_bytes()
        stale = pl.mutate(pl.Save(
            id=first.prompt.id, title='Keep me', purpose='Bug fix', note='n',
            body='gamma-from-stale-window', source='', base_rev=first.prompt.rev,
        ))
        self.assertIsInstance(stale, pl.Conflict)
        self.assertEqual(stale.kind, 'changed')
        self.assertEqual(stale.current.body, 'beta-hand-edit-token')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(pl.load_prompts()[0].body, 'beta-hand-edit-token')

    def test_same_fields_with_old_base_rev_are_unchanged(self):
        pl = self._isolated()
        first = pl.mutate(pl.Save(
            id=None, title='T', purpose='P', note='N', body='B', source='', base_rev=None,
        ))
        before = pl.prompts_path().read_bytes()
        again = pl.mutate(pl.Save(
            id=first.prompt.id, title='T', purpose='P', note='N', body='B',
            source='', base_rev='0' * 12,
        ))
        self.assertIsInstance(again, pl.Wrote)
        self.assertFalse(again.changed)
        self.assertEqual(again.prompt.body, 'B')
        self.assertEqual(pl.prompts_path().read_bytes(), before)

    def test_delete_is_idempotent_and_stale_rev_conflicts(self):
        pl = self._isolated()
        first = pl.mutate(pl.Save(
            id=None, title='T', purpose='', note='', body='to-delete', source='', base_rev=None,
        ))
        deleted = pl.mutate(pl.Delete(first.prompt.id, first.prompt.rev))
        self.assertTrue(deleted.changed)
        self.assertIsNone(deleted.prompt)
        again = pl.mutate(pl.Delete(first.prompt.id, first.prompt.rev))
        self.assertFalse(again.changed)
        self.assertIsNone(again.prompt)
        self.assertEqual(pl.load_prompts(), [])
        second = pl.mutate(pl.Save(
            id=None, title='T', purpose='', note='', body='alive', source='', base_rev=None,
        ))
        changed = pl.mutate(pl.Save(
            id=second.prompt.id, title='T', purpose='', note='', body='alive-edited',
            source='', base_rev=second.prompt.rev,
        ))
        self.assertTrue(changed.changed)
        before = pl.prompts_path().read_bytes()
        stale = pl.mutate(pl.Delete(second.prompt.id, second.prompt.rev))
        self.assertIsInstance(stale, pl.Conflict)
        self.assertEqual(stale.kind, 'changed')
        self.assertEqual(pl.prompts_path().read_bytes(), before)
        self.assertEqual(pl.load_prompts()[0].body, 'alive-edited')

    def test_malformed_file_is_not_overwritten(self):
        pl = self._isolated()
        path = pl.prompts_path()
        path.write_bytes(b':\n  - [\n')
        before = path.read_bytes()
        with self.assertRaises(pl.PromptFileError):
            pl.mutate(pl.Save(
                id=None, title='T', purpose='', note='', body='nope', source='', base_rev=None,
            ))
        self.assertEqual(path.read_bytes(), before)
        path.write_text('other: 1\n', encoding='utf-8')
        before = path.read_bytes()
        with self.assertRaises(pl.PromptFileError):
            pl.load_prompts()
        with self.assertRaises(pl.PromptFileError):
            pl.mutate(pl.Delete('a' * 12, 'b' * 12))
        self.assertEqual(path.read_bytes(), before)

    def test_two_threads_both_persist(self):
        import threading
        pl = self._isolated()
        barrier = threading.Barrier(2)
        errors = []

        def work(body):
            try:
                barrier.wait(timeout=5)
                pl.mutate(pl.Capture(body, body))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(f'body-{i}',)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(prompt.body for prompt in pl.load_prompts()), ['body-0', 'body-1'])

    def test_prompt_save_older_seq_is_stale_and_does_not_write(self):
        pl = self._isolated()
        from whisper_key.history_window import Api
        api = Api('unused')
        raw = {'title': 'T', 'purpose': '', 'note': '', 'body': 'one', 'source': ''}
        first = api.prompt_save(dict(raw), None, 2)
        self.assertEqual(first['status'], 'saved')
        self.assertEqual(first['prompt']['body'], 'one')
        older = api.prompt_save(
            {'id': first['prompt']['id'], 'title': 'T', 'purpose': '', 'note': '',
             'body': 'two', 'source': ''},
            first['prompt']['rev'], 1,
        )
        self.assertEqual(older, {'status': 'stale'})
        self.assertEqual(pl.load_prompts()[0].body, 'one')
        newer = api.prompt_save(
            {'id': first['prompt']['id'], 'title': 'T', 'purpose': '', 'note': '',
             'body': 'two', 'source': ''},
            first['prompt']['rev'], 3,
        )
        self.assertEqual(newer['status'], 'saved')
        self.assertEqual(pl.load_prompts()[0].body, 'two')

    def test_prompts_poll_returns_none_for_unchanged_sig(self):
        pl = self._isolated()
        from whisper_key.history_window import Api
        api = Api('unused')
        first = api.prompts_poll('')
        self.assertEqual(first['prompts'], [])
        self.assertIsNone(api.prompts_poll(first['sig']))
        saved = api.prompt_capture('dictation-key', 'captured text')
        self.assertTrue(saved['created'])
        second = api.prompts_poll(first['sig'])
        self.assertEqual([item['body'] for item in second['prompts']], ['captured text'])
        self.assertIsNone(api.prompts_poll(second['sig']))
        self.assertEqual(pl.load_prompts()[0].body, 'captured text')

    def test_control_characters_round_trip_and_list_loads(self):
        pl = self._isolated()
        bodies = ['a\x1b[0m\nb', 'a\u2028b\nc', 'a\x00b\nc']
        saved = []
        for body in bodies:
            result = pl.mutate(pl.Save(
                id=None, title='T', purpose='', note='', body=body, source='', base_rev=None,
            ))
            self.assertTrue(result.changed)
            saved.append(result.prompt.id)
        loaded = {prompt.id: prompt.body for prompt in pl.load_prompts()}
        self.assertEqual(len(loaded), len(bodies))
        for pid, body in zip(saved, bodies):
            self.assertEqual(loaded[pid], body)

    def test_crlf_round_trip_and_identical_retry_is_unchanged(self):
        pl = self._isolated()
        first = pl.mutate(pl.Save(
            id=None, title='T', purpose='P', note='N', body='line\r\nnext\r', source='', base_rev=None,
        ))
        self.assertEqual(first.prompt.body, 'line\nnext\n')
        self.assertEqual(pl.load_prompts()[0].body, 'line\nnext\n')
        before = pl.prompts_path().read_bytes()
        again = pl.mutate(pl.Save(
            id=first.prompt.id, title='T', purpose='P', note='N', body='line\r\nnext\r',
            source='', base_rev='0' * 12,
        ))
        self.assertIsInstance(again, pl.Wrote)
        self.assertFalse(again.changed)
        self.assertEqual(again.prompt.body, 'line\nnext\n')
        self.assertEqual(pl.prompts_path().read_bytes(), before)

    def test_plain_scalars_from_hand_edit_load(self):
        pl = self._isolated()
        path = pl.prompts_path()
        path.write_text(
            "prompts:\n"
            "- id: abc123abc123\n"
            "  title: true\n"
            "  purpose: 12\n"
            "  note: 1.5\n"
            "  body: hello-scalar\n"
            "  created: 2020-01-02\n"
            "  updated: 2020-01-02T03:04:05\n",
            encoding='utf-8',
        )
        loaded = pl.load_prompts()
        self.assertEqual(len(loaded), 1)
        prompt = loaded[0]
        self.assertEqual(prompt.title, 'True')
        self.assertEqual(prompt.purpose, '12')
        self.assertEqual(prompt.note, '1.5')
        self.assertEqual(prompt.body, 'hello-scalar')
        self.assertEqual(prompt.created, '2020-01-02')
        self.assertEqual(prompt.updated, '2020-01-02T03:04:05')

    def test_duplicate_ids_raise(self):
        pl = self._isolated()
        path = pl.prompts_path()
        entry = (
            "  - id: abc123abc123\n"
            "    title: T\n"
            "    purpose: ''\n"
            "    note: ''\n"
            "    body: one\n"
            "    source: ''\n"
            "    created: 't'\n"
            "    updated: 't'\n"
        )
        path.write_text('prompts:\n' + entry + entry, encoding='utf-8')
        before = path.read_bytes()
        with self.assertRaises(pl.PromptFileError) as raised:
            pl.load_prompts()
        self.assertIn('abc123abc123', str(raised.exception))
        with self.assertRaises(pl.PromptFileError) as raised:
            pl.mutate(pl.Save(
                id=None, title='T', purpose='', note='', body='new', source='', base_rev=None,
            ))
        self.assertIn('abc123abc123', str(raised.exception))
        self.assertEqual(path.read_bytes(), before)

    def test_hand_edit_just_before_replace_is_not_lost(self):
        # A write that lands after the read and before replace is merged, not overwritten.
        import unittest.mock as mock
        pl = self._isolated()
        pl.mutate(pl.Save(
            id=None, title='T', purpose='', note='', body='keep-me', source='', base_rev=None,
        ))
        real = pl._file_sig
        state = {'checks': 0}

        def sig(path):
            state['checks'] += 1
            if state['checks'] == 2:
                text = path.read_text(encoding='utf-8')
                path.write_text(text.replace('keep-me', 'hand-kept-token'), encoding='utf-8')
            return real(path)

        with mock.patch.object(pl, '_file_sig', sig):
            added = pl.mutate(pl.Save(
                id=None, title='T', purpose='', note='', body='new-body', source='', base_rev=None,
            ))
        self.assertTrue(added.changed)
        self.assertEqual(
            sorted(prompt.body for prompt in pl.load_prompts()),
            ['hand-kept-token', 'new-body'],
        )

    def test_round_trip_mismatch_does_not_replace(self):
        import unittest.mock as mock
        pl = self._isolated()
        first = pl.mutate(pl.Save(
            id=None, title='T', purpose='', note='', body='safe-body', source='', base_rev=None,
        ))
        path = pl.prompts_path()
        before = path.read_bytes()
        real = pl._yaml

        def bad_yaml():
            yaml = real()

            def dump(doc, handle):
                handle.write(
                    "prompts:\n"
                    "- id: 'abcdefabcdef'\n"
                    "  title: T\n"
                    "  purpose: ''\n"
                    "  note: ''\n"
                    "  body: DIFFERENT\n"
                    "  source: ''\n"
                    "  created: 'x'\n"
                    "  updated: 'x'\n"
                )

            yaml.dump = dump
            return yaml

        with mock.patch.object(pl, '_yaml', bad_yaml):
            with self.assertRaises(pl.PromptFileError):
                pl.mutate(pl.Save(
                    id=None, title='T', purpose='', note='', body='other-body', source='', base_rev=None,
                ))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(pl.load_prompts()[0].body, first.prompt.body)

    def test_capture_key_is_a_hash_and_body_edit_keeps_dedupe(self):
        import hashlib
        pl = self._isolated()
        from whisper_key.history_window import Api
        text = 'original body'
        timestamp = '2024-05-06T07:08:09'
        digest = hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]
        key = f'{timestamp}|{digest}'
        api = Api('unused')
        first = api.prompt_capture(timestamp, text)
        self.assertTrue(first['created'])
        self.assertEqual(first['prompt']['source'], key)
        self.assertNotIn(text, first['prompt']['source'])
        edited = api.prompt_save(
            {
                'id': first['prompt']['id'], 'title': 'T', 'purpose': '', 'note': '',
                'body': 'edited body', 'source': first['prompt']['source'],
            },
            first['prompt']['rev'], 1,
        )
        self.assertEqual(edited['status'], 'saved')
        self.assertEqual(edited['prompt']['source'], key)
        again = api.prompt_capture(timestamp, text)
        self.assertFalse(again['created'])
        self.assertEqual(again['prompt']['id'], first['prompt']['id'])
        self.assertEqual(again['prompt']['body'], 'edited body')
        raw = pl.prompts_path().read_text(encoding='utf-8')
        self.assertIn(key, raw)
        self.assertNotIn(f'{timestamp}|{text}', raw)

    def test_title_bar_close_asks_once_then_closes(self):
        from whisper_key.history_window import Api, page_flush_outcome
        api = Api('unused')
        self.assertIs(api.allow_close(), False)
        self.assertIs(api.allow_close(), True)
        permitted = Api('unused')
        permitted._close_permit = True
        self.assertIs(permitted.allow_close(), True)

        def boom():
            raise RuntimeError('evaluate_js failed')

        self.assertEqual(page_flush_outcome(boom), 'close')
        self.assertEqual(page_flush_outcome(lambda: None), 'asked')


if __name__ == "__main__":
    unittest.main()
