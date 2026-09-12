"""Diagnostic-only tap on the guarded helper's owned viewer PTY."""
import importlib.util
import json
import os
import select
import sys
import time
from pathlib import Path

original = sys.argv[1]
spec = importlib.util.spec_from_file_location('guarded_viewer', original)
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)
base = Path(os.environ['FOCUS_DIAGNOSTIC_DIR'])

def drain(master):
    fifo = base / 'input.fifo'
    os.mkfifo(fifo)
    control = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    try:
        with (base / 'client.ansi').open('ab', buffering=0) as output, (base / 'client-events.jsonl').open('a') as events:
            def record(kind, **fields):
                events.write(json.dumps(dict(event=kind, monotonic=time.monotonic(), **fields)) + '\n')
                events.flush()
            while True:
                ready, _, _ = select.select([master, control], [], [])
                if master in ready:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        return
                    if not data:
                        return
                    output.write(data)
                    record('client-output', offset=output.tell(), bytes=len(data))
                if control in ready:
                    data = os.read(control, 4096)
                    if data:
                        record('fifo-input', data=data.hex())
                        written = os.write(master, data)
                        record('pty-input', bytes=written)
                        if written != len(data):
                            raise RuntimeError('partial client PTY input write')
    finally:
        os.close(control)

viewer._drain = drain
raise SystemExit(viewer.main(sys.argv[1:]))
