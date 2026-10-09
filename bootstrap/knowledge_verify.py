#!/usr/bin/env python3
"""knowledge_verify.py: the Day-1 knowledge checks (D1-D23), run by `setup.py run` (phase knowledge-verify) and by
`setup.py doctor --deep`. Each check calls a kit CLI that already exists and returns (status, detail, ask-IT text).

Two modes. "setup" may create what a check is about in the live profile (the KB index, one journal line, the find MCP
registration, the first backup). "doctor" only reads the live profile: every check that writes runs in a sandbox
(a temp copy of kb-template, a temp find index, a temp Claude config folder), removed afterwards. Both write exactly one
file, <WB>/state/knowledge-verify.json (IK2), atomically.

Statuses: PASS, WARN, FAIL, SKIP, OPT-IN-OFF. Only the steps in FAIL_LIST can FAIL; any other step is capped at WARN
(they depend on the environment: a blocked model download, a managed MCP policy, an opt-in left off). A child that
runs past its timeout is a WARN naming the step, never a hang. The doctor's exit code is nonzero only for a FAIL.
Test seam: WORKBENCH_VERIFY_JSON = an IK2 file whose steps are taken as the result (the setup tests use it).
"""
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(HERE))
import install as I  # noqa: E402

fwd = I.fwd
PASS, WARN, FAIL, SKIP, OFF = "PASS", "WARN", "FAIL", "SKIP", "OPT-IN-OFF"
FAIL_LIST = ("D1", "D2", "D3", "D4", "D5", "D6", "D7", "D10", "D14", "D20", "D21")
# IT1: every new kit tool answers --self-test offline, in under 10 s, with exit 0. A file this kit lacks is SKIP.
IT1 = ("tools/guard-replay/guard_replay.py", "tools/skill-probe/skill_probe.py", "tools/rules-quiz/rules_quiz.py",
       "tools/model-sweep/model_sweep.py", "tools/token-split/token_split.py", "tools/mcp-nowin/mcp_nowin.py",
       "plugins/workbench-core/skills/office-render/scripts/hidden_text.py",
       "plugins/workbench-core/skills/cleanup/scripts/scan_legacy.py", "plugins/workbench-kb/scripts/kb_facts.py")
JOURNAL = "setup: knowledge layer verified {date}; next: /workbench-core:onboard"
KBS = Path("plugins") / "workbench-kb" / "scripts"
CORE = Path("plugins") / "workbench-core" / "scripts"
PLUGINS = ("workbench-core@workbench", "workbench-kb@workbench")
# StopFailure dry run: last_assistant_message is the rendered API error string (hooks doc); error is one of its enum values.
STOP_EVENT = {"hook_event_name": "StopFailure", "error": "overloaded",
              "last_assistant_message": 'API Error: 529 {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'}
CLI_SESSION = "wb-verify"
HEADLESS_ASK = ("Please allow headless mode for Microsoft Edge (policy HeadlessModeEnabled), so browser checks and tests run "
                "without opening a window.")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class Timeout(Exception):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def jload(path, default=None):
    try:
        return I.read_json(path)
    except (OSError, ValueError, TypeError):
        return default


def jparse(text, default=None):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def write_atomic(path, text):
    """tmp beside the target, then os.replace: a reader or a crash never sees half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    try:
        for _ in range(40):
            try:
                return os.replace(tmp, path)
            except PermissionError:          # Windows: a reader holds the old file open for a moment
                time.sleep(0.05)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def by_path(name, path):
    """A kit module imported by its file path (no package import, no sys.path change)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def updates_row(up):
    """(OK | WARN | INFO, detail) for update.json (IP3): the doctor row `updates` and step D22."""
    items = up.get("items") if isinstance(up, dict) else None
    if not isinstance(items, list):
        return "INFO", "no update record yet: run setup.py update --check"
    by = lambda *a: [r.get("id") for r in items if r.get("action") in a]  # noqa: E731
    bad, held = by("failed", "denied"), by("deferred")
    if bad or held:
        return "WARN", "; ".join(x for x in (f"failed or denied: {', '.join(bad)}" if bad else "",
                                             f"deferred (see update.md for the command): {', '.join(held)}" if held else "") if x)
    n = len(by("current", "upgraded", "skipped-policy"))
    return "OK", f"{n} tool(s) at the pin; {len(by('it-managed'))} managed by IT, reported only"


class Verifier:
    def __init__(self, ctx, mode, kit=KIT):
        self.ctx, self.mode, self.kit = ctx, mode, Path(kit)
        self.checks = jload(self.kit / "bootstrap" / "knowledge-checks.json", {}) or {}
        self.sb = Path(tempfile.mkdtemp(prefix="wb-verify-"))
        self.py = I.console_python()      # setup --detach runs under pythonw: its children would lose their output
        kp = (ctx.cfg or {}).get("knowledge_python")
        self.kpy = next((I.console_python(p) for p in (kp, ctx.venv_python()) if p and Path(p).is_file()), None)
        self.kvenv = self.kpy is not None             # False until setup.py run has made the knowledge venv
        self.kpy = self.kpy or self.py
        self._health, self._sandbox_kb = None, None
        self.find_db = self.sb / "find" / "index.sqlite"
        self.find_built = self.find_timeout = False
        self.find_mode = None

    # ── children ──
    def run(self, argv, env=None, timeout=300, mb=None, stdin=None, cwd=None):
        """(exit code, stdout, stderr) of one child; memcap-wrapped when mb is given and memcap is in the kit."""
        memcap = self.kit / "tools" / "memcap" / "memcap.py"
        argv = [str(a) for a in argv]
        if mb and memcap.is_file():
            argv = [self.py, str(memcap), "--mb", str(mb), "--", *argv]
        e = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_TELEMETRY": "1",
             "DO_NOT_TRACK": "1", **(env or {})}
        try:
            r = subprocess.run(argv, input=(stdin or "").encode("utf-8"), capture_output=True, timeout=timeout,
                               env=e, cwd=str(cwd or self.sb), creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise Timeout(timeout)
        except OSError as err:
            return None, "", str(err)
        dec = lambda b: (b or b"").decode("utf-8", "replace")  # noqa: E731
        return r.returncode, dec(r.stdout), dec(r.stderr)

    def run_to_file(self, argv, log, timeout, cwd):
        """Exit code of a program that may leave a background process behind (the CLI's browser session): its output
        goes to a file, not a pipe, so a child that outlives it can never hold this call open. Timeout: None."""
        try:
            with open(log, "wb") as fh:
                return subprocess.run([str(a) for a in argv], stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                      timeout=timeout, cwd=str(cwd), creationflags=NO_WINDOW,
                                      env={**os.environ, "PATH": self.ctx.fresh_path()}).returncode
        except (subprocess.TimeoutExpired, OSError):
            return None

    def kb_script(self, name):
        return self.kit / KBS / name

    def live_env(self):
        """The live KB, read in place. In doctor mode the KB index goes to the sandbox, so nothing live is written."""
        env = {"CLAUDE_CONFIG_DIR": str(self.ctx.ch), "WORKBENCH_KB_ROOT": str(self.ctx.kb)}
        if self.mode != "setup":
            env["KB_INDEX_DB"] = str(self.sb / "live-kb-index.db")
        return env

    def sandbox_env(self):
        """A copy of kb-template with its own Claude config folder and index: the checks that write run here."""
        if self._sandbox_kb is None:
            self._sandbox_kb = self.sb / "kb"
            shutil.copytree(self.kit / "kb-template", self._sandbox_kb, dirs_exist_ok=True)
        return {"CLAUDE_CONFIG_DIR": str(self.sb / "ch"), "WORKBENCH_KB_ROOT": str(self._sandbox_kb),
                "KB_INDEX_DB": str(self.sb / "sandbox-kb-index.db")}

    def health(self):
        """{check: status} from `kb_health.py --json` (IK5) on the live KB, run once."""
        if self._health is None:
            rc, out, _ = self.run([self.py, self.kb_script("kb_health.py"), "--json"], self.live_env(), timeout=300)
            d = jparse(out, {}) or {}
            self._health = {r.get("check"): r.get("status") for r in d.get("results") or [] if isinstance(r, dict)}
        return self._health

    def feature_ask(self, fid):
        feats = jload(self.kit / "bootstrap" / "features.json", {}) or {}
        rows = feats.get("rows") if isinstance(feats, dict) else None
        return next((f.get("ask_it") for f in rows or [] if isinstance(f, dict) and f.get("id") == fid), None)

    def find(self, *args, env=None, timeout=300, mb=None):
        """The find CLI; WB_FIND_LAZY=0: a check never starts the background refresh a stale index would."""
        return self.run([self.kpy, self.ctx.find_cli(), *args], {"WB_FIND_LAZY": "0", **(env or {})}, timeout=timeout, mb=mb)

    def sfind(self, *args, timeout=300, mb=None):
        env = {"HF_HUB_OFFLINE": "1"} if self.mode != "setup" else {}      # doctor: never downloads the model
        return self.find("--db", self.find_db, *args, env=env, timeout=timeout, mb=mb)

    def live_find_db(self):
        return Path(os.environ.get("WORKBENCH_KNOWLEDGE_DB") or (self.ctx.cfg or {}).get("knowledge_db")
                    or self.ctx.lad / "doc-index" / "knowledge" / "index.sqlite")


# ── the steps: each returns (status, detail[, ask-IT text]) ─────────────────────────────────────────────────
def d1_kb_seeded(v):
    kb = v.ctx.kb
    if not kb.is_dir():
        return FAIL, f"no knowledge base at {fwd(kb)}: run install.py --apply again"
    doms = [p.name for p in kb.iterdir() if p.is_dir() and (p / "HOT.md").is_file()]
    bad = [f"{len(doms)} domain folder(s) with a HOT.md (8 expected)"] if len(doms) < 8 else []
    bad += [f"{n} is missing" for n in ("active-context.md", "00-index.md") if not (kb / n).is_file()]
    lay = v.health().get("layout")
    if lay != PASS:
        bad.append(f"kb_health --json layout: {lay or 'no answer'}")
    return (FAIL, "; ".join(bad)) if bad else (PASS, f"{len(doms)} domains, active-context.md and 00-index.md present")


def d2_kb_state(v):
    code = "import sys; sys.path.insert(0, sys.argv[1]); import kb_audit; print(kb_audit.state_dir().as_posix())"
    rc, out, _ = v.run([v.py, "-c", code, v.kit / KBS], v.live_env(), timeout=60)
    if rc != 0 or not out.strip():
        return FAIL, "kb_audit.state_dir() did not answer"
    sd = Path(out.strip().splitlines()[-1])
    if I.in_onedrive(sd) or I.under(sd, v.ctx.kb):
        return FAIL, f"the KB state folder {fwd(sd)} must be local and outside the KB"
    if v.mode == "setup":
        sd.mkdir(parents=True, exist_ok=True)
    if not sd.is_dir():
        return WARN, f"{fwd(sd)} does not exist yet: the first /workbench-kb:save creates it"
    lock = sd / "save.lock"
    if v.mode == "setup" or lock.exists():
        sl = by_path("wb_verify_savelock", v.kit / KBS / "savelock.py")
        try:
            with sl.filelock(lock, blocking=False):
                pass
        except sl.LockBusy:
            return WARN, "save.lock is held by a save in progress; check again later"
        except OSError as e:
            return FAIL, f"save.lock cannot be taken: {e}"
    if (v.ctx.kb / ".state").is_dir() and not (sd / "migrated-from-kb.json").exists():
        return WARN, "an earlier kit's <KB>/.state is copied to the local state folder at the next save"
    return PASS, f"{fwd(sd)}: local, outside the KB, save.lock free"


def d3_kb_machinery(v):
    tests, rs = v.kit / "plugins" / "workbench-kb" / "tests", v.kit / "tools" / "run_suites.py"
    if not tests.is_dir() or not rs.is_file():
        return FAIL, "the KB tests or tools/run_suites.py are not in this kit"
    out, t = v.sb / "d3.json", v.sb / "d3"
    env = {"CLAUDE_CONFIG_DIR": str(t / "ch"), "WORKBENCH_KB_ROOT": str(t / "kb"), "KB_INDEX_DB": str(t / "kb.db")}
    rc, _, err = v.run([v.py, rs, "--child-unittest", tests, "--child-out", out], env, timeout=600, mb=1024)
    res = jload(out)
    if not isinstance(res, dict):
        return FAIL, f"the KB test run wrote no result (exit {rc}): {err.strip()[-200:]}"
    allow = by_path("wb_verify_run_suites", rs)
    entries, _ = allow.load_allow(v.kit / "tools" / "skips.allow")
    odd = [f"{m}::{t}" for m, t, _r in res.get("skipped") or [] if not allow.allowed(entries, m, t)]
    if res.get("failed") or rc != 0 or odd:
        return FAIL, (f"{res.get('failed')} failure(s)/error(s)" + failing_names(res.get("failures"))
                      + (f"; skips not in tools/skips.allow: {', '.join(odd[:3])}" if odd else ""))
    return PASS, f"{len(res.get('ids') or [])} test(s), 0 failures, {len(res.get('skipped') or [])} allowed skip(s)"


def failing_names(ids, most=10, width=230):
    """': name, name, ...' for up to `most` failing test ids (method names, each cut to an equal share of `width`, so all
    of them fit in the 300-character detail), '' when there are none."""
    names = [str(i).rsplit(".", 1)[-1] for i in (ids or [])[:most]]
    if not names:
        return ""
    w = max(12, width // len(names) - 2)
    more = f" (+{len(ids) - most} more)" if len(ids) > most else ""
    return ": " + ", ".join(n if len(n) <= w else n[:w - 1] + "~" for n in names) + more


def d4_journal(v):
    env = v.live_env() if v.mode == "setup" else v.sandbox_env()
    line = JOURNAL.format(date=datetime.date.today().isoformat())
    rc, _, err = v.run([v.py, v.kb_script("save_driver.py"), "--inbox-add", line], env, timeout=120)
    if rc != 0:
        return FAIL, f"save_driver.py --inbox-add exit {rc}: {err.strip()[-200:]}"
    rc, out, _ = v.run([v.py, v.kb_script("kb_search.py"), "--scope", "all", "knowledge layer verified", "--json"], env,
                       timeout=120)
    hits = (jparse(out, {}) or {}).get("hits") or []
    if not any(isinstance(h, dict) and h.get("path") == "inbox.jsonl" for h in hits):
        return FAIL, "the journal line was written, but kb_search --scope all does not return it"
    return PASS, ("one journal line in the live KB" if v.mode == "setup" else "a sandbox journal line") + \
        ", found by kb_search --scope all"


def d5_kb_index(v):
    rc, out, err = v.run([v.py, v.kb_script("kb_index.py"), "build"], v.live_env(), timeout=300)
    res = jparse(out, {}) or {}
    db = res.get("index")
    if rc != 0 or not db or not Path(db).is_file():
        return FAIL, f"kb_index.py build exit {rc}: {err.strip()[-200:] or 'no index file'}"
    try:
        con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
        try:
            fts = dict(con.execute("select k, v from meta")).get("fts")
        finally:
            con.close()
    except sqlite3.Error as e:
        return FAIL, f"the KB index cannot be read: {e}"
    h = v.health()
    bad = [c for c in ("caps", "frontmatter", "secrets") if h.get(c) == FAIL]
    if bad:
        return FAIL, f"kb_health --json FAIL: {', '.join(bad)} (run kb_health.py --verbose)"
    soft = [c for c in ("caps", "frontmatter", "secrets", "dead-links", "orphans") if h.get(c) == WARN]
    if fts != "1":
        return WARN, "built, but this Python has no FTS5: a plain-table fallback is used"
    return (WARN, f"built (fts5); kb_health WARN: {', '.join(soft)}") if soft else (PASS, "built (fts5); kb_health caps, "
                                                                                       "frontmatter and secrets PASS")


def d6_kb_retrieval(v):
    cases = v.kit / str(v.checks.get("kb_cases") or "plugins/workbench-kb/tests/kb_canned.json")
    if not cases.is_file():
        return FAIL, f"{fwd(cases.relative_to(v.kit))} is not in this kit"
    rc, out, _ = v.run([v.py, v.kb_script("kb_health.py"), "--json", "--eval", cases], v.sandbox_env(), timeout=300)
    rows = (jparse(out, {}) or {}).get("results") or []
    ev = next((r for r in rows if isinstance(r, dict) and r.get("check") == "eval"), None)
    if not ev:
        return FAIL, f"kb_health --json --eval gave no eval result (exit {rc})"
    st = ev.get("status")
    return (st if st in (PASS, FAIL) else WARN), f"kb-template sandbox: {ev.get('detail') or st}"


def d7_kb_graph(v):
    kr = v.checks.get("kb_related") or {}
    rc, out, _ = v.run([v.py, v.kb_script("kb_search.py"), "--related", kr.get("from", "ops/HOT.md"), "--depth",
                        kr.get("depth", 2), "--json"], v.sandbox_env(), timeout=120)
    res = jparse(out, None)
    if rc != 0 or not isinstance(res, list):
        return FAIL, f"kb_search --related exit {rc}"
    got = {str(r.get("path", "")).replace("\\", "/").lower() for r in res if isinstance(r, dict)}
    miss = [p for p in kr.get("expect_all") or [] if p.lower() not in got]
    return (FAIL, f"not reached from {kr.get('from')}: {', '.join(miss)}") if miss else \
        (PASS, f"{kr.get('from')} reaches {', '.join(kr.get('expect_all') or [])} within {kr.get('depth')} hops")


def d8_find_roots(v):
    if not v.live_find_db().is_file():
        return WARN, "no find index yet: setup.py run registers the roots"
    rc, out, _ = v.find("roots", "--json", timeout=120)
    labels = {r.get("label") for r in (jparse(out, {}) or {}).get("roots") or [] if isinstance(r, dict)}
    miss = [x for x in ("captured", "howto", "kb") if x not in labels]
    return (WARN, f"roots missing: {', '.join(miss)} (setup.py run adds them)") if miss else \
        (PASS, f"{len(labels)} root(s), including captured, howto and kb")


def d9_find_build(v):
    try:
        return _find_build(v)
    except Timeout:
        v.find_timeout = True           # D10 then reports the timeout as a WARN, not as an empty index
        raise


def _find_build(v):
    roots = (("howto", v.kit / "docs" / "howto"), ("kb", v.ctx.kb))
    for label, path in roots:
        rc, _, err = v.sfind("add-root", path, "--label", label, "--json", timeout=120)
        if rc != 0:
            return FAIL, f"add-root {label} exit {rc}: {err.strip()[-160:]}"
    for label, _p in roots:
        rc, _, err = v.sfind("refresh", "--root", label, "--embed", "auto", "--max-minutes", "10", "--json",
                             timeout=900, mb=2048)
        if rc != 0:
            return FAIL, f"refresh --root {label} exit {rc}: {err.strip()[-160:]}"
    rc, out, _ = v.sfind("status", "--json", timeout=120)
    st = jparse(out, {}) or {}
    per = {r.get("label"): r for r in st.get("roots") or [] if isinstance(r, dict)}
    v.find_built = int(((per.get("howto") or {}).get("files") or {}).get("ok") or 0) > 0
    empty = [x for x in ("howto", "kb") if not int(((per.get(x) or {}).get("files") or {}).get("ok") or 0) > 0]
    if empty:
        return FAIL, f"no file indexed in: {', '.join(empty)}"
    v.find_mode = st.get("mode")
    novec = [x for x in ("howto", "kb") if not int((per.get(x) or {}).get("vectors") or 0) > 0]
    if v.find_mode != "hybrid" or novec:
        v.find_mode = "keyword"
        return WARN, ("keyword-only: the embedding model is not available" +
                      (" (doctor never downloads it; setup.py run does)" if v.mode != "setup" else "")), \
            v.feature_ask("find-hybrid")
    return PASS, f"howto and kb indexed with vectors ({st.get('paragraphs')} paragraphs, mode hybrid)"


def _questions(v):
    h = v.checks.get("howto") or {}
    qs = (jload(v.kit / str(h.get("questions") or "docs/howto/questions.json"), {}) or {}).get("questions") or []
    return qs, int(h.get("top") or 3), int(h.get("keyword_min") or 10)


def _top(v, q, mode, top):
    rc, out, _ = v.sfind("search", q, "--mode", mode, "--root", "howto", "--limit", "10", "--json", timeout=180)
    res = jparse(out, {}) or {}
    names = []
    for h in res.get("hits") or []:
        n = Path(str(h.get("path", ""))).name
        if n not in names:
            names.append(n)
    return res, names[:top]


def d10_find_keyword(v):
    if not v.find_built:
        return (WARN, "skipped: the sandbox index build timed out (D9)") if v.find_timeout else \
            (FAIL, "the how-to index was not built (see D9)")
    qs, top, need = _questions(v)
    hits = sum(Path(q["expect"]).name in _top(v, q["q"], "keyword", top)[1] for q in qs)
    v.keyword_hits = hits
    return (PASS if hits >= need and qs else FAIL), f"{hits}/{len(qs)} questions find their guide in the first {top} files " \
                                                     f"(keyword; need {need})"


def d11_find_meaning(v):
    if v.find_mode != "hybrid":
        return WARN, "skipped: the index is keyword-only (D9)", v.feature_ask("find-hybrid")
    qs, top, _ = _questions(v)
    hits, dense, modes = 0, False, set()
    for q in qs:
        res, names = _top(v, q["q"], "hybrid", top)
        modes.add(res.get("mode"))
        dense = dense or any((h.get("arms") or {}).get("dense") is not None for h in res.get("hits") or [])
        hits += Path(q["expect"]).name in names
    ok = modes == {"hybrid"} and dense and hits >= getattr(v, "keyword_hits", 0)
    return (PASS if ok else WARN), f"hybrid {hits}/{len(qs)} in the first {top} (keyword {getattr(v, 'keyword_hits', '?')}); " \
                                   f"dense arm {'used' if dense else 'never used'}"


def d12_find_graph(v):
    if not v.find_built:
        return WARN, "skipped: the how-to index was not built (D9)"
    fr = v.checks.get("find_related") or {}
    rc, out, _ = v.sfind("related", fr.get("from", ""), "--json", timeout=120)
    refs = {r.get("ref") for r in (jparse(out, {}) or {}).get("related") or [] if isinstance(r, dict)}
    rc2, out2, _ = v.sfind("newest", fr.get("from", ""), "--json", timeout=120)
    newest = ((jparse(out2, {}) or {}).get("newest") or {}).get("ref")
    if not refs & set(fr.get("expect_any") or []) or newest != fr.get("from"):
        return WARN, f"related from {fr.get('from')}: {len(refs)} file(s), none expected; newest {newest}"
    return PASS, f"related from {fr.get('from')} reaches {', '.join(sorted(refs & set(fr['expect_any'])))}; newest is itself"


def find_golden(v):
    """The template's find entry with its placeholders filled for this machine (one server only)."""
    tpl = jload(v.kit / "mcp" / "golden-config.template.json", {}) or {}
    spec = json.dumps((tpl.get("servers") or {}).get("find") or {})
    spec = spec.replace("{{KNOWLEDGE_PYTHON}}", fwd(v.kpy)).replace("{{WORKBENCH_HOME}}/kit", fwd(v.kit)) \
        .replace("{{WORKBENCH_HOME}}", fwd(v.ctx.wb))
    return {"_readme": "Written by setup.py: the find MCP server only, filled for this machine.",
            "servers": {"find": json.loads(spec)}}


def user_mcp_config(ctx):
    return (ctx.ch / ".claude.json") if os.environ.get("CLAUDE_CONFIG_DIR") else ctx.home / ".claude.json"


def d13_find_mcp(v):
    cfg, ask = user_mcp_config(v.ctx), v.feature_ask("find-mcp")
    healer = v.kit / "tools" / "mcp-healer" / "mcp_healer.py"
    if v.mode == "setup":
        if not cfg.is_file():
            return WARN, f"{fwd(cfg)} does not exist yet: start Claude Code once, then run setup.py run again"
        golden = find_golden(v)
        if "{{" in json.dumps(golden):
            return WARN, "the find entry in mcp/golden-config.template.json has an unknown placeholder"
        had = "find" in ((jload(cfg, {}) or {}).get("mcpServers") or {})
        gf = v.ctx.state_dir / "find-mcp.golden.json"
        write_atomic(gf, json.dumps(golden, indent=2) + "\n")
        rc, _, _ = v.run([v.py, healer, "--config", cfg, "apply", "--golden", gf], timeout=120)
        if rc == 3:
            return WARN, "a managed MCP policy is in force: find was not registered", ask
        if rc != 0:
            return WARN, f"mcp_healer.py apply exit {rc}"
        if not had and "find" in ((jload(cfg, {}) or {}).get("mcpServers") or {}):
            v.ctx.record({"kind": "mcp", "name": "find", "config": fwd(cfg)}, "mcp:find")
    spec = ((jload(cfg, {}) or {}).get("mcpServers") or {}).get("find")
    if not isinstance(spec, dict) or not spec.get("command"):
        return WARN, "find is not registered as a user MCP server (setup.py run registers it)", ask
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                                             "clientInfo": {"name": "wb-verify", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    live = v.live_find_db().is_file()            # a search on a missing index would create one: only initialize then
    msgs += [{"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "search", "arguments": {"query": v.checks.get("mcp_query") or "how to", "limit": 3}}}] * live
    rc, out, _ = v.run([spec["command"], *(spec.get("args") or [])], {**(spec.get("env") or {}), "WB_FIND_LAZY": "0"},
                       timeout=120, stdin="".join(json.dumps(m) + "\n" for m in msgs))
    resp = {r.get("id"): r for r in (jparse(ln, {}) for ln in out.splitlines()) if isinstance(r, dict)}
    tools = {t.get("name") for t in ((resp.get(2) or {}).get("result") or {}).get("tools") or []}
    if not (resp.get(1) or {}).get("result") or not {"search", "show", "related"} <= tools:
        return WARN, f"the find server did not answer initialize and tools/list with search, show and related (exit {rc})"
    res = ((resp.get(3) or {}).get("result") or {}).get("structuredContent") or {}
    hits = res.get("hits") or []
    if not live:
        return WARN, "registered; handshake ok; no live index yet to search (setup.py run builds it)"
    if not hits:
        return WARN, "handshake ok; the search returned no hit (the live index may still be empty)"
    if not (res.get("untrusted") is True and all(h.get("untrusted") is True for h in hits)):
        return WARN, "a search result is not marked untrusted"
    return PASS, f"registered; handshake ok; search returned {len(hits)} hit(s), all marked untrusted"


def stopfailure_floor(path):
    """STOPFAILURE_MIN_CC from bug_hint.py as an int triple, read with ast (the file is never run); None when absent."""
    import ast
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "STOPFAILURE_MIN_CC" for t in node.targets):
            try:
                val = ast.literal_eval(node.value)
            except ValueError:
                return None
            ok = isinstance(val, tuple) and len(val) == 3 and all(isinstance(x, int) for x in val)
            return val if ok else None
    return None


def _relay_dry_run(v, env):
    """IR2 in the sandbox: StopFailure writes this session's pending hint; --pending injects it once and deletes it."""
    hint = v.kit / CORE / "bug_hint.py"
    sid = f"wbverify-{os.getpid()}"
    pending = Path(env["CLAUDE_CONFIG_DIR"]) / "workbench" / "state" / f"pending-hint-{sid}.json"
    rc, _, _ = v.run([v.py, "-S", hint], env, timeout=60, stdin=json.dumps({**STOP_EVENT, "session_id": sid}))
    doc = jload(pending)
    if rc != 0 or not isinstance(doc, dict) or not doc.get("card"):
        return f"StopFailure left no pending hint (exit {rc})"
    ups = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": "hello"})
    rc, out, _ = v.run([v.py, "-S", hint, "--pending"], env, timeout=60, stdin=ups)
    if rc != 0 or not out.strip() or pending.exists():
        return f"--pending did not inject and delete the hint (exit {rc})"
    rc, out, _ = v.run([v.py, "-S", hint, "--pending"], env, timeout=60, stdin=ups)
    return None if rc == 0 and not out.strip() else "--pending injected the same hint twice"


def d14_hooks(v):
    t = v.sb / "hooks"
    kb, ch = t / "kb", t / "ch"
    kb.mkdir(parents=True, exist_ok=True)
    sentinel = f"wb-verify sentinel {os.getpid()}-{int(time.time())}"
    (kb / "active-context.md").write_text(f"# Active context\n\n- {sentinel}\n", encoding="utf-8")
    env = {"CLAUDE_CONFIG_DIR": str(ch), "WORKBENCH_KB_ROOT": str(kb), "KB_INDEX_DB": str(t / "kb.db"),
           "WORKBENCH_REPORT_CLI": str(t / "no-report.py")}       # a missing stand-in: session start starts no report
    rc, out, _ = v.run([v.py, "-S", v.kit / CORE / "session_start.py"], env, timeout=60,
                       stdin=json.dumps({"hook_event_name": "SessionStart", "source": "startup", "session_id": "wbverify"}))
    ctxt = ((jparse(out, {}) or {}).get("hookSpecificOutput") or {}).get("additionalContext") or ""
    bad = [] if rc == 0 and sentinel in ctxt else [f"session_start.py did not emit active-context.md (exit {rc})"]
    before = sorted(p.relative_to(kb).as_posix() for p in kb.rglob("*"))
    rc, _, _ = v.run([v.py, "-S", v.kit / CORE / "precompact.py"], env, timeout=60,
                     stdin=json.dumps({"hook_event_name": "PreCompact", "session_id": "wbverify", "trigger": "auto"}))
    st = ch / "workbench" / "kb-state"
    if rc != 0 or not list(st.glob("*/precompact-wbverify.flag")) or not list(st.glob("*/snapshots/active-context-*.md")):
        bad.append(f"precompact.py wrote no flag and snapshot in the local state folder (exit {rc})")
    if sorted(p.relative_to(kb).as_posix() for p in kb.rglob("*")) != before:
        bad.append("precompact.py wrote inside the KB")
    relay = "the StopFailure relay is not in this kit's bug_hint.py"
    if stopfailure_floor(v.kit / CORE / "bug_hint.py"):
        why = _relay_dry_run(v, env)
        bad += [why] if why else []
        relay = "StopFailure relay dry run ok"
    if bad:
        return FAIL, "; ".join(bad)
    settings = jload(v.ctx.ch / "settings.json", {}) or {}
    off = [p for p in PLUGINS if (settings.get("enabledPlugins") or {}).get(p) is not True]
    hb = jload(v.ctx.state_dir / "guard-heartbeat.json", {}) or {}
    soft = ([f"not enabled yet: {', '.join(off)} (run the plugin commands install.py printed)"] if off else []) + \
        ([] if hb.get("last_start") else ["no Claude Code session has started with the hooks yet"])
    head = f"session start and precompact work in a sandbox; {relay}"
    return (WARN, f"{head}; " + "; ".join(soft)) if soft else (PASS, head + "; heartbeat last_start " + hb["last_start"])


def d15_schedule(v):
    if os.name != "nt":
        return OFF, "not Windows: schedule `doc_index.py refresh --all` and `setup.py backup --if-older-days 7` with cron"
    ctx = v.ctx
    task = "\\claude-workbench\\knowledge-refresh"
    wanted = "nightly" in ctx.with_ if ctx.profile == "corporate" else not ctx.no_nightly
    if not wanted:
        return WARN, ("the nightly task is off (corporate profile: add --with nightly). Instead the index refreshes when a "
                      "search finds it older than 24 h, and backups are by hand: setup.py backup")
    led = next((e for e in ctx.ledger()["entries"] if e.get("kind") == "task" and e.get("name") == task), None)
    rc, _ = ctx.run(["schtasks", "/Query", "/TN", task], timeout=60)
    f = ctx.state_dir / "knowledge-refresh.xml"
    try:     # setup hashes the LF text; Windows text mode wrote the file with CRLF
        digest = hashlib.sha256(f.read_bytes().decode("utf-16").replace("\r\n", "\n").encode("utf-8")).hexdigest()
    except (OSError, UnicodeDecodeError):
        digest = None
    if rc != 0 or not led or led.get("xml_sha256") != digest:
        return WARN, "the nightly task is missing or differs from what setup recorded: run setup.py run --with nightly"
    return PASS, f"task {task} registered as recorded"


def d16_backup(v):
    ctx = v.ctx
    setup_py = v.kit / "bootstrap" / "setup.py"
    if v.mode == "setup":
        rc, _, err = v.run([v.py, setup_py, "backup"], timeout=600)
        if rc != 0:
            return WARN, f"setup.py backup exit {rc}: {err.strip()[-160:]}"
    bj = jload(ctx.state_dir / "backup.json", {}) or {}
    z = Path(str(bj.get("path") or ""))
    if not bj.get("path") or not z.is_file():
        return WARN, "never backed up: run setup.py backup"
    rc, _, err = v.run([v.py, setup_py, "restore", z, "--to", v.sb / "restore"], timeout=600)
    shutil.rmtree(v.sb / "restore", ignore_errors=True)
    if rc != 0:
        return WARN, f"the restore drill of {z.name} failed (exit {rc}): {err.strip()[-160:]}"
    hist = "the KB is in OneDrive, which also keeps version history" if I.in_onedrive(ctx.kb) else \
        "the KB is local: keep the zips somewhere your employer approves"
    return PASS, f"{z.name} restores cleanly (hashes checked in a temp folder); {hist}"


def d17_capture(v):
    ctx = v.ctx
    if "capture" not in ctx.with_:
        return OFF, "capture is off (setup.py run --with capture)"
    app = ctx.wb / "capture" / "app" / "capture.mjs"
    rc, out = ctx.run(["node", str(app), "--version"], timeout=60)
    if rc != 0 or not re.match(r"capture \d+\.\d+\.\d+", (out or b"").decode("utf-8", "replace").strip()):
        return WARN, "capture.mjs --version did not print `capture <version>`"
    fx, t = v.checks.get("ingest_fixture") or {}, v.sb / "capture"
    data, wb = t / "data", t / "wb"
    drop = data / "captured" / "_drop" / "meetings"
    drop.mkdir(parents=True)
    write_atomic(wb / "config.json", json.dumps({"data_root": fwd(data), "kb_root": fwd(t / "kb")}))
    (drop / "planning-check-in-20260105_1000.vtt").write_text(fx.get("vtt") or "WEBVTT\n", encoding="utf-8")
    (drop / "planning-check-in-20260105_1000.meta.json").write_text(json.dumps(fx.get("meta") or {}), encoding="utf-8")
    env = {"WORKBENCH_HOME": str(wb), "CLAUDE_CONFIG_DIR": str(t / "ch"), "WORKBENCH_KNOWLEDGE_DB": str(t / "find.sqlite")}
    ing = v.kit / "plugins" / "workbench-capture" / "skills" / "ingest" / "scripts" / "ingest.py"
    # The sandbox is a fresh profile, so it has no acknowledgement. Mirror the one recorded in the live profile (only that
    # field, only when it exists): the check then tests the pipeline, and never forges what the person has not done.
    ack = (jload(ctx.wb / "capture" / "ingest.json", {}) or {}).get("infosec_ack")
    if ack:
        write_atomic(wb / "capture" / "ingest.json", json.dumps({"infosec_ack": ack}))
    rc, _, err = v.run([v.py, ing, "meetings", "run", "--no-digest", "--json"], env, timeout=300)
    if rc == 5:     # ingest.py: "5 InfoSec acknowledgement missing"; step_row keeps 300 characters, so say the next step early
        return WARN, ("the InfoSec acknowledgement is not recorded in this profile, so ingest stopped (exit 5); the install is "
                      "fine. Next: tell your security team what capture does (bootstrap/infosec-note.txt), then run once: "
                      "ingest.py ack-infosec")
    written = [p for p in (data / "captured").rglob("*.md") if "_drop" not in p.parts]
    if rc != 0 or len(written) != 1 or list(drop.glob("*.vtt")):
        return WARN, f"sandbox meeting ingest: exit {rc}, {len(written)} meeting file(s), original " \
                     f"{'still in the drop folder' if list(drop.glob('*.vtt')) else 'moved'}"
    return PASS, "capture runtime answers; a fixture transcript became one meeting file in a sandbox"


def d18_opt_ins(v):
    pk = {p["id"]: p for p in (jload(v.kit / "bootstrap" / "packages.json", {}) or {}).get("packages") or []}
    rows, bad, tools = [], [], {}
    for pid in ("tokensave", "ctx"):
        p = pk.get(pid)
        if not p:
            continue
        status, ver = v.ctx.verify(p)
        if status == "absent":
            continue
        rows.append(f"{pid} {ver}" if status == "works" else f"{pid} does not answer")
        tools[pid] = PASS if status == "works" else WARN      # per tool: the report rates pkg-ctx and pkg-tokensave on their own
        bad += [] if status == "works" else [pid]
    if not rows:
        return OFF, "no optional knowledge tool is installed (code graph: --with tokensave; transcripts: --with ctx)"
    return (WARN if bad else PASS), "; ".join(rows), None, tools


def d19_full_refresh(v):
    if v.mode == "setup":
        return SKIP, "the full refresh starts when this phase ends; setup.py doctor --deep checks it later"
    if not v.live_find_db().is_file():
        return WARN, "no find index yet"
    rc, out, _ = v.find("status", "--json", timeout=120)
    last = (jparse(out, {}) or {}).get("last_refresh")
    try:
        age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.strptime(last[:19], "%Y-%m-%dT%H:%M:%S")
               .replace(tzinfo=datetime.timezone.utc)).total_seconds() / 3600
    except (TypeError, ValueError):
        age = None
    return (PASS, f"last full refresh {last}") if age is not None and age < 48 else \
        (WARN, f"last full refresh {last or 'never'}: run doc_index.py refresh --all --detach")


def d21_kit_tools(v):
    rows, bad, skipped, novenv = [], [], [], []
    for rel in IT1:
        f = v.kit / rel
        if not f.is_file():
            skipped.append(Path(rel).stem)
            continue
        if (f.parents[1] / "requirements.txt").is_file() and not v.kvenv:     # its packages live in the knowledge venv
            novenv.append(f.stem)
            continue
        rc, out, _ = v.run([v.kpy, f, "--self-test"], timeout=60)
        (rows if rc == 0 else bad).append(Path(rel).stem + ("" if rc == 0 else f" (exit {rc})"))
    if bad:
        return FAIL, f"--self-test failed: {', '.join(bad)}"
    later = f"; after setup.py run makes the knowledge venv: {', '.join(novenv)}" if novenv else ""
    if not rows:
        return SKIP, "none of the listed tools is in this kit" + later
    return PASS, f"{len(rows)} tool(s) pass --self-test" + (f"; not in this kit: {', '.join(skipped)}" if skipped else "") + later


def d22_updates(v):
    if v.ctx.no_update:
        return SKIP, "--no-update"
    st, detail = updates_row(jload(v.ctx.state_dir / "update.json"))
    return (PASS if st == "OK" else WARN), detail


def d23_browser_cli(v):
    ctx = v.ctx
    p = next((x for x in (jload(v.kit / "bootstrap" / "packages.json", {}) or {}).get("packages") or []
              if x.get("id") == "playwright-cli"), None)
    if not p:
        return SKIP, "playwright-cli is not in this kit's package table"
    status, ver = ctx.verify(p)
    if status != "works":
        return WARN, "playwright-cli is not installed or does not answer --version", p.get("ask_it")
    if not ctx.probe:
        ctx.load_probe(run=False)
    cap = ctx.pdata("capture")
    ask = v.feature_ask("browser-automation")
    if cap.get("automation_allowed") is False:
        return WARN, f"playwright-cli {ver}; Edge policy blocks remote debugging: not launched", ask
    if cap.get("headless_allowed") is False:
        return WARN, f"playwright-cli {ver}; Edge policy blocks headless mode (the CLI opens a visible window): not " \
                     "launched here", HEADLESS_ASK
    if "edge_path" in cap and not cap.get("edge_path"):
        return WARN, f"playwright-cli {ver}; no Microsoft Edge was found"
    work = v.sb / "browser"
    work.mkdir(exist_ok=True)
    exe = ctx.which("playwright-cli")
    rc = v.run_to_file([exe, f"-s={CLI_SESSION}", "open", "about:blank", "--browser=msedge"], work / "open.log", 120, work)
    rc2 = v.run_to_file([exe, f"-s={CLI_SESSION}", "close"], work / "close.log", 60, work)
    if rc != 0:
        return WARN, f"playwright-cli {ver} could not open headless Edge (exit {rc if rc is not None else 'none: timed out'})", ask
    return PASS, f"playwright-cli {ver} opened about:blank in headless Edge and closed it (close exit {rc2})"


STEPS = (("D1", "kb-seeded", d1_kb_seeded), ("D2", "kb-state", d2_kb_state), ("D3", "kb-machinery", d3_kb_machinery),
         ("D4", "journal", d4_journal), ("D5", "kb-index", d5_kb_index), ("D6", "kb-retrieval", d6_kb_retrieval),
         ("D7", "kb-graph", d7_kb_graph), ("D8", "find-roots", d8_find_roots), ("D9", "find-build", d9_find_build),
         ("D10", "find-keyword", d10_find_keyword), ("D11", "find-meaning", d11_find_meaning),
         ("D12", "find-graph", d12_find_graph), ("D13", "find-mcp", d13_find_mcp), ("D14", "hooks", d14_hooks),
         ("D15", "schedule", d15_schedule), ("D16", "backup", d16_backup), ("D17", "capture", d17_capture),
         ("D18", "opt-ins", d18_opt_ins), ("D19", "full-refresh", d19_full_refresh), ("D21", "kit-tools", d21_kit_tools),
         ("D22", "updates", d22_updates), ("D23", "browser-cli", d23_browser_cli))


def step_row(sid, name, res, ms):
    status, detail, ask = (list(res) + [None])[:3]
    tools = res[3] if len(res) > 3 else None      # a step that covers several tools may record each one's status
    if status == FAIL and sid not in FAIL_LIST:      # only the named steps can fail Day 1
        status = WARN
    row = {"id": sid, "name": name, "status": status, "detail": str(detail)[:300], "ms": int(ms), "ask_it": ask or None}
    return {**row, "tools": dict(tools)} if tools else row


def run_steps(v):
    rows = []
    for sid, name, fn in STEPS:
        t0 = time.monotonic()
        try:
            res = fn(v)
        except Timeout as e:
            res = (WARN, f"{name} timed out after {e} s (a slow or busy machine): run setup.py doctor --deep again later")
        except Exception as e:      # a crash in the check itself
            res = (FAIL, f"the check crashed: {type(e).__name__}: {e}")
        rows.append(step_row(sid, name, res, (time.monotonic() - t0) * 1000))
    return rows


def document(rows):
    rows = sorted(rows, key=lambda r: int(r["id"][1:]))
    n = lambda s: sum(r["status"] == s for r in rows)  # noqa: E731
    return {"version": 1, "generated": now(), "kit_version": I.VERSION, "steps": rows,
            "summary": {"pass": n(PASS), "warn": n(WARN), "fail": n(FAIL),
                        "failing": [r["id"] for r in rows if r["status"] == FAIL]}}


def record(ctx, rows):
    """D20: write IK2 atomically and read it back; a write that cannot be proven is D20 FAIL."""
    path = ctx.state_dir / "knowledge-verify.json"
    d20 = {"id": "D20", "name": "record", "status": PASS, "detail": f"written atomically: {fwd(path)}", "ms": 0, "ask_it": None}
    doc = document([r for r in rows if r["id"] != "D20"] + [d20])
    try:
        write_atomic(path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        if jload(path) != doc:
            raise OSError("the file read back differs from what was written")
    except OSError as e:
        d20.update(status=FAIL, detail=f"knowledge-verify.json could not be written: {e}"[:300])
        doc = document([r for r in rows if r["id"] != "D20"] + [d20])
    return doc


def run(ctx, mode="doctor", kit=KIT):
    """Run every step (or take WORKBENCH_VERIFY_JSON's steps), write IK2 and return it."""
    canned = os.environ.get("WORKBENCH_VERIFY_JSON")
    if canned:
        rows = [r for r in (jload(canned, {}) or {}).get("steps") or [] if isinstance(r, dict)]
        return record(ctx, rows)
    v = Verifier(ctx, mode, kit)
    try:
        return record(ctx, run_steps(v))
    finally:
        shutil.rmtree(v.sb, ignore_errors=True)
