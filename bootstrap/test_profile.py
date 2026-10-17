"""profile.py: create -> registry entry + a separate config folder (its own KB and index path) -> launch
with that config -> remove cleans up, the main install untouched. Temp home only.
Run: python -m unittest discover -s bootstrap -p "test_profile.py" -v"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install as I  # noqa: E402


class Profiles(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="wb-prof-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        (self.home / "registry.json").write_text("{}", encoding="utf-8")
        self.main = self.home / ".claude"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("OneDrive", "WORKBENCH_", "WB_"))}
        self.env.update(USERPROFILE=str(self.home), HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.main),
                        LOCALAPPDATA=str(self.home / "lad"), WORKBENCH_FAKE_REGISTRY=str(self.home / "registry.json"),
                        WORKBENCH_FAKE_BIN=str(self.home / "nobin"))

    def run_py(self, script, *args, code=0, env=None):
        r = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True,
                           encoding="utf-8", env=env or self.env, timeout=300)
        self.assertEqual(r.returncode, code, r.stdout[-2000:] + r.stderr[-1000:])
        return r.stdout

    def test_create_launch_remove(self):
        self.run_py("install.py", "--apply", "--no-cli")
        main_settings = (self.main / "settings.json").read_bytes()
        self.run_py("profile.py", "create", "Bad_Name", code=2)
        self.run_py("profile.py", "create", "client-a", "--", "--no-cli")
        base = self.home / ".claude-profiles" / "client-a"
        reg = json.loads((self.main / "workbench" / "profiles.json").read_text(encoding="utf-8"))
        (p,) = reg["profiles"]
        self.assertEqual((p["name"], p["config_dir"], p["kb_root"]), ("client-a", I.fwd(base / "config"), I.fwd(base / "kb")))
        self.assertTrue(p["knowledge_db"].endswith("doc-index/knowledge-client-a/index.sqlite"))
        cfg = json.loads((base / "config" / "workbench" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["knowledge_db"], p["knowledge_db"])
        self.assertEqual(cfg["kb_root"], I.fwd(base / "kb"))
        self.assertTrue((base / "kb" / "_shared" / "HOT.md").exists())
        self.assertEqual((self.main / "settings.json").read_bytes(), main_settings, "the main install is untouched")
        self.run_py("profile.py", "create", "client-a", code=2)
        self.assertIn("client-a", self.run_py("profile.py", "list"))
        fake = self.home / "fakeclaude"                  # `launch` runs claude with the profile's config folder
        fake.mkdir()
        (fake / "claude.cmd").write_text(f'@"{sys.executable}" -c "import os;print(os.environ[\'CLAUDE_CONFIG_DIR\'])"\r\n')
        (fake / "claude").write_text(f'#!/bin/sh\n"{sys.executable}" -c "import os;print(os.environ[\'CLAUDE_CONFIG_DIR\'])"\n')
        os.chmod(fake / "claude", 0o755)
        env = {**self.env, "PATH": str(fake) + os.pathsep + self.env.get("PATH", "")}
        self.assertEqual(Path(self.run_py("profile.py", "launch", "client-a", env=env).strip()), base / "config")
        idx = self.home / "lad" / "doc-index"
        (idx / "knowledge-client-a").mkdir(parents=True)
        (idx / "knowledge").mkdir()                       # the main install's shared index must survive
        self.run_py("profile.py", "remove", "client-a")
        self.assertFalse((base / "config").exists())
        self.assertFalse((idx / "knowledge-client-a").exists())
        self.assertTrue((idx / "knowledge").exists(), "a profile uninstall never removes the main index")
        self.assertTrue((base / "kb" / "_shared" / "HOT.md").exists(), "the KB stays without --purge-kb")
        self.assertEqual(json.loads((self.main / "workbench" / "profiles.json").read_text())["profiles"], [])
        self.run_py("profile.py", "create", "client-b", "--", "--no-cli")
        self.run_py("profile.py", "remove", "client-b", "--purge-kb")
        self.assertFalse((self.home / ".claude-profiles" / "client-b").exists())
        self.run_py("profile.py", "remove", "client-b", code=2)


if __name__ == "__main__":
    unittest.main()
