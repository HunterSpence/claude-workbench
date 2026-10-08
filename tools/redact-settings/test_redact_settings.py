import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "redact_settings.py"
KEY = "AKIA" + "R" * 16          # built at runtime: this file holds no credential shape


class Redact(unittest.TestCase):
    def test_masks_env_headers_helpers_and_stray_secrets(self):
        d = Path(tempfile.mkdtemp())
        try:
            src = {"model": "opus", "env": {"MY_TOKEN": "abc", "PLAIN": "1"}, "apiKeyHelper": "get-key.sh",
                   "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python x.py"}]}]},
                   "mcpServers": {"s": {"type": "http", "url": "https://mcp.example.com/mcp",
                                        "headers": {"Authorization": "Bearer abc"}, "env": {"K": "v"}}},
                   "note": f"left here by mistake {KEY}"}
            (d / "in.json").write_text(json.dumps(src))
            r = subprocess.run([sys.executable, str(SCRIPT), str(d / "in.json"), str(d / "out.json")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads((d / "out.json").read_text())
            self.assertEqual(out["env"], {"MY_TOKEN": "<REDACTED:MY_TOKEN>", "PLAIN": "<REDACTED:PLAIN>"})
            self.assertEqual(out["apiKeyHelper"], "<REDACTED:apiKeyHelper>")
            self.assertEqual(out["mcpServers"]["s"]["headers"], {"Authorization": "<REDACTED:Authorization>"})
            self.assertEqual(out["mcpServers"]["s"]["url"], "https://mcp.example.com/mcp")
            self.assertEqual(out["hooks"], src["hooks"])
            self.assertEqual(out["note"], "<REDACTED:credential-shaped>")
            self.assertNotIn(KEY, (d / "out.json").read_text())
            self.assertEqual(json.loads((d / "in.json").read_text()), src, "source untouched")
            r = subprocess.run([sys.executable, str(SCRIPT), str(d / "in.json"), str(d / "in.json")], capture_output=True)
            self.assertEqual(r.returncode, 2)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
