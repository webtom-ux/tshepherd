"""Focused real Herdr slow-fetch interaction; invoked by herdr-lab.sh only."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

from fixtures import sample_snapshot

helper = os.environ['HERDR_LAB_HELPER']
session = os.environ['HERDR_LAB_SESSION']
root = Path.cwd()
lab = Path(os.environ.get('HERDR_LAB_EVIDENCE_DIR', root / '.local')) / session
lab.mkdir(parents=True)


def call(*args):
    result = subprocess.run([helper, 'run', session, *args], capture_output=True,
                            text=True, timeout=10, check=True)
    if args[:2] == ('pane', 'read'):
        return result.stdout
    return json.loads(result.stdout) if result.stdout.strip() else {}


def until(check, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.1)
    raise AssertionError('Live slow-fetch observation did not converge')


viewer = call('workspace', 'create', '--label', 'TShepherd slow-fetch test',
              '--cwd', str(root), '--no-focus')['result']['root_pane']
pane = viewer['pane_id']
call('tab', 'focus', viewer['tab_id'])


def screen():
    return call('pane', 'read', pane, '--source', 'visible')


def selected(index):
    return re.search(r'\b' + str(index + 1) + r'\s+>', screen()) is not None


for key in ('q', 'ctrl+c'):
    case = lab / key.replace('+', '-')
    (case / 'bin').mkdir(parents=True)
    snapshot = sample_snapshot(str(case))
    snapshot['tasks'] = snapshot['tasks'][:2]
    # This scenario tests terminal interaction, not native activity or focus.
    # The inventory is synthetic; the dashboard, subprocess and Herdr are real.
    for task in snapshot['tasks']:
        task['endpoint'] = {}
    (case / 'snapshot.json').write_text(json.dumps(snapshot))
    script = case / 'bin' / 'fm-fleet-snapshot.sh'
    script.write_text(
        '#!' + sys.executable + '\n'
        'import os, pathlib, time\n'
        'root = pathlib.Path(__file__).parent.parent\n'
        'if (root / "served").exists():\n'
        '    (root / "blocked").write_text(str(os.getpid()))\n'
        '    time.sleep(30)\n'
        '    (root / "completed").touch()\n'
        '(root / "served").touch()\n'
        'print((root / "snapshot.json").read_text())\n')
    script.chmod(0o700)
    command = shlex.join([sys.executable, str(root / 'tshepherd.py'),
                          '--fm-home', str(case), '--firstmate-root', str(case),
                          '--lab-helper', helper, '--lab-session', session])
    call('pane', 'run', pane, 'cd ' + shlex.quote(str(case)) + '; stty -g > before; ' + command)
    until(lambda: '> ◆ Firstmate' in screen())
    call('pane', 'send-keys', pane, 'j')
    until(lambda: selected(0))
    until(lambda: (case / 'blocked').exists())
    started = time.monotonic()
    call('pane', 'send-keys', pane, 'j')
    until(lambda: selected(1), seconds=3)
    (case / 'navigated.ansi').write_text(call('pane', 'read', pane, '--source', 'visible', '--ansi'))
    # A real split changes the application's PTY size through the live viewer.
    if key == 'q':
        call('pane', 'split', pane, '--direction', 'right', '--ratio', '0.5',
             '--cwd', str(root), '--no-focus')
    else:
        call('pane', 'zoom', pane, '--off')
    until(lambda: '· Aufgabe' in screen(), seconds=3)
    (case / 'narrow.ansi').write_text(call('pane', 'read', pane, '--source', 'visible', '--ansi'))
    call('pane', 'zoom', pane, '--on')
    until(lambda: selected(1), seconds=3)
    call('pane', 'send-keys', pane, 'k')
    until(lambda: selected(0), seconds=3)
    assert not (case / 'completed').exists()
    assert time.monotonic() - started < 15, 'Interactions exceeded snapshot timeout window'
    call('pane', 'send-keys', pane, key)

    def shell_restored():
        processes = call('pane', 'process-info', '--pane', pane)['result']['process_info']['foreground_processes']
        return bool(processes) and all(p['name'].lower() in ('zsh', 'bash', 'sh', 'fish') for p in processes)

    until(shell_restored, seconds=3)
    # An incomplete shell command must echo but cannot execute before Enter.
    restored = case / 'restored'
    after = case / 'after'
    shell_command = 'stty -g > after; printf "SHELL_OK_%s\\n" "$((2+3))" > restored'
    call('pane', 'send-text', pane, shell_command)
    until(lambda: 'SHELL_OK_' in screen(), seconds=3)
    assert not restored.exists(), 'Shell executed without canonical newline'
    call('pane', 'send-keys', pane, 'Enter')
    until(restored.exists, seconds=3)
    assert restored.read_text() == 'SHELL_OK_5\n'
    assert after.read_text() == (case / 'before').read_text(), 'Terminal attributes changed'
    call('pane', 'run', pane, 'sleep 30')
    until(lambda: not shell_restored(), seconds=3)
    call('pane', 'send-keys', pane, 'ctrl+c')
    until(shell_restored, seconds=3)
    blocked_pid = int((case / 'blocked').read_text())
    try:
        os.kill(blocked_pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError('Snapshot subprocess survived dashboard exit')
    assert not (case / 'completed').exists()
    (case / 'shell.ansi').write_text(call('pane', 'read', pane, '--source', 'visible', '--ansi'))
    print('PASS:', key, 'navigation, real resize, exit during blocked fetch; canonical input, echo, exact stty restoration and subsequent shell SIGINT.', flush=True)

print('Evidence under', lab, flush=True)
