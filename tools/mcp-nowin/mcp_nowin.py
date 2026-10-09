#!/usr/bin/env python3
r"""mcp_nowin.py: start a console program with no console window, for stdio tool servers on Windows.

Use it as the command of a stdio server, under the windowless interpreter, so Claude Code's start does not open a black
window per server:

  command: <path to pythonw.exe>
  args:    ["<KIT>/tools/mcp-nowin/mcp_nowin.py", "<program>", "<the program's own arguments>..."]

argv[1] is the program (a path or a name on PATH), argv[2:] go to it unchanged. The program runs with CREATE_NO_WINDOW and
its exit code becomes this script's. pythonw is a GUI-subsystem program and does not wire C-runtime descriptors 0, 1 and 2,
so the operating-system standard handles Claude Code gave us are re-attached and passed on: that is what keeps the stdio
pipe alive. Test it with python.exe first (the same arguments); then switch the command to pythonw.exe.

  py -3 <KIT>/tools/mcp-nowin/mcp_nowin.py --self-test      offline check, one line, exit 0
"""
import os
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
INVALID = (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF, -1, None)
BINARY = getattr(os, "O_BINARY", 0)
STD_HANDLES = ((-10, os.O_RDONLY | BINARY), (-11, os.O_WRONLY | BINARY), (-12, os.O_WRONLY | BINARY))   # in, out, err


def std_fds(kernel32=None, crt=None):
    """(stdin, stdout, stderr) C descriptors for the OS standard handles; None where a handle is missing or unusable."""
    if kernel32 is None or crt is None:
        if os.name != "nt":
            return (None, None, None)
        import ctypes
        import msvcrt
        kernel32, crt = ctypes.windll.kernel32, msvcrt
        kernel32.GetStdHandle.restype = ctypes.c_void_p
    fds = []
    for std_id, flags in STD_HANDLES:
        handle = kernel32.GetStdHandle(std_id)
        if handle in INVALID:
            fds.append(None)
            continue
        try:
            fds.append(crt.open_osfhandle(handle, flags))
        except OSError:
            fds.append(None)
    return tuple(fds)


def main(argv=None, call=subprocess.call, fds=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        if sys.stderr:
            sys.stderr.write("mcp_nowin: missing program argument\n")
        return 2
    stdin, stdout, stderr = std_fds() if fds is None else fds
    try:
        return call(argv, stdin=stdin, stdout=stdout, stderr=stderr, close_fds=False, creationflags=CREATE_NO_WINDOW)
    except OSError as e:
        if sys.stderr:
            sys.stderr.write(f"mcp_nowin: cannot start {argv[0]!r}: {e.strerror or type(e).__name__}\n")
        return 127


def self_test():
    seen = {}

    def fake_call(argv, **kw):
        seen.update(kw, argv=argv)
        return 0

    assert main(["prog", "a b", "--x"], call=fake_call, fds=(1, 2, 3)) == 0
    assert seen["argv"] == ["prog", "a b", "--x"] and (seen["stdin"], seen["stdout"], seen["stderr"]) == (1, 2, 3)
    assert seen["creationflags"] == CREATE_NO_WINDOW and seen["close_fds"] is False
    assert main([sys.executable, "-c", "import sys; sys.exit(7)"], fds=(None, None, None)) == 7
    print("mcp_nowin self-test ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        sys.exit(0)
    sys.exit(main())
