#!/usr/bin/env python3
"""Cross-process file locking + atomic writes for the knowledge-base tools.

Several Claude Code sessions can run against one knowledge base and each can run save_driver.py at the same time.
Every shared-state mutation goes through one of these primitives.

filelock()   OS-level advisory lock (msvcrt on Windows, fcntl elsewhere). The OS
             releases it when the holding process dies, so there is no stale-lock
             file to garbage-collect and no mtime heuristic to get wrong.
atomic_write() tmp-file + os.replace — a reader never sees a half-written file, and
             a crash mid-write leaves the previous version intact.
append_line() single O_APPEND write syscall — concurrent appends interleave by
             whole lines, never mid-line, without needing a lock.
"""
import contextlib
import os
import time
from pathlib import Path

try:
    import msvcrt  # Windows
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None
    import fcntl


class LockBusy(RuntimeError):
    """Raised by filelock(blocking=False) when another process holds the lock."""


def lock_for(path):
    """Sibling lockfile for a data file. Kept out of the data file's own byte range."""
    path = Path(path)
    return path.with_name(path.name + ".lock")


@contextlib.contextmanager
def filelock(path, timeout=120.0, blocking=True):
    """Exclusive cross-process lock on `path`.

    blocking=True  -> wait up to `timeout`s, then raise LockBusy.
    blocking=False -> raise LockBusy immediately if held.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    deadline = time.monotonic() + (timeout if blocking else 0.0)
    try:
        while True:
            try:
                fh.seek(0)  # lock byte 0 — every process must agree on the range
                if msvcrt:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockBusy(f"lock held by another process: {path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                fh.seek(0)
                if msvcrt:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fh, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        fh.close()


@contextlib.contextmanager
def maybe_lock(path, timeout=120.0, blocking=True):
    """filelock that yields False instead of raising when the lock is unavailable.

    Use for work another concurrent save already covers (git push, reindex): skipping
    is correct, not a failure.
    """
    # Acquire inside its own try so only an ACQUISITION failure yields False. Wrapping the
    # body too would swallow a LockBusy raised by the body itself and then re-yield, which
    # blows up as "generator didn't stop after throw()".
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(filelock(path, timeout=timeout, blocking=blocking))
        except LockBusy:
            yield False
            return
        yield True


def is_locked(path) -> bool:
    """True if another process currently holds `path`. Point-in-time probe only."""
    try:
        with filelock(path, blocking=False):
            return False
    except LockBusy:
        return True
    except OSError:
        return False


def retry_sharing(fn, tries=20, delay=0.05):
    """Call fn(), retrying PermissionError: on Windows a file another process holds open cannot
    be replaced (no FILE_SHARE_DELETE), and one mid-replace cannot be opened. Transient. Re-raises after ~1 s so
    the caller can report it."""
    for i in range(tries):
        try:
            return fn()
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(delay)


def read_text(p):
    """utf-8 (BOM stripped) else latin-1; '' if missing; retries a Windows sharing violation ~1 s."""
    p = Path(p)
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return retry_sharing(lambda: p.read_text(encoding=enc))
        except UnicodeDecodeError:
            continue
        except FileNotFoundError:
            return ""


def atomic_write(path, text, encoding="utf-8", newline="\n"):
    """Replace `path` with `text` atomically. Never leaves a truncated file behind.
    Writes LF by default (git stores LF; a CRLF rewrite of an LF file is a whole-file diff on a
    core.autocrlf=false checkout). Pass newline=None for platform translation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding=encoding, newline=newline)
        retry_sharing(lambda: os.replace(tmp, path))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def append_line(path, line, encoding="utf-8"):
    """Append one line, safe against concurrent appends from other processes.

    O_APPEND is NOT atomic on Windows: the CRT emulates it as seek-to-end + write, so two processes racing can
    lose lines. Hence the lock.
    """
    path = Path(path)
    data = (line.rstrip("\n") + "\n").encode(encoding)
    with filelock(lock_for(path)):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
