"""Opt-in macOS primary ownership + actual client-visible Enter acceptance.

Synthetic harness argv/registration, not a model session. Every endpoint and
mutation belongs to the named lab; the real Firstmate owner library is read-only.
"""
import json
import os
import re
from pathlib import Path
import shlex
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tshepherd as app
from fixtures import sample_snapshot
from client_lab import root, helper, session, base, guard, call, until, send, output, create

if sys.platform != 'darwin':
    raise SystemExit('Primary identity lab requires macOS; other OS stays unavailable')
code_root = Path(helper).resolve().parent.parent
home = base / 'home'
(home / 'state').mkdir(parents=True)
primary = create('Synthetic primary chat')
worker = create('Synthetic child')
dashboard = create('Independent dashboard')
program = base / 'primary-owner.py'
program.write_text('''import os,sys
from pathlib import Path
Path(sys.argv[1]).write_text(str(os.getpid())+'\\n')
print('PRIMARY_CLIENT_VISIBLE_86b2', flush=True)
for line in sys.stdin:
    print('PRIMARY_CLIENT_INPUT_86b2:'+line.strip(), flush=True)
''')
# An explicit synthetic argv0 exercises Firstmate's existing harness classifier
# without launching a real agent, consuming credentials, or inventing metadata.
# Apple's /usr/bin/python3 launcher rewrites argv0 on its framework exec.
# Invoke the real framework binary for this synthetic harness-name fixture.
framework = Path(sys.base_prefix) / 'Resources/Python.app/Contents/MacOS/Python'
interpreter = str(framework) if framework.is_file() else sys.executable
owner_command = 'exec -a pi ' + shlex.join([interpreter, '-u', str(program), str(home / 'state/.lock')])
call('pane', 'run', primary['pane_id'], shlex.join(['/bin/bash', '-c', owner_command]))
until(lambda: (home / 'state/.lock').exists())
call('pane', 'report-agent', primary['pane_id'], '--source', 'primary-lab', '--agent', 'pi', '--state', 'idle', '--seq', '1')
call('pane', 'run', worker['pane_id'], shlex.join([sys.executable, '-c', 'import time; time.sleep(300)']))
call('pane', 'report-agent', worker['pane_id'], '--source', 'primary-lab', '--agent', 'pi', '--state', 'idle', '--seq', '1')
snapshot = sample_snapshot(str(home))
task = snapshot['tasks'][1]
task['id'] = 'only-child'
task['backlog']['title'] = 'ONE CHILD ONLY'
task['endpoint'].update(target=session + ':' + worker['pane_id'], exists=True,
                        observed_at=snapshot['generated'], freshness='fresh')
snapshot['tasks'] = [task]
fixture = base / 'snapshot.json'
fixture.write_text(json.dumps(snapshot))
source = app.Source(app.Config(str(home), str(code_root), lab_helper=helper, lab_session=session,
                               fixture=str(fixture)), app.Runner(threading.Event()))
observed = None

def measured():
    global observed
    observed = source.primary(time.monotonic() + 12)
    (base / 'primary-observation.json').write_text(json.dumps(observed.__dict__, indent=2))
    return bool(observed.physical)

until(measured)
assert observed.pane == primary['pane_id'], observed
from herdr_narrow import verify as verify_narrow
verify_narrow(source.config, base)
(base / 'primary-observation.json').write_text(json.dumps(observed.__dict__, indent=2))
call('tab', 'focus', dashboard['tab_id'])
guard('viewer', 'start', session)
command = [sys.executable, str(root / 'tshepherd.py'), '--fm-home', str(home),
           '--firstmate-root', str(code_root), '--lab-helper', helper, '--lab-session', session,
           '--lab-snapshot', str(fixture)]
call('pane', 'run', dashboard['pane_id'], shlex.join(command))
until(lambda: b'ONE CHILD ONLY' in output())
time.sleep(.5)
# Exact first row is reachable with the same real client arrow handler.
send(b'\x1b[B')
time.sleep(.4)
send(b'\x1b[A')
time.sleep(.4)
screen = call('pane', 'read', dashboard['pane_id'], '--lines', '200')
assert '> ◆ Firstmate' in screen, screen
assert re.search(r'\b1\s+Worker\b', screen), screen
before = len(output())
for _ in range(12):
    send(b'\r')
    time.sleep(1)
    if b'PRIMARY_CLIENT_VISIBLE_86b2' in output()[before:]:
        break
else:
    raise AssertionError('Primary Enter did not change the actual client view')
send(b'primary-keyboard-proof\r')
until(lambda: b'PRIMARY_CLIENT_INPUT_86b2:primary-keyboard-proof' in output()[before:])
(base / 'primary-positive-client.ansi').write_bytes(output()[before:])
print('PASS exact primary row: real client arrows + Enter + subsequent target input', flush=True)

# A claimed endpoint in another synthetic owner's environment does not confer
# ancestry. Read only that home's lock and injected candidate; no namespace scan.
foreign_home = base / 'foreign-home'
(foreign_home / 'state').mkdir(parents=True)
foreign = create('Synthetic wrong-owner process')
foreign_command = 'exec -a pi ' + shlex.join([interpreter, '-u', str(program), str(foreign_home / 'state/.lock')])
forged = ['env', 'HERDR_PANE_ID=' + primary['pane_id'], 'HERDR_TAB_ID=' + primary['tab_id'],
          'HERDR_WORKSPACE_ID=' + primary['workspace_id'], '/bin/bash', '-c', foreign_command]
call('pane', 'run', foreign['pane_id'], shlex.join(forged))
until(lambda: (foreign_home / 'state/.lock').exists())
foreign_source = app.Source(app.Config(str(foreign_home), str(code_root), lab_helper=helper,
                                       lab_session=session), app.Runner(threading.Event()))
wrong = foreign_source.primary(time.monotonic() + 12)
assert not wrong.physical, wrong
(base / 'foreign-owner-rejected.json').write_text(json.dumps(wrong.__dict__, indent=2))

call('tab', 'focus', dashboard['tab_id'])
time.sleep(.5)
lock = home / 'state/.lock'
original, times = lock.read_bytes(), lock.stat()
for case in ('missing', 'malformed', 'stale-generation', 'foreign-owner'):
    if case == 'missing':
        lock.unlink()
    elif case == 'malformed':
        lock.write_text('ambiguous 1 2\n')
    elif case == 'stale-generation':
        os.utime(lock, (1, 1))
    else:
        lock.write_bytes((foreign_home / 'state/.lock').read_bytes())
    start = len(output())
    try:
        source.focus(observed.key)
    except ValueError:
        pass
    else:
        raise AssertionError('Accepted unavailable primary: ' + case)
    # Wait for the actual TUI's unavailable first row, then enter through client.
    until(lambda: 'unavailable' in call('pane', 'read', dashboard['pane_id'], '--lines', '200'))
    send(b'k\r')
    time.sleep(.7)
    assert b'PRIMARY_CLIENT_VISIBLE_86b2' not in output()[start:], case
    assert call('pane', 'get', dashboard['pane_id'])['result']['pane']['focused'] is True
    (base / (case + '-client.ansi')).write_bytes(output()[start:])
    lock.write_bytes(original)
    os.utime(lock, ns=(times.st_atime_ns, times.st_mtime_ns))
    print('PASS primary unavailable without client navigation:', case, flush=True)

send(b'\x03')
guard('viewer', 'stop', session)
# Restored public handles are not the old owner generation. Lifecycle remains
# exclusively at the guarded helper, including deliberate mid-run stop.
guard('stop', session)
guard('provision', session)
restored = call('pane', 'get', primary['pane_id'])['result']['pane']
assert restored['pane_id'] == primary['pane_id']
assert restored['terminal_id'] != observed.physical[2]
after_restart = source.primary(time.monotonic() + 12)
assert not after_restart.physical, after_restart
try:
    source.focus(observed.key)
except ValueError:
    pass
else:
    raise AssertionError('Accepted primary selection after server restart')
(base / 'restart-unavailable.json').write_text(json.dumps(after_restart.__dict__, indent=2))
print('PASS restart retained public handle but refused stale owner; evidence:', base, flush=True)
