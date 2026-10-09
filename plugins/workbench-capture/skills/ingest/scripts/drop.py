"""The drop folder: transcripts the user downloaded by hand (or that graph.py fetched) become one meeting file each.

<DATA>/captured/_drop/meetings/*.vtt|*.docx (+ an optional <name>.meta.json sidecar: title, start, end, organizer,
attendees, series, transcript_source). A .vtt and a .docx of one meeting merge into one file; the .vtt wins for
speaker attribution. Parsed originals move to <WB>/capture/drop-done/<YYYY-MM>/, unparseable ones to failed/."""
import hashlib
import html
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

import common
from common import inline, iso, load_json, put, safe_join, sanitize, slug

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SOURCES = ("recap-page", "teams-transcript", "graph-api")
_NAME = re.compile(r"^(?P<title>.+?)-(?P<d>\d{8})_(?P<t>\d{4,6})(?:UTC|Z)?(?:-.*)?$")
_TS = (r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?|(?:\d+\s*(?:hours?|hrs?|h)\s*)?(?:\d+\s*(?:minutes?|mins?|m)\s*)?"
       r"\d+\s*(?:seconds?|secs?|s)")
# A speaker line in a transcript .docx: the name, a tab or two spaces, then the offset into the meeting.
_HDR = re.compile(rf"^(?P<who>.{{1,120}}?)(?:\t|\s{{2,}})(?P<ts>{_TS})\s*$", re.I)


def fmt_ts(t):
    t = t.strip()
    if ":" in t:
        parts = re.split(r"[.,]", t)[0].split(":")
        while len(parts) < 3:
            parts.insert(0, "0")
        return ":".join(p.zfill(2) for p in parts[-3:])
    n = {u: int(v) for v, u in re.findall(r"(\d+)\s*(h|m|s)", t.lower())}
    return "{:02d}:{:02d}:{:02d}".format(n.get("h", 0), n.get("m", 0), n.get("s", 0))


def parse_vtt(text):
    """WebVTT -> [(HH:MM:SS, speaker or None, text)], from <v Speaker> cue tags."""
    blocks = re.split(r"\n\s*\n", text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").strip())
    if not blocks[0].startswith("WEBVTT"):
        raise ValueError("not a WebVTT file")
    cues = []
    for b in blocks[1:]:
        lines = b.split("\n")
        t = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if t is None or lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        payload = " ".join(lines[t + 1:])
        m = re.match(r"\s*<v(?:\.[^\s>]+)*\s+([^>]*)>", payload)
        body = html.unescape(re.sub(r"<[^>]+>", "", payload)).strip()
        if body:
            cues.append((fmt_ts(lines[t].split("-->")[0]), html.unescape(m.group(1)).strip() if m else None, body))
    if not cues:
        raise ValueError("no cues found")
    return cues


def parse_docx(path):
    """Teams transcript .docx -> (title or None, cues). Stdlib zip + XML; a DTD or entity declaration is refused before
    parsing (Office parts never carry one), which closes the entity-expansion attacks of the stdlib parser."""
    with zipfile.ZipFile(path) as z:
        info = z.getinfo("word/document.xml")
        if info.file_size > 50_000_000:
            raise ValueError("document part too large")
        raw = z.read(info)
    if re.search(rb"<!(doctype|entity)", raw, re.I):
        raise ValueError("unexpected DTD in document part")
    paras = []
    for p in ET.fromstring(raw).iter(W + "p"):
        s = "".join("\t" if e.tag == W + "tab" else " " if e.tag == W + "br" else (e.text or "")
                    for e in p.iter() if e.tag in (W + "t", W + "tab", W + "br"))
        if s.strip():
            paras.append(s.strip("\r\n "))
    title, cues, cur = None, [], None
    for s in paras:
        m = _HDR.match(s)
        if m:
            cur = [fmt_ts(m.group("ts")), m.group("who").strip(), []]
            cues.append(cur)
        elif cur:
            cur[2].append(s)
        elif title is None:
            title = s
    cues = [(ts, who, " ".join(txt)) for ts, who, txt in cues if txt]
    if not cues:
        raise ValueError("no transcript entries recognised")
    return title, cues


def name_meta(stem):
    """(title, start) from a Teams download name such as 'Weekly Sync-20261001_090000-Meeting Transcript'."""
    m = _NAME.match(stem)
    if m:
        d, t = m.group("d"), m.group("t").ljust(6, "0")
        try:
            return m.group("title").strip(" _-"), iso(datetime(int(d[:4]), int(d[4:6]), int(d[6:]), int(t[:2]), int(t[2:4]), int(t[4:6]), tzinfo=timezone.utc))
        except ValueError:
            pass
    return stem.strip(), None


def norm_start(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return iso(d if d.tzinfo else d.replace(tzinfo=timezone.utc))
    except ValueError:
        return str(s).strip()


def meeting_id(title, start, organizer):
    key = "\n".join([re.sub(r"\s+", " ", title).strip().lower(), start or "", (organizer or "").strip().lower()])
    return hashlib.sha256(key.encode()).hexdigest()


def organizer_slug(org):
    if not org:
        return "unsorted"
    name = re.sub(r"<[^>]*>", "", org).strip() or org.split("@")[0]
    return slug(name)


def lines_of(cues, stamps=True):
    out = []
    for ts, who, text in cues:
        text = sanitize(text)
        who = inline(who) if who else None
        if out and out[-1][1] == who:
            out[-1][2].append(text)
        else:
            out.append([ts, who, [text]])
    return [f"{f'[{ts}] ' if stamps else ''}{who + ': ' if who else ''}{' '.join(t)}" for ts, who, t in out]


def _move(files, dest):
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        if f.exists():
            t, n = safe_join(dest, f.name), 1
            while t.exists():
                t, n = safe_join(dest, f"{f.stem}-{n}{f.suffix}"), n + 1
            shutil.move(str(f), str(t))


def process(P, find, rep, pidx):
    """Turn everything waiting in the drop folder into meeting files. Returns the written entries (with `labels` and `when`)."""
    P.drop.mkdir(parents=True, exist_ok=True)
    groups, written = {}, []
    for f in sorted(P.drop.iterdir()):
        if not f.is_file() or f.suffix.lower() not in (".vtt", ".docx") or f.name.startswith(("~$", ".")):
            continue
        side_f = f.with_suffix(".meta.json")
        side = load_json(side_f, {}) if side_f.exists() else {}
        side = side if isinstance(side, dict) else {}
        keep = [f, side_f] if side_f.exists() else [f]
        try:
            label, doc_title, cues = None, None, []
            if f.suffix.lower() == ".docx":
                try:
                    label = find.label(f)
                except Exception as e:  # cannot tell whether it is labelled: leave it where it is
                    rep["skipped"].append({"item": f.name, "reason": f"left in place: {str(e)[:120]}"})
                    continue
                if not label:
                    doc_title, cues = parse_docx(f)
            else:
                cues = parse_vtt(f.read_bytes().decode("utf-8-sig"))
            n_title, n_start = name_meta(f.stem)
            title = inline(side.get("title") or n_title or doc_title or f.stem)[:300]
            start = norm_start(side.get("start")) or n_start or (datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT00:00:00Z"))
            organizer = inline(side.get("organizer"))[:200] or None
            mid = meeting_id(title, start, organizer)
            g = groups.setdefault(mid, {"title": title, "start": start, "organizer": organizer, "files": [], "vtt": [], "docx": [], "labels": set(), "side": side})
            g["files"] += [k for k in keep if k not in g["files"]]
            g["labels"].update([label] if label else [])
            if f.suffix.lower() == ".docx" and cues:
                g["docx"] += cues
            elif cues:
                g["vtt"] += cues
        except Exception as e:
            _move(keep, P.drop / "failed")
            rep["skipped"].append({"item": f.name, "reason": f"failed: {type(e).__name__}: {str(e)[:160]}"})
            rep["counts"]["failed"] = rep["counts"].get("failed", 0) + 1
    for mid, g in groups.items():
        side, cues = g["side"], g["vtt"] or g["docx"]
        attendees = [inline(a)[:200] for a in side.get("attendees") or [] if isinstance(a, str)] or list(dict.fromkeys(who for _, who, _ in cues if who))
        src = side.get("transcript_source") if side.get("transcript_source") in SOURCES else "teams-transcript"
        labels = sorted(g["labels"])
        unknown = side.get("speakers") == "unknown"
        body = "" if labels else (f"# {g['title']}\n\n## Transcript\n\n" + ("Speakers and times were not available for this transcript.\n\n" if unknown else "")
                                  + "\n".join(lines_of(cues, stamps=not unknown)))
        end = norm_start(side.get("end"))
        scope_slug = slug(inline(side.get("series"))) if side.get("series") else organizer_slug(g["organizer"])
        item = {"url": f"teams-meeting:{mid}", "title": g["title"], "author": g["organizer"], "modified": end or g["start"], "labels": labels,
                "scope": f"meetings:{scope_slug}", "body": body,
                "extra": {"meeting_id": mid, "organizer": g["organizer"], "attendees": attendees[:200], "start": g["start"], "end": end, "transcript_source": src}}
        try:
            e = put(P, pidx, "meetings", item, scope_slug, (g["start"] or iso(common.clock()))[:10])
        except Exception as ex:
            _move(g["files"], P.drop / "failed")
            rep["skipped"].append({"item": g["title"], "reason": f"failed: {type(ex).__name__}: {str(ex)[:160]}"})
            rep["counts"]["failed"] = rep["counts"].get("failed", 0) + 1
            continue
        e.update(labels=labels, when=g["start"])
        _move(g["files"], P.drop_done / common.clock().strftime("%Y-%m"))
        c = rep["counts"]
        c[e["status"]] = c.get(e["status"], 0) + 1
        if labels:
            c["labelled"] = c.get("labelled", 0) + 1
        if e["status"] == "written":
            written.append(e)
    return written
