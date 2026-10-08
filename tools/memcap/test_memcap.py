import subprocess, sys, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "memcap.py"
HOG = "b = bytearray(400 * 1024 * 1024); print(len(b))"     # 400 MB, above the 200 MB test cap
SMALL = "b = bytearray(10 * 1024 * 1024); print('ok')"


class MemCap(unittest.TestCase):
    def cap(self, code, mb="200"):
        return subprocess.run([sys.executable, str(SCRIPT), "--mb", mb, "--", sys.executable, "-c", code],
                              capture_output=True, text=True, timeout=120)

    def test_small_job_runs(self):
        r = self.cap(SMALL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok", r.stdout)

    def test_hog_is_stopped(self):
        r = self.cap(HOG)
        self.assertNotEqual(r.returncode, 0, "the 400 MB allocation must fail under a 200 MB cap")
        self.assertNotIn("419430400", r.stdout)

    def test_exit_code_passes_through_and_usage(self):
        self.assertEqual(self.cap("import sys; sys.exit(7)").returncode, 7)
        self.assertEqual(subprocess.run([sys.executable, str(SCRIPT)], capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
