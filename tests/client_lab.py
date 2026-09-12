"""Shared opt-in real-client PTY fixture; every Herdr call uses the lab helper."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

root = Path.cwd()
helper = os.environ['HERDR_LAB_HELPER']
session = os.environ['HERDR_LAB_SESSION']
base = Path(os.environ.get('HERDR_LAB_EVIDENCE_DIR', root / '.local')) / session
base.mkdir(parents=True)
shim = base / 'shim'
shim.mkdir()
viewer_script = str(Path(helper).with_name('fm-herdr-lab-viewer.py'))
(shim / 'python3').write_text('#!/bin/sh\nif [ "$1" = ' + shlex.quote(viewer_script) + ' ]; then\n exec ' + shlex.join([sys.executable, str(root / 'tests/client_viewer_tap.py')]) + ' "$@"\nfi\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
(shim / 'python3').chmod(0o755)
env = {**os.environ, 'PATH': str(shim) + ':' + os.environ['PATH'], 'FOCUS_DIAGNOSTIC_DIR': str(base)}


def guard(*args):
    result = subprocess.run([helper, *args], env=env, capture_output=True, text=True, timeout=25)
    with (base / 'commands.jsonl').open('a') as log:
        log.write(json.dumps({'args': args, 'code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}) + '\n')
    result.check_returncode()
    return result.stdout


def call(*args):
    out = guard('run', session, *args)
    return out if args[:2] == ('pane', 'read') else json.loads(out) if out.strip() else {}


def until(check):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.2)
    raise AssertionError('Client observation timed out; evidence: ' + str(base))


def send(data):
    fd = os.open(base / 'input.fifo', os.O_WRONLY | os.O_NONBLOCK)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def output():
    return (base / 'client.ansi').read_bytes()


def create(label):
    return call('workspace', 'create', '--label', label, '--cwd', str(root), '--no-focus')['result']['root_pane']
