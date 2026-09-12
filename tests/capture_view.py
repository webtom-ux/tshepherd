"""Opt-in screenshot evidence from a real curses window, not a layout mock.

Reads the explicit Firstmate home; never dispatches focus. Saves screen text and
curses attributes after a successful observation. No Herdr lifecycle operations.
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
import signal
import struct
import subprocess
import sys
import termios
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tshepherd as app


def capture(screen, source, output):
    class ObservedWindow:
        captured = False
        def __getattr__(self, name):
            return getattr(screen, name)
        def refresh(self):
            screen.refresh()
            height, width = screen.getmaxyx()
            lines = [screen.instr(y, 0).decode('utf-8', 'replace') for y in range(height)]
            if not self.captured and any(re.search(r'\b\d+\s+Worker\b', line) for line in lines):
                attributes = [[screen.inch(y, x) & curses.A_ATTRIBUTES for x in range(width)] for y in range(height)]
                pairs = {i: curses.pair_content(i) for i in range(1, 17)} if curses.has_colors() else {}
                output.write_text(json.dumps(dict(cols=width, rows=height, lines=lines,
                                                 attributes=attributes, pairs=pairs,
                                                 bold=curses.A_BOLD, dim=curses.A_DIM,
                                                 color_mask=curses.A_COLOR), ensure_ascii=False))
                self.captured = True
        def getch(self):
            if self.captured:
                return ord('q')
            # Consume no input except our own eventual q; never focus a worker.
            time.sleep(.08)
            return -1
    app.tui(ObservedWindow(), source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fm-home', required=True)
    parser.add_argument('--firstmate-root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cols', type=int, default=120)
    parser.add_argument('--rows', type=int, default=40)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if args.child:
        source = app.Source(app.Config(str(Path(args.fm_home).resolve()), str(Path(args.firstmate_root).resolve())),
                            app.Runner(threading.Event()))
        curses.wrapper(capture, source, output)
        return
    if not 28 <= args.cols <= 240 or not 16 <= args.rows <= 80:
        parser.error('capture dimensions: 28..240 columns, 16..80 rows')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', args.rows, args.cols, 0, 0))
    proc = subprocess.Popen([sys.executable, __file__, *sys.argv[1:], '--child'],
                            stdin=slave, stdout=slave, stderr=slave,
                            env=dict(os.environ, TERM='xterm-256color'), start_new_session=True)
    os.set_blocking(master, False)
    transcript = bytearray()
    try:
        deadline = time.monotonic() + 45
        while proc.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], .1)[0]:
                transcript.extend(os.read(master, 65536))
        if proc.poll() is None:
            raise TimeoutError('No successful observation within capture budget')
        if proc.returncode or not output.exists():
            raise RuntimeError(transcript.decode('utf-8', 'replace'))
        print('Captured real curses window:', output)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            # Continue draining terminal restoration output during cancellation.
            deadline = time.monotonic() + 4
            while proc.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    os.read(master, 65536)
        os.close(master)
        os.close(slave)
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=2)


if __name__ == '__main__':
    main()
