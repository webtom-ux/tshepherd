"""Bounded read-only home-lock identity reader, invoked by TShepherd.

Firstmate's fm-session-lock-lib.sh owns harness classification and the PID lock.
Darwin proc_pidinfo and Linux /proc supply generation/ancestry; KERN_PROCARGS2
or /proc/<pid>/environ supplies only selected identity fields. A caller-supplied
exact Pi process may read one process-generation-unique structured session file.
Never enumerate processes or emit argv/env. Unsupported/restricted evidence
remains unavailable.
"""
import ctypes as C
import ctypes.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

IDENTITY_KEYS = frozenset(("HERDR_ENV", "HERDR_SESSION", "HERDR_SOCKET_PATH",
                           "HERDR_PANE_ID", "HERDR_TAB_ID", "HERDR_WORKSPACE_ID"))
RUNTIME_KEYS = frozenset(("FM_TASK_ID", "PI_SESSION_FILE", "PI_SESSION_ID"))
KEYS = IDENTITY_KEYS | RUNTIME_KEYS
MAX_SESSION_BYTES = 16 * 1024 * 1024
MAX_SESSION_LINE = 4 * 1024 * 1024


class BSD(C.Structure):
    # macOS SDK sys/proc_info.h: proc_bsdinfo / PROC_PIDTBSDINFO (3).
    _fields_ = ([(n, C.c_uint32) for n in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid",
        "rgid", "svuid", "svgid", "reserved")]
        + [("comm", C.c_char * 16), ("name", C.c_char * 32)]
        + [(n, C.c_uint32) for n in ("nfiles", "pgid", "pjobc", "tdev", "tpgid")]
        + [("nice", C.c_int32), ("start_sec", C.c_uint64), ("start_usec", C.c_uint64)])


def selected_environment_entries(entries):
    """Parse NUL-delimited env entries in memory; keep only identity fields."""
    result = {}
    allowed = {k.encode("ascii") for k in KEYS}
    for entry in entries:
        key, sep, value = entry.partition(b"=")
        if key in allowed and sep:
            name = key.decode("ascii")
            if name in result:
                raise ValueError("mehrdeutige Prozessidentität")
            result[name] = value.decode("utf-8", "strict")
    return result


class _StatxTimestamp(C.Structure):
    _fields_ = (("tv_sec", C.c_int64), ("tv_nsec", C.c_uint32), ("__reserved", C.c_int32))


class _Statx(C.Structure):
    # linux/stat.h: only stx_mask and stx_btime are read.
    _fields_ = (("stx_mask", C.c_uint32), ("stx_blksize", C.c_uint32),
                ("stx_attributes", C.c_uint64), ("stx_nlink", C.c_uint32),
                ("stx_uid", C.c_uint32), ("stx_gid", C.c_uint32),
                ("stx_mode", C.c_uint16), ("__spare0", C.c_uint16),
                ("stx_ino", C.c_uint64), ("stx_size", C.c_uint64),
                ("stx_blocks", C.c_uint64), ("stx_attributes_mask", C.c_uint64),
                ("stx_atime", _StatxTimestamp), ("stx_btime", _StatxTimestamp),
                ("stx_ctime", _StatxTimestamp), ("stx_mtime", _StatxTimestamp),
                ("spare", C.c_uint64 * 16))


def file_birth_ns(path):
    """Birth time of one file; ctime is not a generation substitute."""
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    birth = getattr(info, "st_birthtime", None)
    if isinstance(birth, (int, float)) and birth > 0:
        return int(birth * 10**9)
    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = C.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        libc.statx.argtypes = (C.c_int, C.c_char_p, C.c_int, C.c_uint, C.POINTER(_Statx))
        buf = _Statx()
        # AT_FDCWD, AT_SYMLINK_NOFOLLOW, STATX_BTIME
        if libc.statx(-100, os.fsencode(path), 0x100, 0x800, C.byref(buf)) != 0:
            return None
        if buf.stx_mask & 0x800 == 0 or buf.stx_btime.tv_sec <= 0:
            return None
        return buf.stx_btime.tv_sec * 10**9 + buf.stx_btime.tv_nsec
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def selected_environment(raw):
    """Parse the Darwin OS buffer in memory; discard argv and other fields."""
    argc = int.from_bytes(raw[:4], byteorder=sys.byteorder, signed=True)
    if not 0 < argc < 100000:
        raise ValueError("Prozessargumente unlesbar")
    pos = raw.index(b"\0", 4) + 1  # executable path, then padding
    while pos < len(raw) and raw[pos] == 0:
        pos += 1
    for _ in range(argc):
        pos = raw.index(b"\0", pos) + 1
    return selected_environment_entries(raw[pos:].split(b"\0"))


class Darwin:
    def __init__(self):
        if sys.platform != "darwin":
            raise ValueError("Firstmate-Identität nur auf macOS verifiziert")
        self.lib = C.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        self.lib.proc_pidinfo.argtypes = (C.c_int, C.c_int, C.c_uint64, C.c_void_p, C.c_int)
        self.lib.sysctl.argtypes = (C.POINTER(C.c_int), C.c_uint, C.c_void_p,
                                    C.POINTER(C.c_size_t), C.c_void_p, C.c_size_t)

    def process(self, pid):
        b = BSD()
        n = self.lib.proc_pidinfo(pid, 3, 0, C.byref(b), C.sizeof(b))
        if n != C.sizeof(b) or b.pid != pid or b.uid != os.getuid() or b.status == 5:
            raise ValueError("Owner-Prozess nicht bestätigt")
        return {"pid": b.pid, "ppid": b.ppid, "uid": b.uid,
                "start": b.start_sec * 10**9 + b.start_usec * 1000}

    def environment(self, pid):
        mib = (C.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
        buf = C.create_string_buffer(1024 * 1024)
        size = C.c_size_t(len(buf))
        if self.lib.sysctl(mib, 3, buf, C.byref(size), None, 0) != 0:
            raise ValueError("Owner-Prozessidentität nicht lesbar")
        return selected_environment(buf.raw[:size.value])


class Linux:
    def __init__(self, proc_root="/proc", clock_ticks=None, boot_time_ns=None):
        if not sys.platform.startswith("linux"):
            raise ValueError("Firstmate identity is unsupported on this operating system")
        self.proc_root = Path(proc_root)
        self.clock_ticks = int(clock_ticks or os.sysconf("SC_CLK_TCK"))
        if self.clock_ticks <= 0:
            raise ValueError("Owner-Prozess nicht bestätigt")
        self.boot_time_ns = int(boot_time_ns) if boot_time_ns is not None else self._boot_time_ns()

    def _read_file(self, path, limit=1024 * 1024):
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
            try:
                chunks, total = [], 0
                while total <= limit:
                    chunk = os.read(fd, min(65536, limit + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                if total > limit:
                    raise ValueError("Owner-Prozessidentität nicht lesbar")
                return b"".join(chunks)
            finally:
                os.close(fd)
        except OSError as error:
            raise ValueError("Owner-Prozess nicht bestätigt") from error

    def _boot_time_ns(self):
        for line in self._read_file(self.proc_root / "stat", 1024 * 1024).splitlines():
            key, _, value = line.partition(b" ")
            if key == b"btime" and value.strip().isdigit():
                return int(value.strip()) * 10**9
        raise ValueError("Owner-Prozess nicht bestätigt")

    def _stat_fields(self, pid):
        raw = self._read_file(self.proc_root / str(pid) / "stat", 65536).strip()
        close = raw.rfind(b")")
        if close < 0:
            raise ValueError("Owner-Prozess nicht bestätigt")
        try:
            found_pid = int(raw[:raw.index(b" ")])
        except (ValueError, IndexError):
            raise ValueError("Owner-Prozess nicht bestätigt")
        fields = raw[close + 2:].split()
        if found_pid != pid or len(fields) <= 19:
            raise ValueError("Owner-Prozess nicht bestätigt")
        try:
            ppid = int(fields[1])
            start_ticks = int(fields[19])
        except (ValueError, IndexError):
            raise ValueError("Owner-Prozess nicht bestätigt")
        return fields[0].decode("ascii", "replace"), ppid, start_ticks

    def _status_uid(self, pid):
        state = uid = None
        for line in self._read_file(self.proc_root / str(pid) / "status", 1024 * 1024).splitlines():
            if line.startswith(b"State:"):
                parts = line.split()
                state = parts[1].decode("ascii", "replace") if len(parts) > 1 else ""
            elif line.startswith(b"Uid:"):
                parts = line.split()
                if len(parts) < 2:
                    raise ValueError("Owner-Prozess nicht bestätigt")
                try:
                    uid = int(parts[1])
                except ValueError:
                    raise ValueError("Owner-Prozess nicht bestätigt")
        if uid is None or (state == "Z"):
            raise ValueError("Owner-Prozess nicht bestätigt")
        return uid

    def process(self, pid):
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
            raise ValueError("Owner-Prozess nicht bestätigt")
        state, ppid, start_ticks = self._stat_fields(pid)
        uid = self._status_uid(pid)
        if uid != os.getuid() or state == "Z":
            raise ValueError("Owner-Prozess nicht bestätigt")
        start = self.boot_time_ns + (start_ticks * 10**9) // self.clock_ticks
        return {"pid": pid, "ppid": ppid, "uid": uid, "start": start}

    def environment(self, pid):
        try:
            raw = self._read_file(self.proc_root / str(pid) / "environ", 1024 * 1024)
        except ValueError as error:
            raise ValueError("Owner-Prozessidentität nicht lesbar") from error
        return selected_environment_entries(raw.split(b"\0"))


def system_reader():
    if sys.platform == "darwin":
        return Darwin()
    if sys.platform.startswith("linux"):
        return Linux()
    raise ValueError("Firstmate identity is unsupported on this operating system")


def read_session_selection(path, session_id="", expected_cwd=""):
    """Read one bounded Pi session file and follow only its active ancestry."""
    path = Path(path)
    if not path.is_absolute():
        return {"model": "", "effort": ""}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return {"model": "", "effort": ""}
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_size > MAX_SESSION_BYTES):
            return {"model": "", "effort": ""}
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw_lines = handle.readlines(MAX_SESSION_BYTES + 1)
        after = os.fstat(fd)
        current = os.stat(path, follow_symlinks=False)
        stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if stamp(before) != stamp(after) or stamp(after) != stamp(current):
            return {"model": "", "effort": ""}
    finally:
        os.close(fd)
    if sum(map(len, raw_lines)) > MAX_SESSION_BYTES or any(len(line) > MAX_SESSION_LINE for line in raw_lines):
        return {"model": "", "effort": ""}
    entries, last_id, header_ok = {}, "", False
    for number, raw in enumerate(raw_lines):
        try:
            entry = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"model": "", "effort": ""}
        if not isinstance(entry, dict):
            return {"model": "", "effort": ""}
        if number == 0:
            header_ok = (entry.get("type") == "session"
                         and isinstance(entry.get("id"), str) and entry.get("id")
                         and (not session_id or entry.get("id") == session_id)
                         and (not expected_cwd or entry.get("cwd") == expected_cwd))
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id or entry_id in entries:
            return {"model": "", "effort": ""}
        entries[entry_id] = entry
        last_id = entry_id
    if not header_ok or not last_id:
        return {"model": "", "effort": ""}
    model = effort = ""
    seen = set()
    current_id = last_id
    while current_id and current_id not in seen and len(seen) <= len(entries):
        seen.add(current_id)
        entry = entries.get(current_id)
        if entry is None:
            break
        if not model and entry.get("type") == "model_change":
            provider, model_id = entry.get("provider"), entry.get("modelId")
            if isinstance(provider, str) and provider and isinstance(model_id, str) and model_id:
                model = provider + "/" + model_id
        if not effort and entry.get("type") == "thinking_level_change":
            value = entry.get("thinkingLevel")
            if isinstance(value, str) and value:
                effort = value
        if model and effort:
            break
        current_id = entry.get("parentId") if isinstance(entry.get("parentId"), str) else ""
    return {"model": model, "effort": effort}


def session_selection(environment, expected_cwd="", process_start=0, harness=""):
    """Use an exact Pi session path, or one generation-unique default session."""
    path_value = environment.get("PI_SESSION_FILE")
    session_id = environment.get("PI_SESSION_ID")
    if path_value and session_id:
        return read_session_selection(path_value, session_id, expected_cwd)
    if harness not in {"pi", "pi-signed"} or not expected_cwd or not process_start:
        return {"model": "", "effort": ""}
    cwd = Path(expected_cwd)
    if not cwd.is_absolute() or cwd.resolve() != cwd:
        return {"model": "", "effort": ""}
    directory = Path.home() / ".pi/agent/sessions" / ("--" + expected_cwd.strip("/").replace("/", "-") + "--")
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return {"model": "", "effort": ""}
    if len(entries) > 32:
        return {"model": "", "effort": ""}
    candidates = []
    for entry in entries:
        try:
            info = entry.stat(follow_symlinks=False)
            if not (entry.name.endswith(".jsonl") and entry.is_file(follow_symlinks=False)
                    and info.st_uid == os.getuid()):
                continue
            born = file_birth_ns(entry.path)
            if born is None:
                return {"model": "", "effort": ""}
            if born + 2 * 10**9 >= process_start:
                candidates.append(Path(entry.path))
        except OSError:
            return {"model": "", "effort": ""}
    if len(candidates) != 1:
        return {"model": "", "effort": ""}
    return read_session_selection(candidates[0], expected_cwd=expected_cwd)


def observe_runtime(pid, expected_cwd="", harness="", os_reader=None):
    """Read one caller-supplied process; do not enumerate or discover PIDs."""
    reader = os_reader if os_reader is not None else system_reader()
    before = reader.process(pid)
    environment = reader.environment(pid)
    runtime = session_selection(environment, expected_cwd, before["start"], harness)
    if reader.process(pid) != before or reader.environment(pid) != environment:
        raise ValueError("Owner/Endpunkt während Prüfung geändert")
    return {"process": before,
            "environment": {key: value for key, value in environment.items()
                            if key in IDENTITY_KEYS or key == "FM_TASK_ID"},
            "runtime": runtime}


def read_lock(home):
    path = Path(home) / "state/.lock"
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or not 1 <= before.st_size <= 32):
            raise ValueError("Home-Lock nicht bestätigt")
        data = os.read(fd, 64).strip()
        if not data.isdigit() or len(data) > 10 or not 1 < int(data) < 2**31:
            raise ValueError("Home-Lock-PID ungültig")
        def signature(s):
            return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
        signature_before = signature(before)
        if (signature_before != signature(os.fstat(fd))
                or signature_before != signature(os.lstat(path))):
            raise ValueError("Home-Lock während Lesen geändert")
        return int(data), signature_before
    finally:
        os.close(fd)


def harness_alive(root, pid):
    # Source the existing read-only owner; never invoke fm-lock.sh (it can write).
    result = subprocess.run([
        "/bin/bash", "-c", '. "$1/bin/fm-session-lock-lib.sh" && fm_harness_pid_alive "$2"',
        "tshepherd-owner", str(root), str(pid)], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    return result.returncode == 0


def observe(home, root, shell_pid=None, os_reader=None, classifier=harness_alive):
    reader = os_reader if os_reader is not None else system_reader()
    pid, lock = read_lock(home)
    before = reader.process(pid)
    if not before["start"] <= lock[3] <= time.time_ns() + 2 * 10**9:
        raise ValueError("Home-Lock passt nicht zur Prozessgeneration")
    if not classifier(root, pid):
        raise ValueError("Home-Owner ist kein bestätigter Harness")
    env = reader.environment(pid)
    chain = []
    if shell_pid is not None:
        if not isinstance(shell_pid, int) or isinstance(shell_pid, bool) or shell_pid <= 1:
            raise ValueError("Native Shell-PID fehlt")
        current = pid
        for _ in range(24):
            process = reader.process(current)
            chain.append(process)
            if current == shell_pid:
                break
            current = process["ppid"]
            if current <= 1:
                raise ValueError("Owner gehört nicht zur nativen Pane-Shell")
        else:
            raise ValueError("Owner-Abstammung nicht bestätigt")
    if (not classifier(root, pid) or reader.process(pid) != before or reader.environment(pid) != env
            or read_lock(home) != (pid, lock)
            or any(reader.process(p["pid"]) != p for p in chain)):
        raise ValueError("Owner/Endpunkt während Prüfung geändert")
    return {"home": str(Path(home).resolve()), "lock": lock,
            "process": before,
            "environment": {key: value for key, value in env.items() if key in IDENTITY_KEYS}}


def main():
    try:
        if len(sys.argv) in (3, 4, 5) and sys.argv[1] == "--runtime":
            result = observe_runtime(int(sys.argv[2]), sys.argv[3] if len(sys.argv) >= 4 else "",
                                     sys.argv[4] if len(sys.argv) == 5 else "")
        else:
            if len(sys.argv) not in (3, 4):
                raise ValueError("Home und Firstmate-Code-Root erforderlich")
            shell = int(sys.argv[3]) if len(sys.argv) == 4 else None
            result = observe(sys.argv[1], sys.argv[2], shell)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        # No raw OS buffers or subprocess output in the diagnostic surface.
        result = {"unavailable": str(error)}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
