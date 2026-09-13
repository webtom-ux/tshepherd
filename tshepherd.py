#!/usr/bin/env python3
"""TShepherd: observational Firstmate fleet TUI (Python standard library only)."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import curses
from dataclasses import dataclass, field, replace
from datetime import datetime
import json
import math
import os
from pathlib import Path
import queue
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata

from i18n import set_language, tr

SCHEMA = "fm-fleet-snapshot.v1"
STATES = ("working", "waiting", "idle", "completed", "unknown")
LIVE_STATES = ("working", "waiting", "idle", "done", "unknown")
ACTIVE_OUTCOMES = {"working", "parked", "blocked", "paused"}
TERMINAL_OUTCOMES = {"done", "failed"}
SHELLS = {"sh", "bash", "zsh", "fish", "dash", "login"}
PRIMARY = ("firstmate-primary",)  # Tuple namespace cannot collide with worker IDs.
MODEL_NAMES = ("Astra", "Terra", "Sol", "Luna", "Grok", "Claude")
MODEL_NAME_WIDTH = 6
MODEL_COLUMN_WIDTH = 9
QUOTA_CACHE_TTL = 90
QUOTA_DISPLAY_TTL = 120
EFFORT_NAMES = {
    "none": "N", "off": "O", "minimal": "Mn", "low": "L", "medium": "M",
    "high": "H", "xhigh": "XH", "max": "Mx", "ultra": "U",
}


def clean(value):
    """Untrusted source text is never a terminal control sequence."""
    if not isinstance(value, str):
        return ""
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())


def compact_model(model, effort):
    """Render a fixed model name or a compact name derived from runtime evidence."""
    value = clean(model)
    lowered = value.casefold()
    name = next((known for known in MODEL_NAMES
                 if re.search(r"(?:^|[^a-z])" + known.casefold() + r"(?:$|[^a-z])", lowered)), None)
    if name is None and value:
        # Runtime selection is normally provider/model-id. Prefer the model-id,
        # normalize its separators, and bound it to the compact column.
        source = next((part for part in reversed(value.split("/")) if part), value)
        derived = re.sub(r"[^0-9A-Za-z]+", "-", source).strip("-")
        if derived:
            name = derived[:MODEL_NAME_WIDTH]
            name = name[0].upper() + name[1:]
        else:
            name = value[:MODEL_NAME_WIDTH]
    level = EFFORT_NAMES.get(clean(effort).casefold(), "?")
    return (name or "?") + "·" + level


def fit(text, width):
    result, used = "", 0
    for char in text:
        char = char if char.isprintable() else " "
        size = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in "WF" else 1)
        if used + size > max(0, width):
            break
        result += char
        used += size
    return result


def epoch(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def fresh(observation, now, ttl):
    observed = epoch(observation.get("observed_at"))
    return (observation.get("freshness") == "fresh" and observed is not None
            and -2 <= now - observed <= ttl)


def process_start(value):
    """Convert a confirmed Darwin process-generation timestamp, or fail closed."""
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return 0
    started = value / 10**9
    return started if started <= time.time() + 2 else 0


def compact_duration(started, now, ended=0):
    """Compact wall time between confirmed bounds, or from a live start to now."""
    if (not isinstance(started, (int, float)) or isinstance(started, bool)
            or not math.isfinite(started) or started <= 0):
        return "—"
    if ended:
        if (not isinstance(ended, (int, float)) or isinstance(ended, bool)
                or not math.isfinite(ended) or ended <= 0 or ended > now + 2):
            return "—"
    elapsed = (ended or now) - started
    if elapsed < -2:
        return "—"
    seconds = max(0, int(elapsed))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 60 * 60:
        return f"{seconds // 60}m"
    if seconds < 24 * 60 * 60:
        return f"{seconds // (60 * 60)}h"
    return f"{seconds // (24 * 60 * 60)}d"


def endpoint(task):
    if task.get("backend") != "herdr" or task.get("remote"):
        raise ValueError(tr("kein lokaler Herdr-Endpunkt"))
    return parse_endpoint(task.get("endpoint", {}).get("target"))


def parse_endpoint(target):
    if not isinstance(target, str) or ":" not in target:
        raise ValueError(tr("Endpunkt fehlt"))
    session, pane = target.split(":", 1)
    # Herdr 0.9 public IDs use uppercase readable base32, not decimal indices.
    handle = r"[0-9ABCDEFGHJKMNPQRSTVWXYZ]+"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", session) or not re.fullmatch(r"w" + handle + r":p" + handle, pane):
        raise ValueError(tr("ungültige Endpunktidentität"))
    return session, pane


def session_confirmed(status, requested):
    """Match explicit CLI routing; only the reserved default name normalizes null.

    Herdr v0.9.0 session::normalize_name / cli::status serialize both session
    fields as null for --session default. Missing fields are NOT that contract.
    The documented socket layout independently rejects a named/default mismatch.
    """
    client, server = status.get("client"), status.get("server")
    if not isinstance(client, dict) or not isinstance(server, dict):
        return False
    expected = None if requested == "default" else requested
    if ("session" not in client or "session" not in server
            or client["session"] != expected or server["session"] != expected
            or server.get("running") is not True or server.get("compatible") is not True):
        return False
    socket = server.get("socket")
    if not isinstance(socket, str) or not Path(socket).is_absolute() or Path(socket).name != "herdr.sock":
        return False
    path = Path(socket)
    if requested == "default":
        return path.parent.parent.name != "sessions"
    return path.parent.name == requested and path.parent.parent.name == "sessions"


def identity(task):
    return (task["id"], task.get("spawn_gen"), task.get("backend"),
            task.get("endpoint", {}).get("target"), task.get("harness"))


def validate_snapshot(data, home):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError(tr("Snapshot-Schema unbekannt"))
    if data.get("fm_home") != str(Path(home).resolve()):
        raise ValueError(tr("Snapshot gehört einem anderen FM_HOME"))
    if epoch(data.get("generated")) is None or not isinstance(data.get("tasks"), list):
        raise ValueError(tr("Snapshot-Zeit/Inventar fehlt"))
    if not isinstance(data.get("main_inventory", {}), dict):
        raise ValueError(tr("Snapshot-Inventarprüfung ungültig"))
    ids = set()
    for task in data["tasks"]:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task["id"] or task["id"] in ids:
            raise ValueError(tr("Snapshot mit fehlender/doppelter Worker-Identität"))
        ids.add(task["id"])
        for key in ("endpoint", "current_state", "paths", "hints"):
            if not isinstance(task.get(key, {}), dict):
                raise ValueError(tr("Snapshot-Feld ungültig: ") + key)
        if task.get("backlog") is not None and not isinstance(task["backlog"], dict):
            raise ValueError(tr("Snapshot-Backlog ungültig"))
    return data


@dataclass
class Native:
    state: str = "unknown"
    detail: str = field(default_factory=lambda: tr("nicht gemessen"))
    observed: float = 0
    binding: tuple = ()
    physical: tuple = ()
    model: str = ""
    effort: str = ""
    session_started: float = 0
    task_started: float = 0


@dataclass(frozen=True)
class Quota:
    provider: str
    percent: int
    observed: float


@dataclass
class Row:
    task: dict
    project: str
    title: str
    live: str
    outcome: str
    activity: str
    reason: str
    key: tuple
    model: str
    session_started: float = 0
    task_started: float = 0
    task_ended: float = 0


@dataclass
class PrimaryRow:
    key: tuple = (PRIMARY,)
    live: str = "unknown"
    reason: str = field(default_factory=lambda: tr("Firstmate-Identität noch nicht bestätigt"))
    observed: float = 0
    provider: str = ""
    session: str = ""
    pane: str = ""
    physical: tuple = ()
    model: str = ""
    effort: str = ""
    session_started: float = 0


def overview_rows(view, now, ttl):
    primary = view.natives.get(PRIMARY, PrimaryRow())
    if view.error or not 0 <= now - primary.observed <= ttl:
        primary = replace(primary, live="unknown", reason=tr("Firstmate nicht verfügbar: Messung fehlt/veraltet"),
                          model="", effort="", session_started=0)
    workers = rows_for(view.snapshot, view.natives, now, ttl, bool(view.error))
    view.retain_task_times(workers, now)
    return [primary] + workers


def rows_for(snapshot, natives, now, ttl, unavailable=False):
    rows = []
    snapshot_time = epoch(snapshot.get("generated"))
    stale = unavailable or snapshot_time is None or not -2 <= now - snapshot_time <= ttl
    for task in snapshot.get("tasks", []):
        backlog = task.get("backlog") or {}
        project = clean(backlog.get("repo")) or clean(task.get("project")) or tr("Projekt unbekannt")
        title = clean(backlog.get("title")) or clean(task["id"])
        current = task.get("current_state", {})
        semantic = current.get("state", "unknown")
        outcome = semantic if semantic in {"working", "parked", "done", "blocked", "paused", "failed", "unknown"} else "unknown"
        reason = ""
        if stale or not fresh(current, now, ttl):
            outcome, reason = "unknown", tr("veraltet / Quelle nicht erreichbar")
        elif backlog.get("state") == "done":
            outcome = "done"
        native = natives.get(task["id"], Native())
        native_valid = not stale and 0 <= now - native.observed <= ttl and native.binding == identity(task)
        live = native.state
        if not native_valid:
            live = "unknown"
            reason = reason or tr("Native-Messung fehlt/veraltet")
        if live not in {"working", "waiting", "idle", "done"}:
            live = "unknown"
        if live == "unknown":
            reason = reason or native.detail
        elif live == "done":
            # Herdr distinguishes an unseen ready response from ordinary idle.
            # Keep that native explanation visible without treating it as task activity.
            reason = " · ".join(detail for detail in (reason, native.detail) if detail)
        model = compact_model(native.model, native.effort) if native_valid else compact_model("", "")
        session_started = native.session_started if native_valid else 0
        task_started = (native.task_started if native_valid and outcome in ACTIVE_OUTCOMES else 0)
        activity = clean(current.get("detail"))
        if not activity:
            log = task.get("paths", {}).get("status_log", {})
            if isinstance(log, dict) and log.get("kind") == "event_history":
                event = log.get("last_event", {})
                if isinstance(event, dict):
                    activity = clean(event.get("note"))
                    if activity:
                        activity = tr("Historie: ") + activity
        rows.append(Row(task, project, title, live, outcome, activity or tr("keine Aktivität geliefert"),
                        clean(reason), identity(task), model, session_started, task_started))
    return sorted(rows, key=lambda row: (row.project.casefold(), row.title.casefold(), row.task["id"]))


def parse_quotas(data, observed):
    """Keep only fresh usable providers with known effective availability."""
    result = []
    providers = data.get("providers") if isinstance(data, dict) else None
    if not isinstance(providers, list):
        raise ValueError(tr("Quota-Antwort ungültig"))
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        state = provider.get("state", {})
        semantics = provider.get("quotaSemantics", {})
        if (not isinstance(state, dict) or state.get("status") != "fresh"
                or state.get("stale") is not False
                or state.get("authStatus") not in (None, "usable")
                or not isinstance(semantics, dict) or semantics.get("status") != "known"):
            continue
        scopes = semantics.get("effectiveAvailability")
        if not isinstance(scopes, list):
            continue
        primary = [scope for scope in scopes if isinstance(scope, dict)
                   and scope.get("scope") in ("all_models", "all_products")]
        if len(primary) != 1:
            continue
        scope = primary[0]
        value = scope.get("effectivePercentRemaining")
        name = clean(provider.get("provider"))
        if (name and scope.get("status") == "known" and isinstance(value, (int, float))
                and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100):
            result.append(Quota(name, int(round(value)), observed))
    return result


def counters(rows):
    # Completion is a separate dimension, not an exclusive live-agent state.
    result = {state: 0 for state in STATES}
    result["done"] = 0
    for row in rows:
        if isinstance(row, PrimaryRow):
            continue
        result[row.live] += 1
        if row.outcome == "done":
            result["completed"] += 1
    return result


class Runner:
    """Bounded subprocess group; cancellation kills descendants as well."""
    def __init__(self, stop):
        self.stop = stop

    def run(self, argv, timeout, env=None):
        if self.stop.is_set():
            raise RuntimeError(tr("abgebrochen"))
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(argv, stdout=out, stderr=err, env=env,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
            deadline = time.monotonic() + max(0, timeout)
            completed = threading.Event()

            def reap():
                proc.wait()
                completed.set()

            waiter = threading.Thread(target=reap, daemon=True)
            waiter.start()
            try:
                while not completed.is_set():
                    if self.stop.is_set():
                        raise RuntimeError(tr("abgebrochen"))
                    if time.monotonic() >= deadline:
                        raise TimeoutError(tr("Zeitlimit: ") + Path(argv[0]).name)
                    if os.fstat(out.fileno()).st_size > 8 * 1024 * 1024 or os.fstat(err.fileno()).st_size > 65536:
                        raise ValueError(tr("Antwort überschreitet Größenlimit"))
                    # Timed Popen.wait uses exponential polling on POSIX.
                    # The blocking reaper wakes this bounded guard immediately.
                    completed.wait(min(0.04, max(0, deadline - time.monotonic())))
                if os.fstat(out.fileno()).st_size > 8 * 1024 * 1024 or os.fstat(err.fileno()).st_size > 65536:
                    raise ValueError(tr("Antwort überschreitet Größenlimit"))
                out.seek(0)
                err.seek(0)
                if proc.returncode:
                    raise RuntimeError(clean(err.read(1024).decode("utf-8", "replace")) or tr("Befehl fehlgeschlagen"))
                data = json.load(out)
                if isinstance(data, dict) and data.get("error"):
                    raise RuntimeError(clean(str(data["error"])))
                return data
            finally:
                # Also clear any children that outlived a completed group leader.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                waiter.join()


@dataclass
class Config:
    home: str
    root: str
    interval: float = 5
    ttl: float = 45
    timeout: float = 20
    herdr: str = "herdr"
    lab_helper: str = ""
    lab_session: str = ""
    fixture: str = ""
    quota_axi: str = "quota-axi"


class Source:
    def __init__(self, config, runner):
        self.config, self.runner = config, runner
        self.current = None  # last complete observation; inventory remains snapshot-owned
        self.quota_cache = []
        self.quota_checked = float("-inf")

    def quotas(self):
        """Read quota-axi without credential renewal; failures clear visible data."""
        now = time.monotonic()
        if now - self.quota_checked < QUOTA_CACHE_TTL:
            return self.quota_cache
        self.quota_checked = now
        try:
            data = self.runner.run([self.config.quota_axi, "--json", "--no-credential-refresh"], 10)
            self.quota_cache = parse_quotas(data, time.time())
        except (ValueError, OSError, RuntimeError, TimeoutError, AttributeError, TypeError):
            self.quota_cache = []
        return self.quota_cache

    def snapshot(self):
        c = self.config
        if c.fixture:
            with open(c.fixture) as handle:
                return validate_snapshot(json.load(handle), c.home)
        env = os.environ.copy()
        # Inherited worker overrides must never redirect the explicit home.
        for key in list(env):
            if key.startswith("FM_"):
                del env[key]
        env.update(FM_HOME=c.home, FM_ROOT_OVERRIDE=c.root)
        data = self.runner.run([str(Path(c.root) / "bin/fm-fleet-snapshot.sh"), "--json"], c.timeout, env)
        return validate_snapshot(data, c.home)

    def argv(self, session, *args):
        c = self.config
        if c.lab_session:
            if session != c.lab_session:
                raise ValueError(tr("Lab verweigert fremde Session"))
            return [c.lab_helper, "run", c.lab_session, *args]
        return [c.herdr, *args, "--session", session]

    def process_runtime(self, pid, cwd, harness, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(tr("Messbudget verbraucht"))
        return self.runner.run([
            sys.executable, str(Path(__file__).with_name("primary_identity.py")),
            "--runtime", str(pid), cwd, harness], min(3, remaining))

    def runtime_selection(self, task, foreground, session, pane, found, socket, deadline):
        """Read only exact pane PIDs and accept an environment bound to this task."""
        matches = []
        for process in foreground[:8]:
            pid, cwd = process.get("pid"), process.get("cwd")
            if (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1
                    or not isinstance(cwd, str) or not cwd):
                continue
            try:
                result = self.process_runtime(pid, cwd, task.get("harness", ""), deadline)
                env = result.get("environment", {})
                runtime = result.get("runtime", {})
                expected_session = env.get("HERDR_SESSION")
                if session == "default" and "HERDR_SESSION" not in env:
                    expected_session = "default"
                if (env.get("FM_TASK_ID") == task["id"] and env.get("HERDR_ENV") == "1"
                        and expected_session == session and env.get("HERDR_SOCKET_PATH") == socket
                        and env.get("HERDR_PANE_ID") == pane
                        and env.get("HERDR_WORKSPACE_ID") == found.get("workspace_id")
                        and env.get("HERDR_TAB_ID") == found.get("tab_id")
                        and isinstance(runtime, dict)):
                    started = process_start(result.get("process", {}).get("start"))
                    matches.append((clean(runtime.get("model")), clean(runtime.get("effort")), started))
            except (ValueError, OSError, RuntimeError, TimeoutError, AttributeError, TypeError):
                continue
        return matches[0] if len(matches) == 1 else ("", "", 0)

    def probe(self, task, deadline, parallel=False):
        try:
            session, pane = endpoint(task)
            def call(*args):
                remaining = deadline - time.monotonic()
                if self.runner.stop.is_set():
                    raise RuntimeError(tr("abgebrochen"))
                if remaining <= 0:
                    raise TimeoutError(tr("Messbudget verbraucht"))
                return self.runner.run(self.argv(session, *args), min(3, remaining))
            # Focus has its own bounded readers; collector probes remain serial
            # inside their existing four-worker pool. These reads depend only on
            # the selected endpoint, not on one another's results.
            commands = (("status", "--json"), ("pane", "get", pane),
                        ("agent", "get", pane), ("pane", "process-info", "--pane", pane))
            if parallel:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    replies = iter(pool.map(lambda args: call(*args), commands))
            else:
                replies = (call(*args) for args in commands)
            status = next(replies)
            if not session_confirmed(status, session):
                raise ValueError(tr("Session/Protokoll nicht bestätigt"))
            socket = status["server"]["socket"]
            info = next(replies).get("result", {})
            found = info.get("pane", {})
            if info.get("type") != "pane_info" or found.get("pane_id") != pane:
                raise ValueError(tr("Pane-Identität nicht bestätigt"))
            agent_info = next(replies).get("result", {})
            agent = agent_info.get("agent", {})
            expected = task.get("harness")
            if (agent_info.get("type") != "agent_info" or not expected
                    or agent.get("agent") != expected or agent.get("pane_id") != pane
                    or any(not found.get(k) or agent.get(k) != found.get(k) for k in ("tab_id", "workspace_id", "terminal_id"))):
                raise ValueError(tr("Provider/Endpunkt nicht bestätigt"))
            process_result = next(replies).get("result", {})
            process = process_result.get("process_info", {})
            foreground = process.get("foreground_processes", [])
            if (process_result.get("type") != "pane_process_info" or process.get("pane_id") != pane
                    or not isinstance(foreground, list) or not foreground
                    or not all(isinstance(p, dict) and p.get("name") for p in foreground)
                    or all(Path(p["name"]).name.lstrip("-") in SHELLS for p in foreground)):
                raise ValueError(tr("Prozessbeleg fehlt / Shell-only (Registrierung eventuell veraltet)"))
            # Focus uses this probe too; runtime display metadata must not extend
            # its latency-sensitive read path.
            model, effort, started = (("", "", 0) if parallel else
                                      self.runtime_selection(task, foreground, session, pane, found, socket, deadline))
            raw = agent.get("agent_status")
            state = {"working": "working", "idle": "idle", "blocked": "waiting", "done": "done"}.get(raw, "unknown")
            physical = tuple(found[k] for k in ("workspace_id", "tab_id", "terminal_id"))
            detail = (tr("Herdr native: done · bereit für Eingabe, ungesehen") if raw == "done"
                      else tr("Native Aktivität unbekannt · Herdr-Registrierung prüfen") if state == "unknown"
                      else tr("Herdr native: ") + clean(raw))
            # The exact process is both the confirmed agent session and this
            # immutable FM_TASK_ID/spawn binding. No snapshot observation time is
            # treated as a start time.
            return Native(state, detail, time.time(), identity(task), physical, model, effort,
                          started, started)
        except (ValueError, OSError, RuntimeError, TimeoutError, AttributeError, TypeError) as error:
            reason = clean(str(error)) if isinstance(error, ValueError) else tr("Quelle nicht lesbar · Firstmate-/Herdr-Zugriff prüfen")
            return Native(detail=reason, observed=time.time(), binding=identity(task))

    def primary(self, deadline, include_runtime=True):
        """Only the explicit home's current lock owner can supply a candidate."""
        try:
            def run(argv):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(tr("Firstmate-Messbudget verbraucht"))
                return self.runner.run(argv, min(3, remaining))
            reader = [sys.executable, str(Path(__file__).with_name("primary_identity.py")),
                      self.config.home, self.config.root]
            owner = run(reader)
            if owner.get("unavailable"):
                # This diagnostic comes from our own reader, not a tool payload.
                raise ValueError(tr(owner["unavailable"]))
            if owner.get("home") != self.config.home:
                raise ValueError(tr("Owner gehört anderem Home"))
            env = owner["environment"]
            socket = env.get("HERDR_SOCKET_PATH")
            session = env.get("HERDR_SESSION")
            if "HERDR_SESSION" not in env:
                # Herdr omits this variable in its reserved default session.
                # Only the selected owner's canonical socket can establish it.
                if socket != str(Path.home() / ".config/herdr/herdr.sock"):
                    raise ValueError(tr("Owner-Session nicht bestätigt"))
                session = "default"
            if env.get("HERDR_ENV") != "1":
                raise ValueError(tr("Owner läuft nicht bestätigt in Herdr"))
            session, pane = parse_endpoint(session + ":" + env.get("HERDR_PANE_ID", ""))
            def call(*args):
                return run(self.argv(session, *args))
            status = call("status", "--json")
            if not session_confirmed(status, session) or status["server"]["socket"] != socket:
                raise ValueError(tr("Owner-Session/Socket nicht bestätigt"))
            info = call("pane", "get", pane).get("result", {})
            agent_info = call("agent", "get", pane).get("result", {})
            found, agent = info.get("pane", {}), agent_info.get("agent", {})
            physical = tuple(found.get(k) for k in ("workspace_id", "tab_id", "terminal_id"))
            if (info.get("type") != "pane_info" or agent_info.get("type") != "agent_info"
                    or found.get("pane_id") != pane or agent.get("pane_id") != pane
                    or not all(isinstance(k, str) and k for k in physical)
                    or physical != tuple(agent.get(k) for k in ("workspace_id", "tab_id", "terminal_id"))
                    or env.get("HERDR_WORKSPACE_ID") != physical[0] or env.get("HERDR_TAB_ID") != physical[1]
                    or not isinstance(agent.get("agent"), str) or not agent["agent"]):
                raise ValueError(tr("Owner-Endpunkt/Registrierung nicht bestätigt"))
            process = call("pane", "process-info", "--pane", pane).get("result", {})
            details = process.get("process_info", {})
            foreground = details.get("foreground_processes", [])
            shell = details.get("shell_pid")
            if (process.get("type") != "pane_process_info" or details.get("pane_id") != pane
                    or not isinstance(foreground, list)
                    or not isinstance(shell, int) or isinstance(shell, bool) or shell <= 1):
                raise ValueError(tr("Native Owner-Shell nicht bestätigt"))
            # The reader rechecks lock, process generation, selected environment,
            # and every ancestor. A live registration alone cannot prove ownership.
            if run(reader + [str(shell)]) != owner:
                raise ValueError(tr("Owner/Abstammung während Prüfung geändert oder unbestätigt"))
            check = call("pane", "get", pane).get("result", {})
            exact = check.get("pane", {})
            if (check.get("type") != "pane_info" or exact.get("pane_id") != pane
                    or tuple(exact.get(k) for k in ("workspace_id", "tab_id", "terminal_id")) != physical):
                raise ValueError(tr("Physischer Owner-Endpunkt während Prüfung geändert"))
            owner_identity = {key: value for key, value in owner.items() if key != "runtime"}
            key = (PRIMARY, json.dumps(owner_identity, sort_keys=True), agent["agent"], physical)
            raw = agent.get("agent_status")
            state = {"working": "working", "blocked": "waiting", "idle": "idle", "done": "done"}.get(raw, "unknown")
            reason = (tr("Herdr native: done · bereit für Eingabe, ungesehen") if raw == "done"
                      else tr("Native Aktivität unbekannt · Herdr-Registrierung prüfen") if state == "unknown"
                      else tr("Primärer Chat · Enter wechselt"))
            runtime = {}
            owner_pid = owner.get("process", {}).get("pid")
            exact_processes = [p for p in foreground if isinstance(p, dict) and p.get("pid") == owner_pid
                               and isinstance(p.get("cwd"), str) and p["cwd"]]
            if include_runtime and len(exact_processes) == 1:
                try:
                    runtime = self.process_runtime(owner_pid, exact_processes[0]["cwd"], agent["agent"], deadline).get("runtime", {})
                except (ValueError, OSError, RuntimeError, TimeoutError, AttributeError, TypeError):
                    runtime = {}
            started = process_start(owner.get("process", {}).get("start"))
            return PrimaryRow(key, state, reason, time.time(),
                              agent["agent"], session, pane, physical,
                              clean(runtime.get("model")), clean(runtime.get("effort")), started)
        except (ValueError, OSError, RuntimeError, TimeoutError, AttributeError, TypeError, KeyError) as error:
            reason = clean(str(error)) if isinstance(error, ValueError) else tr("Quelle nicht lesbar · Owner-/Herdr-Zugriff prüfen")
            return PrimaryRow(reason=tr("Firstmate nicht verfügbar: ") + reason, observed=time.time())

    def primary_target(self, selected):
        current = self.primary(time.monotonic() + 12, include_runtime=False)
        if not current.physical or current.key != selected:
            raise ValueError(tr("Fokus verweigert: Firstmate entfernt/ersetzt/unbestätigt · ") + current.reason)
        return current.provider, "Firstmate", current, current.session, current.pane

    def collect(self):
        snapshot = self.snapshot()
        deadline = time.monotonic() + 12
        with ThreadPoolExecutor(max_workers=4) as pool:
            primary = pool.submit(self.primary, deadline)
            values = list(pool.map(lambda task: self.probe(task, deadline), snapshot["tasks"]))
        natives = dict(zip((t["id"] for t in snapshot["tasks"]), values))
        natives[PRIMARY] = primary.result()
        observation = snapshot, natives
        self.current = observation
        return observation

    def focus_snapshot(self, selected):
        # The lab fixture is its explicit ownership authority. Ordinary Enter
        # reuses ONLY inventory, not an old ownership or native confirmation.
        if self.config.fixture or self.current is None:
            return self.snapshot()
        snapshot = self.current[0]
        task = next((t for t in snapshot["tasks"] if identity(t) == selected), None)
        if task is None:
            raise ValueError(tr("Fokus verweigert: Worker entfernt/ersetzt"))
        try:
            self.check_owner(task)
        except OSError as error:
            raise ValueError(tr("Fokus verweigert: Metadaten nicht lesbar / entfernt")) from error
        return snapshot

    def check_owner(self, task):
        """Bounded read of exactly the snapshot-owned local metadata, no scan.

        Firstmate fm-backend.sh: fm_meta_get takes the LAST key=value;
        Herdr backend identity is backend/window, spawn_gen, harness and no
        remote_host. Never evaluate metadata as shell or parse task status.
        """
        task_id = task["id"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id):
            raise ValueError(tr("Fokus verweigert: ungültige Metadatenidentität"))
        expected = Path(self.config.home) / "state" / (task_id + ".meta")
        metadata = task.get("paths", {}).get("meta", {})
        if (not isinstance(metadata, dict) or metadata.get("present") is not True
                or metadata.get("path") != str(expected)
                or expected.resolve() != expected):
            raise ValueError(tr("Fokus verweigert: Metadaten nicht an dieses Home gebunden"))
        fd = os.open(expected, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > 65536:
                raise ValueError(tr("Fokus verweigert: Metadaten nicht begrenzt lesbar"))
            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(65537)
            after = os.fstat(fd)
            current = os.stat(expected, follow_symlinks=False)
            stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if len(data) > 65536 or stamp(before) != stamp(after) or stamp(after) != stamp(current):
                raise ValueError(tr("Fokus verweigert: Metadaten während Prüfung ersetzt"))
        finally:
            os.close(fd)
        # Binary metadata is not a supported producer contract; Bash versions
        # can handle NUL differently from Python. Do not guess its identity.
        if b"\0" in data:
            raise ValueError(tr("Fokus verweigert: binäre Metadaten"))
        fields = {}
        for line in data.decode("utf-8").split("\n"):
            key, sep, value = line.partition("=")
            if sep and key in {"spawn_gen", "backend", "window", "harness", "remote_host"}:
                fields[key] = value
        if (fields.get("spawn_gen") != task.get("spawn_gen")
                or fields.get("backend", "tmux") != "herdr"
                or fields.get("window") != task.get("endpoint", {}).get("target")
                or fields.get("harness") != task.get("harness")
                or fields.get("remote_host")):
            raise ValueError(tr("Fokus verweigert: Worker entfernt/ersetzt oder fremd"))

    def focus_target(self, selected):
        snapshot = self.focus_snapshot(selected)
        now = time.time()
        generated = epoch(snapshot.get("generated"))
        if generated is None or not -2 <= now - generated <= self.config.ttl:
            raise ValueError(tr("Fokus verweigert: Snapshot veraltet"))
        matches = [task for task in snapshot["tasks"] if identity(task) == selected]
        if len(matches) != 1 or not selected[1]:
            raise ValueError(tr("Fokus verweigert: Worker entfernt/ersetzt oder Generation fehlt"))
        task = matches[0]
        if task.get("endpoint", {}).get("exists") is not True or not fresh(task["endpoint"], now, self.config.ttl):
            raise ValueError(tr("Fokus verweigert: Endpunkt nicht frisch bestätigt"))
        native = self.probe(task, time.monotonic() + 12, parallel=True)
        if not native.physical:
            raise ValueError(tr("Fokus verweigert: ") + native.detail)
        # Recheck ownership after the native reads, not only before them.
        latest = self.focus_snapshot(selected)
        latest_time = epoch(latest.get("generated"))
        latest_matches = [t for t in latest["tasks"] if identity(t) == selected]
        if (latest_time is None or not -2 <= time.time() - latest_time <= self.config.ttl
                or len(latest_matches) != 1 or time.time() - native.observed > self.config.ttl
                or latest_matches[0].get("endpoint", {}).get("exists") is not True
                or not fresh(latest_matches[0]["endpoint"], time.time(), self.config.ttl)):
            raise ValueError(tr("Fokus verweigert: Auswahl während der Prüfung geändert/veraltet"))
        session, pane = endpoint(task)
        check = self.runner.run(self.argv(session, "pane", "get", pane), 3).get("result", {})
        exact = check.get("pane", {})
        if (check.get("type") != "pane_info" or exact.get("pane_id") != pane
                or tuple(exact.get(k) for k in ("workspace_id", "tab_id", "terminal_id")) != native.physical):
            raise ValueError(tr("Fokus verweigert: physischer Endpunkt geändert"))
        return task.get("harness"), task["id"], native, session, pane

    def focus(self, selected, physical=()):
        # Primary input never fetches the fleet: only this owner/endpoint is read.
        target = self.primary_target if selected and selected[0] == PRIMARY else self.focus_target
        provider, label, native, session, pane = target(selected)
        if physical and native.physical != physical:
            raise ValueError(tr("Fokus verweigert: ausgewählter physischer Endpunkt ersetzt"))
        response = self.runner.run(self.argv(session, "agent", "focus", pane), 3)
        result = response.get("result", {})
        focused = result.get("agent", {})
        if (result.get("type") != "agent_info" or focused.get("pane_id") != pane
                or focused.get("agent") != provider or focused.get("focused") is not True
                or tuple(focused.get(k) for k in ("workspace_id", "tab_id", "terminal_id")) != native.physical):
            raise ValueError(tr("Fokusanfrage gesendet, Bestätigung unklar"))
        try:
            # AgentFocus does not project independent client tab views. Revalidate
            # every guard before the second mutation, including physical identity.
            _, _, current, _, _ = target(selected)
            if current.physical != native.physical:
                raise ValueError(tr("physischer Endpunkt geändert"))
            projection = self.runner.run(self.argv(session, "tab", "focus", current.physical[1]), 3).get("result", {})
            tab = projection.get("tab", {})
            if (projection.get("type") != "tab_info" or tab.get("focused") is not True
                    or (tab.get("workspace_id"), tab.get("tab_id")) != native.physical[:2]):
                raise ValueError(tr("Tab-Fokusantwort unklar"))
            _, _, final, _, _ = target(selected)
            if final.physical != native.physical:
                raise ValueError(tr("physischer Endpunkt geändert"))
            confirmation = self.runner.run(self.argv(session, "agent", "get", pane), 3).get("result", {})
            agent = confirmation.get("agent", {})
            if (confirmation.get("type") != "agent_info" or agent.get("focused") is not True
                    or agent.get("pane_id") != pane or agent.get("agent") != provider
                    or tuple(agent.get(k) for k in ("workspace_id", "tab_id", "terminal_id")) != native.physical):
                raise ValueError(tr("abschließender Agent-Fokus unklar"))
        except (ValueError, OSError, RuntimeError, TimeoutError, AttributeError, TypeError) as error:
            raise ValueError(tr("Agent-Fokus bestätigt; Tab-Wechsel nicht bestätigt: ") + clean(str(error))) from error
        return tr("Agent-/Tab-Fokus serverseitig bestätigt: ") + label


class Poller:
    """One collector and one explicit-focus worker; refresh cannot drop Enter."""
    def __init__(self, source, interval):
        self.source, self.interval = source, interval
        self.results = queue.Queue()
        self.jobs = queue.Queue(maxsize=1)
        self.stop = source.runner.stop
        self.busy = threading.Event()
        self.refresh = threading.Event()
        self.refresh_lock = threading.Lock()
        self.thread = threading.Thread(target=self.work, daemon=True)
        self.focusing = threading.Event()
        self.focus_lock = threading.Lock()
        self.focus_thread = threading.Thread(target=self.focus_work, daemon=True)

    def start(self):
        self.thread.start()
        self.focus_thread.start()

    def request_refresh(self):
        # A running collection already rereads all authoritative sources.
        with self.refresh_lock:
            if self.busy.is_set() or self.refresh.is_set() or self.stop.is_set():
                return False
            self.refresh.set()
            return True

    def request_focus(self, key, physical=()):
        with self.focus_lock:
            if self.focusing.is_set() or self.stop.is_set():
                return False
            self.focusing.set()
            self.jobs.put_nowait((key, physical))
            return True

    def focus_work(self):
        while not self.stop.is_set():
            try:
                key, physical = self.jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.results.put(("focus", self.source.focus(key, physical)))
            except Exception as error:
                self.results.put(("focus-error", clean(str(error))))
            finally:
                self.focusing.clear()

    def work(self):
        while not self.stop.is_set():
            with self.refresh_lock:
                self.busy.set()
                self.refresh.clear()
            try:
                self.results.put(("snapshot", self.source.collect()))
            except Exception as error:
                self.results.put(("error", clean(str(error))))
            finally:
                # Quota is supplemental and must not extend the fleet's busy state.
                self.busy.clear()
            try:
                quota_reader = getattr(self.source, "quotas", None)
                if quota_reader is not None:
                    self.results.put(("quota", quota_reader()))
            except Exception:
                self.results.put(("quota", []))
            self.refresh.wait(self.interval)

    def close(self):
        self.stop.set()
        self.refresh.set()
        self.thread.join(timeout=4)
        self.focus_thread.join(timeout=4)


class UnknownRetry:
    """Bounded retry signal; ordinary polling uses the very same discovery path."""
    threshold = 30
    cooldown = 60

    def __init__(self):
        self.since = {}
        self.last = float("-inf")

    def due(self, rows, now):
        self.since = {row.key: self.since.get(row.key, now)
                      for row in rows if row.live == "unknown"}
        if (any(now - start >= self.threshold for start in self.since.values())
                and now - self.last >= self.cooldown):
            self.last = now
            return True
        return False


@dataclass
class View:
    snapshot: dict = field(default_factory=dict)
    natives: dict = field(default_factory=dict)
    last_success: float = 0
    error: str = ""
    message: str = ""
    selected: tuple = ()
    offset: int = 0
    selected_physical: tuple = ()
    quotas: list = field(default_factory=list)
    task_times: dict = field(default_factory=dict)

    def retain_task_times(self, rows, now):
        """Keep the last confirmed active interval for a terminal worker row."""
        keys = {row.key for row in rows}
        self.task_times = {key: timing for key, timing in self.task_times.items() if key in keys}
        for row in rows:
            if row.outcome in ACTIVE_OUTCOMES:
                confirmed_end = self.natives.get(row.task["id"], Native()).observed
                if (row.task_started and isinstance(confirmed_end, (int, float))
                        and not isinstance(confirmed_end, bool) and math.isfinite(confirmed_end)
                        and row.task_started - 2 <= confirmed_end <= now + 2):
                    self.task_times[row.key] = (row.task_started, confirmed_end)
            elif row.outcome in TERMINAL_OUTCOMES:
                timing = self.task_times.get(row.key)
                if timing:
                    row.task_started, row.task_ended = timing

    def apply(self, kind, payload):
        if kind == "snapshot":
            self.snapshot, self.natives = payload
            if self.selected:
                physical = self.natives.get(self.selected[0], Native()).physical
                if self.selected_physical and physical and physical != self.selected_physical:
                    self.selected = ("reselect-after-physical-change", self.selected)
                    self.message = tr("Zielidentität geändert · bitte erneut wählen")
            self.last_success, self.error = time.time(), ""
        elif kind == "error":
            self.error = payload
        elif kind == "quota":
            self.quotas = payload
        else:
            self.message = payload

    def selection(self, rows, movement=0):
        keys = [row.key for row in rows]
        if not keys:
            return -1
        if self.selected not in keys:
            # Never silently retarget a removed/replaced selection.
            if self.selected and movement == 0:
                return -1
            index = 0
        else:
            index = keys.index(self.selected)
        index = max(0, min(len(keys) - 1, index + movement))
        if self.selected != keys[index]:
            self.selected_physical = ()
        self.selected = keys[index]
        physical = self.natives.get(self.selected[0], Native()).physical
        if physical:
            self.selected_physical = physical
        return index


def cells(text):
    return sum(0 if unicodedata.combining(c) else (2 if unicodedata.east_asian_width(c) in "WF" else 1)
               for c in text)


def column(text, width):
    clipped = fit(text, width)
    return clipped + " " * max(0, width - cells(clipped))


def styled(*segments):
    """A line plus cell-positioned colored spans; no ANSI or text interpretation."""
    text, spans, x = "", [], 0
    for value, color in segments:
        spans.append((x, value, color))
        text += value
        x += cells(value)
    return text, tuple(spans)


def quota_segments(quotas, now, compact=False, tiny=False):
    """Render fresh quota evidence with a bounded bar and threshold color."""
    values = [quota for quota in quotas if 0 <= now - quota.observed <= QUOTA_DISPLAY_TTL]
    segments = []
    for index, quota in enumerate(values):
        if index:
            segments.append((" " if compact else " · ", 7))
        label = quota.provider[:1].upper() if tiny else (quota.provider[:3].title() if compact else quota.provider.title())
        bar_width = 2 if tiny else (4 if compact else 10)
        filled = int(round(quota.percent * bar_width / 100))
        bar = "█" * filled + "░" * (bar_width - filled)
        color = 4 if quota.percent >= 50 else (5 if quota.percent <= 10 else 1)
        segments.extend(((label + " ", 7), (f"{bar} {quota.percent}%", color)))
    return segments


def render_lines(view, rows, width, height, busy, now):
    """Reference-like terminal content: count blocks, hierarchy, compact rows."""
    blank = styled(("", 0))
    if height < 16 or width < 28:
        return [(fit(text, max(0, width - 1)), spans) for text, spans in [
            styled((tr("TShepherd — Terminal zu klein"), 5)),
            styled((tr("Mind. 28 Spalten / 16 Zeilen; q beendet"), 7))][:height]]
    primary = next((row for row in rows if isinstance(row, PrimaryRow)), None)
    rows = [row for row in rows if not isinstance(row, PrimaryRow)]
    count = counters(rows)
    total = str(len(rows)) if view.last_success else "?"
    age = f"{max(0, now - view.last_success):.0f}s" if view.last_success else tr("nie")
    wide = width >= 78
    lines = [blank]
    labels = ("Worker",) + STATES
    quota_parts = quota_segments(view.quotas, now, compact=width < 100)
    for i, label in enumerate(labels):
        value = total if i == 0 else (str(count[label]) if view.last_success else "?")
        if wide:
            brand = ("TShepherd", tr("Firstmate fleet"), tr("Live · lokal"), tr("Quota"), "", "")[i]
            prefix = "  " + column(brand, 22)
        else:
            prefix = "  "
        segments = [(prefix, 6 if i == 0 else 7), (f" {value:>3} ", 11 + i), (" " + column(tr(label), 10), 7)]
        if wide and i == 0:
            segments += [(tr("   letzter Erfolg {age}", age=age), 7)]
        if wide and i == 1:
            segments += [("   " + (tr("aktualisiert …") if busy else tr("automatische Aktualisierung")), 7)]
        if wide and i == 2:
            segments += [(tr("   nur dieses Home; keine Unterhomes"), 7)]
        if wide and i == 3:
            segments += [("   ", 0)] + (quota_parts or [("—", 7)])
        if wide and i == 4:
            segments += [(tr("   Aufgabe done; überlappt mit Live"), 7)]
        if wide and i == 5:
            segments += [(tr("   Messung fehlt / nicht bestätigt"), 7)]
        lines.append(styled(*segments))
    if not wide:
        lines[0] = styled(("  TShepherd · " + tr("Live · lokal"), 6),
                          (tr("  ·  Erfolg {age}", age=age) + (tr(" · lädt") if busy else ""), 7))
        available = max(0, width - cells("  " + tr("Quota") + " ") - 1)
        tiny = available < 30
        parts = quota_segments(view.quotas, now, compact=True, tiny=tiny) or [("—", 7)]
        lines.insert(1, styled(("  " + ("Q" if tiny else tr("Quota")) + " ", 7), *parts))
    if wide:
        lines.append(blank)
    if primary is not None:
        mark = ">" if primary.key == view.selected else " "
        status = tr(primary.live) if primary.physical else tr("nicht verfügbar")
        color = LIVE_STATES.index(primary.live) + 1
        model = compact_model(primary.model, primary.effort) if primary.physical else compact_model("", "")
        if wide:
            lines.append(styled((f"    {mark} ◆ Firstmate", color),
                                ("  " + primary.provider + " · " + model + " · ", 7), (status, color),
                                (" · " + primary.reason, 7)))
        else:
            lines.append(styled((f"    {mark} ◆ Firstmate", color)))
            lines.append(styled(("       " + model + " · " + status, color)))
        if wide or height - len(lines) - 4 > 2:
            lines.append(blank)
    title_width = min(36, max(18, width // 4))
    time_width = 4
    prefix_width = 7 + title_width + 2 + 7 + 2 + MODEL_COLUMN_WIDTH + 2 + 7 + 2 + 8 + 2 + time_width + 2
    if wide:
        lines.append(styled(("  #    " + column("Worker", title_width) + "  " + column("Agent", 7)
                             + "  " + column(tr("Model"), MODEL_COLUMN_WIDTH) + "  " + column("Live", 7)
                             + "  " + column(tr("Aufgabe"), 8) + "  " + column(tr("Zeit"), time_width)
                             + tr("  Letzte bekannte Aktivität"), 7)))
    body, project, chosen, chosen_end = [], None, None, None
    group_number = 0
    for number, row in enumerate(rows, 1):
        if row.project != project:
            if project is not None:
                body.append(blank)
            project = row.project
            group_size = sum(r.project == project for r in rows)
            body.append(styled(("  " + project, 8 + group_number % 3), (f" · {group_size}", 7)))
            group_number += 1
        if row.key == view.selected:
            chosen = len(body)
        state_color = LIVE_STATES.index(row.live) + 1
        glyph = {"working": "●", "waiting": "!", "idle": "○", "done": "✓", "unknown": "?"}[row.live]
        mark = ">" if row.key == view.selected else " "
        lead = [(f"{number:>3} {mark}", 7), (glyph + " ", state_color)]
        if wide:
            activity = row.reason + " · " + row.activity if row.reason else row.activity
            body.append(styled(*lead, (column(row.title, title_width), state_color), ("  ", 0),
                               (column(clean(row.task.get("harness")), 7), 9), ("  ", 0),
                               (column(row.model, MODEL_COLUMN_WIDTH), 7), ("  ", 0),
                               (column(tr(row.live), 7), state_color), ("  ", 0),
                               (column(row.outcome, 8), 4 if row.outcome == "done" else 7), ("  ", 0),
                               (column(compact_duration(row.task_started, now, row.task_ended), time_width), 7), ("  ", 0),
                               (fit(activity, width - prefix_width - 1), 7)))
        else:
            body.append(styled(*lead, (row.title, state_color)))
            body.append(styled((tr("       {model} · {duration} · {live} · Aufgabe {outcome} · ",
                                   model=row.model, duration=compact_duration(row.task_started, now, row.task_ended),
                                   live=tr(row.live), outcome=row.outcome), state_color),
                               (row.activity, 7)))
        if row.key == view.selected:
            chosen_end = len(body) - 1
    if not rows:
        body = [styled((tr("  Keine Worker gemessen") if not view.last_success else tr("  Keine Worker im Snapshot"), 7))]
    available = max(1, height - len(lines) - 4)
    if chosen is not None:
        if chosen < view.offset:
            view.offset = chosen
        elif chosen_end >= view.offset + available:
            view.offset = max(0, chosen_end + 1 - available)
    view.offset = max(0, min(view.offset, max(0, len(body) - available)))
    lines.extend(body[view.offset:view.offset + available])
    lines.extend([blank] * max(0, height - 4 - len(lines)))
    selected = next((row for row in rows if row.key == view.selected), None)
    warning = view.error or view.message
    inventory = view.snapshot.get("main_inventory", {})
    if inventory.get("valid") is False:
        warning = tr("Inventar unvollständig: ") + clean(inventory.get("reason")) + (" | " + warning if warning else "")
    if primary is not None and primary.key == view.selected:
        detail = warning or primary.reason
        warning = tr("Session {session} · ", session=compact_duration(primary.session_started, now)) + detail
    elif selected:
        detail = warning or f"{selected.task['id']} · {selected.reason or selected.activity}"
        warning = tr("Session {session} · Aufgabe {task} · ",
                     session=compact_duration(selected.session_started, now),
                     task=compact_duration(selected.task_started, now, selected.task_ended)) + detail
    lines.append(styled(("  " + "─" * (width - 5), 7)))
    lines.append(styled(("  " + (warning or tr("Nur eigenes FM_HOME; Secondmate-Kinder nicht rekursiv")), 5 if view.error else 7)))
    lines.append(styled((tr("  ● working  ! waiting=blocked  ○ idle  ✓ done  ? unknown"), 7),
                        (tr("   completed=Aufgabe done"), 4)))
    keys = tr("  ↑/↓ j/k wählen · Enter Fokus · R neu erkennen · q / Ctrl+C") if wide else tr("  j/k · Enter · R neu · q")
    lines.append(styled((keys, 7)))
    return [(fit(text, width - 1), spans) for text, spans in lines[:height]]


def tui(screen, source):
    curses.curs_set(0)
    screen.timeout(80)
    screen.keypad(True)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        foregrounds = (curses.COLOR_YELLOW, curses.COLOR_MAGENTA, curses.COLOR_CYAN,
                       curses.COLOR_GREEN, curses.COLOR_RED, curses.COLOR_WHITE,
                       curses.COLOR_WHITE, curses.COLOR_GREEN, curses.COLOR_CYAN, curses.COLOR_YELLOW)
        for i, color in enumerate(foregrounds, 1):
            curses.init_pair(i, color, -1)
        for i, background in enumerate((curses.COLOR_WHITE, curses.COLOR_YELLOW, curses.COLOR_MAGENTA,
                                        curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_RED), 11):
            curses.init_pair(i, curses.COLOR_BLACK, background)
    view = View()
    poller = Poller(source, source.config.interval)
    poller.start()
    retry = UnknownRetry()
    try:
        while True:
            while not poller.results.empty():
                view.apply(*poller.results.get_nowait())
            now = time.time()
            rows = overview_rows(view, now, source.config.ttl)
            if retry.due(rows, time.monotonic()):
                poller.request_refresh()
            if view.last_success:
                view.selection(rows)
            height, width = screen.getmaxyx()
            screen.erase()
            for y, (text, spans) in enumerate(render_lines(view, rows, width, height, poller.busy.is_set(), now)):
                try:
                    screen.addstr(y, 0, text)
                    for x, segment, role in spans:
                        if x >= width - 1:
                            continue
                        style = curses.color_pair(role) if curses.has_colors() else 0
                        if role == 7:
                            style |= curses.A_DIM
                        elif role >= 6 or role == 4:
                            style |= curses.A_BOLD
                        screen.addstr(y, x, fit(segment, width - x - 1), style)
                except curses.error:
                    pass  # Last-cell/resize races are harmless; next frame redraws.
            screen.refresh()
            key = screen.getch()
            if key in (ord("q"), 3):
                break
            if key in (curses.KEY_UP, ord("k")):
                view.selection(rows, -1)
            elif key in (curses.KEY_DOWN, ord("j")):
                view.selection(rows, 1)
            elif key == ord("R"):
                view.message = (tr("Neuerkennung angefordert · nur lesen") if poller.request_refresh()
                                else tr("Neuerkennung läuft bereits · nur lesen"))
            elif key in (10, 13, curses.KEY_ENTER):
                if not view.selected or view.selected not in [row.key for row in rows] or view.error:
                    view.message = tr("Keine gültige Auswahl / Quelle nicht erreichbar")
                elif poller.request_focus(view.selected, view.selected_physical):
                    view.message = tr("Prüfe Auswahl vor Fokus …")
                else:
                    view.message = tr("Fokusprüfung läuft bereits")
    finally:
        poller.close()


def parse_args(argv=None):
    # Select explicitly before help/errors or worker threads. No locale detection.
    selector = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    selector.add_argument("--lang", choices=("en", "de"), default="en")
    selected, _ = selector.parse_known_args(argv)
    set_language(selected.lang)
    # argparse's own templates are translated only while parsing our CLI;
    # restore its gettext hook even on --help or errors (SystemExit).
    original_gettext = argparse._
    argparse._ = tr
    try:
        parser = argparse.ArgumentParser(
            description=tr("TShepherd: a terminal dashboard for Firstmate."), allow_abbrev=False)
        parser.add_argument("--lang", choices=("en", "de"), default="en", help=tr("UI language (default: en)"))
        parser.add_argument("--fm-home", default=os.environ.get("TSHEPHERD_FM_HOME"), help=tr("Firstmate data directory"))
        parser.add_argument("--firstmate-root", default=os.environ.get("TSHEPHERD_FIRSTMATE_ROOT"), help=tr("Firstmate source checkout"))
        parser.add_argument("--herdr", default="herdr", help=tr("Pfad zum kompatiblen Herdr-CLI"))
        parser.add_argument("--quota-axi", default="quota-axi", help=tr("Pfad zum lokalen quota-axi-CLI"))
        parser.add_argument("--lab-helper", default="", help=tr("isolated lab helper"))
        parser.add_argument("--lab-session", default="", help=tr("isolated non-default lab session"))
        parser.add_argument("--lab-snapshot", default="", help=tr("nur im isolierten Lab: JSON statt Firstmate-Aufruf"))
        args = parser.parse_args(argv)
        if not args.fm_home or not args.firstmate_root:
            parser.error(tr("--fm-home und --firstmate-root explizit angeben (oder TSHEPHERD_* setzen)"))
        if bool(args.lab_helper) != bool(args.lab_session) or (args.lab_session and not re.fullmatch(r"fm-lab-[A-Za-z0-9][A-Za-z0-9_-]*", args.lab_session)):
            parser.error(tr("Lab braucht Helper und eine nicht-default fm-lab-* Session"))
        if args.lab_snapshot and not args.lab_session:
            parser.error(tr("--lab-snapshot nur mit --lab-helper und --lab-session"))
        return args, parser
    finally:
        argparse._ = original_gettext


def main():
    args, parser = parse_args()
    config = Config(str(Path(args.fm_home).resolve()), str(Path(args.firstmate_root).resolve()),
                    herdr=args.herdr, quota_axi=args.quota_axi, lab_helper=args.lab_helper,
                    lab_session=args.lab_session, fixture=args.lab_snapshot)
    source = Source(config, Runner(threading.Event()))
    try:
        curses.wrapper(tui, source)
    except KeyboardInterrupt:
        pass
    except curses.error as error:
        parser.exit(1, tr("Terminal nicht verfügbar: ") + str(error) + "\n")


if __name__ == "__main__":
    main()
