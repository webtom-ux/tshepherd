"""Read-only rediscovery regression: real snapshot subprocess, no live fleet."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import tshepherd as app
from fixtures import sample_snapshot
from test_tshepherd import FakeRunner


class ReloadTests(unittest.TestCase):
    def test_actual_snapshot_reload_recovers_without_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            directory = str(root)
            (root / 'bin').mkdir()
            data = root / 'snapshot.json'
            script = root / 'bin/fm-fleet-snapshot.sh'
            script.write_text('#!/bin/sh\nexec /bin/cat "$FM_HOME/snapshot.json"\n')
            script.chmod(0o700)
            native = FakeRunner()
            real = app.Runner(native.stop)
            original = native.run
            native.run = lambda argv, timeout, env=None: (real.run(argv, timeout, env)
                if argv[0] == str(script) else original(argv, timeout, env))
            config = app.Config(directory, directory)
            source = app.Source(config, native)
            snapshot = sample_snapshot(directory)
            task = snapshot['tasks'][0]
            snapshot['tasks'] = [task]
            task['endpoint']['target'] = 'named:w1:p1'
            data.write_text(json.dumps(snapshot))
            native.bad = 'shell'
            first = source.collect()
            self.assertEqual(first[1][task['id']].state, 'unknown')
            self.assertIn('Shell-only', first[1][task['id']].detail)
            # Smallest counterfactual: evidence changes; no dashboard restart.
            native.bad = ''
            recovered = source.collect()
            self.assertEqual(recovered[1][task['id']].state, 'idle')
            restarted = app.Source(config, native).collect()
            self.assertEqual(recovered[1][task['id']].physical,
                             restarted[1][task['id']].physical)
            view = app.View()
            view.apply('snapshot', recovered)
            view.selection(app.rows_for(*recovered, time.time(), 45))
            selected = view.selected
            # Fresh authoritative endpoint, not a cached Source.snapshot override.
            task['endpoint']['target'] = 'named:w2:p1'
            native.pane = 'w2:p1'
            data.write_text(json.dumps(snapshot))
            rebound = source.collect()
            self.assertEqual(rebound[1][task['id']].physical[0], 'w2')
            view.apply('snapshot', rebound)
            self.assertEqual(view.selection(app.rows_for(*rebound, time.time(), 45)), -1)
            self.assertNotEqual(view.selected, app.identity(task))
            self.assertNotEqual(selected, app.identity(task))
            # Invalid authoritative endpoint remains unknown, no namespace lookup.
            task['endpoint']['target'] = 'named:garbage'
            data.write_text(json.dumps(snapshot))
            invalid = source.collect()[1][task['id']]
            self.assertEqual(invalid.state, 'unknown')
            self.assertIn('invalid endpoint identity', invalid.detail)
            self.assertFalse(any('focus' in call or 'list' in call for call in native.calls))

    def test_same_logical_identity_physical_replacement_requires_navigation(self):
        snapshot = sample_snapshot(str(Path.cwd()))
        task = snapshot['tasks'][0]
        snapshot['tasks'] = [task]
        view = app.View()
        for physical in [('w1', 't1', 'old'), (), ('w1', 't1', 'new')]:
            native = app.Native('idle' if physical else 'unknown', observed=time.time(),
                                binding=app.identity(task), physical=physical)
            view.apply('snapshot', (snapshot, {task['id']: native}))
            rows = app.rows_for(snapshot, view.natives, time.time(), 45)
            result = view.selection(rows)
        self.assertEqual(result, -1)
        self.assertEqual(view.selection(rows, 1), 0)
        self.assertEqual(view.selected_physical, ('w1', 't1', 'new'))

    def test_unavailable_source_reason_is_actionable_not_stderr(self):
        runner = FakeRunner()
        task = sample_snapshot(str(Path.cwd()))['tasks'][0]
        task['endpoint']['target'] = 'named:w1:p1'
        source = app.Source(app.Config(str(Path.cwd()), '/code'), runner)
        with patch.object(runner, 'run', side_effect=RuntimeError('secret-token=hidden')):
            native = source.probe(task, time.monotonic() + 10)
            primary = source.primary(time.monotonic() + 10)
        for reason in (native.detail, primary.reason):
            self.assertIn('check', reason)
            self.assertNotIn('secret', reason)
        runner.native = 'done'
        native = source.probe(task, time.monotonic() + 10)
        self.assertEqual(native.state, 'done')
        self.assertIn('ready for input', native.detail)
        self.assertTrue(native.physical)

    def test_retry_threshold_cooldown_and_recovery(self):
        retry = app.UnknownRetry()
        row = app.PrimaryRow()
        self.assertFalse(retry.due([row], 0))
        self.assertFalse(retry.due([row], 29))
        self.assertTrue(retry.due([row], 30))
        self.assertFalse(retry.due([row], 89))
        self.assertTrue(retry.due([row], 90))
        row.live = 'idle'
        self.assertFalse(retry.due([row], 150))
        row.live = 'unknown'
        self.assertFalse(retry.due([row], 151))
        self.assertTrue(retry.due([row], 181))

    def test_manual_refresh_single_flight(self):
        class Source:
            runner = FakeRunner()
            entered = threading.Event()
            release = threading.Event()
            calls = 0

            def collect(self):
                self.calls += 1
                self.entered.set()
                self.release.wait(2)
                return {}, {}

        source = Source()
        poller = app.Poller(source, 100)
        poller.start()
        try:
            self.assertTrue(source.entered.wait(1))
            self.assertFalse(poller.request_refresh())
            source.release.set()
            poller.results.get(timeout=1)
            deadline = time.monotonic() + 1
            while poller.busy.is_set() and time.monotonic() < deadline:
                time.sleep(.001)
            self.assertTrue(poller.request_refresh())
            poller.results.get(timeout=1)
            self.assertEqual(source.calls, 2)
        finally:
            source.release.set()
            poller.close()

    def test_primary_semantic_palette_and_manual_key(self):
        for state in ('working', 'waiting', 'idle', 'done', 'unknown'):
            primary = app.PrimaryRow(live=state, physical=('w', 't', 'term'))
            view = app.View(selected=primary.key, last_success=time.time())
            for width in (45, 110):
                lines = app.render_lines(view, [primary], width, 30, False, time.time())
                spans = next(spans for text, spans in lines if '◆ Firstmate' in text)
                self.assertIn((0, '    > ◆ Firstmate', app.LIVE_STATES.index(state) + 1), spans)
                self.assertIn('R refresh', lines[-1][0])
        class Screen:
            keys = iter([ord('R'), ord('q')])
            def getch(self): return next(self.keys)
            def getmaxyx(self): return 30, 110
            def __getattr__(self, name): return lambda *args: None
        with patch.object(app, 'Poller') as poller, patch.object(app.curses, 'curs_set'), patch.object(app.curses, 'has_colors', return_value=False):
            poller.return_value.results.empty.return_value = True
            app.tui(Screen(), app.Source(app.Config('/home', '/root'), FakeRunner()))
            poller.return_value.request_refresh.assert_called_once_with()
