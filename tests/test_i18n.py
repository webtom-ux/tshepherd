"""Deterministic localization coverage: no live fleet or focus dispatch."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import i18n
import tshepherd as app
from fixtures import collect


class LanguageTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language('en')

    def test_default_and_explicit_selection(self):
        for options, expected in [([], 'en'), (['--lang', 'de'], 'de'), (['--lang=en'], 'en')]:
            args, _ = app.parse_args(['--fm-home', '/example', '--firstmate-root', '/example', *options])
            self.assertEqual(args.lang, expected)
            self.assertEqual(i18n.LANGUAGE, expected)
        with self.assertRaises(ValueError):
            i18n.set_language('fr')

    def test_cli_help_errors_and_no_locale_detection(self):
        script = str(Path(app.__file__))
        env = {k: v for k, v in os.environ.items() if not k.startswith('TSHEPHERD_')}
        env.update(PYTHONDONTWRITEBYTECODE='1', LANGUAGE='de_DE', LANG='C')
        for options, word in [([], 'UI language'), (['--lang', 'en'], 'UI language'),
                              (['--lang', 'de'], 'Sprache der Oberfläche')]:
            result = subprocess.run([sys.executable, script, *options, '--help'],
                                    env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(word, result.stdout)
            self.assertIn('--lang {en,de}', result.stdout)
        for options, word in [([], 'provide --fm-home'), (['--lang', 'de'], 'explizit angeben'),
                              (['--lang', 'fr'], 'invalid choice'),
                              (['--lang', 'de', '--unexpected'], 'unbekannte Argumente'),
                              (['--lang', 'de', '--fm-home'], 'ein Argument erwartet')]:
            result = subprocess.run([sys.executable, script, *options], env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertIn(word, result.stderr)
            self.assertNotIn('Traceback', result.stderr)

    def test_argparse_translation_restored_on_exit(self):
        original = argparse._
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            app.parse_args(['--lang', 'de', '--help'])
        self.assertIs(argparse._, original)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            app.parse_args(['--lang', 'de'])
        self.assertIs(argparse._, original)

    def test_owned_ui_labels_both_languages_and_external_text_untouched(self):
        for language, header, duration, refresh, state, too_small in [
            ('en', 'Latest known activity', 'Time', 'R refresh', 'waiting', 'terminal too small'),
            ('de', 'Letzte bekannte Aktivität', 'Zeit', 'R neu', 'wartet', 'Terminal zu klein')]:
            with self.subTest(language=language):
                i18n.set_language(language)
                snapshot, natives = collect(type('Source', (), {'config': app.Config('/example', '/example')})())
                # Deliberately equal to dictionary keys: these are user payloads.
                for task in snapshot['tasks']:
                    task['backlog']['repo'] = 'Projekt unbekannt'
                    task['backlog']['title'] = 'nicht gemessen'
                    task['current_state']['detail'] = 'Befehl fehlgeschlagen'
                view = app.View(snapshot=snapshot, natives=natives, last_success=time.time())
                rows = app.overview_rows(view, time.time(), 45)
                for width, height in [(140, 30), (40, 30), (28, 16)]:
                    frame = app.render_lines(view, rows, width, height, False, time.time())
                    self.assertEqual(len(frame), height)
                    self.assertTrue(all(app.cells(line) <= width - 1 for line, _ in frame))
                text = '\n'.join(line for line, _ in app.render_lines(view, rows, 140, 30, False, time.time()))
                for expected in [header, duration, refresh, state, 'Projekt unbekannt', 'nicht gemessen', 'Befehl fehlgeschlagen']:
                    self.assertIn(expected, text)
                self.assertNotIn('Time/Task', text)
                self.assertNotIn('Zeit/Aufg.', text)
                # Task outcome and raw source fields are not translated.
                self.assertIn('parked', text)
                self.assertIn(too_small, app.render_lines(view, rows, 100, 10, False, time.time())[0][0])
                badges = [role for _, spans in app.render_lines(view, rows, 140, 30, False, time.time())
                          for _, _, role in spans if role >= 11]
                self.assertEqual(badges, list(range(11, 17)))

    def test_owned_errors_defaults_and_external_runner_payload(self):
        for language, invalid, default in [('en', 'invalid endpoint identity', 'not measured'),
                                           ('de', 'ungültige Endpunktidentität', 'nicht gemessen')]:
            i18n.set_language(language)
            with self.assertRaisesRegex(ValueError, invalid):
                app.parse_endpoint('bad:invalid')
            self.assertEqual(app.Native().detail, default)
            with self.assertRaisesRegex(ValueError, i18n.tr('Snapshot-Schema unbekannt')):
                app.validate_snapshot({}, '/example')
            view = app.View(selected=('a',), selected_physical=('old',))
            view.apply('snapshot', ({}, {'a': app.Native(physical=('new',))}))
            self.assertEqual(view.message, i18n.tr('Zielidentität geändert · bitte erneut wählen'))
        # An external tool message is passed through, even if it matches a key.
        import threading
        i18n.set_language('en')
        with self.assertRaisesRegex(RuntimeError, '^Befehl fehlgeschlagen$'):
            app.Runner(threading.Event()).run(
                [sys.executable, '-c', 'import sys; sys.stderr.write("Befehl fehlgeschlagen"); sys.exit(1)'], 3)

    def test_primary_reader_owned_message_translation(self):
        import threading
        for language, expected in [('en', 'owner process not confirmed'), ('de', 'Owner-Prozess nicht bestätigt')]:
            i18n.set_language(language)
            runner = app.Runner(threading.Event())
            source = app.Source(app.Config('/example', '/example'), runner)
            with patch.object(runner, 'run', return_value={'unavailable': 'Owner-Prozess nicht bestätigt'}):
                self.assertIn(expected, source.primary(time.monotonic() + 1).reason)


if __name__ == '__main__':
    unittest.main()
