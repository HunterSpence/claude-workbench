#!/usr/bin/env python3
"""memcap.py: run a command with a memory ceiling, which keeps a runaway test, fuzz or eval job from exhausting
memory.

  memcap.py [--mb 1536] -- <command> [args...]

Windows: the command runs inside a job object. Each process in it may commit at most --mb MB, the whole job at most
twice that, and every process in the job dies when memcap exits. Prints the job's peak process memory at the end.
Linux / WSL / macOS: the child gets RLIMIT_AS = --mb MB (address space, so set it generously for JIT runtimes).
Exit code: the command's. Standard library only. Use it for heavy jobs, one at a time.
"""
import ctypes
import os
import subprocess
import sys


def _windows_job(mb):
    from ctypes import wintypes as wt

    class Basic(ctypes.Structure):
        _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", wt.DWORD), ("c", ctypes.c_size_t),
                    ("d", ctypes.c_size_t), ("e", wt.DWORD), ("f", ctypes.c_size_t), ("g", wt.DWORD), ("h", wt.DWORD)]

    class Ext(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("Io", ctypes.c_ulonglong * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = k.GetCurrentProcess.restype = wt.HANDLE
    k.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    k.QueryInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
    k.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    job, info = k.CreateJobObjectW(None, None), Ext()
    info.Basic.LimitFlags = 0x100 | 0x200 | 0x2000          # PROCESS_MEMORY | JOB_MEMORY | KILL_ON_JOB_CLOSE
    info.ProcessMemoryLimit, info.JobMemoryLimit = mb << 20, (2 * mb) << 20
    # memcap itself joins the job, so every child it starts is inside it from the first instruction.
    if not (job and k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
            and k.AssignProcessToJobObject(job, k.GetCurrentProcess())):
        raise OSError(f"job object setup failed (winerror {ctypes.get_last_error()})")

    def peak_mb():
        k.QueryInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info), None)
        return info.PeakProcessMemoryUsed >> 20
    return peak_mb


def run(cmd, mb):
    if os.name == "nt":
        peak = _windows_job(mb)
        rc = subprocess.call(cmd)
        print(f"[memcap] peak process memory {peak()} MB (cap {mb} MB per process)", file=sys.stderr)
        return rc
    import resource

    def limit():
        resource.setrlimit(resource.RLIMIT_AS, (mb << 20, mb << 20))
    return subprocess.call(cmd, preexec_fn=limit)


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    mb = 1536
    if a[:1] == ["--mb"] and len(a) > 1:
        mb, a = int(a[1]), a[2:]
    if a[:1] == ["--"]:
        a = a[1:]
    if not a or mb < 64:
        print(__doc__, file=sys.stderr)
        return 2
    return run(a, mb)


if __name__ == "__main__":
    sys.exit(main())
