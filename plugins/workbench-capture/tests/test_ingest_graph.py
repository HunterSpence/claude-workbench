"""Ingest: the SHOULD-level Graph client against a fake server on localhost (no tenant, no network)."""
import hashlib
import json
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import harness as H  # noqa: E402
from fakes.fake_graph import FakeGraph, JOIN, event  # noqa: E402
import common  # noqa: E402
import graph  # noqa: E402

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
CLIENT = "11111111-2222-4333-8444-555555555555"
MEET = ("meetings", "run", "--graph", "--no-digest")
MAIL = ("mail", "run", "--experimental", "--source", "graph", "--no-digest")


class GraphBase(unittest.TestCase):
    def setUp(self):
        if os.name != "nt":
            if REQUIRE:
                self.fail("the token cache needs Windows (DPAPI)")
            self.skipTest("DPAPI is Windows only")
        self.fg = FakeGraph()
        self.addCleanup(self.fg.close)
        self.e = H.Env(extra_env={"WB_GRAPH_BASE": self.fg.base})
        self.addCleanup(self.e.close)
        self.e.settings(graph_client_id=CLIENT, graph_tenant_id="example.com")
        p = mock.patch.object(common, "clock", lambda: NOW)
        p.start()
        self.addCleanup(p.stop)
        self.slept, self.said = [], []
        self.hooks = {"sleep": self.slept.append, "say": self.said.append}

    def run_graph(self, *argv, hooks=None):
        return self.e.run(*argv, hooks={**self.hooks, **(hooks or {})})

    def meetings(self):
        return sorted(self.e.P.captured.glob("meetings/*/*.md"))

    def transcript_calls(self):
        return [c for c in self.fg.gets("/v1.0/me/onlineMeetings/") if c[1].endswith("/content")]


class TranscriptTests(GraphBase):
    def test_an_ended_meeting_becomes_a_meeting_file_with_graph_api_as_its_source(self):
        code, out = self.run_graph(*MEET)
        self.assertEqual(code, 0, out)
        (f,) = self.meetings()
        fm, body = common.read_file(f)
        self.assertEqual((fm["transcript_source"], fm["title"], fm["start"], fm["end"], fm["organizer"]),
                         ("graph-api", "Launch Planning", "2026-10-08T08:30:00Z", "2026-10-08T09:30:00Z", "Alice Example <alice@example.com>"))
        self.assertEqual(fm["attendees"], ["Bob Sample <bob@example.com>"])
        self.assertIn("[00:00:03] Alice Example: Graph transcript line about the launch plan.", body)
        raw = f.read_text("utf-8")
        for secret in ("meetup-join", "meeting_fake123", "context=hidden", "FAKE-ACCESS", "FAKE-REFRESH"):
            self.assertNotIn(secret, raw)
        st = (self.e.P.state / "graph-meetings.json").read_text("utf-8")
        self.assertNotIn("meetup-join", st)  # the join URL is held in memory only
        self.assertEqual(len(self.transcript_calls()), 1)  # "Just Ended" is under 15 minutes; the others have no meeting or are cancelled
        self.assertEqual(self.e.reports()[-1]["counts"]["transcripts-fetched"], 1)
        self.assertTrue(any("ABCD-1234" in s for s in self.said))  # the user is shown the code to enter

    def test_a_second_run_signs_in_and_fetches_nothing_again(self):
        self.run_graph(*MEET)
        before = len(self.fg.calls)
        code, out = self.run_graph(*MEET)
        self.assertEqual(code, 0, out)
        new = self.fg.calls[before:]
        self.assertEqual([c for c in new if c[0] == "POST"], [])
        self.assertEqual([c for c in new if c[1].endswith("/content") or "onlineMeetings" in c[1]], [])
        self.assertEqual(len(self.meetings()), 1)

    def test_tenant_gate_stops_the_route_after_one_call_and_reports_the_ask(self):
        self.fg.mode["transcripts"] = "disabled"
        code, out = self.run_graph(*MEET)
        self.assertEqual(code, 3, out)
        self.assertIn(common.ASKS["transcripts-disabled"], out)
        rep = self.e.reports()[-1]
        self.assertEqual((rep["stop"]["kind"], rep["stop"]["ask"]), ("tenant", common.ASKS["transcripts-disabled"]))
        self.assertEqual(len(self.transcript_calls()), 1)
        n = len(self.fg.calls)
        code, out = self.run_graph(*MEET)  # the same day: no call at all
        self.assertEqual((code, len(self.fg.calls)), (3, n))
        self.run_graph("logout")
        self.assertFalse((self.e.P.state / "graph-token.bin").exists())

    def test_a_tenant_gate_does_not_stop_hand_dropped_transcripts(self):
        self.fg.mode["transcripts"] = "disabled"
        self.e.P.drop.mkdir(parents=True)
        (self.e.P.drop / "Hand Dropped-20261007_090000-Meeting Transcript.vtt").write_text(H.vtt(), "utf-8")
        code, _ = self.run_graph(*MEET)
        self.assertEqual(code, 3)
        self.assertEqual(len(self.meetings()), 1)

    def test_speaker_attribution_403_retries_once_without_speakers(self):
        self.fg.mode["transcripts"] = "speaker"
        code, out = self.run_graph(*MEET)
        self.assertEqual(code, 0, out)
        accepts = [c[2]["accept"] for c in self.transcript_calls()]
        self.assertEqual(accepts, ["text/vtt", "application/vnd.microsoft.graph.transcript+text"])
        (f,) = self.meetings()
        body = f.read_text("utf-8")
        self.assertIn("Speakers and times were not available", body)
        self.assertIn("Unattributed line two.", body)
        self.assertNotIn("[00:00:00]", body)

    def test_retry_after_is_honoured(self):
        self.fg.mode.update(transcripts="throttle", throttle_left=1)
        code, out = self.run_graph(*MEET)
        self.assertEqual(code, 0, out)
        self.assertIn(7, self.slept)
        self.assertEqual(len(self.transcript_calls()), 2)
        self.assertEqual(len(self.meetings()), 1)

    def test_no_transcript_yet_backs_off_then_tries_again(self):
        self.fg.mode["transcripts"] = "none"
        self.run_graph(*MEET)
        self.assertEqual(self.meetings(), [])
        rec = list(json.loads((self.e.P.state / "graph-meetings.json").read_text("utf-8"))["events"].values())[0]
        self.assertEqual((rec["attempts"], rec["next"]), (1, "2026-10-08T12:15:00Z"))
        n = len(self.fg.gets("/v1.0/me/onlineMeetings"))
        self.run_graph(*MEET)
        self.assertEqual(len(self.fg.gets("/v1.0/me/onlineMeetings")), n)  # still inside the back-off
        self.fg.mode["transcripts"] = "ok"
        with mock.patch.object(common, "clock", lambda: NOW + timedelta(minutes=20)):  # "Just Ended" is old enough by now, too
            self.assertEqual(self.run_graph(*MEET)[0], 0)
        self.assertEqual(sorted(common.read_file(f)[0]["title"] for f in self.meetings()), ["Just Ended", "Launch Planning"])

    def test_a_meeting_older_than_seven_days_is_given_up(self):
        self.fg.events = [__import__("fakes.fake_graph", fromlist=["event"]).event("ev-9", "Old Review", "2026-09-30T09:00:00", "2026-09-30T10:00:00")]
        self.run_graph(*MEET)
        rep = self.e.reports()[-1]
        self.assertEqual(self.transcript_calls(), [])
        self.assertTrue(any("gave up" in s["reason"] for s in rep["skipped"]))

    def test_admin_approval_is_a_stop_with_its_own_ask(self):
        self.fg.mode["device"] = "consent"
        code, out = self.run_graph(*MEET)
        self.assertEqual(code, 3, out)
        self.assertEqual(self.e.reports()[-1]["stop"]["ask"], common.ASKS["admin-consent"])
        self.assertEqual(self.fg.gets("/v1.0/me/calendarView"), [])


HOSTILE = ["..\\..\\evil", "../../evil", "C:evil", "a/b", "T" * 300, "Plan\x00\x1f\x07 review\r\n", "...", "CON", 'q*?"<>|']


def tree(root):
    return {p for p in Path(root).rglob("*") if p.is_file()}


class FilenameTests(GraphBase):
    """A meeting subject is set by whoever sent the invite: it must never steer where a file is written."""

    def test_hostile_subjects_land_as_files_inside_the_drop_folder_only(self):
        self.e.P.drop.mkdir(parents=True)
        before = tree(self.e.tmp.name)
        ev = event("e", "x", "2026-10-08T08:30:00", "2026-10-08T09:30:00")
        for i, subject in enumerate(HOSTILE):
            graph._write_drop(self.e.P, {**ev, "id": f"e{i}", "subject": subject}, 1, "WEBVTT\n", False)
            new = tree(self.e.tmp.name) - before
            self.assertEqual({p.parent.resolve() for p in new}, {self.e.P.drop.resolve()}, subject)
            self.assertEqual(len(new), 2 * (i + 1), subject)  # the transcript and its sidecar, nothing else, nowhere else
        names = [p.name for p in self.e.P.drop.iterdir()]
        self.assertTrue(all(len(n) <= 60 + len("-20261008_083000-abcdef-Meeting Transcript.meta.json") for n in names), names)
        self.assertTrue(all(not re.search(r'[\\/:*?"<>|\x00-\x1f]', n) and ".." not in n for n in names), names)
        self.assertEqual(sum(n.startswith("Meeting-") for n in names), 2 * 2)  # "..." and "CON" fall back to the default name

    def test_a_run_with_hostile_subjects_writes_only_where_ingest_writes(self):
        evs, meetings, trs = [], {}, {}
        for i, subject in enumerate(HOSTILE):
            join = f"{JOIN}{i}"
            evs.append(event(f"ev-{i}", subject, f"2026-10-07T{6 + i:02d}:00:00", f"2026-10-07T{6 + i:02d}:30:00", join=join))
            meetings[join], trs[f"mtg-{i}"] = f"mtg-{i}", [{"id": "t", "createdDateTime": "2026-10-08T09:40:00Z"}]
        self.fg.events, self.fg.meetings, self.fg.transcripts = evs, meetings, trs
        code, out = self.run_graph(*MEET)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.meetings()), len(HOSTILE))
        self.assertEqual(sorted(p.name for p in self.e.P.captured.iterdir()), ["_drop", "meetings"])
        outside = [p for p in tree(self.e.tmp.name) if not any(r in p.parents for r in (self.e.P.data, self.e.P.wb, self.e.bin))]
        self.assertEqual([p.name for p in outside], ["find.log"] if self.e.find_log.exists() else [])


class TokenTests(GraphBase):
    def test_the_token_cache_is_dpapi_encrypted_never_plaintext_and_never_printed(self):
        code, out = self.run_graph(*MEET)
        raw = (self.e.P.state / "graph-token.bin").read_bytes()
        self.assertEqual(code, 0, out)
        for plain in (self.fg.refresh, self.fg.access, "FAKE-REFRESH", "refresh_token", CLIENT):
            self.assertNotIn(plain.encode(), raw)
        self.assertRaises(ValueError, json.loads, raw)
        every = out + "".join(self.said) + json.dumps(self.e.reports()) + "".join(f.read_text("utf-8") for f in self.e.P.state.glob("*.json"))
        self.assertNotIn("FAKE-REFRESH", every)
        self.assertNotIn("FAKE-ACCESS", every)
        tok = graph.load_token(self.e.P)
        self.assertEqual(tok["refresh_token"], self.fg.refresh)

    def test_dpapi_round_trip_and_tamper(self):
        blob = graph.protect(b"a secret value")
        self.assertNotIn(b"a secret value", blob)
        self.assertEqual(graph.unprotect(blob), b"a secret value")
        self.assertRaises(OSError, graph.unprotect, blob[:-3] + b"xyz")

    def test_an_expired_access_token_is_refreshed_not_signed_in_again(self):
        self.run_graph(*MEET)
        tok = graph.load_token(self.e.P)
        tok["expires_at"] = 0
        graph.save_token(self.e.P, tok)
        self.fg.mode["transcripts"] = "ok"
        before = len([c for c in self.fg.calls if c[0] == "POST"])
        code, out = self.run_graph(*MEET)
        grants = [c[2].get("grant_type") for c in self.fg.calls if c[0] == "POST"][before:]
        self.assertEqual((code, grants), (0, ["refresh_token"]), out)

    def test_a_first_party_or_missing_client_id_is_refused(self):
        self.e.settings(graph_client_id="14d82eec-204b-4c2f-b7e8-296a70dab67e")
        code, out = self.run_graph(*MEET)
        self.assertEqual(code, 4)
        self.assertIn("first-party", out)
        self.e.settings(graph_client_id="", graph_tenant_id="")
        code, out = self.run_graph(*MEET)
        self.assertEqual(code, 4)
        self.assertIn("graph_client_id", out)
        self.assertEqual(self.fg.calls, [])

    def test_the_base_override_is_localhost_only(self):
        self.assertEqual(graph.endpoints({}), (graph.LOGIN, graph.GRAPH))
        for bad in ("https://localhost:9", "http://example.com", "http://evil.localhost.example.com:80"):
            with self.assertRaises(ValueError):
                graph.endpoints({"WB_GRAPH_BASE": bad})

    def test_every_graph_data_call_is_a_get(self):
        self.run_graph(*MEET)
        self.run_graph(*MAIL)
        posts = [c[1] for c in self.fg.calls if c[0] == "POST"]
        self.assertTrue(all(p.endswith(("/devicecode", "/token")) for p in posts), posts)


class MailTests(GraphBase):
    def test_per_folder_delta_writes_thread_files_and_the_next_run_asks_only_for_changes(self):
        code, out = self.run_graph(*MAIL)
        self.assertEqual(code, 0, out)
        files = {common.read_file(p)[0]["title"]: p for p in self.e.P.captured.glob("outlook/*/*.md")}
        self.assertEqual(sorted(files), ["Labelled note", "Launch notes"])
        fm, body = common.read_file(files["Launch notes"])
        self.assertEqual((fm["source"], fm["thread_id"], fm["from"]), ("outlook", hashlib.sha256(b"gc1").hexdigest(), "Alice Example <alice@example.com>"))
        self.assertIn("Graph mail body about the launch.", body)
        self.assertIn("### Attachment: notes.txt", body)
        self.assertIn("Attached notes", body)
        fm, body = common.read_file(files["Labelled note"])
        self.assertEqual(fm["labels"], ["Confidential"])
        self.assertNotIn("GRAPHSECRET", body)
        mtimes = {k: p.stat().st_mtime_ns for k, p in files.items()}
        n = len(self.fg.calls)
        code, out = self.run_graph(*MAIL)
        self.assertEqual(code, 0, out)
        deltas = [c[1] for c in self.fg.calls[n:] if "messages/delta" in c[1]]
        self.assertTrue(deltas and all("deltatoken=1" in d or "f-sent" in d for d in deltas), deltas)
        self.assertEqual({k: p.stat().st_mtime_ns for k, p in files.items()}, mtimes)


if __name__ == "__main__":
    unittest.main()
