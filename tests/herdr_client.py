"""Opt-in real client keyboard/output regression; only named helper operations."""
import json
import re
from pathlib import Path
import shlex
import sys
import time
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tshepherd as app
from fixtures import sample_snapshot

from client_lab import root, helper, session, base, guard, call, until, send, output, create


workers = [create('Client worker A'), create('Client worker B')]
dashboard = create('Client dashboard')
for n, worker in enumerate(workers):
    program = 'import sys; print("TARGET_VISIBLE_' + str(n) + '", flush=True);\nfor line in sys.stdin: print("TARGET_INPUT_' + str(n) + ':" + line.strip(), flush=True)'
    call('pane', 'run', worker['pane_id'], shlex.join([sys.executable, '-u', '-c', program]))
    time.sleep(.3)
    call('pane', 'report-agent', worker['pane_id'], '--source', 'client-test', '--agent', 'pi', '--state', 'idle', '--seq', '1')
snapshot = sample_snapshot(str(base))
template = deepcopy(snapshot['tasks'][1])
snapshot['tasks'] = []
for n, worker in enumerate(workers):
    task = deepcopy(template)
    task.update(id='client-' + str(n), harness='pi')
    task['backlog']['title'] = 'CLIENT WORKER ' + str(n)
    task['endpoint'].update(target=session + ':' + worker['pane_id'], exists=True, freshness='fresh', observed_at=snapshot['generated'])
    snapshot['tasks'].append(task)
fixture = base / 'snapshot.json'


def save(value):
    temporary = fixture.with_suffix('.tmp')
    temporary.write_text(json.dumps(value))
    temporary.replace(fixture)


save(snapshot)
call('tab', 'focus', dashboard['tab_id'])
guard('viewer', 'start', session)
command = [sys.executable, str(root / 'tshepherd.py'), '--fm-home', str(base), '--firstmate-root', str(root), '--lab-helper', helper, '--lab-session', session, '--lab-snapshot', str(fixture)]
call('pane', 'run', dashboard['pane_id'], shlex.join(command))
until(lambda: b'CLIENT WORKER 1' in output())
time.sleep(1)
send(b'\x1b[B\x1b[B')  # Fixed Firstmate row, then worker A, then worker B.
time.sleep(.7)
# Native done remains focusable independently of semantic completion.
pane = workers[1]['pane_id']
call('pane', 'report-agent', pane, '--source', 'client-test', '--agent', 'pi', '--state', 'working', '--seq', '2')
call('pane', 'report-agent', pane, '--source', 'client-test', '--agent', 'pi', '--state', 'idle', '--seq', '3')
until(lambda: call('agent', 'get', pane)['result']['agent']['agent_status'] == 'done')
(base / 'native-done-before.json').write_text(json.dumps(call('agent', 'get', pane)))
offset = len(output())
# Retry busy Enter only before the client has projected the target.
for _ in range(12):
    send(b'\r')
    time.sleep(1)
    if b'TARGET_VISIBLE_1' in output()[offset:]:
        break
else:
    raise AssertionError('Enter did not project target into real client output')
send(b'keyboard-proof-72c8\r')
until(lambda: b'TARGET_INPUT_1:keyboard-proof-72c8' in output()[offset:])
(base / 'positive-client.ansi').write_bytes(output()[offset:])
print('PASS real client Arrow+Enter: native done target rendered and subsequent input received', flush=True)
# Rejections exercise the same Source.focus guards while a real client remains on
# the dashboard. Its subsequent arrows must still reach curses, not a worker.
import threading
source = app.Source(app.Config(str(base), str(root), lab_helper=helper, lab_session=session, fixture=str(fixture)), app.Runner(threading.Event()))
for case in ('removed', 'replaced', 'foreign', 'stale'):
    save(snapshot)
    call('tab', 'focus', dashboard['tab_id'])
    time.sleep(.7)
    changed = deepcopy(snapshot)
    selected = app.identity(snapshot['tasks'][1])
    if case == 'removed':
        changed['tasks'].pop()
    elif case == 'replaced':
        changed['tasks'][1]['spawn_gen'] = 'replacement'
    elif case == 'foreign':
        selected = ('unowned',) + selected[1:]
    else:
        changed['generated'] = '2000-01-01T00:00:00+00:00'
    save(changed)
    offset = len(output())
    try:
        source.focus(selected)
    except ValueError:
        pass
    else:
        raise AssertionError('Accepted ' + case)
    save(snapshot)
    time.sleep(.7)
    send(b'\x1b[A')
    time.sleep(.7)
    send(b'\x1b[B')
    time.sleep(.7)
    frame = output()[offset:]
    assert b'TARGET_VISIBLE_' not in frame, case
    cells = re.sub(rb'\x1b\[[0-9;]*m', b'', frame)
    assert b'\x1b[14;31H>' in cells and b'\x1b[15;31H>' in cells, (case, 'client arrows did not move the rendered dashboard selection')
    (base / (case + '-client.ansi')).write_bytes(frame)
    print('PASS real client unchanged:', case, flush=True)
send(b'\x03')
print('Client evidence:', base, flush=True)
