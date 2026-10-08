"""Credential-value scanner: generic secret shapes only (vendor key formats, private-key headers, connection strings
with inline passwords, NAME=value assignments). Shared by the cred-check Stop hook and the KB save driver.

ONE pattern set, two copies: workbench-core/scripts/secretscan.py and workbench-kb/skills/save/scripts/secretscan.py
are byte-identical (a test enforces it), because the two plugins install to separate folders.

API:
  scan_text(text, values_only=False) -> sorted non-overlapping (start, end) spans of credential-shaped values
  findings(text) -> [{"line": n, "match": masked}]   (never the value)
  mask(s) -> first 4 characters + length
"""
import re

V = "(?P<v>)"                           # where the VALUE starts in a keyword-anchored pattern
REF = r"(?!(?i:vault|rotated|see-))"    # "token: see-vault-entry-X" names a credential, it is not one
# A lowercase hyphenated slug with a g-z letter is a NAME ("sk-agent-notes-2026"), never a key body.
SLUG = r"(?!(?=[a-z0-9-]*[g-z])[a-z]+(?:-[a-z0-9]+)+(?![\w.~+/=-]))"
_PLACEHOLDER = r"(?!<|\$|\{|\[|REDACTED|xxx|\.\.\.|your|changeme|example|os\.|process\.|settings\.|config\.|env\b)"

PATTERNS = [
    r"(?<![A-Za-z0-9])sk-" + SLUG + r"[a-zA-Z0-9_-]{20,}",            # OpenAI / Anthropic style
    r"(?:sk|rk)_live_[0-9a-zA-Z]{20,}", r"sk_test_[0-9a-zA-Z]{20,}",   # Stripe secret / restricted
    r"whsec_[A-Za-z0-9]{24,}",                                       # webhook signing secret
    r"xox[baprs]-[0-9A-Za-z-]{20,}",                                 # Slack token
    r"hooks\.slack\.com/services/T[0-9A-Z]{6,}/B[0-9A-Z]{6,}/[0-9A-Za-z]{20,}",   # Slack webhook
    r"discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]{30,}",     # Discord webhook
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",   # JWT
    r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])",           # AWS access key id
    r"(?i:aws_secret_access_key)\s*[:=]\s*[\"']?" + V + REF + r"[A-Za-z0-9/+=]{40}",
    r"gh[pousr]_[0-9a-zA-Z]{36}", r"github_pat_[0-9a-zA-Z_]{40,}",  # GitHub
    r"glpat-[0-9A-Za-z_-]{20,}",                                     # GitLab
    r"AIza[0-9A-Za-z_-]{35}",                                        # Google API key
    r'"type"\s*:\s*"service_account"',                               # GCP service-account JSON
    r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{30,}",                          # Hugging Face
    r"npm_[A-Za-z0-9]{36}",                                          # npm
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",                           # SSH / TLS private key
    r"(?i:AccountKey)=" + V + r"[A-Za-z0-9+/]{40,}={0,2}",           # Azure storage connection string
    r"(?i:\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://)[^:@\s/]+:" + V + r"(?!<|\$|\{)[^@\s]{6,}@",
    r"(?i:\bbearer[ \t]+)" + V + REF + SLUG + r"(?!<|\$|\{)[A-Za-z0-9._~+/=-]{24,}",
    # NAME ending in API_KEY / SECRET / TOKEN / PASSWORD = value, one line; the value holds a digit and is no
    # placeholder, code reference (process.env.X, os.environ), dotted attribute chain or elided stub.
    r"(?<![?&])(?i:\b[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|PASSWD|APP_KEY)\b[ \t]*[:=][ \t]*[\"']?)"
    + V + REF + _PLACEHOLDER + r"(?![A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_])"
    r"(?![A-Za-z0-9/+_.=-]*(?:\.\.\.|…|(?i:example|dummy|placeholder)))"
    r"(?=[A-Za-z0-9/+_.=-]*\d)[A-Za-z0-9/+_.=-]{16,}",
    # "password: <value>" written in prose or a list; the value ends the line and holds a digit or symbol.
    r"(?im:^[ \t]*[-*|]?[ \t]*(?:\*\*)?pass(?:word|phrase)(?:\*\*)?[ \t]*[:=|][ \t]*[\"']?" + V + REF +
    r"(?!<|\{|\$|\[|REDACTED|xxx|\.\.\.|(?-i:[A-Z][A-Z0-9_]{3,})\b)"
    r"(?=[^\s\"']*[0-9!@#%^&*])[^\s()\[\]{}<>`,;\"'|]{8,}[\"']?,?(?=[ \t]*(?:\|.*)?$))",
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
