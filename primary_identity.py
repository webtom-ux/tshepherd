"""Bounded read-only macOS home-lock identity reader, invoked by TShepherd.

Firstmate's fm-session-lock-lib.sh owns harness classification and the PID lock.
Darwin proc_pidinfo supplies generation/ancestry; KERN_PROCARGS2 supplies only the
selected owner's injected endpoint. Never enumerate processes or emit argv/env.
Unsupported/restricted process visibility is unavailable, not a discovery fallback.
"""
import ctypes as C
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

KEYS = frozenset(("HERDR_ENV", "HERDR_SESSION", "HERDR_SOCKET_PATH",
                  "HERDR_PANE_ID", "HERDR_TAB_ID", "HERDR_WORKSPACE_ID"))


class BSD(C.Structure):
    # macOS SDK sys/proc_info.h: proc_bsdinfo / PROC_PIDTBSDINFO (3).
    _fields_ = ([(n, C.c_uint32) for n in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid",
        "rgid", "svuid", "svgid", "reserved")]
        + [("comm", C.c_char * 16), ("name", C.c_char * 32)]
        + [(n, C.c_uint32) for n in ("nfiles", "pgid", "pjobc", "tdev", "tpgid")]
        + [("nice", C.c_int32), ("start_sec", C.c_uint64), ("start_usec", C.c_uint64)])


def selected_environment(raw):
    """Parse the OS buffer in memory; discard argv and all non-identity fields."""
    argc = int.from_bytes(raw[:4], byteorder=sys.byteorder, signed=True)
    if not 0 < argc < 100000:
        raise ValueError("Prozessargumente unlesbar")
    pos = raw.index(b"\0", 4) + 1  # executable path, then padding
    while pos < len(raw) and raw[pos] == 0:
        pos += 1
    for _ in range(argc):
        pos = raw.index(b"\0", pos) + 1
    result = {}
    for entry in raw[pos:].split(b"\0"):
        key, sep, value = entry.partition(b"=")
        if key in {k.encode("ascii") for k in KEYS} and sep:
            name = key.decode("ascii")
            if name in result:
                raise ValueError("mehrdeutige Prozessidentität")
            result[name] = value.decode("utf-8", "strict")
    return result


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
    reader = os_reader if os_reader is not None else Darwin()
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
            "process": before, "environment": env}


def main():
    try:
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
