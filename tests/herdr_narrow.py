"""Opt-in real curses/keyboard evidence using the named lab's live Source."""
import curses
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tshepherd as app


def child(config, frames):
    source = app.Source(app.Config(**config), app.Runner(threading.Event()))

    def run(screen):
        class ObservedWindow:
            def __getattr__(self, name):
                return getattr(screen, name)

            def refresh(self):
                screen.refresh()
                rows, cols = screen.getmaxyx()
                with frames.open('a') as stream:
                    stream.write(json.dumps({
                        'rows': rows, 'cols': cols,
                        'lines': [screen.instr(y, 0).decode('utf-8', 'replace')
                                  for y in range(rows)],
                    }, ensure_ascii=False) + '\n')

        app.tui(ObservedWindow(), source)

    curses.wrapper(run)


def verify(config, base):
    frames = base / 'narrow-frames.jsonl'
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 16, 28, 0, 0))
    proc = subprocess.Popen(
        [sys.executable, __file__, json.dumps(config.__dict__), str(frames)],
        stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
        env={**os.environ, 'TERM': 'xterm-256color'})
    os.close(slave)
    transcript = bytearray()

    def read_frames():
        if not frames.exists():
            return []
        # A concurrent last write may not yet have its terminating newline.
        return [json.loads(line) for line in frames.read_text().splitlines(keepends=True)
                if line.endswith('\n')]

    def wait(check):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if select.select([master], [], [], .08)[0]:
                transcript.extend(os.read(master, 65536))
            if check(read_frames()):
                return
            if proc.poll() is not None:
                raise AssertionError(transcript.decode('utf-8', 'replace'))
        raise AssertionError('Narrow curses observation timed out: ' + str(frames))

    try:
        wait(lambda items: items and any('> ◆ Firstmate' in line for line in items[-1]['lines'])
             and any('idle' in line for line in items[-1]['lines']))
        # Real PTY keyboard input navigates from the fixed row to the live worker.
        for _ in range(3):
            start = len(read_frames())
            os.write(master, b'j')
            wait(lambda items: len(items) > start and
                 any('>○ ONE CHILD ONLY' in line for line in items[-1]['lines']))
            selected = len(read_frames())
            wait(lambda items: len(items) >= selected + 8)
            for frame in read_frames()[selected:selected + 8]:
                lines = frame['lines']
                assert (frame['cols'], frame['rows']) == (28, 16), frame
                assert any('>○ ONE CHILD ONLY' in line for line in lines), frame
                assert any('idle · task' in line for line in lines), frame
                assert any('◆ Firstmate' in line for line in lines), frame
                assert any('1  Worker' in line for line in lines), frame
                assert any('1  idle' in line for line in lines), frame
            os.write(master, b'k')
            wait(lambda items: any('> ◆ Firstmate' in line for line in items[-1]['lines']))
        os.write(master, b'q')
        wait(lambda items: proc.poll() is not None)
        assert proc.returncode == 0, proc.returncode
        print('PASS real 28x16 curses: three navigation cycles, eight stable selected frames each', flush=True)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
        os.close(master)
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=4)
        (base / 'narrow-client.ansi').write_bytes(transcript)


if __name__ == '__main__':
    child(json.loads(sys.argv[1]), Path(sys.argv[2]))
