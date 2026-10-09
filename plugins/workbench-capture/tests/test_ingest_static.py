"""Ingest: static guarantees about the code and the shipped text (no registry writes, no prompt-bypass library, the skill's
frontmatter, the pinned dependency, the ask texts, the deferred Recap files)."""
import json
import os
import re
import sys
import unittest
from pathlib import Path

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import harness as H  # noqa: E402
import common  # noqa: E402
import digest  # noqa: E402

SCRIPTS = H.SCRIPTS
SKILL = SCRIPTS.parent
PLUGIN = SKILL.parents[1]
CODE = {p.name: p.read_text("utf-8") for p in sorted(SCRIPTS.glob("*.py"))}
ALL = {**CODE, "digest.schema.json": (SCRIPTS / "digest.schema.json").read_text("utf-8")}


def hits(pattern, files=CODE, flags=re.I):
    return [(n, m.group()) for n, t in files.items() for m in re.finditer(pattern, t, flags)]


class StaticTests(unittest.TestCase):
    def test_there_is_no_registry_write_and_the_policy_guard_value_is_never_named(self):
        self.assertEqual(hits(r"\b(SetValueEx?|CreateKeyEx?|DeleteKeyEx?|DeleteValue|SaveKey|LoadKey|RegSetValue\w*|RegCreateKey\w*|RegDeleteKey\w*|RegDeleteValue\w*)\b"), [])
        self.assertEqual(hits(r"\breg(\.exe)?\s+(add|import|delete|copy|restore|load)\b|\b(New|Set|Remove|Clear)-ItemProperty\b|\.reg\b"), [])
        self.assertEqual(hits(r"\bKEY_(WRITE|SET_VALUE|CREATE_SUB_KEY|CREATE_LINK|ALL_ACCESS)\b"), [])
        self.assertEqual(hits(r"ObjectModelGuard"), [])
        reads = hits(r"\bOpenKey(Ex)?\(")
        self.assertTrue(reads and all(n == "outlook_com.py" for n, _ in reads))
        self.assertIn("KEY_READ", CODE["outlook_com.py"])

    def test_there_is_no_prompt_bypass_or_window_automation_library(self):
        banned = r"redemption|clickyes|securitymanager|outlook security manager|pyautogui|pywinauto|uiautomation|autoit|sendkeys|keybd_event|SendInput|FindWindow|PostMessage|SendMessage|user32|win32gui|win32api|win32con|pynput|mapilab|advanced security"
        self.assertEqual(hits(banned), [])
        imports = {m.group(1) for t in CODE.values() for m in re.finditer(r"^\s*(?:import|from)\s+([\w.]+)", t, re.M)}
        imports = {i.split(".")[0] for i in imports}
        self.assertEqual(sorted(imports - set(sys.stdlib_module_names) - {"common", "digest", "drop", "graph", "mailsource", "outlook_com", "ingest", "win32com"}), [])

    def test_the_code_runs_nothing_through_a_shell_and_evaluates_nothing(self):
        self.assertEqual(hits(r"shell\s*=\s*True|os\.system\(|os\.popen\(|\beval\(|\bexec\(|pickle|marshal"), [])

    def test_the_api_key_is_dropped_never_set_and_no_flag_widens_the_digest_call(self):
        self.assertEqual([n for n, _ in hits(r"ANTHROPIC_API_KEY")], ["digest.py"])
        self.assertEqual(hits(r"allowed-?tools|permission-mode|dangerously|--add-dir|--resume|--continue|--bare"), [])
        self.assertIn('"--tools", ""', CODE["digest.py"])
        self.assertIn("--strict-mcp-config", CODE["digest.py"])
        self.assertIn("--no-session-persistence", CODE["digest.py"])

    def test_graph_data_calls_are_get_only_and_tokens_are_never_printed(self):
        g = CODE["graph.py"]
        self.assertEqual(re.findall(r'_send\("(\w+)"', g), ["POST", "POST", "GET"])  # device code, token, the one data call
        self.assertEqual(hits(r"\b(DELETE|PATCH|PUT)\b", {"graph.py": g}, 0), [])
        printing = [ln for ln in g.splitlines() if re.search(r"\b(print|say|log)\w*\(", ln) and re.search(r"access_token|refresh_token|\btok\b", ln)]
        self.assertEqual(printing, [])
        self.assertIn("FIRST_PARTY", g)
        self.assertIn("os.name", g)

    def test_skill_frontmatter_requirements_and_deferred_files(self):
        text = (SKILL / "SKILL.md").read_text("utf-8")
        fm = dict(re.findall(r"^(\w[\w-]*):\s*(.*)$", text.split("---")[1], re.M))
        self.assertEqual((fm["name"], fm["disable-model-invocation"]), ("ingest", "true"))
        self.assertLessEqual(len(fm["description"]), 300)
        self.assertIn("EXPERIMENTAL", fm["description"])
        self.assertEqual((SKILL / "requirements.txt").read_text("utf-8").splitlines(), ['pywin32==312; sys_platform == "win32"'])
        self.assertFalse((PLUGIN / "skills/capture/scripts/sources/teams_recap.mjs").exists())
        self.assertFalse((PLUGIN / "tests/recap.test.mjs").exists())
        self.assertFalse((PLUGIN / "tests/fixtures/recap").exists())
        for f in (text, (SKILL / "references/asks.md").read_text("utf-8")):
            self.assertEqual(sum("Download" in ln and "POST" in ln for ln in f.splitlines()), 1, "the deferral is stated in one line")

    def test_the_ask_texts_in_the_report_and_in_the_reference_are_the_same(self):
        asks = (SKILL / "references/asks.md").read_text("utf-8")
        for key, text in common.ASKS.items():
            self.assertIn(text, asks, key)
        self.assertIn("untrusted-meeting", (SKILL / "references/quarantine.md").read_text("utf-8"))

    def test_the_schema_file_is_the_frozen_digest_shape(self):
        s = json.loads(ALL["digest.schema.json"])
        self.assertFalse(s["additionalProperties"])
        self.assertEqual(sorted(s["properties"]), ["action_items", "decisions", "open_questions", "synopsis", "what_this_changes"])
        self.assertEqual(s["properties"]["synopsis"]["maxLength"], 1200)
        self.assertEqual(s["properties"]["action_items"]["items"]["properties"]["due"]["type"], ["string", "null"])
        self.assertEqual(digest.SCHEMA, s)

    def test_nothing_in_the_shipped_files_is_a_dotted_quad_or_a_real_looking_address(self):
        files = {**ALL, **{p.name: p.read_text("utf-8") for p in (SKILL / "references").glob("*.md")}, "SKILL.md": (SKILL / "SKILL.md").read_text("utf-8")}
        self.assertEqual(hits(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", files), [])
        for n, t in files.items():
            for addr in re.findall(r"[\w.+-]+@([\w-]+\.[\w.-]+)", t):
                self.assertTrue(addr.endswith(("example.com", "example.org")), (n, addr))


if __name__ == "__main__":
    unittest.main()
