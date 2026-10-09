"""The workbench-core copy of secretscan.py finds the shapes found missing in the field (the Stop-hook credential check runs
this copy). Every value is fictional and built at run time, so this file holds no credential-shaped string. Run:
    python -m unittest discover -s plugins/workbench-core/scripts/tests -p test_secretscan_core.py
The kb copy has the full control table (plugins/workbench-kb/tests/test_secretscan.py); here the two copies are also compared byte for byte."""
import importlib.util
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
KB_COPY = SCRIPTS.parents[1] / "workbench-kb" / "scripts" / "secretscan.py"
spec = importlib.util.spec_from_file_location("wb_core_secretscan_under_test", SCRIPTS / "secretscan.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
rep = lambda s, n: s * n  # noqa: E731


class CoreCopy(unittest.TestCase):
    def test_it_is_the_kb_copy(self):
        self.assertEqual((SCRIPTS / "secretscan.py").read_bytes(), KB_COPY.read_bytes())

    def test_values_of_the_new_shapes_are_found_and_names_stay_readable(self):
        for name, text, value in [
                ("api key header", "x-api" + "-key: " + rep("aB1", 8), rep("aB1", 8)),
                ("curl", "curl -s -u " + "svc:" + "Hq7rT2Kx9" + " https://example.com/x", "Hq7rT2Kx9"),
                ("json password", '{"pass' + 'word": "' + "pw1" + '"}', "pw1"),
                ("json password, escaped quote", '{"pass' + 'word": "' + 'ab\\"cd' + '"}', 'ab\\"cd'),
                ("storage signature", "https://demo.example.net/c?sv=1&" + "sig=" + rep("A1", 10) + "%3D", rep("A1", 10) + "%3D"),
                ("password option", "tool --pass" + "word=" + "Pw1x", "Pw1x")]:
            with self.subTest(name):
                self.assertEqual([text[a:b] for a, b in S.scan_text(text, values_only=True)], [value])

    def test_key_blocks_are_covered_through_their_last_line(self):
        head, tail = "-----BEGIN " + "RSA PRIVATE KEY-----", "-----END " + "RSA PRIVATE KEY-----"
        text = f"x\n{head}\n{rep('QUJD', 16)}\n{rep('QUJD', 16)}\n{tail}\ny"
        (a, b), = S.scan_text(text)
        self.assertEqual((text[:a], text[b:]), ("x\n", "\ny"))
        ppk = "PuTTY-User-Key-File-" + "3: ssh-ed25519"
        text = (f"{ppk}\nEncryption: none\nPublic-Lines: 1\n{rep('QUJD', 6)}\nPrivate-Lines: 1\n{rep('QUJD', 8)}\n"
                f"Private-MAC: {rep('ab', 16)}\ny")
        (a, b), = S.scan_text(text)
        self.assertEqual(text[b:], "\ny")

    def test_placeholders_and_ordinary_words_are_quiet(self):
        for text in ("api-key: required", "x-api-key: <your key>", "curl -u svc:$PW https://example.com", '{"password": ""}',
                     '{"password": "${DB_PW}"}', "docker login --password-stdin", "tool --password $PW", "https://example.com/?sig=abc"):
            with self.subTest(text):
                self.assertEqual(S.scan_text(text), [])

    def test_this_file_holds_no_credential_shaped_literal(self):
        self.assertEqual(S.findings(Path(__file__).read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
