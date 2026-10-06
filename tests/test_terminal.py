"""Real POSIX PTY tests, no Herdr, credentials or shared fleet calls."""
import copy
import curses
import fcntl
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

GHOSTTY_TERMINFO = '/Applications/Ghostty.app/Contents/Resources/terminfo'


class TerminalTests(unittest.TestCase):
    def drive(self, args, interrupt=False, script="tshepherd.py", mouse=False, term='xterm-256color'):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 110, 0, 0))
        before = termios.tcgetattr(slave)
        terminfo = {'TERMINFO': GHOSTTY_TERMINFO} if term == 'xterm-ghostty' else {}
        env = dict(os.environ, TERM=term, **terminfo)
        proc = subprocess.Popen([sys.executable, script, *args], stdin=slave,
                                stdout=slave, stderr=slave, env=env, start_new_session=True)
        output = bytearray()
        try:
            deadline = time.monotonic() + 5
            while b'TShepherd' not in output and time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    output.extend(os.read(master, 65536))
            self.assertIn(b'TShepherd', output)
            for height, width in [(16, 34), (4, 10), (30, 110)]:
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', height, width, 0, 0))
                proc.send_signal(signal.SIGWINCH)
                time.sleep(.15)
                if select.select([master], [], [], .1)[0]:
                    output.extend(os.read(master, 65536))
            if mouse:
                def drain_until(token):
                    # Keep draining like a real emulator; backpressure would
                    # otherwise queue later reports before curses reads earlier ones.
                    seen = bytearray()
                    deadline = time.monotonic() + 2
                    while token not in seen and time.monotonic() < deadline:
                        if select.select([master], [], [], .05)[0]:
                            seen.extend(os.read(master, 65536))
                    output.extend(seen)
                    return seen

                # SGR press on the displayed second worker, split across reads.
                # Its ID appears only in the selected footer, not in table rows.
                os.write(master, b'\x1b[<0;13')
                time.sleep(.2)
                os.write(master, b';14M')
                selected = drain_until(b'demo-1')
                self.assertIn(b'demo-1', selected)
                os.write(master, b'\x1b[<0;13;14m')
                # Sideways scroll (buttons 6/7) is ignored; one wheel-down moves.
                os.write(master, b'\x1b[<66;13;14M\x1b[<67;13;14M\x1b[<65;13;14M')
                time.sleep(.3)
                # A resize forces a full repaint, so the footer ID is visible again.
                for height in (29, 30):
                    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', height, 110, 0, 0))
                    proc.send_signal(signal.SIGWINCH)
                    time.sleep(.15)
                scrolled = drain_until(b'demo-2')
                self.assertIn(b'demo-2', scrolled)
                self.assertNotIn(b'demo-3', scrolled)
                self.assertNotIn(b'Check selection', selected + scrolled)
            if interrupt:
                proc.send_signal(signal.SIGINT)
            else:
                os.write(master, b'jkjq')
            deadline = time.monotonic() + 5
            while proc.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], .05)[0]:
                    output.extend(os.read(master, 65536))
            proc.wait(timeout=.5)
            while select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))
            self.assertEqual(proc.returncode, 0, output.decode('utf-8', 'replace'))
            restored = termios.tcgetattr(slave)
            semantic_flags = termios.ECHO | termios.ICANON | termios.ISIG
            self.assertEqual(restored[3] & semantic_flags, before[3] & semantic_flags)
            # On macOS the kernel sets PENDIN when returning to canonical mode,
            # even without curses and with no queued input (see control below).
            # Test actual canonical input/echo, then require ALL flags equal.
            os.write(master, b'RESTORED_LINE')
            self.assertFalse(select.select([slave], [], [], .1)[0], 'canonical input returned without newline')
            self.assertTrue(select.select([master], [], [], 1)[0], 'echo missing')
            self.assertIn(b'RESTORED_LINE', os.read(master, 65536))
            os.write(master, b'\n')
            self.assertTrue(select.select([slave], [], [], 1)[0])
            self.assertEqual(os.read(slave, 100), b'RESTORED_LINE\n')
            self.assertEqual(termios.tcgetattr(slave), before)
            with patch.dict(os.environ, terminfo):
                curses.setupterm(term=term)
            for enter, leave in [('smcup', 'rmcup'), ('civis', 'cnorm')]:
                initial, final = curses.tigetstr(enter), curses.tigetstr(leave)
                self.assertIn(initial, output)
                self.assertIn(final, output)
                self.assertGreater(output.rfind(final), output.rfind(initial))
            self.assertNotIn(b'Traceback', output)
            return output
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            os.close(master)
            os.close(slave)

    def test_no_app_canonical_transition_control(self):
        master, slave = pty.openpty()
        try:
            before = termios.tcgetattr(slave)
            noncanonical = copy.deepcopy(before)
            noncanonical[3] &= ~(termios.ICANON | termios.ECHO)
            termios.tcsetattr(slave, termios.TCSANOW, noncanonical)
            termios.tcsetattr(slave, termios.TCSANOW, before)
            after = termios.tcgetattr(slave)
            if sys.platform == 'darwin':
                # Counterfactual: the same transient state occurs WITHOUT app,
                # curses, pending text, subprocesses, or a resize.
                self.assertEqual(after[3] ^ before[3], termios.PENDIN)
            os.write(master, b'control\n')
            self.assertTrue(select.select([slave], [], [], 1)[0])
            self.assertEqual(os.read(slave, 100), b'control\n')
            self.assertEqual(termios.tcgetattr(slave), before)
        finally:
            os.close(master)
            os.close(slave)

    def test_fixture_navigation_resize_and_clean_quit(self):
        output = self.drive([], script='tests/fixtures.py')
        self.assertIn(b'working', output)
        self.assertIn(b'idle', output)
        # Button reporting with SGR encoding is enabled only inside the application.
        for mode in (b'1000', b'1006'):
            enabled = b'\x1b[?' + mode + b'h'
            disabled = b'\x1b[?' + mode + b'l'
            self.assertIn(enabled, output)
            self.assertIn(disabled, output)
            self.assertGreater(output.rfind(disabled), output.rfind(enabled))
        # Pointer motion must never be reported: no button-event or any-motion mode.
        for mode in (b'1002', b'1003'):
            self.assertNotIn(b'\x1b[?' + mode + b'h', output)

    def test_real_mouse_press_selects_without_focus(self):
        self.drive([], script='tests/fixtures.py', mouse=True)

    @unittest.skipUnless(os.path.isdir(GHOSTTY_TERMINFO), 'Ghostty terminfo not installed')
    def test_real_mouse_with_ghostty_terminfo(self):
        # Ghostty's kmous is the SGR prefix, so keypad() reports it as KEY_MOUSE.
        output = self.drive([], script='tests/fixtures.py', mouse=True, term='xterm-ghostty')
        self.assertIn(b'\x1b[?1006h', output)

    def test_real_shell_usable_after_quit_and_terminal_ctrl_c(self):
        # Isolate the controlling-shell scenario from other PTY fixtures.
        # Cleanup closes the owned master before reaping: on macOS a killed
        # interactive shell can remain in kernel exit state until that close.
        result = subprocess.run([sys.executable, __file__, '--shell-check'],
                                capture_output=True, text=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def _real_shell_check(self):
        curses.setupterm(term='xterm-256color')
        keypad_on = curses.tigetstr('smkx')
        for key in (b'q', b'\x03', b'\x1a'):
            with self.subTest(key=key):
                pid, master = pty.fork()
                if pid == 0:
                    os.environ.update(TERM='xterm-256color', PS1='SHELL_READY> ')
                    os.execl('/bin/sh', 'sh', '-i')
                def read_until(marker, timeout=5):
                    output = bytearray()
                    deadline = time.monotonic() + timeout
                    while marker not in output and time.monotonic() < deadline:
                        if select.select([master], [], [], .05)[0]:
                            output.extend(os.read(master, 65536))
                    self.assertIn(marker, output, output.decode('utf-8', 'replace'))
                    return output
                try:
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 110, 0, 0))
                    read_until(b'SHELL_READY>')
                    command = shlex.join([sys.executable, str(Path('tests/fixtures.py').resolve())])
                    os.write(master, (command + '\n').encode())
                    read_until(b'TShepherd')
                    if key == b'\x1a':
                        # Ctrl+Z hands the shell a terminal without mouse reporting.
                        # Drain like a real emulator so the app is not blocked in output.
                        deadline = time.monotonic() + .5
                        while time.monotonic() < deadline:
                            if select.select([master], [], [], .05)[0]:
                                os.read(master, 65536)
                        os.write(master, key)
                        stopped = read_until(b'SHELL_READY>')
                        self.assertIn(b'\x1b[?1006l\x1b[?1000l', stopped)
                        self.assertNotIn(b'\x1b[?1000h', stopped.split(b'\x1b[?1000l')[-1])
                        # fg restores reporting, keypad mode and SGR click input.
                        os.write(master, b'fg\n')
                        resumed = read_until(b'\x1b[?1000h\x1b[?1006h')
                        resumed += read_until(b'TShepherd')
                        self.assertIn(keypad_on, resumed)
                        os.write(master, b'\x1b[<0;13;14M')
                        read_until(b'demo-1')
                        os.write(master, b'\x1b[<0;13;14m')
                        key = b'q'
                    os.write(master, key)
                    quit_output = read_until(b'SHELL_READY>')
                    self.assertIn(b'\x1b[?1006l\x1b[?1000l', quit_output)
                    os.write(master, b"printf 'SHELL_OK_%s\\n' $((2+3))\n")
                    read_until(b'SHELL_OK_5')
                    # Restored terminal-generated SIGINT interrupts a new child.
                    os.write(master, b'sleep 30\n')
                    time.sleep(.1)
                    os.write(master, b'\x03')
                    time.sleep(.1)
                    os.write(master, b"printf 'SIGNAL_%s\\n' OK\n")
                    read_until(b'SIGNAL_OK', timeout=3)
                finally:
                    # Closing this owned PTY end must precede waitpid: a killed
                    # macOS shell can be stuck in ?Es until its master closes.
                    os.close(master)
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        if os.waitpid(pid, os.WNOHANG)[0] == pid:
                            break
                        time.sleep(.02)
                    else:
                        self.fail('owned shell did not reap within cleanup deadline')

    def test_ctrl_c_responsive_during_snapshot_fetch_and_restores_terminal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'bin').mkdir()
            script = root / 'bin' / 'fm-fleet-snapshot.sh'
            script.write_text('#!/bin/sh\nsleep 30\n')
            script.chmod(0o700)
            started = time.monotonic()
            self.drive(['--fm-home', temp, '--firstmate-root', temp], interrupt=True)
            self.assertLess(time.monotonic() - started, 6)


if __name__ == '__main__':
    if sys.argv[1:] == ['--shell-check']:
        result = unittest.TextTestRunner().run(unittest.TestSuite([TerminalTests('_real_shell_check')]))
        sys.exit(0 if result.wasSuccessful() else 1)
    unittest.main()
