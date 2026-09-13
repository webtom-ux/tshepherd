"""Opt-in, called ONLY by herdr-lab.sh after guarded provisioning.

Synthetic registrations and a sleeping Python process exercise real CLI identity,
native statuses, curses in Herdr, and exact focus. They are not real AI agents.
"""
import json
from copy import deepcopy
import os
import re
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tshepherd as app
from fixtures import sample_snapshot

helper = os.environ['HERDR_LAB_HELPER']
session = os.environ['HERDR_LAB_SESSION']
root = Path.cwd()
lab = Path(os.environ.get('HERDR_LAB_EVIDENCE_DIR', root / '.local')) / session
lab.mkdir(parents=True)


def call(*args):
    result = subprocess.run([helper, 'run', session, *args], capture_output=True, text=True, timeout=10, check=True)
    if args[:2] == ('pane', 'read'):
        return result.stdout
    if result.stdout.strip():
        return json.loads(result.stdout)
    return {}


def until(check, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.2)
    raise AssertionError('Lab observation did not converge')


def create(label):
    result = call('workspace', 'create', '--label', label, '--cwd', str(root), '--no-focus')['result']
    return result['root_pane']


# Cross the decimal-looking prefix in this isolated session. IDs remain opaque:
# use only each creation response, never predict the endpoint from the counter.
for attempt in range(12):
    worker = create('TShepherd synthetic worker')
    if any(c.isupper() for c in worker['workspace_id']):
        break
else:
    raise AssertionError('No uppercase public ID observed within bounded lab setup')
viewer = create('TShepherd real TUI')
pane = worker['pane_id']
call('pane', 'run', pane, 'python3 -c "import time; time.sleep(300)"')
time.sleep(1)
call('pane', 'report-agent', pane, '--source', 'tshepherd-lab', '--agent', 'pi', '--state', 'idle', '--seq', '1')
snapshot = sample_snapshot(str(lab))
task = snapshot['tasks'][1]
task['id'] = 'lab-worker'
task['harness'] = 'pi'
task['backlog']['title'] = 'LAB COMPLETED WORKER'
task['endpoint'].update(target=session + ':' + pane, exists=True, freshness='fresh', observed_at=snapshot['generated'])
snapshot['tasks'] = [task]
fixture = lab / 'snapshot.json'
fixture.write_text(json.dumps(snapshot))
config = app.Config(str(lab), str(root), interval=.5, ttl=120, lab_helper=helper, lab_session=session, fixture=str(fixture))
source = app.Source(config, app.Runner(threading.Event()))
measured = source.probe(task, time.monotonic() + 12)
assert measured.state == 'idle', measured
assert app.rows_for(snapshot, {task['id']: measured}, time.time(), 120)[0].outcome == 'done'
call('pane', 'report-agent', pane, '--source', 'tshepherd-lab', '--agent', 'pi', '--state', 'working', '--seq', '2')
assert source.probe(task, time.monotonic() + 12).state == 'working'
call('pane', 'report-agent', pane, '--source', 'tshepherd-lab', '--agent', 'pi', '--state', 'blocked', '--seq', '3')
assert source.probe(task, time.monotonic() + 12).state == 'waiting'
call('pane', 'report-agent', pane, '--source', 'tshepherd-lab', '--agent', 'pi', '--state', 'idle', '--seq', '4')
# A second project and an unlisted native worker exercise inventory ownership.
waiting = create('TShepherd waiting worker')
foreign = create('TShepherd unowned worker')
for extra in (waiting, foreign):
    call('pane', 'run', extra['pane_id'], 'python3 -c "import time; time.sleep(300)"')
time.sleep(1)
for extra in (waiting, foreign):
    call('pane', 'report-agent', extra['pane_id'], '--source', 'tshepherd-lab', '--agent', 'pi', '--state', 'blocked', '--seq', '1')
print(source.focus(app.identity(task)), flush=True)
waiting_task = deepcopy(task)
waiting_task.update(id='lab-waiting')
waiting_task['backlog'].update(repo='Harbor', title='LAB WAITING WORKER')
waiting_task['current_state'].update(state='parked', detail='Waiting for lab approval')
waiting_task['endpoint']['target'] = session + ':' + waiting['pane_id']
snapshot['tasks'].append(waiting_task)
fixture.write_text(json.dumps(snapshot))
collected, natives = source.collect()
rows = app.rows_for(collected, natives, time.time(), config.ttl)
assert [(row.project, row.live, row.outcome) for row in rows] == [('Atlas', 'idle', 'done'), ('Harbor', 'waiting', 'parked')], rows
assert app.counters(rows) == dict(working=0, waiting=1, idle=1, completed=1, unknown=0, done=0)
view = app.View(snapshot=collected, natives=natives, last_success=time.time())
lines = app.render_lines(view, rows, 120, 40, False, time.time())
assert all(any(row.title in segment and role == app.STATES.index(row.live) + 1
               for text, spans in lines for _, segment, role in spans) for row in rows)
# Rejected selections must leave the real viewer focused.
foreign_task = deepcopy(task)
foreign_task.update(id='lab-unowned')
foreign_task['endpoint']['target'] = session + ':' + foreign['pane_id']
for case in ('removed', 'replaced', 'foreign', 'stale', 'foreign-home'):
    changed = deepcopy(snapshot)
    selected = app.identity(task)
    if case == 'removed':
        changed['tasks'] = [waiting_task]
    elif case == 'replaced':
        changed['tasks'][0]['spawn_gen'] = 'replacement'
    elif case == 'foreign':
        selected = app.identity(foreign_task)
    elif case == 'stale':
        changed['generated'] = '2000-01-01T00:00:00+00:00'
    else:
        changed['fm_home'] = str(lab / 'foreign-home')
    fixture.write_text(json.dumps(changed))
    call('tab', 'focus', viewer['tab_id'])
    try:
        source.focus(selected)
    except ValueError as error:
        print('REJECTED', case, str(error), flush=True)
    else:
        raise AssertionError('Focus accepted ' + case)
    assert call('pane', 'get', viewer['pane_id'])['result']['pane']['focused'] is True
fixture.write_text(json.dumps(snapshot))
# Inspect actual focus response and assert live viewer focus on the exact pane.
call('tab', 'focus', viewer['tab_id'])
response = call('agent', 'focus', pane)
(lab / 'focus-response.json').write_text(json.dumps(response, indent=2))
print('REAL FOCUS RESPONSE:', json.dumps(response), flush=True)
assert call('pane', 'get', pane)['result']['pane']['focused'] is True
call('tab', 'focus', viewer['tab_id'])
print(source.focus(app.identity(task)), flush=True)
assert call('pane', 'get', pane)['result']['pane']['focused'] is True
# Launch the actual curses application inside a real Herdr terminal pane.
command = shlex.join([sys.executable, str(root / 'tshepherd.py'), '--fm-home', str(lab), '--firstmate-root', str(root),
                      '--lab-helper', helper, '--lab-session', session, '--lab-snapshot', str(fixture)])
call('tab', 'focus', viewer['tab_id'])
call('pane', 'run', viewer['pane_id'], command)


def screen():
    return call('pane', 'read', viewer['pane_id'], '--lines', '200')


def has_count(label, value):
    return re.search(r'\b' + str(value) + r'\s+' + re.escape(label) + r'\b', screen()) is not None


until(lambda: 'LAB COMPLETED WORKER' in screen())
until(lambda: all(token in screen() for token in ('LAB WAITING WORKER', 'Atlas', 'Harbor', 'Waiting for lab approval'))
      and all(has_count(label, 1) for label in ('idle', 'waiting', 'completed')))
(lab / 'tui-screen.json').write_text(screen())
(lab / 'tui-screen.ansi').write_text(call('pane', 'read', viewer['pane_id'], '--source', 'visible', '--ansi'))
# Merely opening/refreshing the UI must not steal focus.
assert call('pane', 'get', viewer['pane_id'])['result']['pane']['focused'] is True
# Move from the fixed unavailable Firstmate row to the first worker.
call('pane', 'send-keys', viewer['pane_id'], 'j')
# Empty inventory must not silently retarget the previous selection.
empty = deepcopy(snapshot)
empty['tasks'] = []
fixture.write_text(json.dumps(empty))
until(lambda: has_count('Worker', 0))
replacement = deepcopy(snapshot)
replacement['tasks'] = [waiting_task]
fixture.write_text(json.dumps(replacement))
until(lambda: has_count('Worker', 1) and 'LAB WAITING WORKER' in screen())
call('pane', 'send-keys', viewer['pane_id'], 'Enter')
time.sleep(1)
assert call('pane', 'get', viewer['pane_id'])['result']['pane']['focused'] is True
(lab / 'tui-replacement-screen.json').write_text(screen())
print('PASS: empty inventory followed by a replacement does not retarget Enter.', flush=True)
fixture.write_text(json.dumps(snapshot))
until(lambda: has_count('Worker', 2) and 'LAB COMPLETED WORKER' in screen())
call('pane', 'report-agent', pane, '--source', 'tshepherd-lab', '--agent', 'pi', '--state', 'working', '--seq', '5')
until(lambda: source.probe(task, time.monotonic() + 12).state == 'working')
call('pane', 'report-agent', pane, '--source', 'tshepherd-lab', '--agent', 'pi', '--state', 'idle', '--seq', '6')
until(lambda: call('agent', 'get', pane)['result']['agent']['agent_status'] == 'done')
done = call('agent', 'get', pane)
(lab / 'native-done-before-enter.json').write_text(json.dumps(done, indent=2))
assert done['result']['agent']['focused'] is False
assert call('pane', 'get', viewer['pane_id'])['result']['pane']['focused'] is True
measured = source.probe(task, time.monotonic() + 12)
assert measured.state == 'unknown' and measured.physical, measured
until(lambda: has_count('unknown', 1) and has_count('completed', 1))
# Enter may coincide with a read; retry only while the UI still has focus.
for _ in range(10):
    call('pane', 'send-keys', viewer['pane_id'], 'Enter')
    time.sleep(.25)
    if call('pane', 'get', pane)['result']['pane']['focused'] is True:
        break
else:
    raise AssertionError('TUI Enter did not focus the exact worker')
focused = call('agent', 'get', pane)
assert focused['result']['agent']['focused'] is True
assert tuple(focused['result']['agent'][key] for key in ('workspace_id', 'tab_id', 'terminal_id')) == measured.physical
(lab / 'native-done-after-enter.json').write_text(json.dumps(focused, indent=2))
print('PASS: unfocused native working-to-done is acknowledged only by TUI Enter on the exact worker.', flush=True)
# Lose freshness after a populated screen; old rows must become unknown.
stale = deepcopy(snapshot)
stale['generated'] = '2000-01-01T00:00:00+00:00'
fixture.write_text(json.dumps(stale))
until(lambda: has_count('unknown', 2) and has_count('completed', 0))
assert 'LAB COMPLETED WORKER' in screen() and 'LAB WAITING WORKER' in screen()
(lab / 'tui-stale-screen.json').write_text(screen())
(lab / 'tui-stale-screen.ansi').write_text(call('pane', 'read', viewer['pane_id'], '--source', 'visible', '--ansi'))
print('PASS: populated project groups, activity, independent counters, state colors, ownership/focus rejection, and live stale display.', flush=True)
call('pane', 'send-keys', viewer['pane_id'], 'ctrl+c')
def shell_restored():
    processes = call('pane', 'process-info', '--pane', viewer['pane_id'])['result']['process_info']['foreground_processes']
    return bool(processes) and all(p['name'].lower() in ('zsh', 'bash', 'sh', 'fish') for p in processes)
until(shell_restored)
print('PASS: real Herdr native idle/working/blocked, separate task done, exact Source.focus and TUI Enter; Ctrl+C returned to shell.', flush=True)
print('Evidence under', lab, flush=True)
