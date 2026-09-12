"""Opt-in timing wrapper: real app/CLI, test-owned bounded refresh barrier."""
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import threading
import time

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('latency_subject', os.environ.get('LATENCY_SOURCE', root / 'tshepherd.py'))
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)
base = Path(os.environ['LATENCY_EVIDENCE'])
lock = threading.Lock()


def event(name, **fields):
    with lock, (base / 'timings.jsonl').open('a') as log:
        log.write(json.dumps(dict(event=name, pid=os.getpid(), monotonic=time.monotonic(),
                                  wall_ns=time.time_ns(), **fields)) + '\n')


event('clock', executable=sys.executable, platform=platform.platform(),
      clock=str(time.get_clock_info('monotonic')), units='seconds; process-local durations only')


def wrap(cls, name):
    original = getattr(cls, name)

    def measured(self, *args, **kwargs):
        start = time.monotonic()
        event(name + '.start', args=str(args) if name in ('run', 'request_focus') else '')
        try:
            if name == 'collect' and (base / 'fetch-arm').exists():
                (base / 'fetch-start').touch()
                deadline = time.monotonic() + 30
                while not (base / 'fetch-release').exists():
                    if self.runner.stop.wait(.005) or time.monotonic() >= deadline:
                        raise TimeoutError('test-owned fetch barrier expired/cancelled')
                (base / 'fetch-arm').unlink()
            value = original(self, *args, **kwargs)
            event(name + '.end', duration=time.monotonic() - start,
                  result=str(value) if name == 'request_focus' else '')
            return value
        except Exception as error:
            event(name + '.error', duration=time.monotonic() - start, error=str(error))
            raise
    setattr(cls, name, measured)


# Only Firstmate's snapshot subprocess needs the routing adapter. Native app
# calls already enter the named helper; routing them through the snapshot shim
# again adds a Python startup and a second helper to every measured CLI call.
run = app.Runner.run


def routed_run(self, argv, timeout, env=None):
    if env is not None and Path(argv[0]).name == 'fm-fleet-snapshot.sh':
        env = {**env, 'PATH': os.environ['LATENCY_SNAPSHOT_PATH']}
    return run(self, argv, timeout, env)


app.Runner.run = routed_run


for method in ('snapshot', 'collect', 'probe', 'focus_target', 'focus'):
    wrap(app.Source, method)
wrap(app.Runner, 'run')
wrap(app.Poller, 'request_focus')
app.main()
