"""Fleet-independent primary ownership, selection and focus failure contracts."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import primary_identity as owner_api
import tshepherd as app
from fixtures import sample_snapshot
from test_tshepherd import FakeRunner


class OwnerReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / 'state').mkdir()
        self.lock = self.home / 'state/.lock'
        self.pid = os.getpid()
        self.lock.write_text(str(self.pid) + '\n')
        start = self.lock.stat().st_mtime_ns - 10**9
        class Reader:
            def process(_, pid):
                if pid == self.pid:
                    return dict(pid=pid, ppid=222, start=start, uid=os.getuid())
                if pid == 222:
                    return dict(pid=222, ppid=1, start=start-10**9, uid=os.getuid())
                raise ValueError('missing process')
            def environment(_, pid):
                return {'HERDR_ENV': '1', 'HERDR_PANE_ID': 'wA:p2'}
        self.reader = Reader()

    def observe(self, shell=None, classifier=lambda root, pid: True):
        return owner_api.observe(self.home, self.home, shell, self.reader, classifier)

    def test_exact_lock_generation_and_ancestry(self):
        first = self.observe()
        self.assertEqual(first, self.observe(222))
        self.assertEqual(first['process']['pid'], self.pid)
        with self.assertRaises(ValueError):
            self.observe(333)
        with self.assertRaises(ValueError):
            self.observe(True)

    def test_missing_malformed_symlink_and_stale_lock(self):
        original = self.lock.read_bytes()
        for value in ('', '123 456', '-1', '0', '1', '9999999999999999', '1234' + ' ' * 70 + '5678'):
            self.lock.write_text(value)
            with self.assertRaises(ValueError):
                self.observe()
        self.lock.write_bytes(original)
        os.utime(self.lock, (1, 1))
        with self.assertRaisesRegex(ValueError, 'Prozessgeneration'):
            self.observe()
        self.lock.unlink()
        with self.assertRaises(OSError):
            self.observe()
        self.lock.symlink_to(self.home / 'missing')
        with self.assertRaises(OSError):
            self.observe()

    def test_owner_or_environment_change_is_unavailable(self):
        original = self.reader.environment
        reads = 0
        def changed(pid):
            nonlocal reads
            reads += 1
            return dict(original(pid), HERDR_PANE_ID='w1:p1' if reads == 1 else 'w2:p1')
        self.reader.environment = changed
        with self.assertRaisesRegex(ValueError, 'geändert'):
            self.observe()
        self.reader.environment = original
        with self.assertRaisesRegex(ValueError, 'Harness'):
            self.observe(classifier=lambda root, pid: False)
        calls = 0
        def exec_changed(root, pid):
            nonlocal calls
            calls += 1
            return calls == 1
        with self.assertRaisesRegex(ValueError, 'geändert'):
            self.observe(classifier=exec_changed)

    def test_pid_reuse_and_lock_write_during_read_rejected(self):
        original = self.reader.process
        reads = 0
        def changed(pid):
            nonlocal reads
            reads += 1
            return dict(original(pid), start=original(pid)['start'] + reads)
        self.reader.process = changed
        with self.assertRaisesRegex(ValueError, 'geändert'):
            self.observe()
        self.reader.process = original
        def changed_lock(pid):
            self.lock.write_text('1234\n')
            return {}
        self.reader.environment = changed_lock
        with self.assertRaisesRegex(ValueError, 'geändert'):
            self.observe()

    def test_selected_environment_discards_secret_and_rejects_duplicates(self):
        def buffer(env):
            return (2).to_bytes(4, sys.byteorder) + b'/bin/program\0\0program\0private-arg\0' + env
        selected = owner_api.selected_environment(buffer(b'SECRET=not-output\0HERDR_PANE_ID=w1:p1\0HERDR_ENV=1\0\0'))
        self.assertEqual(selected, {'HERDR_PANE_ID': 'w1:p1', 'HERDR_ENV': '1'})
        with self.assertRaisesRegex(ValueError, 'mehrdeutig'):
            owner_api.selected_environment(buffer(b'HERDR_PANE_ID=w1:p1\0HERDR_PANE_ID=w2:p1\0'))
        with self.assertRaises(ValueError):
            owner_api.selected_environment(b'bad')
        with patch.object(owner_api.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(ValueError, 'macOS'):
                owner_api.Darwin()


class PrimaryRunner(FakeRunner):
    def __init__(self):
        super().__init__()
        self.owner = dict(home=str(Path.cwd()), lock=[1, 2, 4, 10, 10],
                          process=dict(pid=321, start=9, ppid=111, uid=os.getuid()),
                          environment=dict(HERDR_ENV='1', HERDR_SESSION='named',
                                           HERDR_PANE_ID='w1:p1', HERDR_TAB_ID='w1:t1',
                                           HERDR_WORKSPACE_ID='w1',
                                           HERDR_SOCKET_PATH='/fixture/herdr/sessions/named/herdr.sock'))
        self.ancestry = True
        self.after_focus = None

    def run(self, argv, timeout, env=None):
        if len(argv) > 1 and Path(argv[1]).name == 'primary_identity.py':
            self.calls.append(argv)
            if len(argv) == 5 and not self.ancestry:
                return {'unavailable': 'not a descendant'}
            return copy.deepcopy(self.owner)
        result = super().run(argv, timeout, env)
        if argv[1:3] == ['pane', 'process-info']:
            result['result']['process_info']['shell_pid'] = 111
        if argv[1:3] == ['agent', 'focus'] and self.after_focus:
            self.after_focus()
        return result


class PrimaryTests(unittest.TestCase):
    def setUp(self):
        self.runner = PrimaryRunner()
        self.source = app.Source(app.Config(str(Path.cwd()), '/source'), self.runner)
        self.source.snapshot = lambda: self.fail('Primary Enter must not read the fleet')

    def measured(self):
        return self.source.primary(time.monotonic() + 12)

    def test_primary_exact_focus_without_fleet_and_no_outcome(self):
        first = self.measured()
        self.assertTrue(first.physical, first.reason)
        self.assertEqual(first.live, 'idle')
        self.assertFalse(hasattr(first, 'task'))
        self.assertFalse(hasattr(first, 'outcome'))
        self.assertIn('Firstmate', self.source.focus(first.key))
        mutations = [c[1:4] for c in self.runner.calls if 'focus' in c]
        self.assertEqual(mutations, [['agent', 'focus', 'w1:p1'], ['tab', 'focus', 'w1:t1']])
        self.runner.native = 'done'
        done = self.measured()
        self.assertEqual(done.live, 'unknown')
        self.assertTrue(done.physical)
        self.assertIn('confirmed', self.source.focus(done.key))

    def test_missing_ambiguous_foreign_stale_or_restricted_never_focus(self):
        original = copy.deepcopy(self.runner.owner)
        selected = self.measured().key
        changes = [lambda: self.runner.owner.update(unavailable='missing/restricted lock'),
                   lambda: self.runner.owner.update(home='/foreign'),
                   lambda: self.runner.owner['process'].update(start=11),
                   lambda: self.runner.owner['environment'].update(HERDR_TAB_ID='w2:t1'),
                   lambda: self.runner.owner['environment'].update(HERDR_SESSION='foreign'),
                   lambda: self.runner.owner['environment'].update(HERDR_SESSION=''),
                   lambda: self.runner.owner['environment'].update(HERDR_SOCKET_PATH='/wrong/herdr.sock'),
                   lambda: setattr(self.runner, 'ancestry', False)]
        for change in changes:
            self.runner.owner = copy.deepcopy(original)
            self.runner.ancestry = True
            change()
            self.runner.calls.clear()
            with self.assertRaises(ValueError):
                self.source.focus(selected)
            self.assertFalse(any('focus' in c for c in self.runner.calls))

    def test_physical_replacement_after_owner_check_rejected(self):
        original = self.runner.run
        checked = False
        def replace_physical(argv, timeout, env=None):
            nonlocal checked
            response = original(argv, timeout, env)
            if Path(argv[1]).name == 'primary_identity.py' and len(argv) == 5:
                checked = True
            if checked and argv[1:3] == ['pane', 'get']:
                response['result']['pane']['terminal_id'] = 'replacement'
            return response
        self.runner.run = replace_physical
        row = self.measured()
        self.assertFalse(row.physical)
        self.assertIn('physical', row.reason)
        self.assertFalse(any('focus' in c for c in self.runner.calls))

    def test_second_mutation_rechecks_owner_generation(self):
        selected = self.measured().key
        self.runner.after_focus = lambda: self.runner.owner['process'].update(start=11)
        with self.assertRaisesRegex(ValueError, 'tab switch not confirmed'):
            self.source.focus(selected)
        self.assertFalse(any(c[1:3] == ['tab', 'focus'] for c in self.runner.calls))

    def test_guarded_lab_refuses_default_before_native_reads(self):
        self.source.config.lab_session = 'fm-lab-only'
        self.source.config.lab_helper = '/helper'
        row = self.measured()
        self.assertFalse(row.physical)
        self.assertIn('foreign session', row.reason)
        self.assertEqual(len(self.runner.calls), 1)

    def test_default_absent_session_requires_owner_canonical_socket(self):
        self.runner.owner['environment'].pop('HERDR_SESSION')
        first = self.measured()
        self.assertFalse(first.physical)
        self.assertIn('session', first.reason)
        socket = str(Path.home()/'.config/herdr/herdr.sock')
        self.runner.owner['environment']['HERDR_SOCKET_PATH'] = socket
        original = self.runner.run
        def default(argv, timeout, env=None):
            response = original(argv, timeout, env)
            if argv[1:3] == ['status', '--json']:
                response['server']['socket'] = socket
            return response
        self.runner.run = default
        row = self.measured()
        self.assertTrue(row.physical, row.reason)
        self.assertEqual(row.session, 'default')

    def test_minimum_size_selected_worker_stable_across_frames(self):
        now = time.time()
        snapshot = sample_snapshot(str(Path.cwd()))
        natives = {t['id']: app.Native(t['demo_live'], 'native', now, app.identity(t))
                   for t in snapshot['tasks']}
        natives[app.PRIMARY] = self.measured()
        view = app.View(snapshot=snapshot, natives=natives, last_success=now)
        rows = app.overview_rows(view, now, 45)
        view.selection(rows)
        primary_line = None
        for movement in (1, 1, 1, 1, 1, -1, -1, -1, -1):
            index = view.selection(rows, movement)
            row = rows[index]
            previous = None
            for repeat in range(4):
                with self.subTest(worker=index, frame=repeat):
                    lines = [text for text, _ in app.render_lines(view, rows, 28, 16, False, now)]
                    self.assertEqual(len(lines), 16)
                    firstmate = [i for i, text in enumerate(lines) if '◆ Firstmate' in text]
                    self.assertEqual(len(firstmate), 1)
                    if primary_line is None:
                        primary_line = firstmate[0]
                    self.assertEqual(firstmate[0], primary_line)
                    self.assertNotIn('>', lines[primary_line])
                    titles = [i for i, text in enumerate(lines) if row.title in text and '>' in text]
                    self.assertEqual(len(titles), 1)
                    self.assertGreater(titles[0], primary_line)
                    self.assertEqual(lines[titles[0]][:5], f'{index:>3} >')
                    self.assertEqual(lines[titles[0] + 1], app.fit(
                        f'       {row.live} · task {row.outcome} · {row.activity}', 27))
                    for value, label in zip(('5', '1', '1', '2', '1', '1'), ('Worker',) + app.STATES):
                        self.assertIn(f'{value:>3}  {label}', '\n'.join(lines))
                    if previous is not None:
                        self.assertEqual(lines, previous)
                    previous = lines

    def test_fixed_first_row_navigation_counts_staleness_and_worker_removal(self):
        snapshot = sample_snapshot(str(Path.cwd()))
        primary = self.measured()
        view = app.View(snapshot=snapshot, natives={app.PRIMARY: primary}, last_success=time.time())
        rows = app.overview_rows(view, time.time(), 45)
        self.assertIs(rows[0], primary)
        self.assertEqual(app.counters(rows), app.counters(rows[1:]))
        self.assertEqual(view.selection(rows), 0)
        self.assertEqual(view.selected, primary.key)
        self.assertEqual(view.selection(rows, 1), 1)
        self.assertEqual(view.selection(rows, -1), 0)
        for width, height in ((28, 16), (77, 24), (120, 40)):
            view.selection(rows, 99)
            lines = [text for text, _ in app.render_lines(view, rows, width, height, False, time.time())]
            self.assertEqual(sum('◆ Firstmate' in s for s in lines), 1)
            self.assertLess(len(lines), height + 1)
        view.snapshot['tasks'] = []
        empty = app.overview_rows(view, time.time(), 45)
        self.assertEqual(empty, [primary])
        self.assertEqual(sum(app.counters(empty).values()), 0)
        view.selected = primary.key
        view.natives[app.PRIMARY] = app.PrimaryRow(reason='missing', observed=time.time())
        missing = app.overview_rows(view, time.time(), 45)
        self.assertEqual(view.selection(missing), -1)  # no silent replacement
        frame = '\n'.join(t for t, _ in app.render_lines(view, missing, 120, 40, False, time.time()))
        self.assertIn('unavailable', frame)
        view.natives[app.PRIMARY] = primary
        stale = app.overview_rows(view, time.time() + 60, 45)
        self.assertEqual(stale[0].live, 'unknown')
        self.assertIn('stale', stale[0].reason)


if __name__ == '__main__':
    unittest.main()
