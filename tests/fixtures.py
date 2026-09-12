"""Synthetic worker inventory for isolated tests only."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tshepherd as app


def sample_snapshot(home):
    now = datetime.now(timezone.utc).isoformat()
    tasks = []
    for index, (live, semantic, project) in enumerate([
        ("working", "working", "Atlas"), ("idle", "done", "Atlas"),
        ("waiting", "parked", "Harbor"), ("idle", "paused", "Harbor"),
        ("unknown", "unknown", "Harbor")]):
        tasks.append({"id": f"demo-{index}", "spawn_gen": "demo", "backend": "herdr", "harness": "pi",
                      "project": "host", "backlog": {"repo": project, "title": ["Live-Ansicht bauen", "Tests fertig", "Freigabe fehlt", "Wartet auf CI", "Nicht erreichbar"][index]},
                      "current_state": {"state": semantic, "detail": "Synthetische Demo, kein echter Worker", "observed_at": now, "freshness": "fresh"},
                      "endpoint": {"target": f"demo:w1:p{index + 1}"}, "demo_live": live})
    return {"schema": app.SCHEMA, "fm_home": home, "generated": now, "tasks": tasks}


def collect(source):
    snapshot = sample_snapshot(source.config.home)
    return snapshot, {t["id"]: app.Native(t["demo_live"], "Fixture", time.time(), app.identity(t))
                      for t in snapshot["tasks"]}


if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--fm-home", str(Path.cwd()), "--firstmate-root", str(Path.cwd())]
    with patch.object(app.Source, "collect", collect):
        app.main()
