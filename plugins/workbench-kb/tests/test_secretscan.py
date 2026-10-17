"""Tests for secretscan.py, the credential-shape scanner both plugins ship. Run:
    python -m unittest discover -s plugins/workbench-kb/tests

Every positive control is BUILT AT RUN TIME from fragments, so no file in the repository holds a credential-shaped string
(a literal one would trip the scanners that protect the repository, and this test along with them). The values are
fictional. Four things are checked:
  1. the copies of secretscan.py are byte-identical (the two plugins install to separate folders, so each carries one);
  2. every shape in PATTERNS has a control that its own pattern matches, and every control names a shape that still exists;
  3. the closed false-positive classes stay closed (slug names, env references, dotted code chains, placeholders);
  4. findings never print a value, spans are exact, and no input makes the scanner slow.
"""
import base64
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
REPO = PLUGIN.parent.parent
KB_COPY = PLUGIN / "scripts" / "secretscan.py"
CORE_COPY = REPO / "plugins" / "workbench-core" / "scripts" / "secretscan.py"
REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def load(path):
    spec = importlib.util.spec_from_file_location("wb_secretscan_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = load(KB_COPY)
PW = "Zq8!" + "vLm29xT"                      # a fictional password: letters, digits and a symbol
TOKEN20 = "A1b2C3d4" * 2 + "E5f6"           # 20 characters, mixed case with digits


def rep(s, n):
    return s * n


def basic():
    return base64.b64encode(b"fictional-user:Pa55w0rd-1234").decode()


# (name, marker, builder). `marker` is a substring of the pattern source that carries the shape: the test finds the pattern
# by it, so deleting the shape (or renaming it) fails the control instead of passing through a neighbour.
CONTROLS = [
    ("api key sk- prefix", "(?<![A-Za-z0-9])sk-", lambda: "sk-" + "or-v1-" + rep("9f", 32)),
    ("api key sk- in json", "(?<![A-Za-z0-9])sk-", lambda: '{"key": "sk-' + "or-v1-" + rep("9f", 32) + '"}'),
    ("payment live key", "(?:sk|rk)_live_", lambda: "sk_" + "live_" + rep("A1", 12)),
    ("payment restricted key", "(?:sk|rk)_live_", lambda: "rk_" + "live_" + rep("A1", 12)),
    ("payment test key", "sk_test_", lambda: "sk_" + "test_" + rep("A1", 12)),
    ("webhook signing secret", "whsec_", lambda: "whsec" + "_" + rep("a1", 14)),
    ("chat token", "xox[baprs]-", lambda: "xox" + "b-" + rep("1", 24)),
    ("chat webhook", r"hooks\.slack\.com", lambda: "https://hooks." + "slack.com/services/T" + "ABC123DEF/B" + "ABC123DEF/" + rep("a1B2", 6)),
    ("chat bot webhook", r"discord(?:app)?\.com/api/webhooks", lambda: "https://discord." + "com/api/webhooks/" + "123456789012345678/" + rep("A", 40)),
    ("signed web token", "eyJ", lambda: "ey" + "J" + rep("A", 24) + "." + rep("B", 24) + "." + rep("C", 24)),
    ("cloud access key id", "AKIA|ASIA", lambda: "AKIA" + rep("Z", 16)),
    ("cloud temporary key id", "AKIA|ASIA", lambda: "ASIA" + rep("Z", 16)),
    ("cloud secret", "aws_secret_access_key", lambda: "aws_secret" + "_access_key = " + rep("aB3/", 10)),
    ("code host token", "gh[pousr]_", lambda: "gh" + "p_" + rep("A", 36)),
    ("code host fine-grained token", "github_pat_", lambda: "github" + "_pat_" + rep("A1", 25)),
    ("code host group token", "glpat-", lambda: "gl" + "pat-" + rep("A1", 12)),
    ("maps key", "AIza", lambda: "AI" + "za" + rep("A1", 17) + "x"),
    ("service-account file", "service_account", lambda: '{"type": "service' + '_account"}'),
    ("model hub token", "hf_", lambda: "hf" + "_" + rep("aB", 16)),
    ("package registry token", "npm_", lambda: "npm" + "_" + rep("aB1", 12)),
    ("private key header", "PRIVATE KEY(?: BLOCK)?-----", lambda: "-----BEGIN " + "RSA PRIVATE KEY-----"),
    ("openssh key header", "PRIVATE KEY(?: BLOCK)?-----", lambda: "-----BEGIN " + "OPENSSH PRIVATE KEY-----"),
    ("pgp key header", "PRIVATE KEY(?: BLOCK)?-----", lambda: "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"),
    ("storage connection string", "AccountKey", lambda: "DefaultEndpointsProtocol=https;AccountName=demo;AccountKey=" + rep("aB1+", 11) + "=="),
    ("postgres url", r"(?:postgres(?:ql)?|mysql", lambda: "postgres://app:" + "s3cretpw9" + "@db.example.com/x"),
    ("mongodb url", r"(?:postgres(?:ql)?|mysql", lambda: "mongodb+srv://app:" + "s3cretpw9" + "@db.example.com/x"),
    ("bearer header", r"\bbearer", lambda: "Authorization: Bearer " + "see-" + rep("A1b2C3d4", 4)),
    ("bearer session token", r"\bbearer", lambda: "Bearer " + "sess-live-" + "a9b8c7d6e5f4a3b2c1d0e9f8"),
    ("named assignment", "API_KEY|SECRET|TOKEN", lambda: "API_TOKEN=" + rep("abc123", 4)),
    ("named assignment, prefix not exempt", "API_KEY|SECRET|TOKEN", lambda: "API_TOKEN=" + "vault" + "9f8a7b6c5d4e3f2a1b"),
    ("named assignment, env- value", "API_KEY|SECRET|TOKEN", lambda: "API_TOKEN=" + "env-9f8a7b6c5d4e3f2a1b"),
    ("named password assignment", "API_KEY|SECRET|TOKEN", lambda: "DB_PASSWORD=" + "Hq7rT2.Kx9mP4vZ8wQ1"),
    ("query-string key", "API_KEY|SECRET|TOKEN", lambda: "https://mcp.example.com/sse?api_key=" + rep("a1b2c3d4", 4)),
    ("quoted json key", "API_KEY|SECRET|TOKEN", lambda: '{"api_key": "' + TOKEN20 + '"}'),
    ("quoted json client secret", "API_KEY|SECRET|TOKEN", lambda: '"client_secret": "' + TOKEN20 + '"'),
    ("secret_key assignment", "SECRET_KEY|ACCESS_KEY", lambda: "SECRET_KEY = " + TOKEN20),
    ("access_key assignment", "SECRET_KEY|ACCESS_KEY", lambda: "ACCESS_KEY=" + TOKEN20),
    ("password line in a list", r"pass(?:word|phrase)(?:\*\*)?[ \t]*[:=|]", lambda: "- pass" + "word: " + "Fake-Passw0rd!"),
    ("password cell in a table", r"pass(?:word|phrase)(?:\*\*)?[ \t]*[:=|]", lambda: "| pass" + "word | " + "Fake-Passw0rd! |"),
    ("basic auth header", "basic[ \\t]+", lambda: "Authorization: " + "Basic " + basic()),
    ("basic auth header in a command", "basic[ \\t]+", lambda: 'curl -H "Authorization: ' + "Basic " + basic() + '"'),
    ("web url with a password", "ftps?|sftp", lambda: "https://" + "svc-user:" + PW + "@files.example.com/x"),
    ("transfer url with a password", "ftps?|sftp", lambda: "ftp://" + "u:" + "Abcdef12" + "@host.example.com"),
    ("connection string password", "(?:password|pwd)[ \\t]*=", lambda: "Server=db.example.com;Database=app;" + "Password=" + "Hq7rT2Kx9mP4;Encrypt=true"),
    ("connection string pwd", "(?:password|pwd)[ \\t]*=", lambda: "Data Source=x;User Id=app;" + "Pwd=" + PW),
    ("putty key header", "PuTTY-User-Key-File", lambda: "PuTTY-User-Key-File-" + "3: ssh-ed25519"),
    ("admin password in prose", "(?:admin|root|wifi", lambda: "Admin pass" + "word: " + PW),
    ("lead word, password for a thing", "(?:admin|root|wifi", lambda: "Wifi pass" + "word for the guest network: " + PW),
    ("password for a thing, no lead word", r"\bpass(?:word|phrase)[ \t]+for", lambda: "Pass" + "word for all rooms: " + PW),
    ("password is", r"[ \t]+is[ \t]+", lambda: "the db pass" + "word is " + PW + " today"),
    ("app password in groups", r"app[ _-]?password", lambda: "Mail app " + "password: " + "abcd efgh ijkl mnop"),
    # shapes found missing in the field
    ("private key block with a body", "PRIVATE KEY(?: BLOCK)?-----", lambda: "-----BEGIN " + "RSA PRIVATE KEY-----\n" + rep("QUJD" * 16 + "\n", 3) + "-----END " + "RSA PRIVATE KEY-----"),
    ("putty key file with a body", "PuTTY-User-Key-File", lambda: "PuTTY-User-Key-File-" + "3: ssh-ed25519\nEncryption: none\nPrivate-Lines: 1\n" + rep("QUJD", 8) + "\nPrivate-MAC: " + rep("ab", 16)),
    ("api key header", "x-api-key", lambda: "x-api" + "-key: " + rep("aB1", 8)),
    ("api key header, long without a digit", "x-api-key", lambda: "api-" + "key=" + rep("abcdefgh", 4)),
    ("curl user and password", r"\bcurl\b", lambda: "curl -s -u " + "svc:" + "Hq7rT2Kx9" + " https://example.com/x"),
    ("curl user and short password", r"\bcurl\b", lambda: "curl --user " + "svc:" + "pw1" + " https://example.com/x"),
    ("json password of any length", r'\"(?:password|passwd|pwd|secret|client_secret)\"', lambda: '{"pass' + 'word": "' + "pw1" + '"}'),
    ("json password with an escaped quote", r'\"(?:password|passwd|pwd|secret|client_secret)\"', lambda: '{"pass' + 'word": "' + 'ab\\"cd' + '"}'),
    ("storage sas signature", r"[?&;]sig=", lambda: "https://demo.blob.example.net/c?sv=2022-11-02&" + "sig=" + "FAKE%2Fsig%2B" + rep("A1", 10) + "%3D"),
    ("password option, short", "--(?:password|passwd", lambda: "tool --pass" + "word=" + "Pw1x"),
    ("password option, space form", "--(?:password|passwd", lambda: "tool --pass" + "word " + "Pw1x"),
]

NEGATIVES = [
    # the closed false-positive classes: do not reopen them
    ("slug name after sk-", "sk-team-notes-for-the-wiki-2026"),
    ("slug name, longer", "sk-release-planning-notes-for-the-quarter"),
    ("env placeholder with a colon", "API_TOKEN=env:API_TOKEN_2"),
    ("dotted code chain", "token = self.cfg.token_v2"),
    ("dotted chain, secret", "secret     = random_id.tunnel_secret.b64_std"),
    ("process env reference", "token = process.env.API_TOKEN"),
    ("process env, github token name", "GITHUB_TOKEN = process.env.GITHUB_TOKEN"),
    ("os environ reference", "db_pass = os.getenv('DB_PASS')"),
    ("angle placeholder", "API_TOKEN=<YOUR_TOKEN>"),
    ("shell variable", "password: ${DB_PASSWORD}"),
    ("ci secret reference", "TOKEN: ${{ secrets.X }}"),
    ("elided stub", 'accessToken = "sk-ant-oat01-..."'),
    ("example value", "workos.api_key = 'sk_example_123456789'"),
    ("prefix text only", "AKIA is the prefix of cloud key ids"),
    ("redacted line", "Admin password: `[REDACTED - see the vault]`."),
    ("redacted plain", "Password for the share: [REDACTED - see vault]"),
    ("masked reference", "rotated " + "tok_" + "x…" + "Zz9Q" + " and " + "tok_" + "x…(n chars) yesterday"),
    ("env var names only", "Mail works (app password = SMTP_USER/SMTP_APP_PASSWORD)."),
    ("query string with no key name", "https://example.org/dl?id=download&f=12345"),
    ("short model-hub prefix", "hf_" + "short"),
    ("glued model-hub prefix", "g" + "hf_" + rep("x", 32)),
    ("bearer placeholder", "Authorization: Bearer <token>"),
    ("bearer shell variable", "Authorization: Bearer $TOKEN"),
    ("database url without a password", "DATABASE_URL=postgres://user@dbhost:5432/mydb"),
    ("database url placeholder", 'DSN="postgresql://app:<PASS>@db:5432/app"'),
    # the new shapes' own negative controls
    ("basic scheme in prose", "Authorization: Basic authentication is used here"),
    ("basic placeholder", "Authorization: Basic <base64>"),
    ("basic shell variable", "Authorization: Basic $CREDS"),
    ("url password placeholder word", "https://user:password@example.com/x"),
    ("url password variable", "https://user:${PASS}@host/x"),
    ("url port, not a password", "https://example.com:8080/a@b"),
    ("ssh url with only a user", "git clone ssh://git@host/repo.git"),
    ("connection string placeholder", "Server=db;Database=app;Password=<pw>;"),
    ("connection string variable", "Server=db;Database=app;Password=${DB_PW};"),
    ("bare keyword with a short value", "password=pw1234"),
    ("prose: password is required", "the password is required"),
    ("prose: password is stored", "the password is stored in the vault entry"),
    ("prose: admin password required", "Admin password: required"),
    ("prose: a count, not a value", "login password: 8-12-characters"),
    ("prose: placeholder", "router password: <your-password-here>"),
    ("prose: shell variable", "db password: $DB_PASSWORD"),
    ("prose: env name", "server password: SERVER_PASSWORD_ENV"),
    ("prose: dotted chain", "db_password = config.db.password1"),
    ("prose: app password advice", "Use an app password from the mail provider, not your login."),
    ("secret_key from the environment", "SECRET_KEY = os.environ['SECRET_KEY']"),
    ("secret_key from settings", "SECRET_KEY = settings.SECRET_KEY"),
    ("json key that is only a count", '"max_tokens": 1024'),
    ("code that builds a json password", "x = '\"pass" + "word\": \"' + value + '\"'"),
    ("json key that merely starts with token", '"tokenizer": "abc12345678901234567"'),
    ("access key marked required", "ACCESS_KEY: required"),
    # the new shapes' own negative controls
    ("api-key word that is no key", "api-key: required"),
    ("api key header placeholder", "x-api-key: <your key>"),
    ("api key header variable", "x-api-key: ${API_KEY}"),
    ("curl password variable", "curl -u svc:$PW https://example.com/x"),
    ("curl user only", "curl -u svc https://example.com/x"),
    ("json empty password", '{"password": ""}'),
    ("json password placeholder", '{"password": "<pw>"}'),
    ("json password variable", '{"password": "${DB_PW}"}'),
    ("json key that only starts with password", '{"passwordless": "yes-please"}'),
    ("short sig", "https://example.com/?sig=abc"),
    ("password from stdin", "docker login --password-stdin"),
    ("password option placeholder", "tool --password <value>"),
    ("password option followed by a flag", "tool --password -x"),
    ("password option variable", "tool --password $PW"),
    ("private key header words in prose", "A private key begins with a BEGIN line, then base64 text."),
]


def single(i):
    """PATTERNS[i] compiled alone, the way _COMBINED builds it."""
    return re.compile(S.PATTERNS[i].replace(S.V, "(?P<v>)"))


class Copies(unittest.TestCase):
    def copies(self):
        found = []
        for d, dirs, files in os.walk(REPO):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            found += [Path(d) / f for f in files if f == "secretscan.py"]
        return found

    def test_the_two_plugin_copies_are_byte_identical(self):
        a, b = KB_COPY.read_bytes(), CORE_COPY.read_bytes()
        self.assertTrue(a, "the kb copy is empty")
        self.assertNotEqual(KB_COPY.resolve(), CORE_COPY.resolve(), "the two paths are one file")
        self.assertEqual(len(a), len(b), "the copies differ in size: edit both together")
        self.assertEqual(a, b, "the copies differ: edit both together, then copy one over the other")

    def test_every_copy_in_the_repository_is_identical(self):
        paths = self.copies()
        self.assertGreaterEqual(len(paths), 2, paths)
        base = KB_COPY.read_bytes()
        self.assertEqual([p.relative_to(REPO).as_posix() for p in paths if p.read_bytes() != base], [])


class Shapes(unittest.TestCase):
    def test_controls_are_built_at_run_time(self):
        """This file and its sibling hold no credential-shaped literal: the scanner finds nothing in their source."""
        for name in ("test_secretscan.py", "test_save_port.py"):
            p = HERE / name
            if not p.exists():
                self.assertFalse(REQUIRE, f"{name} is missing")
                continue
            self.assertEqual(S.findings(p.read_text(encoding="utf-8")), [], f"{name} holds a credential-shaped literal")

    def test_every_control_is_found(self):
        for name, marker, build in CONTROLS:
            with self.subTest(control=name):
                self.assertTrue(S.scan_text(build()), f"missed: {name}")

    def test_every_control_is_matched_by_the_pattern_that_carries_its_shape(self):
        for name, marker, build in CONTROLS:
            with self.subTest(control=name):
                idx = [i for i, p in enumerate(S.PATTERNS) if marker in p]
                self.assertTrue(idx, f"no pattern carries {marker!r}: the shape for {name!r} was removed")
                text = build()
                self.assertTrue(any(single(i).search(text) for i in idx), f"the pattern for {name!r} does not match its control")

    def test_every_pattern_has_a_control(self):
        built = [(name, build()) for name, _, build in CONTROLS]
        for i, p in enumerate(S.PATTERNS):
            with self.subTest(pattern=i, source=p[:50]):
                rx = single(i)
                self.assertTrue(any(rx.search(t) for _, t in built), "add a control for this shape to CONTROLS")

    def test_every_negative_is_quiet(self):
        for name, text in NEGATIVES:
            with self.subTest(negative=name):
                self.assertEqual(S.scan_text(text), [], f"false positive: {name}")

    def test_the_patterns_compile_alone_and_name_one_value_each(self):
        for i, p in enumerate(S.PATTERNS):
            self.assertLessEqual(p.count(S.V), 1, f"pattern {i} marks the value twice")
            single(i)


class Blocks(unittest.TestCase):
    """The body lines of a key are the secret: one span covers the block, and findings still print no value."""

    def test_a_pem_block_is_one_span_from_header_to_end_line(self):
        head, tail = "-----BEGIN " + "RSA PRIVATE KEY-----", "-----END " + "RSA PRIVATE KEY-----"
        body = "\n".join(rep("QUJD", 16) for _ in range(3))
        text = f"before\n{head}\n{body}\n{tail}\nafter"
        (a, b), = S.scan_text(text)
        self.assertEqual(text[a:b], f"{head}\n{body}\n{tail}")
        self.assertEqual([f["line"] for f in S.findings(text)], [2])

    def test_a_pem_block_without_an_end_line_runs_to_the_end_of_the_text(self):
        head = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
        text = f"x\n{head}\n{rep('QUJD', 16)}\n{rep('QUJD', 8)}"
        (a, b), = S.scan_text(text)
        self.assertEqual((text[:a], b), ("x\n", len(text)))

    def test_a_putty_file_is_covered_through_its_mac_line(self):
        head = "PuTTY-User-Key-File-" + "3: ssh-ed25519"
        text = f"{head}\nEncryption: none\nComment: fictional\nPublic-Lines: 1\n{rep('QUJD', 6)}\nPrivate-Lines: 1\n{rep('QUJD', 8)}\nPrivate-MAC: {rep('ab', 16)}\nafter"
        (a, b), = S.scan_text(text)
        self.assertEqual(text[b:], "\nafter")
        self.assertNotIn("after", text[a:b])

    def test_two_blocks_are_two_spans(self):
        head, tail = "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----", "-----END " + "PGP PRIVATE KEY BLOCK-----"
        text = f"{head}\n{rep('QUJD', 8)}\n{tail}\nmiddle\n{head}\n{rep('QUJD', 8)}\n{tail}"
        self.assertEqual(len(S.scan_text(text)), 2)

    def test_the_new_option_and_header_shapes_keep_the_name_readable(self):
        text = "curl -u svc:" + "Hq7rT2Kx9 https://example.com/x\nx-api" + "-key: aB1aB1aB1aB1\n" + '{"pass' + 'word": "pw1"} --pass' + "word=Pw1x"
        values = [text[a:b] for a, b in S.scan_text(text, values_only=True)]
        self.assertEqual(values, ["Hq7rT2Kx9", "aB1aB1aB1aB1", "pw1", "Pw1x"])


class Output(unittest.TestCase):
    def test_findings_never_print_a_value(self):
        for name, marker, build in CONTROLS:
            text = "line one\n" + build() + "\nline three"
            for f in S.findings(text):
                with self.subTest(control=name):
                    self.assertEqual(f["line"], 2)
                    self.assertRegex(f["match"], r"^.{0,4}\.\.\.\(\d+ chars\)$")
                    self.assertEqual(set(f), {"line", "match"})

    def test_mask_keeps_four_characters_and_the_length(self):
        self.assertEqual(S.mask("abcdefghij"), "abcd...(10 chars)")
        self.assertEqual(S.mask(None), "...(0 chars)")

    def test_values_only_keeps_the_name_and_spans_are_exact(self):
        value = rep("abc123", 4)
        text = "see API_TOKEN=" + value + " and more"
        (a, b), = S.scan_text(text, values_only=True)
        self.assertEqual(text[a:b], value)
        (a, b), = S.scan_text(text)
        self.assertEqual(text[a:b], "API_TOKEN=" + value)

    def test_spans_are_sorted_and_never_overlap(self):
        text = "\n".join(build() for _, _, build in CONTROLS)
        spans = S.scan_text(text, values_only=True)
        self.assertGreaterEqual(len(spans), len(CONTROLS) // 2)
        self.assertEqual(spans, sorted(spans))
        self.assertTrue(all(x[1] <= y[0] for x, y in zip(spans, spans[1:])))

    def test_two_values_on_one_line_are_both_found(self):
        text = "a " + "AKIA" + rep("Z", 16) + " b " + "gh" + "p_" + rep("A", 36)
        self.assertEqual(len(S.scan_text(text)), 2)

    def test_empty_input(self):
        self.assertEqual(S.scan_text(""), [])
        self.assertEqual(S.scan_text(None), [])


class CommandLine(unittest.TestCase):
    def run_cli(self, *args):
        r = subprocess.run([sys.executable, str(KB_COPY), *map(str, args)], capture_output=True, text=True, encoding="utf-8")
        return r.returncode, r.stdout

    def test_exit_codes_and_masked_output(self):
        with tempfile.TemporaryDirectory() as d:
            clean, dirty = Path(d) / "clean.md", Path(d) / "dirty.md"
            clean.write_text("API_TOKEN=<YOUR_TOKEN>\nnothing here\n", encoding="utf-8")
            dirty.write_text("one\ntwo " + "AKIA" + rep("Z", 16) + "\n", encoding="utf-8")
            self.assertEqual(self.run_cli(clean), (0, "CLEAN\n"))
            rc, out = self.run_cli(clean, dirty)
            self.assertEqual(rc, 1)
            self.assertRegex(out, r"dirty\.md:2: AKIA\.\.\.\(20 chars\)")
            self.assertNotIn("ZZZZ", out, "the value must never be printed")
            self.assertNotIn("CLEAN", out)
            rc, out = self.run_cli(clean, Path(d) / "missing.md")
            self.assertEqual(rc, 2)
            self.assertIn("NOT scanned", out)
            self.assertNotIn("CLEAN", out, "an unread file is never reported clean")
            self.assertEqual(self.run_cli(dirty, Path(d) / "missing.md")[0], 2)
        self.assertEqual(self.run_cli()[0], 2)


class Speed(unittest.TestCase):
    def test_hostile_input_stays_fast(self):
        """200 KB inputs built to stress the optional and repeated parts of the patterns; each finishes well under 5 s."""
        for name, text in {
            "equals": "=" * 200_000, "pairs": "a=" * 100_000, "server pairs": "Server=" + "x=" * 50_000,
            "pass words": "pass " * 40_000, "semicolon pairs": "key=val;" * 25_000, "long scheme": "https://" + "a" * 100_000,
            "spaced pairs": "a b=" * 50_000 + ";password=x", "dashes": "sk-" + "a-" * 100_000, "bearer": "bearer " + "a" * 100_000,
            "colons": "https://" + "a:" * 50_000, "quotes": '"' * 100_000 + "token:",
            "curl words": "curl " * 40_000, "curl flags": "curl -u " * 25_000, "key headers": "x-api-key: " * 20_000,
            "begin lines": "-----BEGIN " + "PRIVATE KEY-----" * 8_000, "putty headers": "PuTTY-User-" + "Key-File-2:" * 8_000,
            "json password": '"password": "' + "\\" * 100_000, "password options": "--password " * 20_000, "sig": "&sig=" * 40_000,
        }.items():
            with self.subTest(input=name):
                t = time.monotonic()
                S.scan_text(text)
                self.assertLess(time.monotonic() - t, 5.0)


if __name__ == "__main__":
    unittest.main()
