"""Opt-in real curses/PTY status evidence with synthetic source responses.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/status_ui.py --output DIRECTORY
No real Herdr commands, focus dispatch, lifecycle operations, or services.
Production Source validation, collection, polling, mapping and TUI remain intact.
"""
import argparse
import curses
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tshepherd as app
from fixtures import sample_snapshot
from test_tshepherd import FakeRunner


SCENARIOS = ('done', 'idle', 'invalid', 'stale-task')


class FixtureRunner(FakeRunner):
    def __init__(self, scenario):
        super().__init__()
        self.native = 'idle' if scenario == 'idle' else 'done'
        self.bad = 'provider' if scenario == 'invalid' else ''
        self.snapshot = sample_snapshot(str(Path.cwd()))
        task = self.snapshot['tasks'][0]
        task['backlog']['title'] = 'Status-fixture'
        task['current_state']['detail'] = 'Synthetic activity unchanged'
        task['endpoint'].update(target='named:w1:p1', exists=True,
                                observed_at=self.snapshot['generated'], freshness='fresh')
        if scenario == 'stale-task':
            task['current_state']['observed_at'] = '2000-01-01T00:00:00Z'
        self.snapshot['tasks'] = [task]

    def run(self, argv, timeout, env=None):
        if Path(argv[0]).name == 'fm-fleet-snapshot.sh':
            self.calls.append(argv)
            return self.snapshot
        if 'focus' in argv:
            raise AssertionError('This read-only evidence must never dispatch focus')
        return super().run(argv, timeout, env)


def child(scenario, output):
    runner = FixtureRunner(scenario)
    source = app.Source(app.Config(str(Path.cwd()), str(Path.cwd())), runner)

    def run(screen):
        class ObservedWindow:
            ready = False
            captured = False

            def __getattr__(self, name):
                return getattr(screen, name)

            def refresh(self):
                screen.refresh()
                height, width = screen.getmaxyx()
                lines = [screen.instr(y, 0).decode('utf-8', 'replace') for y in range(height)]
                if any('Status-fixture' in line for line in lines):
                    if not self.ready:
                        (output / 'ready').touch()
                        self.ready = True
                    if not self.captured and 'demo-0' in lines[-3]:
                        frame = dict(scenario=scenario, ui='real curses in isolated PTY',
                                     source='synthetic fixture; no live Herdr transition evidence',
                                     lines=lines, rows=height, cols=width,
                                     attributes=[[screen.inch(y, x) & curses.A_ATTRIBUTES
                                                  for x in range(width)] for y in range(height)])
                        (output / 'frame.json').write_text(json.dumps(frame, ensure_ascii=False))
                        self.captured = True
        app.tui(ObservedWindow(), source)

    curses.wrapper(run)
    (output / 'calls.json').write_text(json.dumps(runner.calls))


def drive(scenario, output):
    output.mkdir(parents=True, exist_ok=False)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 240, 0, 0))
    proc = subprocess.Popen([sys.executable, __file__, '--child', scenario, '--output', str(output)],
                            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                            env=dict(os.environ, TERM='xterm-256color', PYTHONDONTWRITEBYTECODE='1'))
    transcript = bytearray()
    navigated = quit_sent = False
    try:
        deadline = time.monotonic() + 10
        while proc.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], .05)[0]:
                transcript.extend(os.read(master, 65536))
            if not navigated and (output / 'ready').exists():
                os.write(master, b'j')  # Real terminal input selects the worker.
                navigated = True
            if not quit_sent and (output / 'frame.json').exists():
                os.write(master, b'q')
                quit_sent = True
        assert proc.poll() == 0, transcript.decode('utf-8', 'replace')
        while select.select([master], [], [], .05)[0]:
            transcript.extend(os.read(master, 65536))
        assert navigated and quit_sent
        assert b'TShepherd' in transcript and b'Traceback' not in transcript
    finally:
        (output / 'terminal.ansi').write_bytes(transcript)
        os.close(master)
        os.close(slave)
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=2)

    frame = json.loads((output / 'frame.json').read_text())
    lines = frame['lines']
    worker = next(line for line in lines if 'Status-fixture' in line)
    footer = lines[-3]
    expected_live = {'done': 'done', 'idle': 'idle', 'invalid': 'unknown', 'stale-task': 'done'}[scenario]
    expected_task = 'unknown' if scenario == 'stale-task' else 'working'
    assert re.search(r'1\s+>.*Status-fixture\s+pi\s+\?·\?\s+'
                     + expected_live + r'\s+' + expected_task + r'\s+', worker), worker
    assert 'Synthetic activity unchanged' in worker, worker
    for label in ('working', 'completed'):
        assert any(re.search(r'\b0\s+' + label + r'\b', line) for line in lines), lines
    for text in (worker, footer):
        assert ('ready for input, unseen' in text) == (scenario in ('done', 'stale-task')), text
        if scenario == 'stale-task':
            assert 'stale / source unavailable' in text, text
    calls = json.loads((output / 'calls.json').read_text())
    assert not any('focus' in call for call in calls), calls
    assert any('get' in call and 'agent' in call for call in calls), calls
    (output / 'screen.txt').write_text('\n'.join(line.rstrip() for line in lines) + '\n')
    print(f'PASS {scenario}: real PTY/curses UI, synthetic source; no live Herdr evidence')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', choices=SCENARIOS)
    args = parser.parse_args()
    if args.child:
        child(args.child, args.output)
    else:
        for scenario in SCENARIOS:
            drive(scenario, args.output / scenario)
