"""Opt-in real-client input-to-visible timing with real Firstmate inventory.

All timestamps subtracted for visible latency belong to this single observer.
The 32 metadata rows share two owned physical lab endpoints, not 32 AI agents.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import platform

root = Path.cwd()
helper = os.environ['HERDR_LAB_HELPER']
session = os.environ['HERDR_LAB_SESSION']
base = Path(os.environ.get('HERDR_LAB_EVIDENCE_DIR', root / '.local')) / session
base.mkdir(parents=True)
shim = base / 'shim'
shim.mkdir()
original_path = os.environ['PATH']
viewer_script = str(Path(helper).with_name('fm-herdr-lab-viewer.py'))
(shim / 'python3').write_text('#!/bin/sh\nif [ "$1" = ' + shlex.quote(viewer_script) + ' ]; then\n exec ' + shlex.join([sys.executable, str(root / 'tests/client_viewer_tap.py')]) + ' "$@"\nfi\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
(shim / 'python3').chmod(0o755)
env = {**os.environ, 'PATH': str(shim) + ':' + original_path, 'FOCUS_DIAGNOSTIC_DIR': str(base)}


def guard(*args):
    result = subprocess.run([helper, *args], env=env, capture_output=True, text=True, timeout=25)
    with (base / 'commands.jsonl').open('a') as log:
        log.write(json.dumps(dict(args=args, code=result.returncode, stdout=result.stdout, stderr=result.stderr)) + '\n')
    result.check_returncode()
    return result.stdout


def call(*args):
    text = guard('run', session, *args)
    return json.loads(text) if text.strip() else {}


def until(check, label, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.005)
    raise AssertionError(label + '; evidence: ' + str(base))


def send(data):
    fd = os.open(base / 'input.fifo', os.O_WRONLY | os.O_NONBLOCK)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def output():
    return (base / 'client.ansi').read_bytes()


def events():
    path = base / 'timings.jsonl'
    if not path.exists():
        return []
    # Ignore only an incomplete final append, never a complete malformed event.
    return [json.loads(line) for line in path.read_bytes().split(b'\n')[:-1]]


def count(name):
    return sum(e['event'] == name for e in events())


def create(label):
    return call('workspace', 'create', '--label', label, '--cwd', str(root), '--no-focus')['result']['root_pane']


workers = [create('Latency target A'), create('Latency target B')]
dashboard = create('Latency dashboard')
for n, worker in enumerate(workers):
    # Split marker literals so shell command echo cannot be readiness evidence.
    program = ('import sys; print("LATENCY_" + "VISIBLE_' + str(n) + '", flush=True);\n'
               'for line in sys.stdin: print("LATENCY_" + "INPUT_' + str(n) + ':" + line.strip(), flush=True)')
    call('pane', 'run', worker['pane_id'], shlex.join([sys.executable, '-u', '-c', program]))
    call('pane', 'report-agent', worker['pane_id'], '--source', 'latency-test', '--agent', 'pi', '--state', 'idle', '--seq', '1')

# Only the explicit lab home's real metadata feeds the real structured snapshot.
home = base / 'home'
for directory in ('state', 'data', 'config', 'projects'):
    (home / directory).mkdir(parents=True)
for n in range(32):
    (home / 'state' / ('timing-%02d.meta' % n)).write_text(
        'kind=ship\nharness=pi\nspawn_gen=latency-generation\nbackend=herdr\nwindow=' +
        session + ':' + workers[n % 2]['pane_id'] + '\nproject=Latency\n')

# Snapshot-internal Herdr reads must also cross the named helper. This PATH
# contains no other Herdr binary, so protocol fallback cannot bypass the guard.
# The adapter rejects absent/foreign routing rather than trusting ambient state.
read_shim = base / 'snapshot-bin'
read_shim.mkdir()
import shutil
(read_shim / 'jq').symlink_to(shutil.which('jq'))
(read_shim / 'herdr').write_text('#!' + sys.executable + '\n' +
    'import os, sys\na=sys.argv[1:]\n' +
    'assert len(a)>=2 and a[-2:]==["--session",' + repr(session) + '], a\n' +
    'os.environ["PATH"]=' + repr(original_path) + '\n' +
    'os.execv(' + repr(helper) + ',[' + repr(helper) + ',"run",' + repr(session) + ']+a[:-2])\n')
(read_shim / 'herdr').chmod(0o755)
call('tab', 'focus', dashboard['tab_id'])
guard('viewer', 'start', session)
command = ['env', 'PATH=' + original_path,
           'LATENCY_SNAPSHOT_PATH=' + str(read_shim) + ':/usr/bin:/bin:/usr/sbin:/sbin',
           'LATENCY_EVIDENCE=' + str(base)]
if os.environ.get('LATENCY_SOURCE'):
    command.append('LATENCY_SOURCE=' + str(Path(os.environ['LATENCY_SOURCE']).resolve()))
command += [sys.executable, str(root / 'tests/latency_app.py'), '--fm-home', str(home),
            '--firstmate-root', str(Path(helper).parent.parent), '--lab-helper', helper, '--lab-session', session]
call('pane', 'run', dashboard['pane_id'], shlex.join(command))
measurements = []
(base / 'observer-clock.json').write_text(json.dumps(dict(pid=os.getpid(), executable=sys.executable,
    platform=platform.platform(), clock=str(time.get_clock_info('monotonic')), units='seconds; one observer for injection and visible capture')))


def observed(label, marker, action):
    offset = len(output())
    start = time.monotonic()
    with (base / 'observer-events.jsonl').open('a') as log:
        log.write(json.dumps(dict(event='input-start', case=label, monotonic=start, offset=offset)) + '\n')
    action()
    until(lambda: marker in output()[offset:], label + ' visible marker')
    duration = time.monotonic() - start
    measurements.append(dict(case=label, seconds=duration))
    (base / (label + '.ansi')).write_bytes(output()[offset:])
    (base / 'measurements.json').write_text(json.dumps(measurements, indent=2))
    print(label, '%.3fs' % duration, flush=True)


def ready_tab(tab, marker):
    offset = len(output())
    call('tab', 'focus', tab)
    until(lambda: marker in output()[offset:], 'fresh client render before input', 10)
    with (base / 'observer-events.jsonl').open('a') as log:
        log.write(json.dumps(dict(event='render-ready', marker=marker.decode(),
                                  offset=offset, monotonic=time.monotonic())) + '\n')


def focused():
    until(lambda: count('focus.end') + count('focus.error') == count('focus.start'), 'focus completion')
    errors = [e for e in events() if e['event'] == 'focus.error']
    assert not errors, errors


try:
    until(lambda: count('collect.end') > 0, 'real 32-row snapshot complete')
    until(lambda: b'timing-01' in output(), 'dashboard rendered')
    ready_tab(workers[0]['tab_id'], b'LATENCY_VISIBLE_0')
    observed('ordered-clock-control', b'LATENCY_INPUT_0:clock-control-9472', lambda: send(b'clock-control-9472\r'))
    ready_tab(dashboard['tab_id'], b'TShepherd')
    # Pass fixed Firstmate and worker 0; navigation + Enter is one client write.
    observed('ready-32', b'LATENCY_VISIBLE_1', lambda: send(b'jj\r'))
    focused()
    observed('subsequent-target-input', b'LATENCY_INPUT_1:input-proof-9472', lambda: send(b'input-proof-9472\r'))
    ready_tab(dashboard['tab_id'], b'TShepherd')
    (base / 'fetch-arm').touch()
    until(lambda: (base / 'fetch-start').exists(), 'bounded explicit refresh barrier', 30)
    before = count('request_focus.end')
    offset = len(output())
    start = time.monotonic()
    send(b'\r')
    until(lambda: count('request_focus.end') > before, 'busy Enter dispatch', 3)
    accepted = [e for e in events() if e['event'] == 'request_focus.end'][-1]['result'] == 'True'
    if os.environ.get('LATENCY_EXPECT_REJECTION'):
        assert not accepted
        assert b'LATENCY_VISIBLE_1' not in output()[offset:]
        measurements.append(dict(case='busy-32', result='rejected, not queued'))
        print('busy-32: rejected (baseline)', flush=True)
    else:
        assert accepted, 'Enter dropped while refresh blocked'
        until(lambda: b'LATENCY_VISIBLE_1' in output()[offset:], 'busy visible target', 3)
        duration = time.monotonic() - start
        assert not (base / 'fetch-release').exists()
        measurements.append(dict(case='busy-32', seconds=duration))
        (base / 'busy-32.ansi').write_bytes(output()[offset:])
        print('busy-32: %.3fs, fetch still blocked' % duration, flush=True)
        focused()
        # Live UI Enter must reject changed ownership even while the fleet
        # snapshot cannot finish. Preserve the exact old selection throughout.
        meta = home / 'state/timing-01.meta'
        original = meta.read_text()
        ready_tab(dashboard['tab_id'], b'TShepherd')
        for case in ('removed', 'replaced', 'foreign', 'unknown'):
            if case == 'removed':
                meta.unlink()
            elif case == 'replaced':
                meta.write_text(original + 'spawn_gen=replacement\n')
            elif case == 'foreign':
                meta.write_text(original + 'remote_host=foreign\n')
            else:
                meta.write_text('unrecognized-format\n')
            before = count('focus.error')
            offset = len(output())
            send(b'\r')
            until(lambda: count('focus.error') > before, case + ' UI rejection', 3)
            assert b'LATENCY_VISIBLE_' not in output()[offset:], case
            (base / (case + '-client.ansi')).write_bytes(output()[offset:])
            meta.write_text(original)
            print('PASS UI rejection during blocked fetch:', case, flush=True)
        # Disconfirm that responsiveness depends on an otherwise idle machine:
        # release into the actual slow fleet subprocess, then focus while it runs.
        starts, ends = count('snapshot.start'), count('snapshot.end')
        failures, completions = count('focus.error'), count('focus.end')
        (base / 'fetch-release').touch()
        until(lambda: count('snapshot.start') > starts, 'real background snapshot starts', 3)
        observed('during-real-refresh', b'LATENCY_VISIBLE_1', lambda: send(b'\r'))
        assert count('snapshot.end') == ends, 'snapshot completed before visible focus evidence'
        until(lambda: count('focus.end') > completions or count('focus.error') > failures,
              'focus confirmation during real snapshot', 5)
        assert count('focus.error') == failures
    (base / 'measurements.json').write_text(json.dumps(measurements, indent=2))
    # End-to-end visible evidence, never CLI completion or an average that hides
    # a slow switch. Keep every measurement and run rejection guards on failure.
    if not os.environ.get('LATENCY_EXPECT_REJECTION'):
        # Captain: "0,3 ist für mich ok"; observed 305–345ms explicitly accepted.
        limit = 0.345
        slow = [m for m in measurements
                if m['case'] in ('ready-32', 'busy-32', 'during-real-refresh')
                and m['seconds'] > limit]
        assert not slow, f'Enter-to-visible exceeds {limit:.3f}s: {slow}; evidence: {base}'
finally:
    (base / 'fetch-release').touch()
    call('tab', 'focus', dashboard['tab_id'])
    send(b'\x03')
print('Latency evidence:', base, flush=True)
