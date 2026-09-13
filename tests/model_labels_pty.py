"""Opt-in real curses and PTY input with synthetic source replies; no Herdr calls."""
import argparse
import copy
import curses
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time

from test_primary import PrimaryRunner
from fixtures import sample_snapshot
import tshepherd as app

CASES = (
    ('x-ai/grok-4', 'high', 'Grok·H'),
    ('anthropic/claude-sonnet-4', 'medium', 'Claude·M'),
    ('provider/claude-astra-5', 'medium', 'Astra·M'),
    ('google/gemini-2.5-pro', 'high', 'Gemini·H'),
    ('provider/long-unknown-model', 'xhigh', 'Long-u·XH'),
    ('provider/megrokmodel', 'low', 'Megrok·L'),
    ('', '', '?·?'),
)


class FixtureRunner(PrimaryRunner):
    def __init__(self, case):
        super().__init__()
        model, effort, _ = CASES[case]
        self.owner['runtime'] = dict(model=model, effort=effort)

    def run(self, argv, timeout, env=None):
        if 'focus' in argv:
            raise AssertionError('This capture must never dispatch focus')
        if Path(argv[0]).name == 'fm-fleet-snapshot.sh':
            snapshot = sample_snapshot(str(Path.cwd()))
            snapshot['tasks'] = snapshot['tasks'][:1]
            snapshot['tasks'][0]['endpoint']['target'] = 'named:w1:p1'
            snapshot['tasks'][0]['backlog']['title'] = 'Fixture worker'
            return snapshot
        result = super().run(argv, timeout, env)
        if len(argv) > 2 and argv[2] == '--runtime':
            result['environment'] = dict(self.owner['environment'], FM_TASK_ID='demo-0')
        return copy.deepcopy(result)


def child(case, frames):
    source = app.Source(app.Config(str(Path.cwd()), str(Path.cwd())), FixtureRunner(case))

    def run(screen):
        class Window:
            def __getattr__(self, name):
                return getattr(screen, name)

            def refresh(self):
                screen.refresh()
                rows, cols = screen.getmaxyx()
                with frames.open('a') as stream:
                    stream.write(json.dumps(dict(rows=rows, cols=cols, lines=[
                        screen.instr(y, 0).decode('utf-8', 'replace') for y in range(rows)
                    ]), ensure_ascii=False) + '\n')

        app.tui(Window(), source)

    curses.wrapper(run)


def verify(case, cols, directory):
    frames = directory / f'{case}-{cols}.jsonl'
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, cols, 0, 0))
    proc = subprocess.Popen([sys.executable, __file__, '--child', str(case), str(frames)],
                            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                            env=dict(os.environ, TERM='xterm-256color'))
    os.close(slave)
    transcript = bytearray()
    expected = CASES[case][2]

    def wait(predicate):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if select.select([master], [], [], .05)[0]:
                try:
                    transcript.extend(os.read(master, 65536))
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
            items = [] if not frames.exists() else [json.loads(line) for line in
                frames.read_text().splitlines(keepends=True) if line.endswith('\n')]
            if predicate(items):
                return items[-1] if items else None
            if proc.poll() is not None:
                break
        raise AssertionError(f'{case=} {cols=} {expected=}: {transcript.decode("utf-8", "replace")}')

    def visible(items, selection):
        if not items:
            return False
        lines = items[-1]['lines']
        return (any(selection in line for line in lines)
                and sum(expected in line for line in lines) >= 2
                and any('1  Worker' in line for line in lines)
                and any('idle' in line for line in lines))

    try:
        frame = wait(lambda items: visible(items, '> ◆ Firstmate'))
        if cols >= 78:
            header = next(line for line in frame['lines'] if 'Model' in line)
            worker = next(line for line in frame['lines'] if 'Fixture worker' in line)
            assert worker.index(expected) == header.index('Model'), frame
            assert worker.index('idle') == header.index('Live'), frame
        os.write(master, b'j')
        wait(lambda items: visible(items, '>○ Fixture worker'))
        os.write(master, b'k')
        wait(lambda items: visible(items, '> ◆ Firstmate'))
        os.write(master, b'q')
        wait(lambda items: proc.poll() is not None)
        assert proc.returncode == 0, proc.returncode
        print(f'PASS {cols}x24 primary + worker {expected}; PTY j/k/q', flush=True)
    finally:
        os.close(master)
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=4)
        (directory / f'{case}-{cols}.ansi').write_bytes(transcript)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', nargs=2, metavar=('CASE', 'FRAMES'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        child(int(args.child[0]), Path(args.child[1]))
        return
    # All intentional evidence writes stay in this worktree and are cleaned up.
    with tempfile.TemporaryDirectory(prefix='.model-labels-', dir=Path.cwd()) as directory:
        for case in range(len(CASES)):
            for cols in (120, 40, 28):
                verify(case, cols, Path(directory))


if __name__ == '__main__':
    main()
