"""The doctor's D3 field list (field-tests.txt): every line names a real test, every test module is represented, no
wall-clock test is listed, and the list stays a small share of the suite."""
import inspect
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIST = HERE / "field-tests.txt"
TIMING = ("Latency", "Speed")      # classes that measure wall-clock time: a busy machine fails them, not the kit
ELAPSED = re.compile(r"(?:time\.time|perf_counter|monotonic)(?:_ns)?\(\)\s*-\s*[A-Za-z_]")   # an elapsed time: now() - start


def names():
    return [ln.strip() for ln in LIST.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def flat(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from flat(t)
        else:
            yield t


class FieldList(unittest.TestCase):
    def test_every_line_names_a_real_test(self):
        loader = unittest.TestLoader()
        for n in names():
            with self.subTest(n):
                tests = list(flat(loader.loadTestsFromName(n)))
                self.assertTrue(tests, f"{n} names no test")
                self.assertEqual([t.id() for t in tests if type(t).__name__ == "_FailedTest"], [], f"{n} does not load")
                self.assertTrue(all(t.id() == n or t.id().startswith(n + ".") for t in tests), n)

    def test_every_test_module_is_represented_and_no_line_repeats(self):
        listed = names()
        self.assertEqual(len(listed), len(set(listed)), "a line repeats")
        modules = {n.split(".", 1)[0] for n in listed}
        self.assertEqual(sorted(p.stem for p in HERE.glob("test_*.py")), sorted(modules))

    def test_no_timing_test_is_listed_and_the_list_stays_small(self):
        loader = unittest.TestLoader()
        tests = [t for n in names() for t in flat(loader.loadTestsFromName(n))]
        ids = [t.id() for t in tests]
        self.assertEqual([i for i in ids if set(i.split(".")) & set(TIMING)], [])
        timed = [t.id() for t in tests if ELAPSED.search(src := inspect.getsource(getattr(type(t), t._testMethodName)))
                 and "WB_FIELD_CHECK" not in src]
        self.assertEqual(timed, [], "a listed test measures elapsed time without skipping that budget under the doctor")
        everything = [t.id() for t in flat(loader.discover(str(HERE), pattern="test_*.py", top_level_dir=str(HERE)))]
        self.assertLessEqual(len(ids), len(everything) // 2, "the field list is a subset, not the suite")
