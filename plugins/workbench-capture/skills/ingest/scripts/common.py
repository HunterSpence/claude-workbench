"""Shared pieces of the ingest skill: paths and settings, the captured-file writer (interface I5), the sanitiser,
pacing, run reports, the find CLI wrapper and the thread writer. Standard library only."""
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

VERSION = "0.3.0"
HERE = Path(__file__).resolve().parent
FRONT = ("source", "url", "title", "author", "modified", "captured_at", "labels", "scope")
EXTRA = ("thread_id", "message_ids", "from", "to", "cc", "received", "meeting_id", "organizer", "attendees", "start",
         "end", "transcript_source")
DIGEST_H = "## Digest (AI)"
MAX_PATH = 240
MAX_BODY = 2_000_000

clock = lambda: datetime.now(timezone.utc)  # tests replace this  # noqa: E731

# What a stop tells the user to ask for. references/asks.md carries the same texts and a test keeps them equal.
ASKS = {
    "outlook-guard": "Outlook refused or prompted for a protected mail property while a read-only script read my own cached "
                     "mailbox. Please tell me whether a local read-only script may read my own cached mailbox through classic "
                     "Outlook, and what the programmatic-access (Object Model Guard) policy is on this device. Nothing was "
                     "changed and the run did not try another way.",
    "transcripts-disabled": "Please ask the Teams administrator to turn on Microsoft Graph access to meeting transcripts "
                            "(Teams admin center, Meetings, Meeting settings, Transcript API access; or the "
                            "EnableGraphTranscriptAccess setting of the Teams meeting configuration) and, if wanted, speaker "
                            "attribution (EnableAttributedTranscripts). To see the tenant setting: Get-CsTeamsMeetingConfiguration | "
                            "Select EnableGraphTranscriptAccess, EnableAttributedTranscripts. Until then, download the transcript "
                            "from the meeting recap yourself and drop it in the drop folder.",
    "admin-consent": "Please ask the Entra administrator to approve a read-only public-client app registration for me only, "
                     "with the delegated permissions User.Read, offline_access, Calendars.Read, OnlineMeetings.Read, "
                     "OnlineMeetingTranscript.Read.All (and Mail.Read for mail) and the redirect address http://localhost. "
                     "And, if I hold a Microsoft 365 Copilot licence, also the delegated permission OnlineMeetingAiInsight.Read.All "
                     "for meeting AI insights (admin consent).",
}


class Stop(Exception):
    """A guard, policy or tenant gate said no: the run ends with exit 3 and the ask-IT text, with no retry by another route."""

    def __init__(self, kind, reason, ask_key):
        super().__init__(reason)
        self.kind, self.reason, self.ask = kind, reason, ASKS[ask_key]


def fwd(p):
    return str(p).replace("\\", "/")


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text("utf-8-sig"))
    except (OSError, ValueError):
        return default


# ---- paths and settings -----------------------------------------------------------------------------------------
class Paths:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        home = env.get("WORKBENCH_HOME") or os.path.join(env.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"), "workbench")
        self.wb = Path(fwd(home))
        self.cfg = load_json(self.wb / "config.json", {})
        self.cap = self.wb / "capture"
        self.runs = self.cap / "runs"
        self.settings_file = self.cap / "ingest.json"
        self.drop_done = self.cap / "drop-done"
        self.state = self.wb / "state" / "ingest"
        self.data = Path(fwd(self.cfg.get("data_root") or os.path.join(os.path.expanduser("~"), "Workbench")))
        self.captured = self.data / "captured"
        self.drop = self.captured / "_drop" / "meetings"
        self.kb = Path(fwd(self.cfg.get("kb_root") or self.data / "kb"))


DEFAULTS = {"graph_client_id": "", "graph_tenant_id": "", "mail_folders": ["Inbox", "Sent Items"], "digest_model": None,
            "digest_max_per_day": 30, "digest_window_days": 14, "infosec_ack": None}


def load_settings(P):
    return {**DEFAULTS, **{k: v for k, v in load_json(P.settings_file, {}).items() if k in DEFAULTS}}


def save_settings(P, s):
    atomic_write(P.settings_file, json.dumps(s, indent=2) + "\n")


# ---- sanitiser --------------------------------------------------------------------------------------------------
_INVISIBLE = re.compile("[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f\U000e0100-\U000e01ef]")
_CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_URL = re.compile(r"\b(?:https?|ftp)://[^\s<>\"')\]]+", re.I)
_HIDDEN = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em|rem|%)?\s*(?:;|$)|mso-hide\s*:\s*all|"
                     r"opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)|(?:max-)?height\s*:\s*0(?:px|pt)?\s*(?:;|$)", re.I)
_BLOCK = {"p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr",
          "section", "article", "header", "footer"}
_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}
_SKIP = {"script", "style", "head", "title", "template", "noscript", "svg", "object", "iframe", "canvas"}


def _host(u):
    try:
        return urllib.parse.urlsplit(u).hostname or "unknown"
    except ValueError:
        return "unknown"


class _Text(HTMLParser):
    """HTML to text: hidden elements dropped, links inert, quoted-history blockquotes dropped when asked."""

    def __init__(self, drop_quotes):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.drop_quotes, self.anchor = [], [], drop_quotes, None

    def _hidden(self):
        return any(h for _, h in self.stack)

    def _nl(self, tag):
        if tag in _BLOCK and not self._hidden():
            self.out.append("\n")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in _VOID:
            return self._nl(tag)
        hid = tag in _SKIP or "hidden" in a or bool(_HIDDEN.search(a.get("style") or "")) or (self.drop_quotes and tag == "blockquote")
        self.stack.append((tag, hid))
        self._nl(tag)
        if tag == "a" and not self._hidden():
            self.anchor = (a.get("href") or "", len(self.out))

    def handle_startendtag(self, tag, attrs):
        self._nl(tag)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor and not self._hidden():
            href, at = self.anchor
            host = _host(href) if re.match(r"https?://", href, re.I) else None
            shown = "".join(self.out[at:])
            if host and host.lower() not in shown.lower():
                self.out.append(f" [link: {host}]")
            self.anchor = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        self._nl(tag)

    def handle_data(self, data):
        if not self._hidden():
            self.out.append(data)


def clean_text(s):
    """Strip invisible and control characters, render every web address inert, and defuse anything that could forge
    our own markers (HTML comments, a digest heading, a closing untrusted tag)."""
    s = _CTRL.sub("", _INVISIBLE.sub("", s))
    s = _URL.sub(lambda m: f"[link: {_host(m.group())}]", s)
    s = s.replace("<!--", "&lt;!--")
    s = re.sub(r"<(/?\s*untrusted)", r"&lt;\1", s, flags=re.I)
    s = re.sub(r"(?m)^(#+\s*Digest \(AI\))", r"\\\1", s)
    return s


def sanitize(text, html=False, drop_quotes=False):
    if html:
        p = _Text(drop_quotes)
        p.feed(text)
        p.close()
        text = "".join(p.out)
    text = clean_text(text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " "))
    text = "\n".join(re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def inline(s):
    return re.sub(r"\s+", " ", clean_text(str(s or ""))).strip()


# ---- pacing -----------------------------------------------------------------------------------------------------
class Pacer:
    """Local mailbox reads and Graph calls at a human pace: a minimum gap between calls and a jittered pause per batch."""

    def __init__(self, gap=0.05, pause=2.0, sleep=time.sleep):
        self.gap, self.pause, self.sleep, self.last = gap, pause, sleep, 0.0

    def tick(self):
        wait = self.gap - (time.monotonic() - self.last)
        if wait > 0:
            self.sleep(wait)
        self.last = time.monotonic()

    def batch(self):
        self.sleep(self.pause * (1 + random.random() / 2))


# ---- run reports ------------------------------------------------------------------------------------------------
def new_report(kind, experimental=False):
    return {"version": 1, "tool": f"ingest {VERSION}", "kind": kind, "experimental": experimental,
            "label": "experimental" if experimental else None, "started": iso(clock()), "finished": None, "status": "running",
            "exit": None, "stop": None, "error": None, "counts": {}, "entries": [], "skipped": [], "notes": []}


def save_report(P, rep, exit_code):
    rep.update(finished=iso(clock()), exit=exit_code)
    if rep["status"] == "running":
        rep["status"] = "ok" if exit_code == 0 else "error"
    P.runs.mkdir(parents=True, exist_ok=True)
    for n in range(1000):  # a second run in the same second takes the next second's name, so names still sort by time
        f = P.runs / f"{iso(clock() + timedelta(seconds=n)).replace('-', '').replace(':', '')}-ingest.json"
        try:
            with open(f, "x", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(rep, indent=2) + "\n")
            return f
        except FileExistsError:
            continue
    raise OSError("could not name a run report")


# ---- find CLI (interface I4) ------------------------------------------------------------------------------------
class Find:
    def __init__(self, P, env=None):
        env = os.environ if env is None else env
        cands = [env.get("WORKBENCH_FIND_CLI"), P.wb / "kit/plugins/workbench-core/skills/find/scripts/doc_index.py",
                 HERE.parents[3] / "workbench-core/skills/find/scripts/doc_index.py"]
        self.cli = next((str(c) for c in cands if c and os.path.exists(c)), None)
        self.py = P.cfg.get("knowledge_python") or sys.executable
        self.env = env

    def _run(self, *args):
        if not self.cli:
            raise RuntimeError("the find CLI was not found (set WORKBENCH_FIND_CLI or install the workbench-core plugin)")
        r = subprocess.run([self.py, self.cli, *args, "--json"], capture_output=True, text=True, encoding="utf-8", timeout=180,
                           env={**self.env, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        if r.returncode:
            raise RuntimeError(f"find {args[0]} failed (exit {r.returncode})")
        return json.loads(r.stdout)

    def label(self, f):
        return self._run("label", str(f))["label"]

    def convert(self, f):
        return self._run("convert", str(f))


# ---- captured files (interface I5) ------------------------------------------------------------------------------
_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_DEVICE = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)


def safe_name(text, fallback="Meeting", max_len=60):
    """A file-name part from outside text (a meeting subject anyone can set): separators, drive colons, wildcard and control
    characters become spaces, `..` collapses, leading and trailing dots and spaces go, the length is capped, and what is left
    must not be empty or a Windows device name. Use with safe_join: the name alone is not the whole defence."""
    s = _INVISIBLE.sub("", str(text or ""))
    s = re.sub(r"\.{2,}", ".", _BAD_NAME.sub(" ", s))
    s = re.sub(r"\s+", " ", s)[:max_len].strip(" .")
    return fallback if not s or _DEVICE.match(s) else s


def safe_join(folder, name):
    """folder/name, resolved; refused unless the result sits directly inside folder."""
    folder = Path(folder).resolve()
    p = (folder / name).resolve()
    if Path(name).name != name or p.parent != folder:
        raise ValueError(f"refusing to write outside {folder}")
    return p


def slug(s, mx=60):
    v = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", str(s or "")).lower()).strip("-")[:mx].rstrip("-")
    return v or "untitled"


def clean_url(u):
    return re.split(r"[?#]", str(u), maxsplit=1)[0]


def _js(v):
    return json.dumps(v, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029").replace("\x85", "\\u0085")


def render(item, source, captured_at):
    fm = {"source": source, "url": clean_url(item["url"]), "title": re.sub(r"\s+", " ", str(item.get("title") or "")).strip()[:300],
          "author": item.get("author"), "modified": item.get("modified"), "captured_at": captured_at,
          "labels": item.get("labels") or [], "scope": item.get("scope") or ""}
    for k, v in (item.get("extra") or {}).items():
        if k not in EXTRA:
            raise ValueError(f"unknown front matter key: {k}")
        fm[k] = v
    body = str(item.get("body") or "")[:MAX_BODY].strip()
    return "---\n" + "\n".join(f"{k}: {_js(fm[k])}" for k in [*FRONT, *[k for k in fm if k not in FRONT]]) + f"\n---\n\n{body}\n"


def read_file(path):
    """(front matter dict or None, body) of a captured file."""
    lines = Path(path).read_text("utf-8").split("\n")
    if not lines or lines[0].strip() != "---":
        return None, "\n".join(lines)
    end = next((i for i, ln in enumerate(lines) if i and ln.strip() == "---"), None)
    if end is None:
        return None, "\n".join(lines)
    fm = {}
    for ln in lines[1:end]:
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
        if m:
            try:
                fm[m.group(1)] = json.loads(m.group(2))
            except ValueError:
                fm[m.group(1)] = m.group(2)
    return fm, "\n".join(lines[end + 1:]).lstrip("\n")


def split_digest(raw):
    """(text without the digest section, the digest section or None)."""
    head, sep, tail = raw.partition(f"\n{DIGEST_H}\n")
    return head, (tail if sep else None)


def target_path(base, source, dir_slug, title, url, date):
    h = hashlib.sha1(clean_url(url).encode()).hexdigest()[:8]
    d = f"{fwd(base)}/{source}/{dir_slug}"
    room = max(1, min(60, MAX_PATH - len(f"{d}/{date}--{h}.md")))
    full = f"{d}/{date}-{slug(title, room)}-{h}.md"
    if len(full) > MAX_PATH:
        raise ValueError(f"captured path would be {len(full)} characters (limit {MAX_PATH}); use a shorter data folder")
    return Path(full), h


class PathIndex:
    """hash -> existing files of one source, scanned once, so a rerun finds its own file instead of making another."""

    def __init__(self, P, source):
        self.root, self.m = P.captured / source, None

    def find(self, h, url):
        if self.m is None:
            self.m = {}
            for d in (self.root.iterdir() if self.root.is_dir() else []):
                for f in (d.iterdir() if d.is_dir() else []):
                    mm = re.search(r"-([0-9a-f]{8})\.md$", f.name)
                    if mm:
                        self.m.setdefault(mm.group(1), []).append(f)
        for f in self.m.get(h, []):
            fm, _ = read_file(f)
            if fm and fm.get("url") == clean_url(url):
                return f
        return None

    def add(self, h, f):
        self.m.setdefault(h, []).append(f)


def put(P, pidx, source, item, dir_slug, date):
    """Write one captured item. A file for the same url is rewritten in place; identical content writes nothing, and a
    rewrite drops the AI digest (it described the old text). Returns the run-report entry plus `status`."""
    url = clean_url(item["url"])
    h = hashlib.sha1(url.encode()).hexdigest()[:8]
    path = pidx.find(h, url)
    new = path is None
    if new:
        path, _ = target_path(P.captured, source, dir_slug, item.get("title"), url, date)
        if (P.captured / source).resolve() != path.resolve().parents[1]:  # slugs are [a-z0-9-] already; belt and braces
            raise ValueError("refusing to write outside the captured folder")
    status, now = "written", iso(clock())
    if not new:
        raw = path.read_text("utf-8")
        old_fm, _ = read_file(path)
        text = render(item, source, (old_fm or {}).get("captured_at") or now)
        if split_digest(raw)[0] == text:
            status = "unchanged"
    if status == "written":
        text = render(item, source, now)
        atomic_write(path, text)
        if new:
            pidx.add(h, path)
    return {"url": url, "path": fwd(path), "sha256": hashlib.sha256(text.encode()).hexdigest(), "expires": None, "status": status}


# ---- mail threads -----------------------------------------------------------------------------------------------
_MARK = re.compile(r"^<!-- wb:msg (\{.*\}) -->$", re.M)
_QUOTE_START = re.compile(r"^(>|-{2,}\s*(original message|forwarded message)\s*-{2,}|on .{4,200} wrote:\s*$|_{8,}\s*$)", re.I)


def norm_subject(s):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    while True:
        t = re.sub(r"^(re|fw|fwd|aw|wg|sv|vs|antw)\s*:\s*", "", s, flags=re.I)
        if t == s:
            return s or "(no subject)"
        s = t


def strip_quoted(text):
    """Cut quoted history: a quote marker line, 'On ... wrote:', an original-message line, or a From/Sent header block."""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        hdr = re.match(r"^from:\s", ln, re.I) and any(re.match(r"^(sent|date):\s", x, re.I) for x in lines[i + 1:i + 6])
        if _QUOTE_START.match(ln.strip()) or hdr:
            return "\n".join(lines[:i]).strip() or text
    return text


def _head(meta):
    return json.dumps(meta, ensure_ascii=True, separators=(",", ":"), sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e")


def message_raw(m):
    """The readable section of one message (everything after its marker line)."""
    out = [f"## {m.get('received') or 'undated'} - {inline(m.get('from')) or 'unknown sender'}", ""]
    for k, lab in (("to", "To"), ("cc", "Cc")):
        if m.get(k):
            out.append(f"{lab}: " + "; ".join(inline(x) for x in m[k]))
    out.append("")
    if m.get("labels") or m.get("withheld"):
        out.append("_Content withheld: this message carries a sensitivity label or rights management._")
    else:
        out.append(m.get("text") or "")
        for a in m.get("attachments") or []:
            out += ["", f"### Attachment: {inline(a['name'])}", "", a["markdown"]]
    return "\n".join(out).strip("\n")


def _union(seq):
    seen, out = set(), []
    for x in seq:
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out[:200]


def write_thread(P, pidx, conv_id, folder, msgs):
    """Merge `msgs` (dicts with key, message_id, subject, from, to, cc, received, modified, labels, text, attachments) into the
    one file of this conversation. Returns the entry, with `status` and `labels`."""
    thread_id = hashlib.sha256(str(conv_id).encode()).hexdigest()
    url = f"outlook-thread:{thread_id}"
    h = hashlib.sha1(url.encode()).hexdigest()[:8]
    old = pidx.find(h, url)
    have = {}
    if old:
        ofm, obody = read_file(old)
        folder = (ofm or {}).get("scope", "").removeprefix("outlook:") or folder  # the thread keeps the folder it was first seen in
        parts = _MARK.split(split_digest(obody)[0])
        for js, raw in zip(parts[1::2], parts[2::2]):
            meta = json.loads(js)
            have[meta["key"]] = (meta, raw.strip("\n"))
    for m in msgs:
        meta = {k: m.get(k) for k in ("key", "message_id", "subject", "from", "to", "cc", "received", "modified", "labels")}
        have[m["key"]] = (meta, message_raw(m))
    ordered = sorted(have.values(), key=lambda t: (t[0].get("received") or "", t[0]["key"]))
    metas = [t[0] for t in ordered]
    title = norm_subject(metas[0].get("subject"))
    body = f"# {inline(title)}\n\n" + "\n\n".join(f"<!-- wb:msg {_head(me)} -->\n{raw}" for me, raw in ordered)
    labels = sorted({x for me in metas for x in me.get("labels") or []})
    item = {"url": url, "title": title, "author": metas[0].get("from"), "modified": max((me.get("modified") or "") for me in metas) or None,
            "labels": labels, "scope": f"outlook:{folder}", "body": body,
            "extra": {"thread_id": thread_id, "message_ids": [me.get("message_id") or f"entry:{me['key'][:12]}" for me in metas],
                      "from": metas[0].get("from"), "to": _union(x for me in metas for x in me.get("to") or []),
                      "cc": _union(x for me in metas for x in me.get("cc") or []),
                      "received": max((me.get("received") or "") for me in metas) or None}}
    date = (metas[0].get("received") or iso(clock()))[:10]
    entry = put(P, pidx, "outlook", item, slug(folder), date)
    entry["labels"] = labels
    entry["received"] = item["extra"]["received"]
    return entry
