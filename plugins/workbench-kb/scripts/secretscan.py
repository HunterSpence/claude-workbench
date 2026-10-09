"""Credential-value scanner: generic secret shapes only (public vendor key formats, private-key headers, connection
strings and URLs with inline passwords, Basic and Bearer headers, NAME=value assignments, passwords written in prose).
Shared by the cred-check Stop hook, the guards and the KB save driver. Every pattern has a positive control in
plugins/workbench-kb/tests/test_secretscan.py, built at run time so no test file holds a credential-shaped string.

ONE pattern set, two copies: workbench-core/scripts/secretscan.py and workbench-kb/scripts/secretscan.py
are byte-identical (a test enforces it), because the two plugins install to separate folders.

API:
  scan_text(text, values_only=False) -> sorted non-overlapping (start, end) spans of credential-shaped values
  findings(text) -> [{"line": n, "match": masked}]   (never the value)
  mask(s) -> first 4 characters + length
CLI:  python secretscan.py FILE [FILE ...]   prints FILE:LINE: <masked> per finding (never the value) or CLEAN;
      exit 0 clean, 1 findings, 2 a file could not be read (it was NOT scanned, so it is never reported clean)
"""
import re

V = "(?P<v>)"                           # where the VALUE starts in a keyword-anchored pattern
# A slug of short lowercase words with a g-z letter is a NAME ("sk-team-notes-2026"), never a key body. A segment of
# 12+ characters (a hex or base62 body) makes it a key again, so "sk-or-v1-<hex>" and "sess-live-<body>" are caught.
SLUG = r"(?!(?=[a-z0-9-]*[g-z])[a-z]{1,11}(?:-[a-z0-9]{1,11})+(?![\w.~+/=-]))"
_PLACEHOLDER = r"(?!<|\$|\{|\[|REDACTED|xxx|\.\.\.|your|changeme|example|os\.|process\.|settings\.|config\.|env[.:\[])"

PATTERNS = [
    r"(?<![A-Za-z0-9])sk-" + SLUG + r"[a-zA-Z0-9_-]{20,}",            # OpenAI / Anthropic style
    r"(?:sk|rk)_live_[0-9a-zA-Z]{20,}", r"sk_test_[0-9a-zA-Z]{20,}",   # Stripe secret / restricted
    r"whsec_[A-Za-z0-9]{24,}",                                       # webhook signing secret
    r"xox[baprs]-[0-9A-Za-z-]{20,}",                                 # Slack token
    r"hooks\.slack\.com/services/T[0-9A-Z]{6,}/B[0-9A-Z]{6,}/[0-9A-Za-z]{20,}",   # Slack webhook
    r"discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]{30,}",     # Discord webhook
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",   # JWT
    r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])",           # AWS access key id
    r"(?i:aws_secret_access_key)\s*[:=]\s*[\"']?" + V + r"[A-Za-z0-9/+=]{40}",
    r"gh[pousr]_[0-9a-zA-Z]{36}", r"github_pat_[0-9a-zA-Z_]{40,}",  # GitHub
    r"glpat-[0-9A-Za-z_-]{20,}",                                     # GitLab
    r"AIza[0-9A-Za-z_-]{35}",                                        # Google API key
    r'"type"\s*:\s*"service_account"',                               # GCP service-account JSON
    r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{30,}",                          # Hugging Face
    r"npm_[A-Za-z0-9]{36}",                                          # npm
    # SSH / TLS / PGP private key: the whole block, not the header alone (the body lines are the secret); a block with no END
    # line runs to the end of the text.
    r"(?s:-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\Z))",
    r"(?i:AccountKey)=" + V + r"[A-Za-z0-9+/]{40,}={0,2}",           # Azure storage connection string
    r"(?i:\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://)[^:@\s/]+:" + V + r"(?!<|\$|\{)[^@\s]{6,}@",
    r"(?i:\bbearer[ \t]+)" + V + SLUG + r"(?!<|\$|\{)[A-Za-z0-9._~+/=-]{24,}",
    # NAME ending in API_KEY / SECRET / TOKEN / PASSWORD (or SECRET_KEY, ACCESS_KEY, PRIVATE_KEY, ...) = value, one line,
    # the NAME optionally quoted as a JSON key; the value holds a digit and is no placeholder, code reference
    # (process.env.X, os.environ), lowercase attribute chain or elided stub. A query-string key (?api_key=, &token=) counts too.
    r"(?i:\b[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|PASSWD|APP_KEY|SECRET_KEY|ACCESS_KEY|PRIVATE_KEY|SIGNING_KEY"
    r"|ENCRYPTION_KEY|AUTH_KEY)\b[\"']?[ \t]*[:=][ \t]*[\"']?)"
    + V + _PLACEHOLDER + r"(?![a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+(?![\w/+=.-]))"
    r"(?![A-Za-z0-9/+_.=-]*(?:\.\.\.|…|(?i:example|dummy|placeholder)))"
    r"(?=[A-Za-z0-9/+_.=-]*\d)[A-Za-z0-9/+_.=-]{16,}",
    # "password: <value>" written in prose or a list; the value ends the line and holds a digit or symbol.
    r"(?im:^[ \t]*[-*|]?[ \t]*(?:\*\*)?pass(?:word|phrase)(?:\*\*)?[ \t]*[:=|][ \t]*[\"']?" + V +
    r"(?!<|\{|\$|\[|REDACTED|xxx|\.\.\.|(?-i:[A-Z][A-Z0-9_]{3,})\b)"
    r"(?=[^\s\"']*[0-9!@#%^&*])[^\s()\[\]{}<>`,;\"'|]{8,}[\"']?,?(?=[ \t]*(?:\|.*)?$))",
    # ---- vendor-neutral shapes (each has a run-time positive control in test_secretscan.py) ----
    # Authorization: Basic <base64 of user:password>; the value holds a digit, so prose after the word "Basic" is not a hit.
    r"(?i:\bauthorization[ \t]*[:=][ \t]*[\"']?basic[ \t]+)" + V + r"(?!<|\$|\{|\[|REDACTED|xxx|\.\.\.)"
    r"(?=[A-Za-z0-9+/]*\d)[A-Za-z0-9+/]{16,}={0,2}",
    # user:password@ in the URL of a web, file-transfer or mail service (the database schemes are above); the password
    # holds a digit or symbol, so "user:password@host" in documentation is no hit.
    r"(?i:\b(?:https?|ftps?|sftp|ssh|smtps?|imaps?|pop3s?|ldaps?|wss?)://)[^:@\s/]+:" + V + r"(?!<|\$|\{|\[)"
    r"(?=[^@\s/]*[0-9!#%^&*])[^@\s/]{8,}@",
    # ...;Password=value; in an ADO/ODBC style connection string: a key=value pair must come before it on the line
    r"(?i:\b\w[\w ]{0,40}=[^;\n]{0,200};[ \t]*(?:password|pwd)[ \t]*=[ \t]*)" + V + _PLACEHOLDER +
    r"(?![a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+(?![\w/+=.-]))(?=[^;\s\"']*[0-9!@#%^&*])[^;\s\"'<>{}]{8,}",
    r"(?s:PuTTY-User-Key-File-[0-9]+:.*?(?:Private-MAC:[^\n]*|\Z))",   # PuTTY private key file: header through Private-MAC
    # "<admin|root|wifi|db|...> password: value" and "password for <thing>: value" in prose; the value is 8+ characters with
    # a digit or symbol AND a capital or symbol, so a phrase such as "8-12-characters" is no hit.
    r"(?i:\b(?:admin|root|wifi|ssid|router|login|db|database|ssh|vpn|server|account|service)[ \t_-]{0,3}"
    r"pass(?:word|phrase)[ \t]*(?:for[^:=\n]{0,40})?[:=][ \t]*[\"'`]?)" + V + _PLACEHOLDER +
    r"(?![a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+(?![\w/+=.-]))(?!(?-i:[A-Z][A-Z0-9_]{3,})\b)"
    r"(?=[^\s\"'|`]*[0-9!@#%^&*])(?=[^\s\"'|`]*[A-Z!@#%^&*])[^\s\"'|`()\[\]{}<>,;]{8,}",
    r"(?i:\bpass(?:word|phrase)[ \t]+for[^:=\n]{1,40}[:=][ \t]*[\"'`]?)" + V + _PLACEHOLDER + r"(?!(?-i:[A-Z][A-Z0-9_]{3,})\b)"
    r"(?=[^\s\"'|`]*[0-9!@#%^&*])(?=[^\s\"'|`]*[A-Z!@#%^&*])[^\s\"'|`()\[\]{}<>,;]{8,}",
    r"(?i:\bpass(?:word|phrase)[ \t]+is[ \t]+[\"'`]?)" + V + _PLACEHOLDER + r"(?!(?-i:[A-Z][A-Z0-9_]{3,})\b)"
    r"(?=[^\s\"'|`]*[0-9!@#%^&*])(?=[^\s\"'|`]*[A-Z!@#%^&*])[^\s\"'|`()\[\]{}<>,;]{8,}",
    r"(?i:app[ _-]?password[ \t]*[:=|]?[ \t]*)" + V + r"[a-z]{4} [a-z]{4} [a-z]{4} [a-z]{4}\b",   # 16-letter app password in 4 groups
    # ---- shapes found missing in the field (each has a run-time positive control in test_secretscan.py) ----
    # an opaque API-key header or option: the value holds a digit or runs 24+ characters, so "api-key: required" is no hit
    r"(?i:\b(?:x-api-key|api-key|x-auth-token|x-functions-key|ocp-apim-subscription-key)[ \t]*[:=][ \t]*[\"']?)" + V + _PLACEHOLDER +
    r"(?=[^\s\"',;]*\d|[^\s\"',;]{24})[^\s\"',;]{8,}",
    # curl with -u (or --user) and a user:password pair: the password, of any length
    r"(?i:\bcurl\b[^\n]{0,200}?[ \t](?:-u|--user)[ \t=]+[\"']?[^\s:\"']+:)" + V + _PLACEHOLDER + r"[^\s\"']+",
    # a JSON "password" of any length, including a value with an escaped quote in it (not code that builds the JSON: '...' + x)
    r"(?i:\"(?:password|passwd|pwd|secret|client_secret)\"[ \t]*:[ \t]*\")" + V + _PLACEHOLDER + r"(?!')(?:[^\"\\\n]|\\.)+",
    # an Azure storage SAS signature in a URL
    r"(?i:[?&;]sig=)" + V + r"[A-Za-z0-9%+/=_-]{16,}",
    # a password option with its value after = or a space (not the -stdin form, not another flag, not a placeholder), 3+ characters
    r"(?i:(?<![\w-])--(?:password|passwd|api-key|apikey|secret-key|client-secret|access-key)(?:=|[ \t]+)[\"']?)" + V +
    r"(?!-|<|\$|\{|\[|REDACTED|xxx|\.\.\.)[^\s\"']{3,}",
]
_COMBINED = re.compile("|".join(f"(?:{p.replace(V, f'(?P<v{i}>)')})" for i, p in enumerate(PATTERNS)))


def scan_text(text, values_only=False):
    """Sorted, non-overlapping (start, end) spans. values_only: for keyword-anchored patterns, the span starts at the
    value, so masking keeps "API_TOKEN=" and the reader still knows WHICH credential it was."""
    spans = []
    for m in _COMBINED.finditer(text or ""):
        a = m.start()
        if values_only:
            starts = [m.start(g) for g, v in m.groupdict().items() if v is not None and m.start(g) >= 0]
            a = min(starts) if starts else a
        if m.end() > a and (not spans or a >= spans[-1][1]):
            spans.append((a, m.end()))
    return spans


def mask(s):
    s = s or ""
    return f"{s[:4]}...({len(s)} chars)"


def findings(text):
    out = []
    for a, b in scan_text(text, values_only=True):
        out.append({"line": text.count("\n", 0, a) + 1, "match": mask(text[a:b])})
    return out


def main(argv):
    if not argv:
        print("usage: secretscan.py FILE [FILE ...]")
        return 2
    rc = 0
    for f in argv:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as e:
            print(f"{f}: NOT scanned ({e.strerror or type(e).__name__})")
            rc = 2
            continue
        hits = findings(text)
        for h in hits:
            print(f"{f}:{h['line']}: {h['match']}")
        rc = max(rc, 1 if hits else 0)
    if rc == 0:
        print("CLEAN")
    return rc


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
