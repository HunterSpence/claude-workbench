#!/usr/bin/env python3
"""eval_nav.py: score the navigation assistant's answers against the routes they should link (stdlib; --live needs
the anthropic SDK and a credential).

  eval_nav.py --map help/nav-map.md --cases evals/cases.jsonl --answers evals/answers.jsonl
  eval_nav.py --map help/nav-map.md --cases evals/cases.jsonl --live --docs help [--backend DIR] [--record out.jsonl]

cases.jsonl, one object per line: {"question": "...", "role": "member", "expect": ["/reports"]}. A question the docs do
not cover has "not_covered": true and must link the support route and nothing else. Optional "forbid": [routes].
answers.jsonl lines are {"question", "role", "answer_text"}, joined to the cases by question and role. --live asks the
model through the backend's navassist.py (default: this skill's Python template) and can --record the answers.
Checks: an expected route is linked (route accuracy); every link is an in-app path (unsafe) found in the map (unknown);
no link goes to a page whose Who column excludes the caller's role, or that the case forbids (role leak).
Exit 1 when accuracy is under --min-accuracy or any reply failed, any link is unsafe or unknown, any role leaks or
any not-covered question misses support; 2 on bad input.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from route_inventory import read_map  # noqa: E402

DEFAULT_BACKEND = HERE.parent / "templates" / "python"
LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
SAFE_ROUTE = re.compile(r"/(?![/\\])[^\s\\:\x00-\x1f\x7f]*\Z")   # the same rule as the widget and navassist.py
OPEN = {"everyone", "all", "anyone"}
UNFILLED = {"", "todo", "-"}


def load_routes(map_path):
    """{route: set of who-tags, or None when anyone may open it or the cell is not filled in}"""
    out = {}
    for route, (_, _, _, who) in read_map(map_path).items():
        tags = {t.strip().lower() for t in who.split(",") if t.strip()}
        out[route] = None if (tags & OPEN or not tags or tags <= UNFILLED) else tags
    return out


def pattern(route):
    segs = [s for s in route.strip("/").split("/") if s]
    parts = [".+" if s == "*" or s.startswith(("[...", "[[...")) else "[^/]+" if s[0] in "[:{" else re.escape(s)
             for s in segs]
    return re.compile("^/" + "/".join(parts) + "$")


def norm(href):
    path = re.split(r"[?#]", href, maxsplit=1)[0]
    return path.rstrip("/") or "/"


def match(link, routes):
    if link in routes:
        return link
    return next((r for r in routes if r != "/" and pattern(r).match(link)), None)


def tags(role):
    return {str(r).lower() for r in (role if isinstance(role, list) else [role]) if r}


def score(case, answer, routes, support):
    """Problems with one answer: a list of short strings (empty = pass) and whether an expected route was linked."""
    hrefs = [h for _, h in LINK.findall(answer)]
    unsafe = [h for h in hrefs if not SAFE_ROUTE.match(h)]
    links = [norm(h) for h in hrefs if SAFE_ROUTE.match(h)]
    found = {lk: match(lk, routes) for lk in links}
    expect, forbid = [norm(x) for x in case.get("expect", [])], {norm(x) for x in case.get("forbid", [])}
    probs = [f"unsafe link {h}" for h in unsafe]
    probs += [f"unknown route {lk}" for lk, r in found.items() if r is None and lk != support]
    probs += [f"role leak {lk}" for lk, r in found.items()
              if lk in forbid or r in forbid or (r and routes[r] is not None and not routes[r] & tags(case.get("role")))]
    hit = any(lk in expect or r in expect for lk, r in found.items()) if expect else None
    if expect and not hit:
        probs.append("expected " + " or ".join(expect) + (", linked " + ", ".join(found) if found else ", linked nothing"))
    if case.get("not_covered") and (support not in found or any(lk != support for lk in found)):
        probs.append(f"not covered: must link {support} and nothing else")
    return probs, hit


def read_jsonl(path):
    out = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError as e:
                raise ValueError(f"{path}:{n}: {e}") from e
    return out


def key(row):
    return (str(row.get("question", "")).strip(), json.dumps(row.get("role")))


def load_backend(backend):
    spec = importlib.util.spec_from_file_location("navassist", Path(backend) / "navassist.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ask_live(cases, docs, backend=DEFAULT_BACKEND, client=None, app_name="the app", support="/help"):
    """[{question, role, answer_text, failure, cache_read}] from one model call per case, built exactly like the backend."""
    nav = load_backend(backend)
    corpus = nav.load_corpus(docs)
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    out = []
    for c in cases:
        req = nav.build_request(corpus, {"role": c.get("role")}, [{"role": "user", "content": c["question"]}],
                                app_name, support)
        try:
            msg = client.messages.create(**req)
            problem = nav.failure(msg)
            text, cache = ("" if problem else nav.text_of(msg)), getattr(getattr(msg, "usage", None), "cache_read_input_tokens", 0)
        except Exception as e:   # noqa: BLE001 - one failed call is one failed case, the run goes on
            problem, text, cache = f"error {type(e).__name__}", "", 0
        out.append({"question": c["question"], "role": c.get("role"), "answer_text": text, "failure": problem,
                    "cache_read": cache or 0})
    return out


def evaluate(cases, answers, routes, support, min_accuracy):
    """(report lines, passed)"""
    by_key, lines, fails = {key(a): a for a in answers}, [], 0
    hits = scored = support_ok = support_n = failed = 0
    totals = {"unsafe link": 0, "unknown route": 0, "role leak": 0}
    for c in cases:
        a = by_key.get(key(c))
        if a is None or a.get("failure"):
            failed += 1
            probs, hit = ["no answer" if a is None else "reply failed: " + a["failure"]], (False if c.get("expect") else None)
        else:
            probs, hit = score(c, a.get("answer_text", ""), routes, support)
        if hit is not None:
            scored, hits = scored + 1, hits + bool(hit)
        if c.get("not_covered"):
            support_n += 1
            support_ok += not any(p.startswith(("not covered", "no answer", "reply failed")) for p in probs)
        for p in probs:
            for k in totals:
                totals[k] += p.startswith(k)
        if probs:
            fails += 1
            lines.append(f"FAIL [{c.get('role')}] {c['question'][:70]!r}: " + "; ".join(probs))
    acc = hits / scored if scored else 1.0
    lines += [f"route accuracy: {hits}/{scored} ({acc:.0%})", f"support fallback: {support_ok}/{support_n}",
              "unsafe links: {unsafe link}  unknown-route links: {unknown route}  role leaks: {role leak}".format(**totals)
              + f"  failed replies: {failed}"]
    unchecked = sorted(r for r, t in routes.items() if t is None)
    if unchecked:
        lines.append(f"open to everyone or Who not filled in (no role check): {len(unchecked)} route(s)")
    ok = acc >= min_accuracy and not failed and not any(totals.values()) and support_ok == support_n
    lines.append(f"RESULT: {'PASS' if ok else 'FAIL'} ({len(cases) - fails}/{len(cases)} cases clean)")
    return lines, ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--map", required=True)
    ap.add_argument("--cases", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--answers")
    src.add_argument("--live", action="store_true")
    ap.add_argument("--docs", help="help folder for --live")
    ap.add_argument("--backend", default=str(DEFAULT_BACKEND), help="folder holding the navassist.py to use for --live")
    ap.add_argument("--record", help="write the --live answers here as JSONL")
    ap.add_argument("--support", default="/help")
    ap.add_argument("--app-name", default="the app")
    ap.add_argument("--min-accuracy", type=float, default=0.9)
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    try:
        routes, cases = load_routes(a.map), read_jsonl(a.cases)
        if not routes:
            raise ValueError(f"{a.map}: no route rows (a table whose first cell is a /route)")
        if a.live:
            if not a.docs:
                raise ValueError("--live needs --docs")
            answers = ask_live(cases, a.docs, a.backend, app_name=a.app_name, support=a.support)
        else:
            answers = read_jsonl(a.answers)
    except ImportError as e:
        print(f"error: --live needs the anthropic package (pip install -r <backend>/requirements.txt): {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.record:
        Path(a.record).write_text("".join(json.dumps(x) + "\n" for x in answers), encoding="utf-8")
    lines, ok = evaluate(cases, answers, routes, a.support, a.min_accuracy)
    if a.live and len(answers) > 1:
        warm = sum(1 for x in answers[1:] if x.get("cache_read"))
        lines.insert(-1, f"prompt cache: {warm}/{len(answers) - 1} later calls read the cached prefix"
                     + ("" if warm else " (check the prefix is identical and above the minimum)"))
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
