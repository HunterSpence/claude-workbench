#!/usr/bin/env python3
"""ingest.py: meeting transcripts and (experimental, opt-in) cached mail into the knowledge layer (interface I25).

  ingest.py setup [--apply] | meetings run [--graph] [--no-digest] [--json]
            mail probe [--json] | mail run --experimental --source com|graph [--folders L] [--since D] [--max-items N] [--no-digest] [--json]
            digest PATH | digest --pending [--max N] | rollup [--date D] | config get|set KEY [VALUE]
            purge --source meetings|outlook [--older-than DAYS] | logout | status --json
Exit: 0 ok, 3 stopped by a sign-in prompt, policy or tenant gate (report carries the ask-IT text), 4 error."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import digest  # noqa: E402
import drop  # noqa: E402
from mailsource import PolicyBlock  # noqa: E402

ATTACH_OK = {".docx", ".pptx", ".xlsx", ".pdf", ".txt", ".md", ".csv"}
MAX_ATTACH = 10 * 2**20
CAPS = {"skipped": 200, "entries": 2000}  # a 100k-message backfill must not make a 20 MB report


def skip(rep, item, reason):
    if len(rep["skipped"]) < CAPS["skipped"]:
        rep["skipped"].append({"item": item, "reason": reason})
    else:
        rep["counts"]["skipped-not-listed"] = rep["counts"].get("skipped-not-listed", 0) + 1


def bump(rep, k, n=1):
    rep["counts"][k] = rep["counts"].get(k, 0) + n


def emit(rep, report_file, as_json):
    rep = {**rep, "report": C.fwd(report_file)}
    if as_json:
        print(json.dumps(rep, indent=2))
        return
    print(f"{rep['kind']}: {rep['status']}  {json.dumps(rep['counts'])}")
    if rep["stop"]:
        print(f"STOPPED ({rep['stop']['kind']}): {rep['stop']['reason']}\nAsk: {rep['stop']['ask']}")
    if rep["error"]:
        print(f"error: {rep['error']}")
    for n in rep["notes"]:
        print(f"note: {n}")
    print(f"report: {rep['report']}")


def job(kind, P, a, body, experimental=False):
    """Run `body(rep)`; a Stop becomes exit 3 with the ask-IT text, any other failure exit 4. Always writes a run report."""
    rep = C.new_report(kind, experimental)
    try:
        body(rep)
        code = 0
    except C.Stop as s:
        rep["status"], rep["stop"], code = "stopped", {"kind": s.kind, "reason": s.reason, "ask": s.ask}, 3
    except PolicyBlock as e:
        s = C.Stop("outlook-blocked", str(e), "outlook-blocked")
        rep["status"], rep["stop"], code = "stopped", {"kind": s.kind, "reason": s.reason, "ask": s.ask}, 3
    except Exception as e:
        if os.environ.get("WB_DEBUG"):
            raise
        rep["status"], rep["error"], code = "error", f"{type(e).__name__}: {str(e)[:300]}", 4
    emit(rep, C.save_report(P, rep, code), getattr(a, "json", False))
    return code


def within_window(S, when):
    try:
        d = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        return C.clock() - (d if d.tzinfo else d.replace(tzinfo=timezone.utc)) <= timedelta(days=int(S["digest_window_days"]))
    except ValueError:
        return False


def finish_digests(P, S, rep, env, hooks, newly, no_digest):
    """Queue the new, unlabelled, recent items; unless --no-digest, digest what the daily cap allows, then write the rollup."""
    digest.add_pending(P, [e["path"] for e in newly if not e["labels"] and within_window(S, e.get("when") or e.get("received"))])
    if no_digest:
        return
    if digest.run_pending(P, S, rep, env, timeout=hooks.get("digest_timeout", 300)) and digest.rollup(P, C.iso(C.clock())[:10]):
        rep["notes"].append(f"rollup written to {C.fwd(P.kb / 'inbox')}")


def entries_of(written):
    return [{k: e[k] for k in ("url", "path", "sha256", "expires")} for e in written[:CAPS["entries"]]]


# ---- meetings ---------------------------------------------------------------------------------------------------
def cmd_meetings_run(a, P, S, env, hooks):
    def body(rep):
        stopped = None
        if a.graph:  # a tenant gate stops the Graph route only; transcripts already in the drop folder are still processed
            import graph
            try:
                graph.fetch_transcripts(P, S, rep, env, hooks)
            except C.Stop as s:
                stopped = s
        written = drop.process(P, hooks.get("find") or C.Find(P, env), rep, C.PathIndex(P, "meetings"))
        rep["entries"] = entries_of(written)
        finish_digests(P, S, rep, env, hooks, written, a.no_digest)
        if stopped:
            raise stopped
    return job("meetings", P, a, body)


# ---- mail -------------------------------------------------------------------------------------------------------
class BodyTimer:
    """A protected read that never returns (a security prompt is waiting) ends the run: after `timeout` seconds a watchdog
    thread records the stop and exits the process. A read that returns late raises PolicyBlock from the context manager."""

    def __init__(self, timeout, on_hang):
        self.timeout, self.on_hang, self.fired, self.t = timeout, on_hang, False, None

    def __enter__(self):
        self.t = threading.Timer(self.timeout, self._fire)
        self.t.daemon = True
        self.t.start()

    def _fire(self):
        self.fired = True
        self.on_hang()

    def __exit__(self, et, ev, tb):
        self.t.cancel()
        if self.fired and et is None:
            raise PolicyBlock(f"a mailbox read did not return within {self.timeout} s (a security prompt may be waiting)")
        return False


def wanted_folder(path, wanted):
    p = path.lower()
    return any(p == w or (w.endswith("/*") and p.startswith(w[:-1])) for w in wanted)


def make_source(kind, P, S, env, hooks):
    if hooks.get("source"):
        return hooks["source"]
    if kind == "graph":
        import graph
        return graph.GraphMail(P, S, env, hooks)
    import outlook_com
    try:
        return outlook_com.OutlookCom()
    except Exception as e:
        raise RuntimeError(f"classic Outlook could not be reached ({type(e).__name__}); the new Outlook has no object model, use --source graph or the Outlook on the web source of capture") from e


def cmd_mail_run(a, P, S, env, hooks):
    if not a.experimental:
        print("Mail ingest is experimental: add --experimental to run it.", file=sys.stderr)
        return 4
    since0 = f"{a.since}T00:00:00Z" if a.since else None
    if a.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.since):
        print("--since must be YYYY-MM-DD", file=sys.stderr)
        return 4

    def body(rep):
        src, find, pacer = make_source(a.source, P, S, env, hooks), hooks.get("find") or C.Find(P, env), hooks.get("pacer") or C.Pacer()
        cp_file = P.state / "mail-checkpoint.json"
        cp = C.load_json(cp_file, {"version": 1, "folders": {}})
        cp.setdefault("folders", {})
        wanted = [w.strip().lower() for w in (a.folders.split(",") if a.folders else S["mail_folders"]) if w.strip()]
        pidx, written, total = C.PathIndex(P, "outlook"), [], 0

        def on_hang():  # the main thread is stuck inside a mailbox call
            rep.update(status="stopped", stop={"kind": "outlook-blocked", "reason": "a mailbox read did not return (a security prompt may be waiting)", "ask": C.ASKS["outlook-blocked"]})
            emit(rep, C.save_report(P, rep, 3), False)
            hooks.get("hard_exit", os._exit)(3)
        timer = BodyTimer(hooks.get("body_timeout", 20), on_hang)

        def convert_attachments(atts):
            out = []
            for at in atts:
                ext = Path(at.name).suffix.lower()
                if ext not in ATTACH_OK or at.size > MAX_ATTACH:
                    skip(rep, at.name, "attachment not converted: type or size")
                    continue
                pacer.tick()
                try:
                    with tempfile.TemporaryDirectory(prefix="wb-att-") as d:  # the attachment's own name is never used as a path
                        f = Path(d) / f"attachment{ext}"
                        with timer:
                            at.save(str(f))
                        c = find.convert(f)
                except PolicyBlock:
                    raise
                except Exception as e:
                    skip(rep, at.name, f"attachment not converted: {str(e)[:100]}")
                    continue
                if c.get("label") or c.get("error") or not c.get("markdown"):
                    skip(rep, at.name, "attachment not converted: labelled or unreadable")
                else:
                    out.append({"name": at.name, "markdown": C.sanitize(c["markdown"])[:20000]})
            return out

        def read_message(it):
            with timer:
                labels = src.labels(it)
            irm = any(t in it.message_class.lower() for t in ("rpmsg", "rightsmanagement"))
            atts = []
            if not labels:
                with timer:
                    atts = src.attachments(it)
                irm = irm or any(x.name.lower().endswith(".rpmsg") for x in atts)
            prot = bool(labels) or irm
            with timer:
                h = src.body(it, headers_only=prot)
            m = {"key": hashlib.sha1((h.get("message_id") or it.entry_id).encode()).hexdigest(), "message_id": h.get("message_id"),
                 "subject": C.inline(it.subject), "from": h.get("from"), "to": h.get("to") or [], "cc": h.get("cc") or [],
                 "received": it.received, "modified": it.modified, "labels": labels or (["rights-managed"] if irm else []), "withheld": prot}
            if prot:
                bump(rep, "protected")
            else:
                html = bool(h.get("html"))
                m["text"] = C.strip_quoted(C.sanitize(h["html"] if html else h.get("text") or "", html=html, drop_quotes=True))
                m["attachments"] = convert_attachments(atts)
            return m

        for store in src.stores():
            if not store.cached:
                skip(rep, store.name, "not a cached Exchange store (online archive, public folder or other): not read")
                continue
            for folder in src.folders(store):
                if not wanted_folder(folder.path, wanted) or (a.max_items and total >= a.max_items):
                    continue
                key = f"{store.id}|{folder.path}"
                st = cp["folders"].get(key)
                since = st["since"] if st else since0
                ids = set(st["ids"]) if st else set()
                done_before = bool(st and st.get("backfill_done"))
                hw, hwids, threads, n, complete = since, set(ids), {}, 0, True

                def flush():
                    for conv, msgs in threads.items():
                        e = C.write_thread(P, pidx, conv, folder.path, msgs)
                        bump(rep, e["status"])
                        if e["status"] == "written":
                            written.append(e)
                            if done_before:  # the first pass over a folder (the backfill) is never digested
                                e["when"] = e["received"]
                    threads.clear()
                    cp["folders"][key] = {"since": hw, "ids": sorted(hwids), "backfill_done": done_before}
                    C.atomic_write(cp_file, json.dumps(cp, indent=1) + "\n")

                for it in src.items(folder, since, ids):
                    if a.max_items and total >= a.max_items:
                        complete = False
                        break
                    pacer.tick()
                    threads.setdefault(it.conversation_id or it.entry_id, []).append(read_message(it))
                    total, n = total + 1, n + 1
                    if hw is None or it.modified > hw:
                        hw, hwids = it.modified, {it.entry_id}
                    elif it.modified == hw:
                        hwids.add(it.entry_id)
                    if n % 200 == 0:
                        flush()
                        pacer.batch()
                flush()
                if complete and not done_before:  # the pass reached the end of the folder
                    cp["folders"][key]["backfill_done"] = True
                    C.atomic_write(cp_file, json.dumps(cp, indent=1) + "\n")
        bump(rep, "items", total)
        rep["entries"] = entries_of(written)
        finish_digests(P, S, rep, env, hooks, [e for e in written if e.get("when")], a.no_digest)
    return job("mail", P, a, body, experimental=True)


def run_child(cmd, timeout):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        return "timeout"
    return "ok" if p.returncode == 0 else "failed"


def cmd_mail_probe(a, P, S, env, hooks):
    import outlook_com

    def body(rep):
        out = rep["probe"] = {"classic_outlook": False, "policy": {}, "auto_deny": [], "inbox_count": None, "subject_read": False, "body_read": None, "advice": None}
        out["policy"] = hooks["policy"] if "policy" in hooks else outlook_com.read_policy()
        out["auto_deny"] = outlook_com.auto_denied(out["policy"])
        try:
            src = hooks.get("source") or outlook_com.OutlookCom()
            out.update(src.probe_summary())
        except Exception as e:
            out["advice"] = (f"Classic Outlook could not be reached ({type(e).__name__}). The new Outlook has no object model: use the Graph route "
                             "(set graph_client_id and graph_tenant_id, then mail run --source graph) or the Outlook on the web source of capture.")
            return
        if not out["inbox_count"]:
            out["body_read"] = "skipped: the Inbox is empty"
            return
        res = run_child(hooks.get("child_cmd") or [sys.executable, str(C.HERE / "outlook_com.py"), "--body-probe"], hooks.get("probe_timeout", 20))
        out["body_read"] = res
        if res != "ok":
            raise C.Stop("outlook-blocked", f"reading one message body {'timed out (a security prompt may be waiting)' if res == 'timeout' else 'was refused or failed'}", "outlook-blocked")
    return job("mail-probe", P, a, body)


# ---- digest, rollup ---------------------------------------------------------------------------------------------
def cmd_digest(a, P, S, env, hooks):
    if bool(a.path) == bool(a.pending):
        print("give a PATH or --pending", file=sys.stderr)
        return 4

    def body(rep):
        if a.pending:
            digest.run_pending(P, S, rep, env, a.max, hooks.get("digest_timeout", 300))
        else:
            status, why = digest.digest_file(P, S, a.path, env, digest.load_state(P), hooks.get("digest_timeout", 300), windowed=False)
            bump(rep, f"digest-{status}")
            if status != "digested":
                raise RuntimeError(f"not digested ({status}): {why}")
        if rep["counts"].get("digest-digested") or not a.pending:
            digest.rollup(P, C.iso(C.clock())[:10])
    return job("digest", P, a, body)


def cmd_rollup(a, P, S, env, hooks):
    f = digest.rollup(P, a.date or C.iso(C.clock())[:10])
    print(C.fwd(f) if f else "no digests recorded for that day")
    return 0


# ---- housekeeping -----------------------------------------------------------------------------------------------
SETTING_TYPES = {"graph_client_id": str, "graph_tenant_id": str, "mail_folders": list, "digest_model": str, "digest_max_per_day": int,
                 "digest_window_days": int}


def cmd_config(a, P, S, env, hooks):
    if a.key not in C.DEFAULTS:
        print(f"unknown setting; known: {', '.join(C.DEFAULTS)}", file=sys.stderr)
        return 4
    if a.action == "get":
        print(json.dumps(S[a.key]))
        return 0
    if a.key not in SETTING_TYPES or a.value is None:
        print("usage: config set KEY VALUE", file=sys.stderr)
        return 4
    t = SETTING_TYPES[a.key]
    try:
        v = [x.strip() for x in a.value.split(",") if x.strip()] if t is list else (int(a.value) if t is int else (a.value or None))
        if t is int and v < 1:
            raise ValueError
    except ValueError:
        print(f"{a.key} needs {'a positive whole number' if t is int else 'a value'}", file=sys.stderr)
        return 4
    S[a.key] = v
    C.save_settings(P, S)
    print(f"{a.key} = {json.dumps(v)}")
    return 0


def cmd_setup(a, P, S, env, hooks):
    kpy = P.cfg.get("knowledge_python")
    if not kpy:
        print("knowledge_python is not set in config.json: run the workbench setup first", file=sys.stderr)
        return 4
    cmd = [kpy, "-m", "pip", "install", "-r", str(C.HERE.parent / "requirements.txt")]
    print(("running: " if a.apply else "would run (add --apply): ") + " ".join(cmd))
    if not a.apply:
        return 0
    return 0 if subprocess.run(cmd, env={**env, "DO_NOT_TRACK": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONUTF8": "1"}).returncode == 0 else 4


def purge_source(P, source, days):
    removed = kept = 0
    now = C.clock()
    for f in sorted((P.captured / source).glob("*/*.md")):
        fm, _ = C.read_file(f)
        try:
            old = days is None or now - datetime.fromisoformat(fm["captured_at"].replace("Z", "+00:00")) > timedelta(days=days)
        except (KeyError, TypeError, ValueError, AttributeError):
            old = False
        if fm and fm.get("source") == source and old:
            f.unlink()
            removed += 1
        else:
            kept += 1
    for d in sorted((P.captured / source).glob("*")):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return removed, kept


def cmd_purge(a, P, S, env, hooks):
    removed, kept = purge_source(P, a.source, a.older_than)
    if a.source == "meetings" and P.drop_done.is_dir():  # the originals are copies of the same content
        cut = C.clock().timestamp() - (a.older_than or 0) * 86400
        for f in P.drop_done.rglob("*"):
            if f.is_file() and (a.older_than is None or f.stat().st_mtime < cut):
                f.unlink()
    if a.source == "outlook" and a.older_than is None:
        (P.state / "mail-checkpoint.json").unlink(missing_ok=True)
    print(json.dumps({"source": a.source, "removed": removed, "kept": kept}))
    return 0


def cmd_logout(a, P, S, env, hooks):
    for f in (P.state / "graph-token.bin", P.state / "graph-delta.json", P.state / "graph-meetings.json", P.state / "graph-mail-delta.json"):
        f.unlink(missing_ok=True)
    print("signed out: the encrypted token cache and the Graph progress files were removed")
    return 0


def cmd_status(a, P, S, env, hooks):
    count = lambda g: sum(1 for _ in g)  # noqa: E731
    st = digest.load_state(P)
    runs = sorted(P.runs.glob("*-ingest.json")) if P.runs.is_dir() else []
    out = {"version": C.VERSION, "data_root": C.fwd(P.data),
           "drop_waiting": count(f for f in P.drop.glob("*") if f.is_file() and f.suffix.lower() in (".vtt", ".docx")) if P.drop.is_dir() else 0,
           "drop_failed": count((P.drop / "failed").glob("*")) if (P.drop / "failed").is_dir() else 0,
           "meetings_files": count(P.captured.glob("meetings/*/*.md")), "outlook_files": count(P.captured.glob("outlook/*/*.md")),
           "mail_folders_checkpointed": len(C.load_json(P.state / "mail-checkpoint.json", {}).get("folders", {})),
           "digests_today": st["days"].get(C.iso(C.clock())[:10], {}).get("calls", 0), "digest_pending": len(st["pending"]),
           "digest_max_per_day": S["digest_max_per_day"], "digest_window_days": S["digest_window_days"],
           "graph_configured": bool(S["graph_client_id"] and S["graph_tenant_id"]), "graph_signed_in": (P.state / "graph-token.bin").is_file(),
           "last_report": C.fwd(runs[-1]) if runs else None}
    print(json.dumps(out, indent=2) if a.json else "\n".join(f"{k}: {v}" for k, v in out.items()))
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="ingest.py", description="Meeting transcripts and cached mail into the knowledge layer (experimental).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def add(parent, name, fn, **kw):
        p = parent.add_parser(name, **kw)
        if fn:
            p.set_defaults(fn=fn)
        return p
    add(sub, "setup", cmd_setup).add_argument("--apply", action="store_true")
    m = add(sub, "meetings", None).add_subparsers(dest="sub", required=True)
    r = add(m, "run", cmd_meetings_run)
    r.add_argument("--graph", action="store_true")
    mail = add(sub, "mail", None).add_subparsers(dest="sub", required=True)
    add(mail, "probe", cmd_mail_probe)
    mr = add(mail, "run", cmd_mail_run)
    mr.add_argument("--experimental", action="store_true")
    mr.add_argument("--source", choices=("com", "graph"), required=True)
    mr.add_argument("--folders")
    mr.add_argument("--since")
    mr.add_argument("--max-items", type=int, dest="max_items")
    for p in (r, mr):
        p.add_argument("--no-digest", action="store_true", dest="no_digest")
    for p in (r, mr, mail.choices["probe"]):
        p.add_argument("--json", action="store_true")
    d = add(sub, "digest", cmd_digest)
    d.add_argument("path", nargs="?")
    d.add_argument("--pending", action="store_true")
    d.add_argument("--max", type=int)
    d.add_argument("--json", action="store_true")
    add(sub, "rollup", cmd_rollup).add_argument("--date")
    c = add(sub, "config", cmd_config)
    c.add_argument("action", choices=("get", "set"))
    c.add_argument("key")
    c.add_argument("value", nargs="?")
    pg = add(sub, "purge", cmd_purge)
    pg.add_argument("--source", choices=("meetings", "outlook"), required=True)
    pg.add_argument("--older-than", type=int, dest="older_than")
    add(sub, "logout", cmd_logout)
    add(sub, "status", cmd_status).add_argument("--json", action="store_true")
    return ap


def main(argv=None, env=None, hooks=None):
    """`env` and `hooks` exist for tests (a source, a find client, a pacer, a clock of the process); the CLI passes neither."""
    env = dict(os.environ if env is None else env)
    a = build_parser().parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    P = C.Paths(env)
    try:
        return a.fn(a, P, C.load_settings(P), env, hooks or {})
    except Exception as e:
        if os.environ.get("WB_DEBUG"):
            raise
        print(f"error: {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
