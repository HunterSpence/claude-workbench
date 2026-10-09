"""Tests for report.py and devbench.py. Run: WB_REQUIRE_ALL=1 py -3 -m unittest discover -s bootstrap -p test_report.py -v

  py -3 bootstrap/test_report.py --write-fixture PATH    writes the package-table fixture the live run uses
A missing dependency FAILS when WB_REQUIRE_ALL=1 (REQUIRE) instead of skipping. WB_LIVE=1 adds the live bench test."""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"

import contextlib  # noqa: E402
import copy  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import asks  # noqa: E402
import devbench  # noqa: E402
import probe  # noqa: E402
import report  # noqa: E402
import test_probe as tp  # noqa: E402

LIVE = os.environ.get("WB_LIVE") == "1"
ASK_TRANSCRIPTS = ("Please (1) enable Graph API access to meeting transcripts for my account (Teams meeting configuration setting "
                   "EnableGraphTranscriptAccess), (2) approve a read-only connector or tenant app with Calendars.Read, "
                   "OnlineMeetings.Read and OnlineMeetingTranscript.Read.All for my own meetings, (3) confirm whether "
                   "attendees may download transcripts from the meeting Recap, and (4) if I hold a Microsoft 365 Copilot licence, "
                   "also the delegated permission OnlineMeetingAiInsight.Read.All for meeting AI insights (admin consent). "
                   "Purpose: a local, on-device meeting-notes index. To see the tenant setting: Get-CsTeamsMeetingConfiguration | "
                   "Select EnableGraphTranscriptAccess, EnableAttributedTranscripts")
ASK_DIGESTS = ("Please confirm that summarising my own mail and meeting transcripts through our approved Claude Code login is "
               "permitted, including speech from external participants.")
ASK_OUTLOOK = ("Please confirm whether scripted read-only access to my own Outlook mailbox (local cache) is permitted for a local, "
               "on-device search index, and the policy setting that governs it.")
BLOCKS = {r"HKLM\SOFTWARE\Policies\Microsoft\Edge": {"RemoteDebuggingAllowed": 0},
          r"HKLM\SOFTWARE\Policies\WSL": {"AllowWSL": 0},
          r"HKLM\SOFTWARE\Policies\ClaudeCode": {"Settings": json.dumps({"allowManagedHooksOnly": True, "deniedModels": ["claude-opus-5-5"]})}}
EXPECT_BLOCKED = {"wsl2", "browser-automation", "capture-intranet", "capture-shared-files",
                  "hooks-guards", "model-flagship-claude-opus-5-5"}


rd, rj = tp.rd, tp.rj


def need(tc, what, ok):
    tp.need(tc, what, ok)


def make_kit(tmp):
    def put(rel, obj):
        p = os.path.join(tmp, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj) if not isinstance(obj, str) else obj)
    put("mcp/golden-config.template.json", {"servers": {"alpha": {"action": "ensure", "command": "npx", "args": []},
                                                        "beta": {"type": "http", "url": "https://mcp.example.com/mcp"}}})
    put("settings/model-routing.json", {"version": 1, "provider_ids": {"claude-opus-5-5": {"anthropic": "claude-opus-5-5", "bedrock": "us.example-opus-v1"}},
                                        "rows": [{"id": "R1", "persona": "flagship", "chain": [{"model": "claude-opus-5-5", "effort": "xhigh"},
                                                                                              {"model": "claude-sonnet-5-5", "effort": "xhigh"}]},
                                                 {"id": "R2", "persona": "worker", "chain": [{"model": "claude-sonnet-5-5", "effort": "high"}]}]})
    put("plugins/workbench-core/skills/spawn/SKILL.md", "x")
    put("plugins/workbench-kb/skills/save/SKILL.md", "x")
    return tmp


class Base(unittest.TestCase):
    def setUp(self):
        need(self, "Windows", probe.IS_WIN)
        self.tmp = tp.tmpdir(self)
        self.kit = make_kit(os.path.join(self.tmp, "kit"))

    def probe(self, **fs_kw):
        self.fs = tp.FakeSystem(os.path.join(self.tmp, "m%d" % len(os.listdir(self.tmp))), **fs_kw)
        return tp.collect(self.fs, packages=tp.fixture_file(), kit=self.kit)

    def rows(self, p, rules=None, kit=None):
        return {r["id"]: r for r in report.evaluate(p, kit or self.kit, tp.fixture_file(), rules=rules)}


def resolves(doc, pointer):
    cur = doc
    for part in pointer.strip("/").split("/"):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False
    return True


def check_policy_flips(base_rows, blocked_rows):
    """Errors if the simulated policy blocks did not flip exactly the expected rows (used by the test and by its own test)."""
    errs = []
    for i, r in blocked_rows.items():
        if i in EXPECT_BLOCKED:
            if r["status"] != report.B:
                errs.append("%s should be BLOCKED-BY-POLICY, is %s" % (i, r["status"]))
            elif not r["ask_it"]:
                errs.append("%s has no ask_it" % i)
        elif i == "sandbox":
            if r["status"] != report.U:
                errs.append("sandbox should fall to UNKNOWN, is " + r["status"])
        elif r["status"] != base_rows[i]["status"]:
            errs.append("%s changed without a reason: %s to %s" % (i, base_rows[i]["status"], r["status"]))
    return errs


class RowTests(Base):
    def test_every_row_has_a_status_and_a_resolving_pointer(self):
        for label, p in (("healthy", self.probe()), ("blocked", self.probe(registry=BLOCKS)),
                         ("everything failing", probe.collect(run_=lambda a, t=15: (None, b""), which_=lambda n: None, environ={},
                                                              managed_files=[], kit=self.kit, network=False))):
            for kit in (self.kit, tp.KIT):
                rows = report.evaluate(p, kit, tp.fixture_file())
                self.assertGreater(len(rows), 30)
                for r in rows:
                    self.assertIn(r["status"], report.STATUSES, (label, r["id"]))
                    self.assertTrue(any(resolves(p, e["pointer"]) for e in r["evidence"]), (label, r["id"], r["evidence"]))
                    if r["status"] in (report.N, report.B):
                        self.assertTrue(r["ask_it"], (label, r["id"]))
                self.assertEqual(len({r["id"] for r in rows}), len(rows), "row ids must be unique")

    def test_generated_rows_follow_packages_mcp_models_and_skills(self):
        ids = set(self.rows(self.probe()))
        for want in ("pkg-git", "pkg-node", "mcp-alpha", "mcp-beta", "model-flagship-claude-opus-5-5", "model-worker-claude-sonnet-5-5",
                     "skill-spawn", "skill-save", "skill-setup", "skill-policy-qa", "wsl2", "storage-work-cloud", "ai-digests"):
            self.assertIn(want, ids)
        self.assertEqual(sum(1 for i in ids if i.startswith("pkg-")), len(tp.FIXTURE_PACKAGES["packages"]))

    def test_package_rules(self):
        p = self.probe(registry={r"HKLM\SOFTWARE\Policies\Microsoft\Windows\AppInstaller": {"EnableAppInstaller": 0}},
                       tools={"jq": None, "node": None})
        rows = self.rows(p)
        self.assertEqual(rows["pkg-git"]["status"], report.R)
        self.assertEqual(rows["pkg-node"]["status"], report.B)     # winget switched off, node missing
        self.assertEqual(rows["pkg-jq"]["status"], report.I)       # missing, release download needs no admin
        fs = self.fs
        fs.fetch = lambda url, timeout=4: {"method": "HEAD", "result": "blocked", "category": "connect", "http_status": None, "bytes": 0, "ms": 1}
        p = tp.collect(fs, packages=tp.fixture_file(), kit=self.kit)
        row = self.rows(p)["pkg-jq"]
        self.assertEqual(row["status"], report.N)
        self.assertEqual(row["ask_it"], "Please allow release downloads from github.com.")


class PolicyFlipTests(Base):
    def test_policy_blocks_flip_exactly_the_right_rows(self):
        base, blocked = self.rows(self.probe()), self.rows(self.probe(registry=BLOCKS))
        self.assertEqual(check_policy_flips(base, blocked), [])
        self.assertEqual({i for i, r in blocked.items() if r["status"] == report.B}, EXPECT_BLOCKED)
        self.assertEqual(base["wsl2"]["status"], report.I)
        self.assertEqual(base["browser-automation"]["status"], report.R)
        self.assertEqual(base["sandbox"]["status"], report.I)

    def test_the_policy_test_notices_a_missing_edge_rule(self):
        base = self.rows(self.probe())
        rules = {k: v for k, v in report.RULES.items() if k != "capture_browser"}
        broken = self.rows(self.probe(registry=BLOCKS), rules=rules)
        errs = check_policy_flips(base, broken)
        self.assertTrue(any("capture-intranet" in e for e in errs), errs)

    def test_deferred_capture_rows_stay_unknown(self):
        for reg in ({}, BLOCKS):
            rows = {r["id"]: r for r in report.evaluate(self.probe(registry=reg), self.kit, tp.fixture_file())}
            for rid in ("capture-teams", "capture-outlook"):
                self.assertEqual(rows[rid]["status"], report.U, rid)
                self.assertIn("deferred", rows[rid]["note"])

    def test_flipped_rows_reach_the_roadmap_ranked_by_unlocks(self):
        rows = report.evaluate(self.probe(registry=BLOCKS), self.kit, tp.fixture_file())
        road = report.roadmap(rows)
        self.assertEqual([r["rank"] for r in road], list(range(1, len(road) + 1)))
        self.assertEqual([len(r["unlocks"]) for r in road], sorted((len(r["unlocks"]) for r in road), reverse=True))
        top = road[0]
        self.assertIn("RemoteDebuggingAllowed", top["ask"])
        self.assertLessEqual({"browser-automation", "capture-intranet"}, set(top["unlocks"]))
        wsl = next(r for r in road if "AllowWSL" in r["ask"])
        self.assertEqual(set(wsl["unlocks"]), {"wsl2", "sandbox"})

    def test_roadmap_counts_direct_and_listed_unlocks_once(self):
        rows = [{"id": "a", "status": report.N, "ask_it": "ask one", "unlocks": ["b", "zz"]},
                {"id": "b", "status": report.U, "ask_it": None, "unlocks": []},
                {"id": "c", "status": report.B, "ask_it": "ask two", "unlocks": []},
                {"id": "d", "status": report.B, "ask_it": "ask two", "unlocks": ["c"]},
                {"id": "f", "status": report.N, "ask_it": "ask two", "unlocks": []},
                {"id": "e", "status": report.R, "ask_it": "x", "unlocks": []}]
        self.assertEqual(report.roadmap(rows), [{"rank": 1, "ask": "ask two", "unlocks": ["c", "d", "f"]},
                                                {"rank": 2, "ask": "ask one", "unlocks": ["a", "b"]}])

    def test_mcp_and_marketplace_policy(self):
        reg = {r"HKLM\SOFTWARE\Policies\ClaudeCode": {"Settings": json.dumps(
            {"deniedMcpServers": [{"serverName": "alpha"}], "strictKnownMarketplaces": []})}}
        rows = self.rows(self.probe(registry=reg))
        self.assertEqual(rows["mcp-alpha"]["status"], report.B)
        self.assertIn("alpha", rows["mcp-alpha"]["ask_it"])
        self.assertEqual(rows["plugin-core"]["status"], report.B)
        self.assertEqual(rows["skill-spawn"]["ask_it"], rows["plugin-core"]["ask_it"])
        road = report.roadmap(list(rows.values()))
        self.assertGreater(len(next(r for r in road if "strictKnownMarketplaces" in r["ask"])["unlocks"]), 5)


class ModelVersionTests(Base):
    """The recommended Claude Code version for Haiku 5.5 is advice, checked AFTER every policy check: it never changes a status."""
    HAIKU, OPUS = "claude-haiku-5-5", "claude-opus-5-5"
    ADVICE = "v2.1.293 or later is recommended for claude-haiku-5-5"

    def policy(self, **settings):
        return {r"HKLM\SOFTWARE\Policies\ClaudeCode": {"Settings": json.dumps(settings)}}

    def verdict(self, claude, model=None, **settings):
        p = self.probe(tools={"claude": claude}, registry=self.policy(**settings) if settings else None)
        return report.model_rule(model or self.HAIKU, {})(p)

    def test_an_old_claude_code_adds_advice_and_keeps_the_status(self):
        status, note = self.verdict("2.1.292")[:2]
        self.assertEqual(status, report.U)                         # today's result: no allow-list to verify against
        self.assertIn("not verified: no managed allow list", note)
        self.assertIn("Claude Code 2.1.292 found", note)
        self.assertIn(self.ADVICE, note)
        self.assertIn("claude update", note)
        named = self.verdict("2.1.292", availableModels=[self.HAIKU])
        self.assertEqual(named[0], report.R)                       # named in the allow list: still READY, with the advice
        self.assertIn(self.ADVICE, named[1])
        for status, *_ in (self.verdict("2.1.292"), named):
            self.assertNotIn(status, (report.I, report.N, report.B))   # never INSTALLABLE: setup cannot update Claude Code

    def test_a_policy_block_wins_over_the_version_check(self):
        for settings in ({"deniedModels": [self.HAIKU]}, {"availableModels": ["claude-sonnet-5-5"]}):
            res = self.verdict("2.1.292", **settings)
            self.assertEqual(res[0], report.B)
            self.assertTrue(res[2])                                  # still carries its ask-IT text
            self.assertNotIn("Claude Code 2.1.292", res[1])

    def test_a_new_enough_or_unknown_version_keeps_the_policy_result(self):
        for ok in ("2.1.293", "2.1.1000", "2.2.0"):
            self.assertEqual(self.verdict(ok)[:2], (report.U, "not verified: no managed allow list"), ok)
        self.assertEqual(self.verdict("2.1.293", availableModels=[self.HAIKU])[0], report.R)
        self.assertEqual(self.verdict(None)[:2], (report.U, "not verified: no managed allow list"))   # claude not found
        p = self.probe()
        p["sections"]["claude"]["data"]["version"] = "nightly"
        self.assertNotIn("recommended", report.model_rule(self.HAIKU, {})(p)[1])

    def test_a_banner_line_before_the_version_does_not_hide_it(self):
        rule = report.model_rule(self.HAIKU, {})
        for text in ("Update available: 9.9.9\n2.1.292 (Claude Code)", "2.1.292 (Claude Code)", "Claude Code v2.1.292",
                     "Welcome back 7.7.7\nClaude Code 2.1.292"):
            p = self.probe()
            p["sections"]["claude"]["data"]["version"] = text
            self.assertEqual(report.claude_version(p), (2, 1, 292), text)
            self.assertIn(self.ADVICE, rule(p)[1], text)
        p["sections"]["claude"]["data"]["version"] = "Update available: 9.9.9\n2.1.293 (Claude Code)"
        self.assertNotIn("recommended", rule(p)[1])               # the banner's larger number must not pass an old install

    def test_other_models_are_unaffected(self):
        self.assertEqual(self.verdict("2.1.0", model=self.OPUS)[:2], (report.U, "not verified: no managed allow list"))
        self.assertEqual(self.verdict("2.1.0", model=self.OPUS, availableModels=[self.OPUS])[:2],
                         (report.R, "named in the managed allow list"))

    def test_in_the_real_kit_only_haiku_rows_change_with_the_version(self):
        old = self.rows(self.probe(tools={"claude": "2.1.292"}), kit=tp.KIT)
        new = self.rows(self.probe(tools={"claude": "2.1.293"}), kit=tp.KIT)
        self.assertEqual({i: r["status"] for i, r in old.items()}, {i: r["status"] for i, r in new.items()})   # statuses equal
        changed = {i for i in old if i.startswith("model-") and old[i]["note"] != new[i]["note"]}   # pkg-claude has its own note
        self.assertTrue(changed)
        self.assertTrue(all(i.endswith(self.HAIKU) for i in changed), changed)
        pointer = "/sections/claude/data/version"
        for i, r in old.items():
            has = pointer in [e["pointer"] for e in r["evidence"]]
            self.assertEqual(has, i.startswith("model-") and i.endswith(self.HAIKU), i)   # only the Haiku 5.5 rows carry it


class PowerShellRuleTests(Base):
    """The powershell row: READY, NEEDS-IT (group policy blocks scripts), BLOCKED-BY-POLICY (restricted language), UNKNOWN."""

    def row(self, **ps):
        return self.rows(self.probe(ps=ps))["powershell"]

    def test_full_language_and_no_group_policy_is_ready(self):
        r = self.row()
        self.assertEqual(r["status"], report.R)
        self.assertIsNone(r["ask_it"])
        self.assertEqual(self.row(pol_machine="RemoteSigned", pol_user="Unrestricted")["status"], report.R)   # not a restriction

    def test_any_restricted_language_mode_is_blocked_with_the_fallback_named(self):
        for mode in ("ConstrainedLanguage", "RestrictedLanguage", "NoLanguage"):
            r = self.row(lang=mode)
            self.assertEqual(r["status"], report.B, mode)
            self.assertIn(mode, r["note"])
            self.assertIn("WSL or Git Bash", r["note"])
            self.assertIn("Full Language mode", r["ask_it"])

    def test_a_group_policy_that_forbids_scripts_needs_it_while_commands_still_work(self):
        for scope in ("pol_machine", "pol_user"):
            for value in ("Restricted", "AllSigned"):
                r = self.row(**{scope: value})
                self.assertEqual(r["status"], report.N, (scope, value))
                self.assertIn("commands work", r["note"])
                self.assertIn(value, r["note"])
                self.assertTrue(r["ask_it"])
        both = self.row(pol_machine="AllSigned", pol_user="Restricted")["note"]
        self.assertIn("machine group policy sets AllSigned", both)
        self.assertIn("user group policy sets Restricted", both)

    def test_the_language_mode_wins_over_a_script_policy(self):
        self.assertEqual(self.row(lang="ConstrainedLanguage", pol_machine="AllSigned")["status"], report.B)

    def test_a_local_restricted_policy_is_ready_but_says_scripts_will_not_run(self):
        r = self.row(execpol="Restricted")
        self.assertEqual(r["status"], report.R)
        self.assertIn("will not run until you change it", r["note"])

    def test_unreadable_or_unknown_language_mode_is_unknown(self):
        self.assertEqual(self.row(lang="bogus")["status"], report.U)
        dead = probe.collect(run_=lambda a, t=15: (None, b""), which_=lambda n: None, environ={}, managed_files=[],
                             kit=self.kit, network=False)
        r = {x["id"]: x for x in report.evaluate(dead, self.kit, tp.fixture_file())}["powershell"]
        self.assertEqual(r["status"], report.U)
        self.assertIn("could not be read", r["note"])

    def test_the_row_is_in_the_platform_group_with_resolving_evidence(self):
        p = self.probe()
        r = self.rows(p)["powershell"]
        self.assertEqual(r["group"], "platform")
        self.assertEqual([e["pointer"].rsplit("/", 1)[1] for e in r["evidence"]],
                         ["language_mode", "execution_policy", "gpo_machine", "gpo_user"])
        self.assertTrue(all(resolves(p, e["pointer"]) for e in r["evidence"]))


class AddendumRuleTests(Base):
    def mod(self, p, **data):
        p = copy.deepcopy(p)
        for sec, kv in data.items():
            p["sections"][sec]["data"].update(kv)
        return p

    def test_storage_work_cloud(self):
        p = self.probe()
        wc = lambda **k: self.mod(p, knowledge={"work_cloud": dict({"found": False, "root": None, "kfm": None, "accounts": 0}, **k)})   # noqa: E731
        self.assertEqual(report.RULES["storage_work_cloud"](wc()), (report.U, "local-only fallback"))
        self.assertEqual(report.RULES["storage_work_cloud"](wc(found=True, root="D:/Work", accounts=1)),
                         (report.R, "knowledge Markdown can live in the work cloud"))
        s, note = report.RULES["storage_work_cloud"](wc(found=True, accounts=2))
        self.assertEqual((s, note), (report.U, "several work accounts: setup will ask which one"))

    def test_capture_mail_full(self):
        p = self.probe()
        cap = lambda **k: self.mod(p, capture=k)   # noqa: E731
        f = report.RULES["capture_mail_full"]
        s, note = f(cap(outlook_client="classic", outlook_cache_window="3 months"))[:2]
        self.assertEqual(s, report.I)
        self.assertIn("local-cache route, InfoSec note first", note)
        self.assertIn("3 months", note)
        self.assertEqual(f(cap(outlook_client="both"))[0], report.I)
        self.assertEqual(f(cap(outlook_client="new"))[0], report.N)
        self.assertEqual(f(cap(outlook_client="none"))[0], report.U)
        self.assertEqual(f(cap(outlook_client="unknown"))[0], report.U)
        for om in ({"PromptOOMAddressBookAccess": 2}, {"PromptOOMAddressInformationAccess": 0}, {"AdminSecurityMode": 3, "PromptOOMAddressBookAccess": 3}):
            r = f(cap(outlook_client="classic", outlook_cache_window="14 days", outlook_object_model_policy=om))
            self.assertEqual((r[0], r[2]), (report.B, ASK_OUTLOOK), om)
            self.assertIn("14 days", r[1])
        self.assertEqual(f(cap(outlook_client="classic", outlook_object_model_policy={"PromptOOMAddressBookAccess": 1}))[0], report.I)
        self.assertEqual(f(cap(outlook_client="new", outlook_object_model_policy={"PromptOOMAddressBookAccess": 2}))[0], report.N)

    def test_mail_full_row_carries_the_right_ask(self):
        reg = {r"HKLM\SOFTWARE\Classes\Outlook.Application": {"(Default)": "x"},
               r"HKLM\Software\Policies\Microsoft\Office\16.0\Outlook\Security": {"PromptOOMAddressBookAccess": 2},
               r"HKCU\Software\Microsoft\Office\16.0\Outlook\Cached Mode": {"SyncWindowSetting": 6}}
        r = self.rows(self.probe(registry=reg))["capture-mail-full"]
        self.assertEqual((r["status"], r["ask_it"]), (report.B, ASK_OUTLOOK))
        self.assertIn("6 months", r["note"])
        r = self.rows(self.probe(ps={"outlook_new": True}))["capture-mail-full"]
        self.assertEqual(r["status"], report.N)
        self.assertIn("read-only access to my own mailbox", r["ask_it"])

    def test_capture_meeting_transcripts(self):
        p = self.probe()
        self.assertEqual(report.RULES["capture_meeting_transcripts"](p)[0], report.N)
        r = self.rows(p)["capture-meeting-transcripts"]
        self.assertEqual((r["status"], r["ask_it"]), (report.N, ASK_TRANSCRIPTS))

    def test_ai_digests(self):
        p = self.probe()
        r = self.rows(p)["ai-digests"]
        self.assertEqual((r["status"], r["ask_it"]), (report.U, ASK_DIGESTS))
        self.assertNotIn(ASK_DIGESTS, [x["ask"] for x in report.roadmap(report.evaluate(p, self.kit, tp.fixture_file()))])


class Agreement(Base):
    """G12: the quick report agrees with doctor --deep (a Day-1 check that passes proves its feature: never INSTALLABLE; UNKNOWN
    only when nothing can be measured). G13: one IT ask is one line wherever it is shown."""
    REAL = os.path.join(tp.KIT, "bootstrap", "packages.json")
    ASK = ("Please allow downloads from huggingface.co (a one-time embedding model), or provide an approved internal mirror of "
           "the model files.")
    PROVED = ("find-keyword", "find-hybrid", "find-mcp", "mcp-find", "knowledge-refresh-task", "scheduled-tasks", "hooks-guards",
              "plugin-core", "plugin-kb", "skill-find", "skill-save")

    def machine(self, steps=None, quick=True, tools=None, **fs_kw):
        fs = tp.FakeSystem(os.path.join(self.tmp, "a%d" % len(os.listdir(self.tmp))), **fs_kw)
        p = tp.collect(fs, packages=self.REAL, kit=tp.KIT, quick=quick, network=not quick)
        if steps is not None:
            p["sections"]["knowledge"]["data"]["verify"] = {"pass": 22, "warn": 0, "fail": 0, "failing": [], "steps": steps,
                                                            "tools": tools or {}}
        return fs, p, {r["id"]: r for r in report.evaluate(p, tp.KIT, self.REAL)}

    def test_the_package_table_names_the_embedding_model_host_so_the_probe_measures_it(self):
        table = rj(self.REAL)
        self.assertEqual([e["host"] for e in table["endpoints"]], ["huggingface.co"])
        self.assertTrue(all("huggingface" not in h for p in table["packages"] for h in p["hosts"]), "it is not a package download")
        _, p, rows = self.machine()
        urls = [e["url"] for e in p["sections"]["network"]["data"]["endpoints"]]
        self.assertIn("https://huggingface.co/", urls)
        self.assertNotIn("not in the package table", rows["find-hybrid"]["note"])

    def test_a_blocked_model_host_reads_needs_it_with_the_ask_and_a_reachable_one_installable(self):
        fs = tp.FakeSystem(os.path.join(self.tmp, "blocked"))
        fs.fetch = lambda url, timeout=4: {"method": "HEAD", "result": "blocked" if "huggingface" in url else "ok", "category": "connect",
                                           "http_status": None, "bytes": 0, "ms": 1}
        p = tp.collect(fs, packages=self.REAL, kit=tp.KIT)
        row = {r["id"]: r for r in report.evaluate(p, tp.KIT, self.REAL)}["find-hybrid"]
        self.assertEqual((row["status"], row["ask_it"]), (report.N, self.ASK))
        fs.fetch = lambda url, timeout=4: {"method": "HEAD", "result": "ok", "category": None, "http_status": 200, "bytes": 0, "ms": 1}
        p = tp.collect(fs, packages=self.REAL, kit=tp.KIT)
        self.assertEqual({r["id"]: r for r in report.evaluate(p, tp.KIT, self.REAL)}["find-hybrid"]["status"], report.I)

    def test_nothing_a_passing_day_one_check_proves_is_installable_or_unknown(self):
        _, _, bare = self.machine()
        self.assertEqual(bare["find-keyword"]["status"], report.I, "without the record the quick report cannot know")
        _, _, rows = self.machine({"D%d" % i: "PASS" for i in range(1, 24)})
        for rid in self.PROVED:
            self.assertEqual(rows[rid]["status"], report.R, (rid, rows[rid]["note"]))
        self.assertEqual(rows["mcp-postgres"]["status"], report.R, "uvx is measured through the uv in the package table")

    def test_playwright_cli_follows_d23_and_ctx_and_tokensave_follow_their_own_d18_status(self):
        _, _, bare = self.machine()
        for rid in ("pkg-playwright-cli", "pkg-ctx", "pkg-tokensave"):
            self.assertEqual(bare[rid]["status"], report.I, rid)
        _, _, rows = self.machine({"D23": "PASS", "D18": "WARN"}, tools={"ctx": "PASS", "tokensave": "WARN"})
        self.assertEqual(rows["pkg-playwright-cli"]["status"], report.R)
        self.assertIn("D23", rows["pkg-playwright-cli"]["note"])
        self.assertEqual(rows["pkg-ctx"]["status"], report.R)
        self.assertIn("D18", rows["pkg-ctx"]["note"])
        self.assertEqual(rows["pkg-tokensave"]["status"], report.I, "tokensave did not answer: not READY because ctx did")
        _, _, rows = self.machine({"D23": "WARN"}, tools={})
        self.assertEqual(rows["pkg-playwright-cli"]["status"], report.I)
        _, _, rows = self.machine({"D23": "PASS"}, tools={"tokensave": "PASS"})
        self.assertEqual((rows["pkg-tokensave"]["status"], rows["pkg-ctx"]["status"]), (report.R, report.I))

    def test_a_failed_keyword_check_is_never_ready_even_when_the_probes_own_find_call_answers(self):
        _, p, _ = self.machine({"D10": "FAIL"})
        p["sections"]["knowledge"]["data"]["find"] = {"available": True, "mode": "keyword", "vectors": 0}
        row = {r["id"]: r for r in report.evaluate(p, tp.KIT, self.REAL)}["find-keyword"]
        self.assertEqual(row["status"], report.I)
        self.assertIn("D10", row["note"])

    def test_each_row_follows_only_its_own_check(self):
        _, _, rows = self.machine({"D10": "PASS", "D13": "WARN", "D14": "WARN", "D15": "FAIL", "D9": "PASS"})
        self.assertEqual(rows["find-keyword"]["status"], report.R)
        self.assertEqual(rows["find-hybrid"]["status"], report.R, "D9 passed: the index has vectors")
        for rid in ("find-mcp", "mcp-find", "knowledge-refresh-task", "hooks-guards", "plugin-core"):
            self.assertEqual(rows[rid]["status"], report.I, rid)

    def test_a_keyword_only_index_is_needs_it_with_the_ask_doctor_attaches_and_nothing_measurable_is_unknown_with_a_reason(self):
        _, _, rows = self.machine({"D9": "WARN", "D11": "WARN", "D10": "PASS"})
        self.assertEqual((rows["find-hybrid"]["status"], rows["find-hybrid"]["ask_it"]), (report.N, self.ASK))
        feats = json.loads(rd(os.path.join(tp.KIT, "bootstrap", "features.json")))["rows"]
        self.assertEqual(self.ASK, next(f["ask_it"] for f in feats if f["id"] == "find-hybrid"), "the ask D9 and D11 carry")
        _, _, rows = self.machine()
        self.assertEqual(rows["find-hybrid"]["status"], report.U)
        self.assertIn("not tested", rows["find-hybrid"]["note"])
        self.assertIn("quick report", rows["find-hybrid"]["note"])

    def test_one_blocked_host_is_one_ask_in_the_roadmap_the_shared_list_and_the_written_report(self):
        fs = tp.FakeSystem(os.path.join(self.tmp, "g13"))
        state = os.path.join(fs.environ["CLAUDE_CONFIG_DIR"], "workbench", "state")
        os.makedirs(state)
        loud = self.ASK.upper().replace(" ", "  ")                     # the same ask in other case and spacing
        steps = [{"id": "D9", "status": "WARN", "ask_it": self.ASK}, {"id": "D11", "status": "WARN", "ask_it": loud},
                 {"id": "D10", "status": "PASS", "ask_it": None}]
        with open(os.path.join(state, "knowledge-verify.json"), "w", encoding="utf-8") as f:
            json.dump({"summary": {"pass": 1, "warn": 2, "fail": 0, "failing": []}, "steps": steps}, f)
        with open(os.path.join(state, "setup-state.json"), "w", encoding="utf-8") as f:
            json.dump({"ask_it": [{"item": "knowledge:find-build", "text": self.ASK}, {"item": "widget", "text": "Please unlock the widget."}]}, f)
        c = report.run_report("refresh", state, quick=True, packages=self.REAL, probe_kw=fs.kw())
        self.assertEqual(c["features"][[r["id"] for r in c["features"]].index("find-hybrid")]["status"], report.N)
        same = lambda lst: [x for x in lst if asks.key(x["ask"]) == asks.key(self.ASK)]  # noqa: E731
        self.assertEqual(len(same(c["roadmap"])), 1, "the report lists it once")
        self.assertEqual(len(same(rj(os.path.join(state, "capability-refresh.json"))["roadmap"])), 1, "and so does the written file")
        shared = asks.gather(state)
        self.assertEqual(len(same(shared)), 1, "the list setup, doctor and report share has it once")
        self.assertEqual(sorted(same(shared)[0]["sources"]), ["day-1 check D11", "day-1 check D9", "report find-hybrid", "setup"])
        widget = [r for r in c["roadmap"] if r["ask"] == "Please unlock the widget."]
        self.assertEqual((len(widget), widget[0]["unlocks"]), (1, []), "an ask only setup raised joins the same list")
        self.assertEqual(sorted(a["ask"] for a in shared), sorted(r["ask"] for r in c["roadmap"]), "one list, three views")

    def test_a_check_that_passed_or_a_row_that_is_ready_raises_no_ask(self):
        _, p, rows = self.machine({"D9": "PASS"})
        d = tempfile.mkdtemp(prefix="wb-asks-")
        self.addCleanup(shutil.rmtree, d, True)
        with open(os.path.join(d, "knowledge-verify.json"), "w", encoding="utf-8") as f:
            json.dump({"steps": [{"id": "D9", "status": "PASS", "ask_it": self.ASK}]}, f)
        c = report.build(p, "refresh", None, True, tp.KIT, self.REAL)
        self.assertEqual([a for a in asks.gather(d, report=c) if asks.key(a["ask"]) == asks.key(self.ASK)], [])

    def test_merge_keeps_the_first_wording_and_every_source_once(self):
        got = asks.merge([("Please allow  X.", "a"), ("please allow x.", "b"), ("Please allow Y.", "a"), (None, "c"), ("", "c"),
                          ("PLEASE ALLOW X.", "a")])
        self.assertEqual(got, [{"ask": "Please allow X.", "sources": ["a", "b"]}, {"ask": "Please allow Y.", "sources": ["a"]}])


class BootRowsTests(Base):
    """A3: the Day-1 verify row (IK2), the find MCP row, the Playwright CLI rows."""
    NPM_PACKAGES = {"version": 1, "packages": [
        {"id": "node", "name": "Node.js", "winget": "OpenJS.NodeJS.LTS", "scope": "machine", "source": "winget",
         "hosts": ["nodejs.org"], "admin": True, "optional_with": None, "verify": ["node", "--version"], "expect": r"v(\d+\.\d+\.\d+)",
         "ask_it": "Please allow Node.js.", "policy_keys": []},
        {"id": "playwright-cli", "name": "Playwright CLI", "winget": None, "scope": "user", "source": "npm", "npm": "@playwright/cli",
         "pin": "0.1.22", "hosts": ["registry.npmjs.org"], "admin": False, "optional_with": None,
         "verify": ["playwright-cli", "--version"], "expect": r"(\d+\.\d+\.\d+)", "ask_it": "Please allow the npm install.",
         "policy_keys": []}]}

    def packages_file(self):
        d = tempfile.mkdtemp(prefix="wb-npmfx-")
        self.addCleanup(shutil.rmtree, d, True)
        f = os.path.join(d, "packages.json")
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(self.NPM_PACKAGES, fh)
        return f

    def with_verify(self, verify):
        p = self.probe()
        p["sections"]["knowledge"]["data"]["verify"] = verify
        return self.rows(p)["knowledge-verified"]

    def test_knowledge_verified_reads_the_day_one_summary(self):
        r = self.with_verify({"pass": 14, "warn": 0, "fail": 0, "failing": [], "generated": "2026-10-08T00:00:00Z"})
        self.assertEqual((r["status"], r["note"], r["ask_it"]), (report.R, "14/14 PASS", None))
        r = self.with_verify({"pass": 12, "warn": 2, "fail": 0, "failing": []})
        self.assertEqual((r["status"], r["note"]), (report.R, "12/14 PASS, 2 warning(s)"))
        r = self.with_verify({"pass": 11, "warn": 1, "fail": 2, "failing": ["D3", "D8"]})
        self.assertEqual(r["status"], report.I)
        self.assertIn("11/14 PASS, failing: D3, D8", r["note"])
        self.assertIsNone(r["ask_it"], "no ask on this row")
        r = self.with_verify(None)
        self.assertEqual((r["status"], r["ask_it"]), (report.U, None))
        self.assertIn("not run yet", r["note"])
        self.assertEqual(self.with_verify({"pass": 0, "warn": 0, "fail": 0, "failing": []})["status"], report.U)

    def test_find_mcp_follows_the_managed_mcp_policy(self):
        r = self.rows(self.probe())["find-mcp"]
        self.assertEqual((r["status"], r["ask_it"]), (report.I, None))
        reg = {r"HKLM\SOFTWARE\Policies\ClaudeCode": {"Settings": json.dumps({"deniedMcpServers": [{"serverName": "find"}]})}}
        r = self.rows(self.probe(registry=reg))["find-mcp"]
        self.assertEqual(r["status"], report.B)
        self.assertEqual(r["ask_it"], "Please allow the local stdio MCP server `find` (a local search index; no network egress) in the managed MCP allow list.")
        reg = {r"HKLM\SOFTWARE\Policies\ClaudeCode": {"Settings": json.dumps({"allowManagedMcpServersOnly": True, "allowedMcpServers": [{"serverName": "other"}]})}}
        self.assertEqual(self.rows(self.probe(registry=reg))["find-mcp"]["status"], report.B, "an allow list that omits find")

    def day_one_rows(self, steps, available=False):
        p = self.probe()
        data = p["sections"]["knowledge"]["data"]
        data["find"]["available"] = available
        data["verify"] = None if steps is None else {"pass": 21, "warn": 1, "fail": 0, "failing": [], "steps": steps}
        return self.rows(p, kit=tp.KIT)        # the real kit: its MCP template carries find and github-local

    FOUR = ("find-keyword", "find-mcp", "mcp-find", "mcp-github-local")

    def test_the_four_find_rows_are_ready_when_the_day_one_checks_d10_and_d13_passed(self):
        rows = self.day_one_rows({"D10": "PASS", "D13": "PASS"})
        for rid in self.FOUR:
            self.assertEqual(rows[rid]["status"], report.R, (rid, rows[rid]["note"]))
        self.assertIn("D10", rows["find-keyword"]["note"])
        self.assertIn("D13", rows["find-mcp"]["note"])

    def test_they_stay_installable_when_those_checks_did_not_pass_or_never_ran(self):
        for steps in ({"D10": "FAIL", "D13": "WARN"}, {}, None):
            rows = self.day_one_rows(steps)
            for rid in ("find-keyword", "find-mcp", "mcp-find"):
                self.assertEqual(rows[rid]["status"], report.I, (steps, rid))
        rows = self.day_one_rows({"D10": "PASS", "D13": "WARN"})
        self.assertEqual((rows["find-keyword"]["status"], rows["find-mcp"]["status"], rows["mcp-find"]["status"]),
                         (report.R, report.I, report.I), "each row follows its own check")

    def test_find_keyword_is_still_ready_when_the_probes_own_find_call_answers(self):
        rows = self.day_one_rows(None, available=True)
        self.assertEqual(rows["find-keyword"]["status"], report.R)

    def test_a_managed_policy_still_blocks_the_find_server_even_when_d13_passed(self):
        reg = {r"HKLM\SOFTWARE\Policies\ClaudeCode": {"Settings": json.dumps({"deniedMcpServers": [{"serverName": "find"}]})}}
        p = self.probe(registry=reg)
        p["sections"]["knowledge"]["data"]["verify"] = {"pass": 22, "warn": 0, "fail": 0, "failing": [], "steps": {"D13": "PASS"}}
        rows = self.rows(p, kit=tp.KIT)
        self.assertEqual((rows["find-mcp"]["status"], rows["mcp-find"]["status"]), (report.B, report.B))

    def test_the_transcripts_ask_names_the_copilot_permission_and_the_tenant_check(self):
        r = self.rows(self.probe())["capture-meeting-transcripts"]
        self.assertIn("OnlineMeetingAiInsight.Read.All", r["ask_it"])
        self.assertIn("Get-CsTeamsMeetingConfiguration | Select EnableGraphTranscriptAccess, EnableAttributedTranscripts", r["ask_it"])

    def cli_row(self, **fs_kw):
        fs = tp.FakeSystem(os.path.join(self.tmp, "n%d" % len(os.listdir(self.tmp))), **fs_kw)
        p = tp.collect(fs, packages=self.packages_file(), kit=self.kit)
        return {r["id"]: r for r in report.evaluate(p, self.kit, self.packages_file())}

    def test_the_playwright_cli_row_needs_node_and_reads_its_version(self):
        rows = self.cli_row(tools={"node": None})
        self.assertEqual(rows["pkg-playwright-cli"]["status"], report.N)
        self.assertIn("needs Node.js", rows["pkg-playwright-cli"]["note"])
        self.assertEqual(rows["pkg-playwright-cli"]["ask_it"], report.ASK_NODE)
        rows = self.cli_row()                                         # node present, CLI not installed
        self.assertEqual(rows["pkg-playwright-cli"]["status"], report.I)
        self.assertIn("without admin", rows["pkg-playwright-cli"]["note"])
        rows = self.cli_row(tools={"playwright-cli": "0.1.22"})
        self.assertEqual((rows["pkg-playwright-cli"]["status"], rows["pkg-playwright-cli"]["note"]), (report.R, "version 0.1.22"))

    def test_browser_automation_names_playwright_cli_and_edge_headless_policy(self):
        r = self.cli_row()["browser-automation"]
        self.assertEqual(r["status"], report.R)
        self.assertIn("setup installs playwright-cli", r["note"])
        r = self.cli_row(tools={"playwright-cli": "0.1.22"})["browser-automation"]
        self.assertIn("playwright-cli 0.1.22", r["note"])
        r = self.cli_row(registry={r"HKLM\SOFTWARE\Policies\Microsoft\Edge": {"HeadlessModeEnabled": 0}})["browser-automation"]
        self.assertEqual(r["status"], report.R)
        self.assertIn("visible window", r["note"])
        r = self.cli_row(registry=BLOCKS)["browser-automation"]
        self.assertEqual(r["status"], report.B, "remote debugging off still blocks")


class OutputTests(Base):
    def run_one(self, phase="pre", out=None, fs=None, **kw):
        fs = fs or tp.FakeSystem(os.path.join(self.tmp, "out-m"))
        out = out or os.path.join(self.tmp, "state")
        self.bench_kw = {}

        def bench(**k):
            self.bench_kw = k
            return {"metrics": [{"name": "small_files_ms", "value": 123, "unit": "ms", "n": 1}], "verdict": "fast", "because": [],
                    "fix": [], "peak_mb": 77}
        return report.run_report(phase, out, packages=tp.fixture_file(), kit=self.kit, probe_kw=fs.kw(kit=self.kit), bench_fn=bench, **kw), out

    def test_files_and_shape(self):
        c, out = self.run_one()
        self.assertEqual(sorted(os.listdir(out)), ["capability-pre.html", "capability-pre.json", "capability-pre.md", "probe-pre.json"])
        doc = rj(os.path.join(out, "capability-pre.json"))
        self.assertEqual(set(doc), {"version", "kit_version", "phase", "generated", "duration_s", "quick", "specs", "features", "posture",
                                    "devspeed", "roadmap", "probe"})
        self.assertEqual(set(doc["specs"]), {"cpu", "cores", "ram_gb", "gpu", "npu", "disks", "os", "power", "latency_ms"})
        self.assertEqual(doc["specs"]["latency_ms"]["model_api"], 25)
        self.assertEqual(set(doc["posture"]), {"managed_claude", "intune", "epm", "defender", "app_control", "edge", "wsl_policy",
                                               "proxy", "tls_inspection", "dlp", "labels"})
        self.assertEqual(set(doc["features"][0]), {"id", "group", "feature", "status", "evidence", "ask_it", "note", "unlocks"})
        self.assertEqual(doc["devspeed"]["peak_mb"], 77)
        self.assertEqual(doc["probe"], os.path.join(out, "probe-pre.json"))
        self.assertFalse(self.bench_kw["model_call"])   # not logged in: no model call
        self.assertEqual(len(report.summary(c, out)), len(report.summary(c, out)[:40]))
        self.assertLessEqual(len(report.summary(c, out)), 40)

    def test_html_is_self_contained(self):
        _c, out = self.run_one()
        h = rd(os.path.join(out, "capability-pre.html"))
        self.assertNotRegex(h, r"(?i)<script|<link|<img|<iframe|@import")
        self.assertNotRegex(h, r"(?i)(?:src|href)\s*=\s*[\"']?\s*(?:https?:)?//")
        self.assertIsNone(re.search(r"(?i)(?:src|href)\s*=\s*[\"']?http", h))
        self.assertIn("<style>", h)
        self.assertIn("wsl2", h)
        md = rd(os.path.join(out, "capability-pre.md"))
        self.assertIn("Roadmap", md)

    def test_post_writes_a_diff_listing_the_changed_rows(self):
        _c, out = self.run_one("pre")
        self.assertFalse(os.path.exists(os.path.join(out, "capability-diff.md")))
        after = tp.FakeSystem(os.path.join(self.tmp, "post-m"), wsl_installed=True, distros=[("Linux-A", 2)], tools={"jq": None})
        self.run_one("post", out=out, fs=after)
        dm = rd(os.path.join(out, "capability-diff.md"))
        dj = rj(os.path.join(out, "capability-diff.json"))
        self.assertIn("`wsl2`: INSTALLABLE to READY", dm)
        self.assertIn("wsl2", {c["id"] for c in dj["changed"]})
        self.assertNotIn("find-keyword", {c["id"] for c in dj["changed"]})
        self.assertEqual(dj["from"], "pre")

    def test_refresh_and_pre_write_no_diff(self):
        _c, out = self.run_one("pre")
        self.run_one("refresh", out=out)
        self.assertFalse(os.path.exists(os.path.join(out, "capability-diff.md")))
        self.assertTrue(os.path.exists(os.path.join(out, "capability-refresh.json")))

    def test_doctor_is_opt_in(self):
        fs = tp.FakeSystem(os.path.join(self.tmp, "nd"))
        self.run_one(fs=fs)
        self.assertFalse([c for c in fs.calls if c[:2] == ["claude", "doctor"]])
        fs = tp.FakeSystem(os.path.join(self.tmp, "wd"))
        self.run_one(fs=fs, doctor=True)
        self.assertTrue([c for c in fs.calls if c[:2] == ["claude", "doctor"]])

    def test_quick_runs_no_network_and_no_bench(self):
        fs = tp.FakeSystem(os.path.join(self.tmp, "q"))
        c, _out = self.run_one(fs=fs, quick=True)
        self.assertEqual(fs.fetched, [])
        self.assertEqual(self.bench_kw, {})
        self.assertTrue(c["quick"])

    def test_diff_cli_prints_the_change(self):
        _c, out = self.run_one("pre")
        after = tp.FakeSystem(os.path.join(self.tmp, "d-m"), wsl_installed=True, distros=[("Linux-A", 2)])
        self.run_one("post", out=out, fs=after)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(report.main(["diff", os.path.join(out, "capability-pre.json"), os.path.join(out, "capability-post.json")]), 0)
        self.assertIn("wsl2", buf.getvalue())

    def test_usage_error_exits_2(self):
        p = subprocess.run([sys.executable, os.path.join(HERE, "report.py"), "run"], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2)

    def test_detach_relaunches_without_the_flag(self):
        with mock.patch.object(report.subprocess, "Popen") as pop:
            pop.return_value.pid = 4242
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(report.main(["run", "--phase", "pre", "--detach", "--quick"]), 0)
        cmd, kw = pop.call_args[0][0], pop.call_args[1]
        self.assertNotIn("--detach", cmd)
        self.assertIn("--quick", cmd)
        self.assertTrue(os.path.basename(cmd[0]).lower().startswith(("pythonw", "python")))
        self.assertEqual(kw["creationflags"] & 0x208, 0x208)   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        self.assertIn("4242", buf.getvalue())

    def test_real_quick_run_on_this_machine(self):
        out = os.path.join(self.tmp, "real")
        env = dict(os.environ, CLAUDE_CONFIG_DIR=os.path.join(self.tmp, "cc"))
        before = tp.tree(HERE)
        p = subprocess.run([sys.executable, os.path.join(HERE, "report.py"), "run", "--phase", "pre", "--quick", "--out", out,
                            "--packages", tp.fixture_file()], capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertLessEqual(len(p.stdout.splitlines()), 40)
        self.assertEqual(sorted(os.listdir(out)), ["capability-pre.html", "capability-pre.json", "capability-pre.md", "probe-pre.json"])
        self.assertEqual(len(rj(os.path.join(out, "probe-pre.json"))["sections"]), 16)
        self.assertEqual(tp.tree(HERE), before, "report.py wrote into the kit folder (for example a __pycache__)")


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeRunner:
    """Pretends to run commands: each costs `cost[program]` seconds on the fake clock."""

    def __init__(self, clock, cost=None, distro=False, fail=()):
        self.clock, self.cost, self.distro, self.fail, self.calls = clock, cost or {}, distro, set(fail), []

    def __call__(self, argv, timeout=60, cwd=None, env=None):
        self.calls.append(list(argv))
        name = os.path.basename(argv[0]).lower()
        key = ("git_status" if "status" in argv else "clone" if "clone" in argv else "git") if name == "git" else name
        self.clock.t += self.cost.get(key, self.cost.get("default", 0.01))
        if name in self.fail:
            return 1, b""
        if name == "wsl" and argv[1:] == ["-l", "-q"]:
            return (0, "Linux-A\r\n".encode("utf-16-le")) if self.distro else (1, b"")
        if name == "claude":
            return 0, b'{"is_error": false, "result": "OK"}'
        return 0, b""


class DevbenchTests(unittest.TestCase):
    def bench(self, cost=None, tmp_root=None, **kw):
        clock = FakeClock()
        runner = FakeRunner(clock, cost, kw.pop("distro", False), kw.pop("fail", ()))
        kw.setdefault("model", "haiku")
        doc = devbench.run_bench(runner, clock, tmp_root=tmp_root, n_files=20, repo_files=10, **kw)
        return doc, runner

    def test_fast_machine_prints_numbers_and_a_verdict(self):
        doc, _r = self.bench()
        by = {m["name"]: m for m in doc["metrics"]}
        for name in ("small_files_ms", "git_status_ms", "git_clone_ms", "python_start_ms", "node_start_ms", "pip_resolve_ms",
                     "npm_resolve_ms", "model_rtt_ms"):
            self.assertIn(name, by)
            self.assertIsInstance(by[name]["value"], int)
        self.assertEqual(by["git_status_ms"]["n"], 5)
        self.assertEqual(by["python_start_ms"]["n"], 5)
        self.assertEqual(doc["verdict"], "fast")
        text = devbench.render(doc)
        self.assertIn("verdict: fast", text)
        self.assertRegex(text, r"git_status_ms\s+10 ms")
        self.assertEqual(doc["facts"]["dev_drive_query"], "ok")

    def test_ok_and_slow_verdicts_name_cause_and_fix(self):
        doc, _r = self.bench(cost={"git_status": 0.4})
        self.assertEqual(doc["verdict"], "OK")
        self.assertEqual(doc["because"], [])
        doc, _r = self.bench(cost={"git_status": 2.0, "py": 1.0, "node": 1.0})
        self.assertEqual(doc["verdict"], "slow")
        self.assertTrue(any("git status" in b and "2000 ms" in b for b in doc["because"]), doc["because"])
        self.assertTrue(any("scan" in f for f in doc["fix"]), doc["fix"])
        self.assertIn("because:", devbench.render(doc))
        self.assertIn("fix:", devbench.render(doc))

    def test_small_file_slowness_asks_for_a_dev_drive_and_wsl_comparison(self):
        clock = FakeClock()
        slow_files = lambda d, n: setattr(clock, "t", clock.t + (20 if "files" in d else 0))   # noqa: E731
        runner = FakeRunner(clock, distro=True, cost={"wsl": 1.0})
        with mock.patch.object(devbench, "_write_files", slow_files), mock.patch.object(devbench, "_remove_files", lambda d, n: None):
            doc = devbench.run_bench(runner, clock, n_files=20, repo_files=10, model="haiku")
        self.assertEqual(doc["verdict"], "slow")
        self.assertTrue(any("WSL file system" in b for b in doc["because"]), doc["because"])
        self.assertTrue(any("inside the WSL home" in f for f in doc["fix"]))
        self.assertTrue(any("Dev Drive" in f for f in doc["fix"]) or doc["facts"]["dev_drive_query"] == "ok")

    def test_temp_dirs_are_deleted_even_when_a_step_breaks(self):
        root = tp.tmpdir(self)
        self.bench(tmp_root=root)
        self.assertEqual(os.listdir(root), [])

        def boom(argv, timeout=60, cwd=None, env=None):
            raise RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            devbench.run_bench(boom, FakeClock(), tmp_root=root, n_files=5, repo_files=5)
        self.assertEqual(os.listdir(root), [])

    def test_wsl_files_are_timed_and_cleaned_up(self):
        doc, runner = self.bench(distro=True, cost={"wsl": 0.3})
        self.assertIn("wsl_small_files_ms", {m["name"] for m in doc["metrics"]})
        self.assertTrue(any(c[:3] == ["wsl", "-e", "sh"] and "rm -rf ~/wb-bench-*" in c[-1] for c in runner.calls))

    def test_flags_skip_network_and_model_steps(self):
        doc, runner = self.bench(network=False, model_call=False)
        names = {m["name"] for m in doc["metrics"]}
        self.assertFalse(names & {"pip_resolve_ms", "npm_resolve_ms", "model_rtt_ms"})
        self.assertEqual({s["name"]: s["why"] for s in doc["skipped"]}["pip_resolve_ms"], "--no-network")
        self.assertFalse([c for c in runner.calls if c[0] in ("npm", "claude")])

    def test_budget_stops_the_bench(self):
        doc, _r = self.bench(cost={"default": 90.0}, budget_s=170)
        self.assertTrue(any(s["why"] == "budget" for s in doc["skipped"]) or len(doc["metrics"]) < 8)

    def test_a_failing_tool_is_skipped_with_its_exit_code(self):
        doc, _r = self.bench(fail=("npm",))
        self.assertNotIn("npm_resolve_ms", {m["name"] for m in doc["metrics"]})
        self.assertIn("exit 1", next(s["why"] for s in doc["skipped"] if s["name"] == "npm_resolve_ms"))

    def test_pick_model_takes_the_cheapest_allowed(self):
        self.assertEqual(devbench.pick_model(), "haiku")
        self.assertEqual(devbench.pick_model(["claude-haiku-5-5"]), "sonnet")
        self.assertEqual(devbench.pick_model(["claude-haiku", "claude-sonnet"]), "opus")
        self.assertIsNone(devbench.pick_model(["haiku", "sonnet", "opus"]))
        self.assertEqual(devbench.pick_model([], ["claude-opus-5-5"]), "opus")

    def test_thresholds_are_one_table(self):
        for name, (label, fast, ok) in devbench.THRESHOLDS.items():
            self.assertLess(fast, ok, name)
        self.assertEqual(devbench.judge([{"name": "git_status_ms", "value": 801, "unit": "ms", "n": 5}], {})[0], "slow")
        self.assertEqual(devbench.judge([{"name": "git_status_ms", "value": 200, "unit": "ms", "n": 5}], {})[0], "fast")
        self.assertEqual(devbench.judge([{"name": "git_status_ms", "value": 201, "unit": "ms", "n": 5}], {})[0], "OK")

    def test_real_runner_refuses_other_programs(self):
        with self.assertRaises(ValueError):
            devbench.real_runner(["cmd", "/c", "dir"])

    def test_small_real_bench_cleans_up(self):
        need(self, "git", shutil.which("git"))
        root = tp.tmpdir(self)
        doc = devbench.run_bench(tmp_root=root, network=False, model_call=False, n_files=30, repo_files=15, reps=2, budget_s=90)
        self.assertIn("small_files_ms", {m["name"] for m in doc["metrics"]})
        self.assertIn("git_status_ms", {m["name"] for m in doc["metrics"]})
        self.assertIn(doc["verdict"], ("fast", "OK", "slow"))
        self.assertEqual(os.listdir(root), [])
        self.assertTrue(doc["tmp_removed"])

    @unittest.skipUnless(LIVE, "WB_LIVE=1 runs the capped bench with its real defaults")
    def test_capped_run_reports_peak_under_the_cap(self):
        doc = devbench.run_capped(budget_s=120, mb=1024, network=False, model_call=False)
        self.assertIn(doc["verdict"], ("fast", "OK", "slow"))
        self.assertIsNotNone(doc["peak_mb"])
        self.assertLess(doc["peak_mb"], 1024)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--write-fixture":
        os.makedirs(os.path.dirname(os.path.abspath(sys.argv[2])), exist_ok=True)
        with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as f:
            json.dump(tp.FIXTURE_PACKAGES, f, indent=1)
        print("wrote " + sys.argv[2])
        sys.exit(0)
    unittest.main()
