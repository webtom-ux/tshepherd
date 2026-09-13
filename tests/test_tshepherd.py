import copy
import contextlib
import io
import os
from pathlib import Path
import sys
import threading
import tempfile
import time
import unittest
from unittest.mock import patch

import tshepherd as app
from fixtures import sample_snapshot


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = sample_snapshot(str(Path.cwd()))
        self.natives = {t['id']: app.Native(t['demo_live'], 'native', time.time(), app.identity(t))
                        for t in self.snapshot['tasks']}

    def rows(self, **kw):
        return app.rows_for(self.snapshot, self.natives, kw.pop('now', time.time()), 45, **kw)

    def test_separate_completion_live_idle_and_waiting(self):
        rows = self.rows()
        self.assertEqual(app.counters(rows), dict(working=1, waiting=1, idle=2, completed=1, unknown=1, done=0))
        completed = next(r for r in rows if r.outcome == 'done')
        self.assertEqual(completed.live, 'idle')
        waiting = next(r for r in rows if r.live == 'waiting')
        self.assertEqual(waiting.outcome, 'parked')

    def test_task_duration_requires_confirmed_nonterminal_status(self):
        task = self.snapshot['tasks'][0]
        self.snapshot['tasks'] = [task]
        native = self.natives[task['id']]
        started = time.time() - 125
        native.session_started = native.task_started = started
        cases = [('done', None, 'fresh', False),
                 ('failed', None, 'fresh', False),
                 ('working', 'done', 'fresh', False),
                 ('unknown', None, 'fresh', False),
                 ('working', None, 'cached', False),
                 ('working', None, 'fresh', True),
                 ('parked', None, 'fresh', True),
                 ('blocked', None, 'fresh', True),
                 ('paused', None, 'fresh', True)]
        for elapsed in (125, 3725):
            now = started + elapsed
            observed = app.datetime.fromtimestamp(now).astimezone().isoformat()
            self.snapshot['generated'] = observed
            native.observed = now
            for state, backlog, freshness, running in cases:
                for live in ('working', 'idle', 'done'):
                    with self.subTest(elapsed=elapsed, state=state, backlog=backlog,
                                      freshness=freshness, live=live):
                        native.state = live
                        task['backlog']['state'] = backlog
                        task['current_state'].update(state=state, freshness=freshness,
                                                     observed_at=observed)
                        rows = self.rows(now=now)
                        row = rows[0]
                        duration = app.compact_duration(started, now)
                        expected = duration if running else '—'
                        self.assertEqual(app.compact_duration(row.task_started, now), expected)
                        self.assertEqual(app.compact_duration(row.session_started, now), duration)
                        view = app.View(snapshot=self.snapshot, natives=self.natives,
                                        last_success=now, selected=row.key)
                        for width in (77, 160):
                            frame = app.render_lines(view, rows, width, 40, False, now)
                            text = '\n'.join(line for line, _ in frame)
                            self.assertIn(f'Session {duration} · Task {expected}', text)
                            body = text.split('Session ')[0]
                            self.assertIn(expected, body)
                            if not running:
                                self.assertNotIn(duration, body)

    def test_stale_and_error_invalidate_previous_success(self):
        for rows in [self.rows(now=time.time() + 46), self.rows(unavailable=True)]:
            self.assertEqual(app.counters(rows), dict(working=0, waiting=0, idle=0, completed=0, unknown=5, done=0))
            self.assertTrue(all(r.outcome == 'unknown' for r in rows))
        self.assertEqual(app.counters(self.rows())['idle'], 2)

    def test_expired_native_does_not_invent_idle(self):
        self.natives['demo-1'].observed -= 50
        row = next(r for r in self.rows() if r.task['id'] == 'demo-1')
        self.assertEqual(row.live, 'unknown')
        self.assertEqual(row.outcome, 'done')  # independent, fresh semantic evidence

    def test_generation_replacement_invalidates_native_and_selection(self):
        rows = self.rows()
        view = app.View(selected=rows[0].key)
        self.snapshot['tasks'][0]['spawn_gen'] = 'replacement'
        changed = self.rows()
        self.assertEqual(changed[0].live, 'unknown')
        self.assertEqual(view.selection(changed), -1)
        view.selection(changed, 1)
        self.assertIn(view.selected, [r.key for r in changed])

    def test_empty_inventory_preserves_selection_until_explicit_navigation(self):
        rows = self.rows()
        view = app.View()
        self.assertEqual(view.selection([]), -1)
        self.assertEqual(view.selection(rows), 0)
        original = view.selected
        for movement in (0, -1, 1):
            self.assertEqual(view.selection([], movement), -1)
            self.assertEqual(view.selected, original)
        replacement = rows[1:2]
        self.assertEqual(view.selection(replacement), -1)
        self.assertEqual(view.selected, original)
        self.assertEqual(view.selection(rows), 0)
        self.assertEqual(view.selection(replacement, 1), 0)
        self.assertEqual(view.selected, replacement[0].key)

    def test_grouping_prefers_logical_repo_and_supported_activity(self):
        self.snapshot['tasks'][0]['project'] = '/some/hosting/firstmate'
        row = self.rows()[0]
        self.assertEqual(row.project, 'Atlas')
        self.assertEqual(row.title, 'Live-Ansicht bauen')
        self.snapshot['tasks'][0]['current_state']['detail'] = '\x1b]52;payload\a\ntext'
        self.assertNotIn('\x1b', self.rows()[0].activity)
        self.assertNotIn('\n', self.rows()[0].activity)

    def test_missing_unknown_future_and_absent_inventory(self):
        self.snapshot['tasks'][0]['current_state']['state'] = 'new-status'
        self.snapshot['tasks'][0]['current_state']['freshness'] = 'cached'
        self.assertEqual(self.rows()[0].outcome, 'unknown')
        self.assertEqual(app.rows_for({}, {}, time.time(), 45), [])
        self.natives['demo-0'].observed += 100
        self.assertEqual(self.rows()[0].live, 'unknown')

    def test_snapshot_validation(self):
        app.validate_snapshot(self.snapshot, Path.cwd())
        for field, value in [('schema', 'new'), ('fm_home', '/other'), ('tasks', None), ('generated', 'nonsense')]:
            malformed = dict(self.snapshot, **{field: value})
            with self.assertRaises(ValueError):
                app.validate_snapshot(malformed, Path.cwd())
        self.snapshot['tasks'].append(self.snapshot['tasks'][0])
        with self.assertRaises(ValueError):
            app.validate_snapshot(self.snapshot, Path.cwd())


class CliTests(unittest.TestCase):
    def test_removed_options_are_rejected(self):
        for args in (['--demo'], ['--interval', '1'], ['--stale-after', '60'], ['--timeout', '10']):
            with self.subTest(args=args), patch.object(sys, 'argv', ['tshepherd', *args]):
                with contextlib.redirect_stderr(io.StringIO()) as error:
                    with self.assertRaises(SystemExit) as exit_status:
                        app.main()
                self.assertEqual(exit_status.exception.code, 2)
                self.assertIn('unrecognized arguments', error.getvalue())

    def test_cli_uses_internal_timing_defaults(self):
        args = ['tshepherd', '--fm-home', str(Path.cwd()), '--firstmate-root', str(Path.cwd())]
        with patch.object(sys, 'argv', args), patch.object(app.curses, 'wrapper') as wrapper:
            app.main()
        config = wrapper.call_args.args[1].config
        self.assertEqual((config.interval, config.ttl, config.timeout), (5, 45, 20))


class FakeRunner:
    def __init__(self):
        self.stop = threading.Event()
        self.calls = []
        self.bad = ''
        self.native = 'idle'
        self.runtime = None
        self.pane = 'w1:p1'

    def run(self, argv, timeout, env=None):
        self.calls.append(argv)
        if Path(argv[1]).name == 'primary_identity.py':
            if len(argv) > 2 and argv[2] == '--runtime' and self.runtime is not None:
                return copy.deepcopy(self.runtime)
            return {'unavailable': 'worker-only fixture has no primary owner'}
        command = tuple(argv[1:-2])
        if command[0] == 'status':
            session = argv[-1]
            normalized = None if session == 'default' else session
            socket = '/fixture/herdr/' + ('' if normalized is None else 'sessions/' + session + '/') + 'herdr.sock'
            return {'client': {'session': normalized},
                    'server': {'running': True, 'session': normalized, 'compatible': True, 'socket': socket}}
        workspace = self.pane.split(':')[0]
        pane = {'pane_id': self.pane, 'tab_id': workspace + ':t1', 'workspace_id': workspace, 'terminal_id': 'term123'}
        if self.bad == 'pane':
            pane['pane_id'] = 'w9:p9'
        if command[:2] == ('pane', 'get'):
            if self.bad == 'missing':
                raise RuntimeError('pane_not_found')
            return {'result': {'type': 'pane_info', 'pane': pane}}
        if command[:2] == ('agent', 'get'):
            # Real Herdr 0.9 agent_info has no model or effort fields.
            return {'result': {'type': 'agent_info', 'agent': dict(
                pane, agent='wrong' if self.bad == 'provider' else 'pi', agent_status=self.native,
                focused=True)}}
        if command[:2] == ('pane', 'process-info'):
            return {'result': {'type': 'pane_process_info', 'process_info': {
                'pane_id': self.pane, 'foreground_processes': [{
                    'name': 'zsh' if self.bad == 'shell' else 'node', 'pid': 321, 'cwd': str(Path.cwd())}]}}}
        if command[:2] == ('agent', 'focus'):
            return {'result': {'type': 'agent_info', 'agent': dict(pane, agent='pi', focused=True)}}
        if command[:2] == ('tab', 'focus'):
            return {'result': {'type': 'tab_info', 'tab': dict(pane, focused=True)}}
        raise AssertionError(argv)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.source = app.Source(app.Config(str(Path.cwd()), '/code'), self.runner)
        self.snapshot = sample_snapshot(str(Path.cwd()))
        self.task = self.snapshot['tasks'][0]
        self.task['endpoint'].update(target='named:w1:p1', exists=True,
                                     observed_at=self.snapshot['generated'], freshness='fresh')
        self.snapshot['tasks'] = [self.task]
        self.source.snapshot = lambda: copy.deepcopy(self.snapshot)

    def test_native_mapping_and_unknown_failures(self):
        for raw, expected in [('working', 'working'), ('blocked', 'waiting'), ('idle', 'idle'), ('done', 'done'), ('new', 'unknown')]:
            self.runner.native = raw
            self.assertEqual(self.source.probe(self.task, time.monotonic() + 10).state, expected)
        for bad in ['pane', 'provider', 'missing', 'shell']:
            self.runner.bad = bad
            self.assertEqual(self.source.probe(self.task, time.monotonic() + 10).state, 'unknown')

    def test_probe_collects_only_exact_process_runtime_metadata(self):
        started = time.time_ns() - 125 * 10**9
        self.runner.runtime = {
            'process': {'pid': 321, 'start': started},
            'environment': {'FM_TASK_ID': self.task['id'], 'HERDR_ENV': '1',
                            'HERDR_SESSION': 'named', 'HERDR_SOCKET_PATH': '/fixture/herdr/sessions/named/herdr.sock',
                            'HERDR_PANE_ID': 'w1:p1', 'HERDR_WORKSPACE_ID': 'w1', 'HERDR_TAB_ID': 'w1:t1'},
            'runtime': {'model': 'openai/gpt-sol-5.6', 'effort': 'medium'}}
        native = self.source.probe(self.task, time.monotonic() + 10)
        self.assertEqual((native.model, native.effort), ('openai/gpt-sol-5.6', 'medium'))
        self.assertAlmostEqual(native.session_started, started / 10**9, places=3)
        self.assertEqual(native.task_started, native.session_started)
        row = app.rows_for(self.snapshot, {self.task['id']: native}, time.time(), 45)[0]
        self.assertEqual(row.model, 'Sol·M')
        self.assertEqual(app.compact_duration(row.task_started, time.time()), '2m')
        self.runner.runtime['environment']['FM_TASK_ID'] = 'replacement'
        self.assertEqual(self.source.probe(self.task, time.monotonic() + 10).model, '')
        self.task.update(model='Astra', effort='high')  # desired task config is not runtime evidence
        self.runner.runtime = None
        native = self.source.probe(self.task, time.monotonic() + 10)
        self.assertEqual(app.rows_for(self.snapshot, {self.task['id']: native}, time.time(), 45)[0].model,
                         '?·?')

    def test_focus_verified_native_done_without_semantic_completion(self):
        self.runner.native = 'done'
        measured = self.source.probe(self.task, time.monotonic() + 10)
        row = app.rows_for(self.snapshot, {self.task['id']: measured}, time.time(), 45)[0]
        self.assertEqual(row.live, 'done')
        self.assertEqual(row.outcome, 'working')
        self.assertEqual(app.counters([row])['done'], 1)
        self.assertEqual(app.counters([row])['completed'], 0)
        self.assertIn('ready for input, unseen', row.reason)
        self.runner.calls.clear()
        self.assertIn('confirmed', self.source.focus(app.identity(self.task)))
        self.assertIn(['herdr', 'tab', 'focus', 'w1:t1', '--session', 'named'], self.runner.calls)
        self.assertFalse(any('--runtime' in call for call in self.runner.calls))
        for bad in ['pane', 'provider', 'missing', 'shell']:
            with self.subTest(bad=bad):
                self.runner.bad = bad
                self.runner.calls.clear()
                with self.assertRaises(ValueError):
                    self.source.focus(app.identity(self.task))
                self.assertFalse(any('focus' in call for call in self.runner.calls))

    def test_native_done_preserves_expired_task_explanation(self):
        self.runner.native = 'done'
        native = self.source.probe(self.task, time.monotonic() + 10)
        self.task['current_state']['observed_at'] = '2000-01-01T00:00:00Z'
        now = time.time()
        row = app.rows_for(self.snapshot, {self.task['id']: native}, now, 45)[0]
        self.assertEqual(row.live, 'done')
        self.assertEqual(row.outcome, 'unknown')
        self.assertEqual(row.activity, self.task['current_state']['detail'])
        stale_reason = app.tr('veraltet / Quelle nicht erreichbar')
        self.assertIn(stale_reason, row.reason)
        self.assertIn(native.detail, row.reason)
        view = app.View(snapshot=self.snapshot, natives={self.task['id']: native},
                        last_success=now, selected=row.key)
        lines = [text for text, _ in app.render_lines(view, [row], 300, 24, False, now)]
        worker = next(text for text in lines if row.title in text)
        footer = lines[-3]
        for text in (worker, footer):
            self.assertIn(stale_reason, text)
            self.assertIn(native.detail, text)

    def test_terminal_render_distinguishes_done_idle_and_true_unknown(self):
        expected = {
            'en': ('done', 'ready for input, unseen', 'idle', 'unknown'),
            'de': ('bereit', 'bereit für Eingabe, ungesehen', 'ruhend', 'unklar'),
        }
        self.addCleanup(app.set_language, 'en')
        for language, labels in expected.items():
            with self.subTest(language=language):
                app.set_language(language)
                rendered = {}
                for raw in ('done', 'idle', 'unclassified'):
                    self.runner.native = raw
                    native = self.source.probe(self.task, time.monotonic() + 10)
                    row = app.rows_for(self.snapshot, {self.task['id']: native}, time.time(), 45)[0]
                    view = app.View(snapshot=self.snapshot, natives={self.task['id']: native},
                                    last_success=time.time(), selected=row.key)
                    rendered[raw] = '\n'.join(
                        text for text, _ in app.render_lines(view, [row], 140, 24, False, time.time()))
                self.assertIn(labels[0], rendered['done'])
                self.assertIn(labels[1], rendered['done'])
                self.assertIn(labels[2], rendered['idle'])
                self.assertNotIn(labels[1], rendered['idle'])
                self.assertIn(labels[3], rendered['unclassified'])
                self.assertIn(app.tr('Native Aktivität unbekannt · Herdr-Registrierung prüfen'),
                              rendered['unclassified'])

    def test_real_default_null_and_uppercase_handles(self):
        self.runner.pane = 'wA:p2'
        self.task['endpoint']['target'] = 'default:wA:p2'
        measured = self.source.probe(self.task, time.monotonic() + 10)
        self.assertEqual(measured.state, 'idle')
        self.assertEqual(measured.physical[0], 'wA')
        self.assertEqual([call for call in self.runner.calls if call[0] == 'herdr'][-1][-2:],
                         ['--session', 'default'])
        self.assertIn('confirmed', self.source.focus(app.identity(self.task)))
        self.assertIn(['herdr', 'tab', 'focus', 'wA:t1', '--session', 'default'], self.runner.calls)
        measured.observed -= 50
        row = app.rows_for(self.snapshot, {self.task['id']: measured}, time.time(), 45)[0]
        self.assertEqual(row.live, 'unknown')
        for handle in ['wZ:pA', 'w10:p0', 'wABCDEFGH:pJKMN']:
            self.task['endpoint']['target'] = 'named:' + handle
            self.assertEqual(app.endpoint(self.task), ('named', handle))

    def test_default_null_is_not_missing_or_arbitrary_session_identity(self):
        status = self.runner.run(['herdr', 'status', '--json', '--session', 'default'], 1)
        self.assertTrue(app.session_confirmed(status, 'default'))
        self.assertFalse(app.session_confirmed(status, 'named'))
        for path in [('client', 'session'), ('server', 'session'), ('server', 'socket')]:
            missing = copy.deepcopy(status)
            del missing[path[0]][path[1]]
            self.assertFalse(app.session_confirmed(missing, 'default'))
        for section, key, value in [('server', 'session', 'default'), ('client', 'session', 'other'),
                                    ('server', 'socket', '/fixture/herdr/sessions/other/herdr.sock'),
                                    ('server', 'socket', 'herdr.sock'), ('server', 'running', False),
                                    ('server', 'compatible', None)]:
            ambiguous = copy.deepcopy(status)
            ambiguous[section][key] = value
            self.assertFalse(app.session_confirmed(ambiguous, 'default'))

    def test_safe_focus_exact_identity_only(self):
        self.assertIn('confirmed', self.source.focus(app.identity(self.task)))
        self.assertIn(['herdr', 'tab', 'focus', 'w1:t1', '--session', 'named'], self.runner.calls)
        self.assertTrue(all(c[-2:] == ['--session', 'named']
                            for c in self.runner.calls if c[0] == 'herdr'))
        self.runner.calls.clear()
        old = app.identity(self.task)
        self.task['spawn_gen'] = 'new'
        with self.assertRaises(ValueError):
            self.source.focus(old)
        self.assertEqual(self.runner.calls, [])

    def test_focus_rejects_replacement_of_displayed_physical_target(self):
        with self.assertRaisesRegex(ValueError, 'physical endpoint replaced'):
            self.source.focus(app.identity(self.task), ('w1', 'w1:t1', 'old-terminal'))
        self.assertFalse(any('focus' in c for c in self.runner.calls))

    def test_physical_replacement_after_owner_recheck_prevents_next_mutation(self):
        for replace_after in (2, 4):  # before agent focus, then before tab focus
            with self.subTest(replace_after=replace_after):
                self.setUp()
                snapshots = 0
                original_snapshot = self.source.snapshot
                original_run = self.runner.run

                def snapshot():
                    nonlocal snapshots
                    result = original_snapshot()
                    snapshots += 1
                    return result

                def run(argv, timeout, env=None):
                    result = original_run(argv, timeout, env)
                    if snapshots >= replace_after and argv[1:3] == ['pane', 'get']:
                        result['result']['pane']['terminal_id'] = 'replaced-after-owner-read'
                    return result

                self.source.snapshot = snapshot
                self.runner.run = run
                with self.assertRaisesRegex(ValueError, 'physical endpoint changed'):
                    self.source.focus(app.identity(self.task))
                forbidden = ['agent', 'focus'] if replace_after == 2 else ['tab', 'focus']
                self.assertFalse(any(c[1:3] == forbidden for c in self.runner.calls))

    def test_focus_reads_independent_evidence_concurrently(self):
        barrier = threading.Barrier(4)
        released = threading.Event()
        original = self.runner.run

        def held(argv, timeout, env=None):
            if not released.is_set():
                # None of the four endpoint reads can finish until all have
                # started. Serial preflight fails instead of hiding its delay.
                barrier.wait(timeout=1)
                released.set()
            return original(argv, timeout, env)

        self.runner.run = held
        self.assertIn('confirmed', self.source.focus(app.identity(self.task)))
        self.assertTrue(released.is_set())

    def test_focus_rechecks_ownership_after_probe(self):
        original_probe = self.source.probe
        def raced_probe(task, deadline, **kwargs):
            value = original_probe(task, deadline, **kwargs)
            self.task['endpoint']['exists'] = False
            return value
        self.source.probe = raced_probe
        with self.assertRaisesRegex(ValueError, 'during check'):
            self.source.focus(app.identity(self.task))
        self.assertFalse(any('focus' in c for c in self.runner.calls))

    def test_second_mutation_revalidates_all_guards(self):
        for change in ('removed', 'generation', 'stale', 'endpoint', 'provider', 'session', 'physical'):
            with self.subTest(change=change):
                self.setUp()
                original = self.runner.run
                def raced(argv, timeout, env=None):
                    result = original(argv, timeout, env)
                    if argv[1:3] == ['agent', 'focus']:
                        if change == 'removed':
                            self.snapshot['tasks'] = []
                        elif change == 'generation':
                            self.task['spawn_gen'] = 'replacement'
                        elif change == 'stale':
                            self.snapshot['generated'] = '2000-01-01T00:00:00Z'
                        elif change == 'endpoint':
                            self.task['endpoint']['exists'] = False
                        elif change == 'provider':
                            self.runner.bad = 'provider'
                        elif change == 'session':
                            self.task['endpoint']['target'] = 'foreign:w1:p1'
                    if change == 'physical' and any(c[1:3] == ['agent', 'focus'] for c in self.runner.calls):
                        for field in ('pane', 'agent'):
                            if field in result.get('result', {}) and argv[2] != 'focus':
                                result['result'][field]['terminal_id'] = 'replacement'
                    return result
                self.runner.run = raced
                with self.assertRaisesRegex(ValueError, 'tab switch not confirmed'):
                    self.source.focus(app.identity(self.task))
                self.assertFalse(any(c[1:3] == ['tab', 'focus'] for c in self.runner.calls))

    def test_tab_failure_and_final_confirmation_are_truthful(self):
        for failure in ('command', 'confirmation'):
            with self.subTest(failure=failure):
                self.setUp()
                original = self.runner.run
                projected = False
                def fail(argv, timeout, env=None):
                    nonlocal projected
                    if argv[1:3] == ['tab', 'focus']:
                        projected = True
                        if failure == 'command':
                            raise RuntimeError('tab rejected')
                    result = original(argv, timeout, env)
                    if projected and argv[1:3] == ['agent', 'get']:
                        result['result']['agent']['focused'] = False
                    return result
                self.runner.run = fail
                with self.assertRaisesRegex(ValueError, 'agent focus confirmed; tab switch not confirmed'):
                    self.source.focus(app.identity(self.task))

    def test_budget_expired_or_cancelled_makes_no_herdr_calls(self):
        value = self.source.probe(self.task, time.monotonic() - 1)
        self.assertEqual(value.state, 'unknown')
        self.assertEqual(self.runner.calls, [])
        self.runner.stop.set()
        value = self.source.probe(self.task, time.monotonic() + 10)
        self.assertEqual(value.state, 'unknown')
        self.assertEqual(self.runner.calls, [])

    def test_reject_injection_remote_and_stale_focus(self):
        for target in ['default:w1:p1;touch /tmp/pwn', '--session:x', 'default:w1:p1 --other', 'x:$(ls)',
                       'default:wI:pL', 'default:wa:p2']:
            self.task['endpoint']['target'] = target
            with self.assertRaises(ValueError):
                app.endpoint(self.task)
        self.task['endpoint']['target'] = 'named:w1:p1'
        self.task['remote'] = {'host': 'remote'}
        with self.assertRaises(ValueError):
            app.endpoint(self.task)
        self.task['remote'] = None
        self.snapshot['generated'] = '2000-01-01T00:00:00Z'
        with self.assertRaises(ValueError):
            self.source.focus(app.identity(self.task))
        self.assertFalse(any('focus' in c for c in self.runner.calls))

    def test_lab_requires_exact_session_and_helper(self):
        self.source.config.lab_helper = '/helper'
        self.source.config.lab_session = 'fm-lab-test'
        self.assertEqual(self.source.argv('fm-lab-test', 'pane', 'get', 'w1:p1'),
                         ['/helper', 'run', 'fm-lab-test', 'pane', 'get', 'w1:p1'])
        with self.assertRaises(ValueError):
            self.source.argv('default', 'status', '--json')


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        home = Path(self.directory.name).resolve()
        (home / 'state').mkdir()
        self.snapshot = sample_snapshot(str(home))
        self.task = self.snapshot['tasks'][0]
        self.snapshot['tasks'] = [self.task]
        self.task['endpoint'].update(target='named:w1:p1', exists=True,
                                     freshness='fresh', observed_at=self.snapshot['generated'])
        self.meta = home / 'state' / (self.task['id'] + '.meta')
        self.task.setdefault('paths', {})['meta'] = dict(path=str(self.meta), present=True)
        self.fields = dict(spawn_gen=self.task['spawn_gen'], backend='herdr',
                           window='named:w1:p1', harness='pi')
        self.save()
        self.runner = FakeRunner()
        self.source = app.Source(app.Config(str(home), '/source'), self.runner)
        self.source.snapshot = lambda: copy.deepcopy(self.snapshot)
        self.source.collect()
        self.runner.calls.clear()
        def forbidden():
            raise AssertionError('fleet-wide refresh on Enter')
        self.source.snapshot = forbidden

    def save(self):
        self.meta.write_text(''.join(k + '=' + v + '\n' for k, v in self.fields.items()))

    def test_hot_path_uses_only_current_target_proof(self):
        self.assertIn('confirmed', self.source.focus(app.identity(self.task)))
        self.assertTrue(any(c[1:3] == ['tab', 'focus'] for c in self.runner.calls))
        self.assertTrue(all(c[-1] == 'named' for c in self.runner.calls if c[0] == 'herdr'))

    def test_last_metadata_value_matches_firstmate_not_first_value(self):
        with self.meta.open('a') as f:
            f.write('spawn_gen=replacement\n')
        with self.assertRaises(ValueError):
            self.source.focus(app.identity(self.task))
        self.assertEqual(self.runner.calls, [])

    def test_last_value_and_no_final_newline_are_supported(self):
        self.meta.write_text('spawn_gen=old\nremote_host=foreign\n' +
                             self.meta.read_text() + 'remote_host=')
        self.assertIn('confirmed', self.source.focus(app.identity(self.task)))

    def test_metadata_replaced_during_read_is_rejected(self):
        original = os.fstat
        replaced = False
        def race(fd):
            nonlocal replaced
            result = original(fd)
            if not replaced:
                replaced = True
                new = self.meta.with_suffix('.new')
                new.write_text(self.meta.read_text())
                new.replace(self.meta)
            return result
        with patch.object(app.os, 'fstat', race), self.assertRaises(ValueError):
            self.source.focus(app.identity(self.task))
        self.assertEqual(self.runner.calls, [])

    def test_absent_replaced_foreign_unknown_and_unsafe_metadata_rejected(self):
        for change in ('absent', 'generation', 'foreign', 'remote', 'provider',
                       'backend', 'empty', 'huge', 'binary', 'utf8', 'directory', 'fifo', 'symlink', 'path', 'stale'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'absent': self.meta.unlink()
                elif change == 'generation': self.fields['spawn_gen'] = 'new'; self.save()
                elif change == 'foreign': self.fields['window'] = 'foreign:w1:p1'; self.save()
                elif change == 'remote': self.fields['remote_host'] = 'remote'; self.save()
                elif change == 'provider': self.fields['harness'] = 'other'; self.save()
                elif change == 'backend': self.fields['backend'] = 'tmux'; self.save()
                elif change == 'empty': self.meta.write_text('')
                elif change == 'huge': self.meta.write_bytes(b'x' * 65537)
                elif change == 'binary': self.meta.write_bytes(self.meta.read_bytes() + b'rem\x00ote_host=foreign\n')
                elif change == 'utf8': self.meta.write_bytes(self.meta.read_bytes() + b'\xff')
                elif change == 'directory': self.meta.unlink(); self.meta.mkdir()
                elif change == 'fifo': self.meta.unlink(); os.mkfifo(self.meta)
                elif change == 'symlink':
                    other = self.meta.with_suffix('.other'); self.meta.rename(other); self.meta.symlink_to(other)
                elif change == 'path': self.source.current[0]['tasks'][0]['paths']['meta']['path'] = '/foreign/meta'
                else: self.source.current[0]['generated'] = '2000-01-01T00:00:00Z'
                with self.assertRaises((ValueError, OSError)):
                    self.source.focus(app.identity(self.task))
                self.assertFalse(any('focus' in c for c in self.runner.calls))

    def test_owner_changed_during_probe_and_between_mutations(self):
        for after in ('probe', 'agent-focus'):
            with self.subTest(after=after):
                self.setUp()
                original = self.runner.run
                def raced(argv, timeout, env=None):
                    result = original(argv, timeout, env)
                    if ((after == 'probe' and argv[1:3] == ['pane', 'process-info'])
                            or (after == 'agent-focus' and argv[1:3] == ['agent', 'focus'])):
                        self.fields['spawn_gen'] = 'replacement'
                        self.save()
                    return result
                self.runner.run = raced
                with self.assertRaises(ValueError):
                    self.source.focus(app.identity(self.task))
                self.assertFalse(any(c[1:3] == ['tab', 'focus'] for c in self.runner.calls))


class PollingTests(unittest.TestCase):
    def test_refresh_never_blocks_or_drops_explicit_focus(self):
        release = threading.Event()
        entered = threading.Event()
        class Slow:
            runner = FakeRunner()
            active = 0
            peak = 0
            count = 0
            def focus(self, key, physical=()):
                self.focused = key
                return 'focused'
            def collect(self):
                self.active += 1
                self.peak = max(self.peak, self.active)
                entered.set()
                release.wait(1)
                self.active -= 1
                self.count += 1
                if self.count == 1:
                    raise ValueError('offline')
                return ({'tasks': []}, {})
        source = Slow()
        poller = app.Poller(source, 0.02)
        poller.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(poller.request_focus(('exact-selection',)))
            self.assertEqual(poller.results.get(timeout=1), ('focus', 'focused'))
            self.assertEqual(source.focused, ('exact-selection',))
            self.assertFalse(release.is_set())  # focus finished with fetch still blocked
            release.set()
            self.assertEqual(poller.results.get(timeout=1), ('error', 'offline'))
            self.assertEqual(poller.results.get(timeout=1)[0], 'snapshot')
            self.assertEqual(source.peak, 1)
        finally:
            poller.close()
        self.assertFalse(poller.thread.is_alive())
        self.assertFalse(poller.focus_thread.is_alive())

    def test_focus_is_single_flight_and_cannot_retarget(self):
        entered, release = threading.Event(), threading.Event()
        class Source:
            runner = FakeRunner()
            keys = []
            def collect(self):
                return ({'tasks': []}, {})
            def focus(self, key, physical=()):
                self.keys.append((key, physical))
                entered.set()
                release.wait(1)
                return 'focused'
        source = Source()
        poller = app.Poller(source, 5)
        poller.start()
        try:
            self.assertTrue(poller.request_focus(('first',), ('workspace', 'tab', 'terminal')))
            self.assertTrue(entered.wait(1))
            self.assertFalse(poller.request_focus(('other',)))
            release.set()
        finally:
            release.set()
            poller.close()
        self.assertEqual(source.keys, [(('first',), ('workspace', 'tab', 'terminal'))])
        self.assertFalse(poller.request_focus(('after-close',)))

    def test_runner_timeout_cancel_and_bad_json(self):
        stop = threading.Event()
        runner = app.Runner(stop)
        with self.assertRaises(TimeoutError):
            runner.run([sys.executable, '-c', 'import time; time.sleep(30)'], .1)
        with self.assertRaises(ValueError):
            runner.run([sys.executable, '-c', 'print("not json")'], 1)
        self.assertEqual(runner.run([sys.executable, '-c', 'print("{}")'], 1), {})
        stop.set()
        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            runner.run([sys.executable, '-c', 'import time; time.sleep(30)'], 30)
        self.assertLess(time.monotonic() - started, 1)

    def test_source_clears_inherited_fm_overrides(self):
        class Capture(FakeRunner):
            def run(self, argv, timeout, env=None):
                self.env = env
                return sample_snapshot(str(Path.cwd()))
        runner = Capture()
        source = app.Source(app.Config(str(Path.cwd()), '/source'), runner)
        os.environ['FM_STATE_OVERRIDE'] = '/wrong'
        try:
            source.snapshot()
        finally:
            del os.environ['FM_STATE_OVERRIDE']
        self.assertNotIn('FM_STATE_OVERRIDE', runner.env)
        self.assertEqual(runner.env['FM_HOME'], str(Path.cwd()))
        self.assertEqual(runner.env['FM_ROOT_OVERRIDE'], '/source')


class RenderingTests(unittest.TestCase):
    def test_compact_duration_units_and_fail_closed_values(self):
        now = 1_000_000
        self.assertEqual(app.compact_duration(now - 42, now), '42s')
        self.assertEqual(app.compact_duration(now - 7 * 60, now), '7m')
        self.assertEqual(app.compact_duration(now - 3 * 3600, now), '3h')
        self.assertEqual(app.compact_duration(now - 2 * 86400, now), '2d')
        for value in (0, None, True, now + 3):
            self.assertEqual(app.compact_duration(value, now), '—')

    def test_compact_model_fixed_generic_unknown_and_effort_levels(self):
        # Existing fixed names retain priority when several names are present.
        self.assertEqual(app.compact_model('claude-astra-5', 'medium'), 'Astra·M')
        self.assertEqual(app.compact_model('Terra', 'low'), 'Terra·L')
        self.assertEqual(app.compact_model('provider/luna', 'xhigh'), 'Luna·XH')
        self.assertEqual(app.compact_model('Astra', 'max'), 'Astra·Mx')
        self.assertEqual(app.compact_model('Sol', 'ultra'), 'Sol·U')
        self.assertEqual(app.compact_model('sol', ''), 'Sol·?')
        self.assertEqual(app.compact_model('x-ai/GROK-4', 'high'), 'Grok·H')
        self.assertEqual(app.compact_model('anthropic/CLAUDE-3-7', 'medium'), 'Claude·M')

        # Unlisted models use the model-id component, never a role label.
        self.assertEqual(app.compact_model('google/gemini-2.5-pro', 'high'), 'Gemini·H')
        self.assertEqual(app.compact_model('openai/gpt-4o-mini', ''), 'Gpt-4o·?')
        self.assertEqual(app.compact_model('long-unknown-model', 'high'), 'Long-u·H')
        self.assertEqual(app.compact_model('megrokmodel', 'low'), 'Megrok·L')
        self.assertEqual(app.compact_model('', ''), '?·?')

    def test_count_blocks_and_aligned_single_line_rows(self):
        snapshot = sample_snapshot(str(Path.cwd()))
        snapshot['tasks'][0]['backlog']['title'] = '中 Kürzer'
        natives = {t['id']: app.Native(t['demo_live'], 'native', time.time(), app.identity(t)) for t in snapshot['tasks']}
        now = time.time()
        natives['demo-0'].session_started = now - 7200
        natives['demo-0'].task_started = now - 125
        rows = app.rows_for(snapshot, natives, now, 45)
        target = next(row for row in rows if row.task['id'] == 'demo-0')
        view = app.View(snapshot=snapshot, natives=natives, last_success=now, selected=target.key)
        view.selection(rows)
        frame = app.render_lines(view, rows, 120, 40, False, now)
        badges = [(y, x, text, role) for y, (_, spans) in enumerate(frame)
                  for x, text, role in spans if 11 <= role <= 16]
        self.assertEqual([role for _, _, _, role in badges], list(range(11, 17)))
        self.assertEqual(len({x for _, x, _, _ in badges}), 1)
        self.assertEqual([text.strip() for _, _, text, _ in badges], ['5', '1', '1', '2', '1', '1'])
        worker_lines = [line for line in frame if any(row.title in line[0] for row in rows)]
        self.assertEqual(len(worker_lines), len(rows))  # one compact row per worker
        provider_columns = [next(x for x, text, role in spans if text.strip() == 'pi') for _, spans in worker_lines]
        model_columns = [next(x for x, text, role in spans if text.strip() == '?·?') for _, spans in worker_lines]
        self.assertEqual(len(set(provider_columns)), 1)
        self.assertEqual(len(set(model_columns)), 1)
        text = '\n'.join(line for line, _ in frame)
        self.assertIn('Time/Task', text)
        target_line = next(line for line, _ in worker_lines if target.title in line)
        self.assertIn('2m', target_line)
        self.assertIn('Session 2h · Task 2m', text)
        self.assertNotIn('Session', target_line)
        self.assertEqual(app.fit('a   b', 5), 'a   b')  # layout spaces must survive clipping
        self.assertEqual(app.cells(app.column('中', 6)), 6)

    def test_model_column_in_both_languages_and_narrow_rows(self):
        snapshot = sample_snapshot(str(Path.cwd()))
        now = time.time()
        natives = {t['id']: app.Native(t['demo_live'], 'native', now, app.identity(t))
                   for t in snapshot['tasks']}
        natives['demo-0'].model, natives['demo-0'].effort = 'Sol', 'medium'
        rows = app.rows_for(snapshot, natives, now, 45)
        view = app.View(snapshot=snapshot, natives=natives, last_success=now)
        try:
            for language, heading in [('en', 'Model'), ('de', 'Modell')]:
                with self.subTest(language=language):
                    app.set_language(language)
                    wide = '\n'.join(text for text, _ in app.render_lines(view, rows, 120, 40, False, now))
                    narrow = '\n'.join(text for text, _ in app.render_lines(view, rows, 28, 16, False, now))
                    self.assertIn(heading, wide)
                    self.assertIn('Sol·M', wide)
                    self.assertIn('Sol·M', narrow)
        finally:
            app.set_language('en')

    def test_sizes_unicode_selection_scrolling_and_error(self):
        snapshot = sample_snapshot(str(Path.cwd()))
        rows = app.rows_for(snapshot, {}, time.time(), 45)
        view = app.View(snapshot=snapshot, last_success=time.time())
        view.selection(rows)
        view.selection(rows, 4)
        view.error = 'offline'
        for width, height in [(120, 40), (80, 24), (28, 16), (1, 1), (10, 5), (0, 0)]:
            lines = app.render_lines(view, rows, width, height, False, time.time())
            self.assertLessEqual(len(lines), height)
            self.assertTrue(all(len(text) <= max(0, width - 1) for text, _ in lines))
        lines = app.render_lines(view, rows, 120, 24, False, time.time())
        self.assertTrue(any('offline' in text for text, _ in lines))
        self.assertTrue(any('>' in text for text, _ in lines))
        self.assertEqual(app.fit('中ab', 3), '中a')


if __name__ == '__main__':
    unittest.main()
