"""Tests for mcp_nowin.py: fake kernel32 and C-runtime objects for the handle logic, real python child processes for the pipe."""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing here skips

import contextlib  # noqa: E402
import io  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mcp_nowin as nw  # noqa: E402

BIN = getattr(os, "O_BINARY", 0)


class FakeKernel32:
    def __init__(self, handles):
        self.handles, self.asked = handles, []

    def GetStdHandle(self, std_id):
        self.asked.append(std_id)
        return self.handles.get(std_id)


class FakeCrt:
    def __init__(self, bad=()):
        self.opened, self.bad = [], bad

    def open_osfhandle(self, handle, flags):
        if handle in self.bad:
            raise OSError("bad handle")
        self.opened.append((handle, flags))
        return handle + 1000


class StdHandles(unittest.TestCase):
    def test_all_three_handles_are_reattached_with_the_right_modes(self):
        k, c = FakeKernel32({-10: 11, -11: 22, -12: 33}), FakeCrt()
        self.assertEqual(nw.std_fds(k, c), (1011, 1022, 1033))
        self.assertEqual(k.asked, [-10, -11, -12])
        self.assertEqual(c.opened, [(11, os.O_RDONLY | BIN), (22, os.O_WRONLY | BIN), (33, os.O_WRONLY | BIN)])

    def test_missing_invalid_or_unopenable_handles_become_none(self):
        k = FakeKernel32({-10: None, -11: 0xFFFFFFFF, -12: 7})
        self.assertEqual(nw.std_fds(k, FakeCrt()), (None, None, 1007))
        self.assertEqual(nw.std_fds(FakeKernel32({-10: 5, -11: 6, -12: 7}), FakeCrt(bad=(6,))), (1005, None, 1007))


class Launch(unittest.TestCase):
    def capture(self, argv, fds=(1, 2, 3), rc=0):
        seen = {}

        def call(a, **kw):
            seen.update(kw, argv=a)
            return rc

        return nw.main(argv, call=call, fds=fds), seen

    def test_the_program_runs_windowless_with_the_reattached_handles_and_its_arguments_unchanged(self):
        rc, seen = self.capture(["prog.exe", "--flag", "a b", "-x"], rc=0)
        self.assertEqual(seen["argv"], ["prog.exe", "--flag", "a b", "-x"])
        self.assertEqual((seen["stdin"], seen["stdout"], seen["stderr"]), (1, 2, 3))
        self.assertEqual(seen["creationflags"], nw.CREATE_NO_WINDOW)
        if os.name == "nt":
            self.assertEqual(nw.CREATE_NO_WINDOW & 0x08000000, 0x08000000)
        self.assertIs(seen["close_fds"], False)

    def test_the_exit_code_passes_through_and_a_missing_program_is_127(self):
        self.assertEqual(self.capture(["p"], rc=5)[0], 5)

        def boom(a, **kw):
            raise FileNotFoundError(2, "no such file")

        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(nw.main(["no-such-program"], call=boom, fds=(None, None, None)), 127)
        self.assertIn("cannot start", err.getvalue())

    def test_no_program_is_a_usage_error_and_nothing_is_started(self):
        with contextlib.redirect_stderr(io.StringIO()):
            rc, seen = self.capture([])
        self.assertEqual((rc, seen), (2, {}))


class RealChild(unittest.TestCase):
    def run_nowin(self, code, data=b""):
        return subprocess.run([sys.executable, "-I", str(HERE / "mcp_nowin.py"), sys.executable, "-c", code],
                              input=data, capture_output=True)

    def test_stdio_is_piped_through_and_the_exit_code_comes_back(self):
        p = self.run_nowin("import sys; sys.stdout.write(sys.stdin.read().upper()); sys.stderr.write('err'); sys.exit(5)",
                           b"hello pipe")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (5, b"HELLO PIPE", b"err"))

    def test_the_child_has_no_console_window_on_windows(self):
        code = "import os, sys\nif os.name == 'nt':\n import ctypes; sys.stdout.write(str(ctypes.windll.kernel32.GetConsoleWindow()))\nelse:\n sys.stdout.write('0')"
        self.assertEqual(self.run_nowin(code).stdout, b"0")

    def test_self_test_is_one_offline_line(self):
        p = subprocess.run([sys.executable, "-I", str(HERE / "mcp_nowin.py"), "--self-test"], capture_output=True, text=True)
        self.assertEqual((p.returncode, len(p.stdout.strip().splitlines())), (0, 1), p.stderr)


if __name__ == "__main__":
    unittest.main()
