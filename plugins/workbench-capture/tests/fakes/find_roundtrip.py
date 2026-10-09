"""Acceptance 3 for ingest: transcripts in the drop folder become meeting files, the REAL find CLI indexes them, `search`
finds the transcript text with source meetings, and `related` reaches another item that shares an attendee key.

Run with the knowledge environment's Python (it has the find dependencies):
    <knowledge python> find_roundtrip.py [--db PATH]
Exit 0 and a line `find roundtrip OK` on success; any failed check raises."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness as H  # noqa: E402
from fake_mailsource import FakeMailSource  # noqa: E402

CLI = HERE.parents[2] / "workbench-core" / "skills" / "find" / "scripts" / "doc_index.py"
PHRASE = "zebracrossing rollout checklist"


def cli(db, *args):
    r = subprocess.run([sys.executable, str(CLI), "--db", str(db), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, (args, r.returncode, r.stderr[-500:])
    return json.loads(r.stdout) if "--json" in args else r.stdout


def side(title, start, org="Alice Example <alice@example.com>", att=("alice@example.com", "bob@example.com")):
    return json.dumps({"title": title, "start": start, "end": start.replace("09:00", "09:30"), "organizer": org, "attendees": list(att)})


def main():
    db = Path(sys.argv[sys.argv.index("--db") + 1]) if "--db" in sys.argv else Path(tempfile.mkdtemp(prefix="wb-acc3-")) / "index.sqlite"
    e = H.Env()
    e.env["WORKBENCH_FIND_CLI"] = str(CLI)  # the real CLI, not the fake
    e.P.drop.mkdir(parents=True)
    cues = H.CUES + [("00:00:40", "Bob Sample", f"Please review the {PHRASE} before Friday.")]
    stem = "Launch Planning-20261001_090000-Meeting Transcript"
    (e.P.drop / f"{stem}.vtt").write_text(H.vtt(cues), "utf-8")
    H.docx(e.P.drop / f"{stem}.docx", title="Launch Planning", cues=cues)
    (e.P.drop / f"{stem}.meta.json").write_text(side("Launch Planning", "2026-10-01T09:00:00Z"), "utf-8")
    stem2 = "Budget Review-20261002_090000-Meeting Transcript"
    (e.P.drop / f"{stem2}.vtt").write_text(H.vtt([("00:00:05", "Carol Test", "Budget numbers look fine.")]), "utf-8")
    (e.P.drop / f"{stem2}.meta.json").write_text(side("Budget Review", "2026-10-02T09:00:00Z", "Carol Test <carol@example.com>", ("alice@example.com", "carol@example.com")), "utf-8")
    code, out = e.run("meetings", "run", "--no-digest")
    assert code == 0, out
    src = FakeMailSource()
    src.add_store("s1", "Mailbox A")
    src.add("s1", "Inbox", "m1", "c1", "Lunch notes", "2026-10-03T09:00:00Z", text="Lunch is at noon.", sender="Alice Example <alice@example.com>")
    code, out = e.run("mail", "run", "--experimental", "--source", "com", "--no-digest", hooks={"source": src})
    assert code == 0, out
    captured = e.P.captured
    assert (captured / "_drop").is_dir()
    cli(db, "add-root", str(captured), "--json")
    cli(db, "refresh", "--root", "captured", "--embed", "off", "--json")
    hits = cli(db, "search", PHRASE, "--mode", "keyword", "--json")["hits"]
    assert hits, "search found nothing"
    top = hits[0]
    assert top["source"] == "meetings", top
    assert "zebracrossing" in top["snippet"].lower() and top["path"].startswith("meetings/"), top  # the hit marks query words in [brackets]
    assert top["url"].startswith("teams-meeting:"), top
    assert not any("_drop" in h["path"] for h in cli(db, "search", "Welcome everyone", "--mode", "keyword", "--json")["hits"]), "the staging folder was indexed"
    rel = cli(db, "related", top["ref"], "--json")
    blob = json.dumps(rel)
    assert "budget-review" in blob, "related did not reach the meeting that shares an attendee"
    assert "lunch-notes" in blob, "related did not reach the mail thread from the shared attendee"
    print("find roundtrip OK")
    e.close()


if __name__ == "__main__":
    main()
