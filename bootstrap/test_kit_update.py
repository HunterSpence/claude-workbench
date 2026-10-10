"""K1 / K1+: kit_update.py. A fake GitHub (S.curl is replaced; no network), fake release archives with good and bad SHA-256, a fake
setup runner (K.run_py), and a temp Claude home: nothing here touches this PC's settings, registry, PATH or home folder. Every
user, computer, domain and host name below is fictional.
Run: python -m unittest discover -s bootstrap -p "test_kit_update.py" -v"""
import ast
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import asks as ASKS  # noqa: E402,F401
import install as I  # noqa: E402
import kit_update as K  # noqa: E402
import setup as S  # noqa: E402

REAL_SPAWN = K.spawn                       # Machine replaces K.spawn; this is the real one, for the test that looks at its command line
SLUG = "example-org/example-kit"
FAKE_USER, FAKE_HOST, FAKE_DOMAIN = "alice_example", "WS-0042", "EXAMPLECORP"
TOKEN = "ghp_" + "A1b2C3d4" * 4 + "Zz9Y"             # built at run time: this file holds no credential-shaped string
IP = ".".join(("192", "0", "2", "44"))            # an address from the documentation range, built at run time too
OLD, NEW = "0.3.1", "0.3.2"


def archive(version, extra=None, install_version=None):
    """(asset name, bytes) of a release archive in the shape the platform downloads (zip on Windows, tar.gz elsewhere)."""
    name = K.ASSET.format(tag=f"v{version}", ext=".zip" if S.WIN else ".tar.gz")
    files = {f"claude-workbench-{version}/bootstrap/install.py": f'VERSION = "{install_version or version}"\n',
             f"claude-workbench-{version}/README.md": "x\n", **(extra or {})}
    buf = io.BytesIO()
    if S.WIN:
        with zipfile.ZipFile(buf, "w") as z:
            for n, c in files.items():
                z.writestr(n, c)
    else:
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            for n, c in files.items():
                ti = tarfile.TarInfo(n)
                ti.size = len(c.encode())
                t.addfile(ti, io.BytesIO(c.encode()))
    return name, buf.getvalue()


class Net:
    """A fake `S.curl`: GitHub's API answer and the release assets, by URL. Records every call."""
    def __init__(self, version=NEW, body_hash="", digest="", data=None, draft=False, url_repo=None, tag=None, with_asset=True, slug=SLUG):
        self.name, self.data = archive(version) if data is None else (archive(version)[0], data)
        good = hashlib.sha256(self.data).hexdigest()
        self.tag = tag or f"v{version}"
        url = f"https://github.com/{url_repo or slug}/releases/download/{self.tag}/{self.name}"
        asset = {"name": self.name, "size": len(self.data), "browser_download_url": url,
                 "digest": "sha256:" + (digest or good)} if with_asset else None
        self.release = {"tag_name": self.tag, "draft": draft, "prerelease": False,
                        "assets": [asset] if asset else [],
                        "body": f"| `{self.name}` (Windows) | `{body_hash or good}` |\n"}
        self.api = f"https://api.github.com/repos/{slug}/releases/latest"
        self.files = {self.api: json.dumps(self.release).encode(), url: self.data}
        self.calls = []

    def __call__(self, ctx, args, timeout):
        self.calls.append(list(args))
        url, out = args[-1], Path(args[args.index("-o") + 1])
        if url not in self.files:
            return 22, b"curl: (22) The requested URL returned error: 404\n404"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(self.files[url])
        return 0, b"200"

    def urls(self):
        return [c[-1] for c in self.calls]


class Run:
    """A fake `K.run_py`: install.py and setup.py as scripted. Every call is recorded as (script name, args)."""
    def __init__(self, status=None, rows=None, install_rc=0, run_rc=0, doctor_rc=0):
        self.calls, self.install_rc, self.run_rc, self.doctor_rc = [], install_rc, run_rc, doctor_rc
        self.status = list(status or [{"phase": "done", "running": False, "exit_code": 0, "updated": "2999-01-01T00:00:00Z"}])
        self.rows = [{"check": "capability report (quick)", "status": "OK", "detail": "refreshed"}] if rows is None else rows

    def __call__(self, ctx, script, *args, timeout=0):
        self.calls.append((Path(script).name, tuple(str(a) for a in args)))
        if Path(script).name == "install.py":
            self.install_cwd = os.getcwd()
            return self.install_rc, "installed\n", "" if self.install_rc == 0 else "the policy says no\n"
        if args[0] == "run":
            return self.run_rc, "setup is running in the background (pid 1)\n", ""
        if args[0] == "status":
            st = self.status.pop(0) if len(self.status) > 1 else self.status[0]
            return 0, json.dumps(st), ""
        if args[0] == "doctor":
            return self.doctor_rc, json.dumps({"rows": self.rows}), ""
        return 0, "", ""

    def named(self, name, first=None):
        return [a for n, a in self.calls if n == name and (first is None or a[:1] == (first,))]


class Machine(unittest.TestCase):
    """A temp Claude home with a healthy install of kit 0.3.1 and the patches that keep every test off this PC."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-ku-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home, self.kit = self.tmp / "home", self.tmp / "kit"
        self.ch = self.home / ".claude"
        self.wb, self.state = self.ch / "workbench", self.ch / "workbench" / "state"
        self.state.mkdir(parents=True)
        for name in ("workbench-core", "workbench-kb"):
            m = self.kit / "plugins" / name / ".claude-plugin" / "plugin.json"
            m.parent.mkdir(parents=True)
            m.write_text(json.dumps({"name": name, "userConfig": {"python": {"type": "string"}}}), encoding="utf-8")
        sc = self.kit / "plugins" / "workbench-core" / "scripts"
        sc.mkdir()
        for f in ("_wb.py", "secretscan.py"):
            shutil.copyfile(REPO / "plugins" / "workbench-core" / "scripts" / f, sc / f)
        self.py = I.fwd(sys.executable)
        self.settings({"enabledPlugins": {"workbench-core@workbench": True, "workbench-kb@workbench": True},
                       "pluginConfigs": {"workbench-core@workbench": {"options": {"python": self.py}},
                                         "workbench-kb@workbench": {"options": {"python": self.py}}}})
        S.jwrite(self.wb / "config.json", {"profile": "corporate", "data_root": I.fwd(self.home / "Workbench"),
                                           "kb_root": I.fwd(self.home / "Workbench" / "kb")})
        S.jwrite(self.state / "setup-state.json", {"kit_version": OLD, "phase": "done", "exit_code": 0,
                                                   "options": {"with": ["ctx", "tokensave"], "no_nightly": True, "no_update": False}})
        S.jwrite(self.state / "guard-heartbeat.json", {"version": 1, "last_fired": "2999-01-01T00:00:00Z", "sessions_since_fire": 0})
        env = {k: v for k, v in os.environ.items() if not k.startswith(("WORKBENCH_", "WB_", "OneDrive", "USERDNS"))}
        env.update(CLAUDE_CONFIG_DIR=str(self.ch), USERPROFILE=str(self.home), HOME=str(self.home), LOCALAPPDATA=str(self.tmp / "lad"),
                   WORKBENCH_FAKE_REGISTRY=str(self.tmp / "reg.json"), WORKBENCH_MANAGED_SETTINGS=str(self.tmp / "none.json"),
                   USERNAME=FAKE_USER, COMPUTERNAME=FAKE_HOST, USERDOMAIN=FAKE_DOMAIN, PATH=os.environ.get("PATH", ""))
        (self.tmp / "reg.json").write_text("{}")
        self.spawned, self.hold = [], False

        def fake_spawn(ctx, out, run):                      # the background doctor job: run in place, or "still running" (self.hold)
            self.spawned.append(Path(out).name)
            if self.hold:
                return os.getpid()
            K.doctor_job_main(ctx, out, run)
            return 0
        for p in (mock.patch.dict(os.environ, env, clear=True), mock.patch.object(S, "KIT", self.kit), mock.patch.object(K, "KIT", self.kit),
                  mock.patch.object(I, "VERSION", OLD), mock.patch.object(K, "nap", lambda s: None), mock.patch.object(K, "spawn", fake_spawn),
                  mock.patch.object(Path, "home", return_value=self.home)):
            p.start()
            self.addCleanup(p.stop)

    def settings(self, d):
        S.jwrite(self.ch / "settings.json", d)

    def ctx(self):
        return S.Ctx()

    def update(self, net, run, repo=SLUG, **kw):
        with mock.patch.object(S, "curl", net):
            return K.cmd_update(self.ctx(), repo, run=run, **kw)

    def marker(self):
        return S.jload(self.state / S.MARKER)


class SetChoices(Machine):
    """`kit_update.py set --approvals off|ask --guard minimal|...`: the installed installer again, same profile and opt-ins."""
    def setUp(self):
        super().setUp()
        inst = self.wb / "kit" / "bootstrap" / "install.py"
        inst.parent.mkdir(parents=True)
        inst.write_text("# the installed kit's installer (never run: the Run fake answers)\n", encoding="utf-8")

    class Plan(Run):
        def __call__(self, ctx, script, *args, timeout=0):
            super().__call__(ctx, script, *args, timeout=timeout)
            if "off" in args:
                return 0, ("[settings] profile corporate; approvals: off (new windows start in acceptEdits)\n"
                           "WARNING approvals off: your organisation's managed settings keep bypass mode off\n"), ""
            return 0, "[settings] profile corporate; approvals: ask\n", ""

    def go(self, run, **kw):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = K.cmd_set(self.ctx(), run=run, **kw)
        return code, out.getvalue()

    def test_approvals_off_and_guard_minimal_rerun_the_installed_installer_once_with_the_same_choices(self):
        run = self.Plan()
        code, text = self.go(run, approvals="off", guard="minimal")
        self.assertEqual(code, 0)
        (name, args), = run.calls
        self.assertEqual(name, "install.py")
        self.assertEqual(args, ("--apply", "--profile", "corporate", "--with", "ctx,tokensave", "--approvals", "off", "--guard", "minimal"))
        self.assertEqual(Path(run.install_cwd).resolve(), self.state.resolve(), "never from inside the kit folder")
        self.assertIn("Approvals OFF", text)
        self.assertIn("new windows start in acceptEdits", text)
        self.assertIn("approvals off: your organisation's managed settings keep bypass mode off", text)
        self.assertIn("Guard MINIMAL: it refuses nothing", text)
        self.assertIn("Restart every Claude Code window", text)

    def test_each_choice_alone_and_back(self):
        run = self.Plan()
        code, text = self.go(run, approvals="ask")
        self.assertEqual((code, run.calls[-1][1][-2:]), (0, ("--approvals", "ask")))
        self.assertIn("Approvals back ON", text)
        code, text = self.go(run, guard="standard")
        self.assertEqual((code, run.calls[-1][1][-2:]), (0, ("--guard", "standard")))
        self.assertNotIn("--approvals", run.calls[-1][1])

    def test_the_permissive_profile_keeps_its_approvals_and_a_missing_kit_or_choice_is_a_usage_error(self):
        S.jwrite(self.wb / "config.json", {"profile": "permissive"})
        run = self.Plan()
        code, text = self.go(run, approvals="off")
        self.assertEqual((code, run.calls), (0, []))
        self.assertIn("already runs commands without asking", text)
        code, text = self.go(run, approvals="off", guard="minimal")
        self.assertEqual(run.calls[-1][1][-2:], ("--guard", "minimal"), "the guard part still applies")
        self.assertNotIn("--approvals", run.calls[-1][1])
        S.jwrite(self.wb / "config.json", {"profile": "corporate"})
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(K.main(["set"]), 2)
        (self.wb / "kit" / "bootstrap" / "install.py").unlink()
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(K.main(["set", "--approvals", "off"]), 2)

    def test_a_policy_stop_is_exit_3_and_a_bad_value_is_a_usage_error(self):
        with mock.patch.object(K, "run_py", Run(install_rc=3)), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(K.main(["set", "--guard", "minimal"]), 3)
        self.assertIn("policy stopped it", out.getvalue())
        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(K.main(["set", "--approvals", "maybe"]), 2)
            self.assertEqual(K.main(["set", "--guard", "none"]), 2)
            self.assertEqual(K.main(["set", "--appr", "off"]), 2)                # no abbreviations: the guard reads the full words


class Update(Machine):
    def test_a_newer_release_is_downloaded_checked_installed_and_set_up_with_the_remembered_opt_ins(self):
        net, run = Net(), Run()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = self.update(net, run)
        text = out.getvalue()
        self.assertEqual(code, 0, text)
        self.assertEqual(net.urls()[0], net.api)
        self.assertIn("Accept: application/vnd.github+json", net.calls[0])
        dl = net.calls[1]
        self.assertTrue(dl[-1].startswith(f"https://github.com/{SLUG}/releases/download/v{NEW}/"))
        for want in ("--fail", "--location", "--proto", "=https", "--proto-redir"):
            self.assertIn(want, dl)
        self.assertFalse({"-k", "--insecure", "--ssl-no-revoke"} & {a for c in net.calls for a in c}, "never TLS-lenient")
        inst = run.named("install.py")[0]
        self.assertEqual(inst[:5], ("--apply", "--profile", "corporate", "--with", "ctx,tokensave"))
        self.assertNotIn("--force", inst)
        self.assertNotIn("permissive", inst)
        setup = run.named("setup.py", "run")[0]
        self.assertEqual(setup, ("run", "--detach", "--with", "ctx,tokensave", "--no-nightly"), "the remembered opt-ins, nothing more")
        self.assertEqual(Path(run.install_cwd).resolve(), self.state.resolve(), "the installer replaces <WB>/kit, so it must not run from inside it")
        self.assertEqual(self.spawned, ["doctor-update.out.json"], "the doctor ran as its own background job")
        self.assertNotEqual(Path(os.getcwd()).resolve(), self.state.resolve(), "and the caller's folder is restored")
        self.assertEqual(run.named("setup.py", "doctor")[0], ("doctor", "--deep", "--json"))
        order = [n + ":" + (a[0] if a else "") for n, a in run.calls]
        self.assertLess(order.index("install.py:--apply"), order.index("setup.py:run"))
        self.assertLess(order.index("setup.py:run"), order.index("setup.py:doctor"))
        mk = self.marker()
        self.assertEqual((mk["version"], mk["from_version"], mk["source"]), (NEW, OLD, "kit_update"))
        self.assertTrue(mk["time"].endswith("Z"))
        self.assertFalse((self.state / K.RUN_FILE).exists())
        self.assertEqual(S.jload(self.wb / "config.json")["kit_repo"], SLUG, "the repository that worked is remembered")
        self.assertFalse([p for p in (self.state / "kit-update").glob("v*")], "the unpacked release is cleaned up on success")
        self.assertIn(K.RESTART, text)
        self.assertEqual(text.strip().splitlines()[-1], K.RESTART)
        for step in ("latest release", "download + SHA-256", "install", "setup", "doctor --deep"):
            self.assertIn(step, text)
        self.assertRegex(text, r"update notes .*kit/IMPORT\.md\n\n" + K.RESTART, "the release's own notes are pointed to, then the restart")
        self.assertNotIn("claude update", text)

    def test_a_published_hash_that_does_not_match_stops_everything_and_nothing_is_installed(self):
        net, run = Net(digest="0" * 64, body_hash="0" * 64), Run()
        with self.assertRaises(I.Stop) as e:
            self.update(net, run)
        self.assertEqual(e.exception.code, 4)
        self.assertIn("SHA-256 mismatch", str(e.exception))
        self.assertEqual(run.calls, [], "install.py and setup.py were never started")
        self.assertIsNone(self.marker())
        self.assertFalse((self.state / K.RUN_FILE).exists())
        self.assertFalse(list((self.state / "kit-update").rglob("*.zip")) + list((self.state / "kit-update").rglob("*.tar.gz")),
                         "the bad download was deleted")
        self.assertEqual(S.jload(self.wb / "config.json").get("kit_repo"), None)

    def test_two_published_values_that_disagree_or_none_at_all_stop_before_any_download(self):
        for kw, why in ((dict(digest="1" * 64, body_hash="2" * 64), "two different SHA-256"), ):
            net = Net(**kw)
            with self.assertRaises(I.Stop) as e:
                self.update(net, Run())
            self.assertIn(why, str(e.exception))
            self.assertEqual(len(net.calls), 1, "only the API was asked")
        net = Net()
        net.release["assets"][0]["digest"] = ""
        net.release["body"] = "no checksum table"
        net.files[net.api] = json.dumps(net.release).encode()
        with self.assertRaises(I.Stop) as e:
            self.update(net, Run())
        self.assertIn("publishes no SHA-256", str(e.exception))
        self.assertEqual(len(net.calls), 1)

    def test_the_digest_alone_or_the_table_alone_is_enough_when_it_matches(self):
        net = Net()
        net.release["body"] = ""
        net.files[net.api] = json.dumps(net.release).encode()
        self.assertEqual(self.update(net, Run()), 0)

    def test_already_current_says_so_and_runs_the_verify_without_downloading(self):
        net, run = Net(version=OLD), Run()
        with mock.patch.object(K, "cmd_verify", return_value=0) as ver, mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = self.update(net, run)
        self.assertEqual((code, ver.call_count), (0, 1))
        self.assertIn("already current", out.getvalue())
        self.assertEqual(len(net.calls), 1, "only the API was asked")
        self.assertEqual(run.calls, [])
        self.assertIsNone(self.marker())

    def test_an_update_never_starts_while_a_setup_run_holds_the_lock(self):
        net, run = Net(), Run()
        with mock.patch.object(S, "lock_holder", return_value=4242), self.assertRaises(I.Stop) as e:
            self.update(net, run)
        self.assertEqual(e.exception.code, 2)
        self.assertIn("already running", str(e.exception))
        self.assertEqual((net.calls, run.calls), ([], []))

    def test_check_changes_nothing(self):
        net, run = Net(), Run()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = self.update(net, run, check=True)
        self.assertEqual(code, 0)
        self.assertIn(f"v{NEW}", out.getvalue())
        self.assertEqual((len(net.calls), run.calls, self.marker()), (1, [], None))
        with mock.patch.object(K, "cmd_verify") as ver, mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(self.update(Net(version=OLD), Run(), check=True), 0)
        self.assertEqual(ver.call_count, 0, "--check never runs the verify")
        self.assertIn("already current", out.getvalue())

    def test_a_still_running_setup_returns_6_and_the_same_command_resumes_without_downloading_again(self):
        net = Net()
        run = Run(status=[{"phase": "knowledge", "running": True}])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = self.update(net, run, budget=0)
        self.assertEqual(code, 6)
        self.assertIn("still running", out.getvalue())
        self.assertEqual(S.jload(self.state / K.RUN_FILE)["stage"], "setup")
        self.assertIsNone(self.marker(), "no marker until setup and the doctor are done")
        self.assertLessEqual(int(run.named("setup.py", "status")[0][-1]), 1, "a call never blocks in status past its own budget")
        net2, run2 = Net(), Run()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = self.update(net2, run2)
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(net2.calls, [], "the resumed call downloads nothing")
        self.assertEqual(run2.named("install.py"), [], "and installs nothing")
        self.assertEqual(self.marker()["version"], NEW)
        self.assertFalse((self.state / K.RUN_FILE).exists())

    def test_the_doctor_is_its_own_stage_a_job_that_outlives_the_call_and_the_same_command_finishes_it(self):
        self.hold = True                                    # the doctor job is still running when the first call's budget is spent
        net, run = Net(), Run()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = self.update(net, run, budget=0)
        self.assertEqual(code, 6, out.getvalue())
        self.assertIn("doctor --deep) is still running", out.getvalue())
        rs = S.jload(self.state / K.RUN_FILE)
        self.assertEqual(rs["stage"], "doctor")
        self.assertEqual([s[0] for s in rs["steps"]], ["latest release", "download + SHA-256", "install", "setup"], "the finished stages are kept")
        self.assertIsNone(self.marker())
        self.assertEqual(run.named("setup.py", "doctor"), [], "the in-flight job has not answered yet")
        # the job finishes (here: the same job function, run by hand) and the SAME command carries on
        self.hold = False
        K.doctor_job_main(self.ctx(), self.state / "kit-update" / "doctor-update.out.json", run)
        net2, run2 = Net(), Run()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = self.update(net2, run2)
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual((net2.calls, run2.calls), ([], []), "nothing is downloaded, installed, set up or checked again")
        self.assertEqual(self.spawned, ["doctor-update.out.json"], "one job only")
        self.assertEqual(self.marker()["version"], NEW)
        for step in ("latest release", "download + SHA-256", "install", "setup", "doctor --deep"):
            self.assertIn(step, out.getvalue())
        self.assertFalse((self.state / "kit-update" / "doctor-update.json").exists(), "the job files are cleaned up")

    def test_a_doctor_job_that_dies_without_an_answer_is_a_failed_step_not_an_endless_wait(self):
        def dead(ctx, out, run):
            self.spawned.append("dead")
            return 0                                        # no pid, no output file
        with mock.patch.object(K, "spawn", dead), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = self.update(Net(), Run())
        self.assertEqual(code, 1)
        self.assertRegex(out.getvalue(), r"doctor --deep\s+FAIL\s+no result")
        self.assertIn(K.RESTART, out.getvalue())

    def test_the_background_job_is_started_detached_through_the_kits_own_command(self):
        calls = []

        class P:
            pid = 4321
        with mock.patch.object(K.subprocess, "Popen", side_effect=lambda cmd, **kw: calls.append((cmd, kw)) or P()):
            pid = REAL_SPAWN(self.ctx(), self.tmp / "o.json", None)
        self.assertEqual(pid, 4321)
        cmd, kw = calls[0]
        self.assertEqual(cmd[1:], [str(Path(K.__file__).resolve()), "_doctor", str(self.tmp / "o.json")])
        self.assertEqual(Path(kw["cwd"]).resolve(), self.state.resolve())
        self.assertTrue(kw["creationflags"] & 0x8 if S.WIN else kw["start_new_session"], "detached from the call that started it")

    def test_the_hidden_doctor_command_runs_setup_doctor_and_writes_its_whole_answer_to_one_file(self):
        out = self.tmp / "doctor.out.json"
        run = Run(rows=[{"check": "x", "status": "OK", "detail": "d"}])
        with mock.patch.object(K, "run_py", run):
            self.assertEqual(K.main(["_doctor", str(out)]), 0)
        got = S.jload(out)
        self.assertEqual(got["rc"], 0)
        self.assertEqual(json.loads(got["out"])["rows"][0]["check"], "x")
        self.assertEqual(run.named("setup.py", "doctor")[0], ("doctor", "--deep", "--json"))

    def test_setup_that_never_starts_is_a_failure_after_three_minutes(self):
        run = Run(status=[{"phase": "done", "running": False, "exit_code": 0, "pid": 1234, "updated": "2000-01-01T00:00:00Z"}])
        now = [0.0]
        clock = types.SimpleNamespace(time=lambda: now[0], strftime=time.strftime, sleep=lambda s: None)
        with mock.patch.object(K, "time", clock), mock.patch.object(K, "nap", lambda s: now.__setitem__(0, now[0] + s)):
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                for _ in range(2):
                    self.assertEqual(self.update(Net(), run), 6, "a call spends its 90 seconds and says to run it again")
            with self.assertRaises(I.Stop) as e:           # the three minutes are counted from the start of setup, across calls
                self.update(Net(), run)
        self.assertIn("did not start", str(e.exception))
        self.assertRegex(str(e.exception), r'run py -3 "[^"]+setup\.py" run --detach, then run this same command again')
        self.assertGreater(now[0], 180)

    def test_a_setup_that_started_and_died_says_so_and_names_the_recovery_not_that_it_never_started(self):
        run = Run(status=[{"phase": "knowledge", "running": True, "pid": 4242, "updated": "2999-01-01T00:00:00Z"},
                          {"phase": "knowledge", "running": False, "pid": 4242, "updated": "2999-01-01T00:00:05Z", "exit_code": None}])
        (self.state / "setup.log").write_text("phase knowledge\n\nRuntimeError: example failure in the knowledge phase\n", encoding="utf-8")
        now = [0.0]
        clock = types.SimpleNamespace(time=lambda: now[0], strftime=time.strftime, sleep=lambda s: None)
        with mock.patch.object(K, "time", clock), mock.patch.object(K, "nap", lambda s: now.__setitem__(0, now[0] + s)):
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(self.update(Net(), run), 6, "the first call saw it running")
                with self.assertRaises(I.Stop) as e:
                    for _ in range(5):
                        self.update(Net(), run)
        msg = str(e.exception)
        self.assertIn("started", msg)
        self.assertIn("stopped before it finished", msg)
        self.assertNotIn("did not start", msg)
        self.assertIn("pid 4242", msg)
        self.assertIn("last phase knowledge", msg)
        self.assertIn("RuntimeError: example failure in the knowledge phase", msg, "the end of setup.log")
        self.assertRegex(msg, r'run py -3 "[^"]+setup\.py" run --detach, then run this same command again')

    def test_the_install_time_counts_against_the_first_calls_wait(self):
        now = [0.0]

        class Slow(Run):                                    # the install takes 70 s; a status call blocks for the --wait it is given
            def __call__(self, ctx, script, *args, timeout=0):
                if Path(script).name == "install.py":
                    now[0] += 70
                elif args[0] == "status":
                    now[0] += int(args[args.index("--wait") + 1])
                return super().__call__(ctx, script, *args, timeout=timeout)
        clock = types.SimpleNamespace(time=lambda: now[0], strftime=time.strftime, sleep=lambda s: None)
        run = Slow(status=[{"phase": "knowledge", "running": True}])
        with mock.patch.object(K, "time", clock), mock.patch.object(K, "nap", lambda s: now.__setitem__(0, now[0] + s)):
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(self.update(Net(), run), 6)
        self.assertLessEqual(now[0], 95, "70 s of install + the rest of the 90 s wait, not another 90 s on top")
        self.assertGreaterEqual(now[0], 85, "and the wait is still spent")

    def test_a_failed_setup_and_a_failed_doctor_are_failures_in_the_table_but_the_restart_line_still_comes(self):
        run = Run(status=[{"phase": "done", "running": False, "exit_code": 4, "updated": "2999-01-01T00:00:00Z",
                           "failed": [{"item": "ctx", "error": "download exit 22"}]}],
                  rows=[{"check": "guard heartbeat", "status": "FAIL", "detail": "x"}], doctor_rc=2)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = self.update(Net(), run)
        text = out.getvalue()
        self.assertEqual(code, 1)
        self.assertRegex(text, r"setup\s+FAIL\s+ctx: download exit 22")
        self.assertRegex(text, r"doctor --deep\s+FAIL")
        self.assertIn(K.RESTART, text)
        self.assertEqual(self.marker()["version"], NEW)

    def test_a_reboot_request_stops_with_5_and_no_restart_line(self):
        run = Run(status=[{"phase": "reboot-wait", "running": False, "exit_code": None, "reboot_pending": True,
                           "updated": "2999-01-01T00:00:00Z"}])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = self.update(Net(), run)
        self.assertEqual(code, 5)
        self.assertNotIn(K.RESTART, out.getvalue())
        self.assertEqual(run.named("setup.py", "doctor"), [])

    def test_an_installer_stopped_by_policy_is_a_hard_stop_and_setup_is_not_started(self):
        run = Run(install_rc=3)
        with self.assertRaises(I.Stop) as e:
            self.update(Net(), run)
        self.assertEqual(e.exception.code, 3)
        self.assertIn("policy", str(e.exception))
        self.assertEqual(run.named("setup.py"), [])
        self.assertIsNone(self.marker())

    def test_a_proxy_403_is_a_policy_stop_with_the_hosts_to_ask_for(self):
        def deny(ctx, args, timeout):
            return 22, b"curl: (22) The requested URL returned error: 403\n403"
        with mock.patch.object(S, "curl", deny), self.assertRaises(I.Stop) as e:
            K.cmd_update(self.ctx(), SLUG, run=Run())
        self.assertEqual(e.exception.code, 3)
        self.assertIn("api.github.com", str(e.exception))

    def test_the_release_must_be_a_plain_tag_with_its_asset_under_the_repository(self):
        for net, why in ((Net(draft=True), "plain vX.Y.Z"), (Net(tag="nightly"), "plain vX.Y.Z"), (Net(with_asset=False), "has no"),
                         (Net(url_repo="someone-else/other"), "not under")):
            with self.assertRaises(I.Stop) as e:
                self.update(net, Run())
            self.assertIn(why, str(e.exception))
            self.assertEqual(len(net.calls), 1)

    def test_a_package_that_says_another_version_than_its_release_is_refused(self):
        name, data = archive(NEW, install_version="9.9.9")
        net, run = Net(data=data), Run()
        with self.assertRaises(I.Stop) as e:
            self.update(net, run)
        self.assertIn("the package says it is v9.9.9", str(e.exception))
        self.assertEqual(run.calls, [])

    def test_where_the_releases_live_comes_from_the_remembered_repo_then_the_env_var_then_the_kits_own_file(self):
        ctx = self.ctx()
        with self.assertRaises(I.Stop) as e:
            K.resolve_repo(ctx, None)
        self.assertEqual(e.exception.code, 2)
        self.assertIn("--repo OWNER/REPO", str(e.exception))
        src = self.kit / K.SOURCE
        src.parent.mkdir(parents=True)
        src.write_text(json.dumps({"repo": "from-file/kit"}), encoding="utf-8")
        self.assertEqual(K.resolve_repo(ctx, None), "from-file/kit")
        with mock.patch.dict(os.environ, {"WB_KIT_REPO": "from-env/kit"}):
            self.assertEqual(K.resolve_repo(self.ctx(), None), "from-env/kit", "the environment outranks the kit's own file")
            S.set_config(ctx, kit_repo="from-config/kit")
            self.assertEqual(K.resolve_repo(self.ctx(), None), "from-config/kit", "what the kit remembers outranks the environment")
        self.assertEqual(K.resolve_repo(self.ctx(), "from-config/kit"), "from-config/kit")
        self.assertEqual(K.resolve_repo(self.ctx(), "From-Config/Kit"), "From-Config/Kit", "the same repository, however it is cased")
        for bad in ("nonsense", "a/b/c", "../x/y", "a b/c", "https://github.com/a/b"):
            with self.assertRaises(I.Stop):
                K.resolve_repo(ctx, bad)
        self.assertTrue(json.loads((REPO / K.SOURCE).read_text(encoding="utf-8")).keys() >= {"repo"}, "the kit ships the file to fill in")

    def test_a_different_repo_than_the_remembered_one_is_refused_before_any_network_call_unless_new_repo_says_it_moved(self):
        S.set_config(self.ctx(), kit_repo=SLUG)
        net, run = Net(), Run()
        with self.assertRaises(I.Stop) as e:
            self.update(net, run, repo="attacker-org/evil-kit")
        self.assertEqual(e.exception.code, 2)
        self.assertIn("--new-repo", str(e.exception))
        self.assertIn(SLUG, str(e.exception))
        self.assertEqual((net.calls, run.calls), ([], []), "nothing was asked, downloaded or run")
        self.assertEqual(S.jload(self.wb / "config.json")["kit_repo"], SLUG)
        with mock.patch.dict(os.environ, {"WB_KIT_REPO": "attacker-org/evil-kit"}):
            self.assertEqual(K.resolve_repo(self.ctx(), None), SLUG, "an environment variable cannot redirect a remembered kit")
        net2, run2 = Net(slug="moved-org/moved-kit"), Run()
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(self.update(net2, run2, repo="moved-org/moved-kit", new_repo=True), 0)
        self.assertTrue(net2.urls()[0].startswith("https://api.github.com/repos/moved-org/moved-kit/"))
        self.assertEqual(S.jload(self.wb / "config.json")["kit_repo"], "moved-org/moved-kit", "the new repository is the remembered one now")

    def test_a_first_run_with_no_remembered_repo_takes_the_flag_and_remembers_it(self):
        self.assertIsNone(S.jload(self.wb / "config.json").get("kit_repo"))
        with mock.patch.object(K, "cmd_verify", return_value=0):
            self.assertEqual(self.update(Net(version=OLD), Run(), repo=SLUG), 0)
        self.assertEqual(S.jload(self.wb / "config.json")["kit_repo"], SLUG)

    def test_an_archive_member_outside_its_folder_or_a_link_is_refused_before_anything_is_written(self):
        for members, why in (({"../evil.txt": "x"}, "outside"), ({"/abs.txt": "x"}, "outside"), ({"C:/drive.txt": "x"}, "outside"),
                             ({"a\\..\\..\\up.txt": "x"}, "outside")):
            name, data = archive(NEW, extra=members)
            net, run = Net(data=data), Run()
            with self.assertRaises(I.Stop) as e:
                self.update(net, run)
            self.assertIn(why, str(e.exception))
            self.assertEqual(run.calls, [])
            self.assertFalse((self.tmp / "evil.txt").exists())
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            ti = tarfile.TarInfo("kit/link")
            ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
            t.addfile(ti)
        z = self.tmp / "evil.tar.gz"
        z.write_bytes(buf.getvalue())
        with self.assertRaises(I.Stop):
            K.unpack(z, self.tmp / "out")

    def test_an_archive_over_the_entry_or_size_cap_is_refused_before_anything_is_written(self):
        def zip_of(files):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for n, c in files.items():
                    z.writestr(n, c)
            return buf.getvalue()

        def tar_of(files):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as t:
                for n, c in files.items():
                    ti = tarfile.TarInfo(n)
                    ti.size = len(c)
                    t.addfile(ti, io.BytesIO(c))
            return buf.getvalue()
        many = {f"k/f{i}.txt": b"x" for i in range(6)}
        fat = {"k/bootstrap/install.py": b"VERSION = '0'\n", "k/big.bin": b"0" * 4000}            # compresses to a few dozen bytes
        for ext, make in ((".zip", zip_of), (".tar.gz", tar_of)):
            for files, caps, word in ((many, (5, 10**9), "entries"), (fat, (10**9, 3000), "MB unpacked")):
                z = self.tmp / f"cap-{len(files)}{ext}"
                z.write_bytes(make(files))
                out = self.tmp / f"out-{len(files)}{ext}"
                with mock.patch.object(K, "MAX_ENTRIES", caps[0]), mock.patch.object(K, "MAX_BYTES", caps[1]):
                    with self.assertRaises(I.Stop) as e:
                        K.unpack(z, out)
                self.assertEqual(e.exception.code, 4)
                self.assertIn(word, str(e.exception))
                self.assertIn("nothing was installed", str(e.exception))
                self.assertEqual(list(out.iterdir()), [], "refused before a single member was written")
            with mock.patch.object(K, "MAX_ENTRIES", 6), mock.patch.object(K, "MAX_BYTES", 4000 + 100):           # at the caps: fine
                z = self.tmp / f"ok{ext}"
                z.write_bytes(make({**{f"k/f{i}": b"x" for i in range(5)}, "k/bootstrap/install.py": b"VERSION = '0'\n"}))
                self.assertTrue((K.unpack(z, self.tmp / f"ok-out{ext}") / "bootstrap" / "install.py").is_file())
        self.assertEqual((K.MAX_ENTRIES, K.MAX_BYTES), (20_000, 500 * 1024 * 1024), "the shipped caps")

    def test_main_parses_the_verbs_and_turns_a_stop_into_its_exit_code(self):
        with mock.patch.object(K, "cmd_update", side_effect=I.Stop(3, "blocked")) as upd, mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(K.main(["--check", "--repo", SLUG, "--new-repo"]), 3)
        self.assertEqual(upd.call_args.args[1:3], (SLUG, True))
        self.assertTrue(upd.call_args.kwargs["new_repo"])
        self.assertIn("STOP: blocked", out.getvalue())
        with mock.patch.object(K, "cmd_verify", return_value=1) as ver:
            self.assertEqual(K.main(["verify"]), 1)
        self.assertEqual(ver.call_count, 1)


class Verify(Machine):
    def setUp(self):
        super().setUp()
        self.run = Run(rows=[])
        mark = {"version": NEW, "time": "2026-01-01T00:00:00Z", "from_version": OLD}
        S.jwrite(self.state / S.MARKER, mark)
        S.jwrite(self.state / "guard-heartbeat.json", {"version": 1, "last_start": "2026-02-01T08:59:00Z", "last_fired": "2026-02-01T09:00:00Z",
                                                       "sessions_since_fire": 0})
        p = mock.patch.object(K, "claude_version", return_value="9.8.7")
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"PATH": str(self.wb / "bin") + os.pathsep + os.environ.get("PATH", "")})
        p.start()
        self.addCleanup(p.stop)

    def rows(self, **patch):
        rows, asks, marker = K.verify_rows(self.ctx(), self.run)
        return {r["id"]: r for r in rows}, asks

    def heartbeat(self, **hb):
        S.jwrite(self.state / "guard-heartbeat.json", {"version": 1, **hb})
        return self.rows()[0]["guard-heartbeat"]

    def verify(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = K.cmd_verify(self.ctx(), self.run)
        return code, out.getvalue()

    def debug_log(self, text, when=None):
        d = self.ch / "debug"
        d.mkdir(exist_ok=True)
        f = d / "11111111-aaaa.txt"
        f.write_text(text, encoding="utf-8")
        if when:
            os.utime(f, (when, when))
        return f

    # ── every row, its PASS path and its FAIL path ──
    def test_plugin_python_option_per_plugin_pass_unset_missing_interpreter_and_not_enabled(self):
        r, _ = self.rows()
        self.assertEqual((r["plugin-python:workbench-core"]["status"], r["plugin-python:workbench-kb"]["status"]), ("PASS", "PASS"))
        self.settings({"enabledPlugins": {"workbench-core@workbench": True},
                       "pluginConfigs": {"workbench-core@workbench": {"options": {}}}})
        r, _ = self.rows()
        core, kb = r["plugin-python:workbench-core"], r["plugin-python:workbench-kb"]
        self.assertEqual(core["status"], "FAIL")
        self.assertIn("isn't set", core["detail"])
        self.assertIn("--config python=", core["cmd"])
        self.assertEqual((kb["status"], kb["detail"]), ("FAIL", "the plugin is not enabled in settings.json"))
        self.settings({"enabledPlugins": {"workbench-core@workbench": True, "workbench-kb@workbench": True},
                       "pluginConfigs": {i: {"options": {"python": I.fwd(self.tmp / "no" / "python.exe")}}
                                         for i in ("workbench-core@workbench", "workbench-kb@workbench")}})
        r, _ = self.rows()
        self.assertEqual((r["plugin-python:workbench-core"]["status"], r["plugin-python:workbench-core"]["detail"]),
                         ("FAIL", "the configured interpreter does not run"))
        (self.ch / "settings.json").write_text("{broken", encoding="utf-8")
        r, _ = self.rows()
        self.assertEqual(r["settings"]["status"], "FAIL")

    def test_hook_errors_are_counted_in_the_newest_debug_log_and_not_measured_without_one(self):
        r, _ = self.rows()
        self.assertEqual((r["hook-errors"]["status"], r["hook-errors"]["detail"]), ("INFO", "not measured: no Claude Code debug log"))
        self.debug_log("ok line\nanother line\n")
        self.assertEqual(self.rows()[0]["hook-errors"]["status"], "PASS")
        self.debug_log("a\nHook failed to run: x\nPlugin option \"python\" isn't set\nHook failed to run: y\nz\n")
        row = self.rows()[0]["hook-errors"]
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("3 ", row["detail"])
        self.assertEqual(len(row["lines"]), 3)
        self.debug_log("Hook failed to run\n", when=time.mktime((2025, 6, 1, 0, 0, 0, 0, 0, -1)))
        row = self.rows()[0]["hook-errors"]
        self.assertEqual((row["status"], row["detail"]), ("INFO", "not measured: the newest debug log is older than the update"))

    def test_guard_heartbeat_needs_a_session_started_after_the_update_in_which_the_guard_fired(self):
        row = self.rows()[0]["guard-heartbeat"]
        self.assertEqual(row["status"], "PASS")
        self.assertIn("after the update", row["detail"])
        # fired after the update but no session has started since: the fire belongs to the old plugins (the false PASS)
        row = self.heartbeat(last_start="2025-12-31T08:00:00Z", last_fired="2026-02-01T09:00:00Z")
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("no Claude Code session has started since the update", row["detail"])
        self.assertEqual(self.heartbeat(last_fired="2026-02-01T09:00:00Z")["status"], "FAIL", "no session start recorded at all")
        # a session started after the update but the guard did not fire in it
        row = self.heartbeat(last_start="2026-02-02T08:00:00Z", last_fired="2026-02-01T09:00:00Z")
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("before this session started", row["detail"])
        self.assertEqual(self.heartbeat(last_start="2026-02-02T08:00:00Z", last_fired="2026-02-02T08:00:00Z")["status"], "PASS",
                         "fired at or after the start")
        (self.state / "guard-heartbeat.json").unlink()
        self.assertEqual(self.rows()[0]["guard-heartbeat"]["status"], "FAIL")
        (self.state / S.MARKER).unlink()                                    # no marker: the doctor's rule (three silent sessions)
        self.assertEqual(self.heartbeat(last_fired="2026-10-01T00:00:00Z", sessions_since_fire=3)["status"], "FAIL")
        self.assertEqual(self.heartbeat(last_fired="2026-10-01T00:00:00Z", sessions_since_fire=1)["status"], "PASS")

    @unittest.skipUnless(S.WIN, "the Path row is Windows only")
    def test_path_pass_in_registry_only_warns_to_restart_and_missing_everywhere_fails(self):
        self.assertEqual(self.rows()[0]["path"]["status"], "PASS")
        plain = {"PATH": os.environ["PATH"].split(os.pathsep, 1)[1]}
        with mock.patch.dict(os.environ, plain):
            row = self.rows()[0]["path"]
            self.assertEqual(row["status"], "FAIL")
            S.jwrite(self.tmp / "reg.json", {"HKCU\\Environment": {"Path": [r"C:\\Tools;" + str(self.wb / "bin"), 2]}})
            row = self.rows()[0]["path"]
            self.assertEqual(row["status"], "WARN")
            self.assertIn("fresh terminal", row["detail"])
            self.assertFalse(row["kit"], "not a kit defect: the window predates the change")

    def test_doctor_rows_are_summarised_and_only_real_problems_get_their_own_row(self):
        self.run.rows = [{"check": "capability report (quick)", "status": "OK", "detail": "refreshed"},
                         {"check": "TLS + network", "status": "WARN", "detail": "blocked: pypi"},
                         {"check": "knowledge index", "status": "FAIL", "detail": "no index"},
                         {"check": "backup", "status": "WARN", "detail": "never backed up"},
                         {"check": "guard heartbeat", "status": "FAIL", "detail": "own row instead"},
                         {"check": "knowledge: hybrid", "status": "WARN", "detail": "D10 the model host is blocked"}]
        S.jwrite(self.state / "knowledge-verify.json", {"steps": [{"id": "D10", "status": "WARN", "ask_it": "Please allow host-x."}]})
        r, asks = self.rows()
        self.assertEqual(r["doctor"]["status"], "FAIL")
        self.assertIn("1 need IT", r["doctor"]["detail"])
        self.assertEqual({k for k in r if k.startswith("doctor:")}, {"doctor:TLS + network", "doctor:knowledge index", "doctor:backup"})
        self.assertEqual([a["ask"] for a in asks], ["Please allow host-x."])
        self.assertEqual((r["doctor:TLS + network"]["status"], r["doctor:TLS + network"]["kit"]), ("NEEDS-IT", False),
                         "a blocked host is IT's: NEEDS-IT, never a kit WARN")
        self.assertFalse(r["doctor:backup"]["kit"], "advice to the user is never a kit defect")
        self.assertTrue(r["doctor:knowledge index"]["kit"])
        self.run.rows = []
        r, _ = self.rows()
        self.assertEqual(r["doctor"]["status"], "PASS")

    def test_a_blocked_host_is_needs_it_only_and_the_users_own_mcp_servers_are_not_a_kit_defect_and_not_named(self):
        self.run.rows = [{"check": "TLS + network", "status": "WARN", "detail": "blocked: pypi, model-host; TLS fails: python"},
                         {"check": "MCP servers", "status": "WARN", "detail": "DOWN: zeta-intranet, other-private (run mcp_healer.py check)"}]
        S.jwrite(self.state / "knowledge-verify.json", {"steps": [{"id": "D10", "status": "WARN", "ask_it": "Please allow model-host."}]})
        code, text = self.verify()
        box = text.split("FOR THE KIT AUTHOR")[1]
        self.assertNotIn("TLS + network", box)
        self.assertNotIn("MCP servers", box)
        self.assertRegex(text, r"doctor: TLS \+ network\s+NEEDS-IT")
        self.assertNotRegex(text, r"doctor: TLS \+ network\s+WARN")
        self.assertIn("none: every check passed, or needs IT.", box)
        saved = (self.state / K.REPORT).read_text(encoding="utf-8")
        self.assertNotIn("zeta-intranet", saved)
        self.assertNotIn("other-private", saved)
        self.assertIn("MCP servers", saved)
        self.assertIn("zeta-intranet", text, "the user's own screen still names them")

    def test_a_doctor_that_prints_nothing_is_a_failure_row(self):
        class Silent(Run):
            def __call__(self, ctx, script, *args, timeout=0):
                return (1, "", "boom\n") if args[:1] == ("doctor",) else super().__call__(ctx, script, *args, timeout=timeout)
        self.run = Silent()
        row = self.rows()[0]["doctor"]
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("no result (exit 1)", row["detail"])

    def test_skill_listing_row_warns_from_85_percent_and_its_public_text_has_no_names(self):
        self.assertEqual(self.rows()[0]["skill-listing"]["status"], "PASS")
        for i in range(14):
            d = self.ch / "skills" / f"fakeskill{i:02d}"
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: fakeskill{i:02d}\ndescription: {'d' * 1500}\n---\n", encoding="utf-8")
        row = self.rows()[0]["skill-listing"]
        self.assertEqual(row["status"], "WARN")
        self.assertIn("fakeskill", row["detail"])
        self.assertNotIn("fakeskill", row["public"])
        self.assertIn("setup.py skills", row["public"])
        self.assertNotIn("fakeskill", " ".join(row["lines"]), "the box lines come from the public text")
        code, text = self.verify()
        self.assertIn("fakeskill", text.split("FOR THE KIT AUTHOR")[0], "the user's own screen names the top contributors")
        self.assertNotIn("fakeskill", text.split("FOR THE KIT AUTHOR")[1])
        self.assertNotIn("fakeskill", (self.state / K.REPORT).read_text(encoding="utf-8"), "skill names never reach the saved report")

    def test_issues_since_the_update_are_counted_and_older_ones_are_not(self):
        self.assertEqual(self.rows()[0]["issues-log"]["status"], "PASS")
        old = {"time": "2025-12-01T07:00:00Z", "tool": "Bash", "session": "s", "error": ["before the update"]}
        new = [{"time": f"2026-02-01T09:0{i}:00Z", "tool": "Bash", "session": "s", "error": [f"failure {i}", "second line"]} for i in range(4)]
        (self.state / "issues.jsonl").write_text("\n".join(json.dumps(x) for x in [old, *new]) + "\nnot json\n", encoding="utf-8")
        row = self.rows()[0]["issues-log"]
        self.assertEqual(row["status"], "WARN")
        self.assertIn("4 failed tool call", row["detail"])
        self.assertEqual(row["lines"], ["Bash: failure 1", "Bash: failure 2", "Bash: failure 3"], "the newest three, first line each")

    # ── the guard activity row ──
    @staticmethod
    def loc(hours):
        """A guard-log timestamp: local time, no zone, `hours` after the marker (2026-01-01T00:00:00Z)."""
        t = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(hours=hours)
        return t.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")

    def guard_log(self, where=None, old=()):
        """A fabricated guards.log: lines before the marker, lines after it (with and without the newer `level` field), lines that are
        not decisions, and private text in the commands, the folder names and the reasons."""
        L = self.loc
        pre = "sid=s1 tool=Bash cwd=C:/work"
        guards = REPO / "plugins" / "workbench-core" / "scripts" / "guards"            # the kit under test carries the real guard source
        shutil.copytree(guards, self.kit / "plugins" / "workbench-core" / "scripts" / "guards", ignore=shutil.ignore_patterns("tests", "__pycache__"),
                        dirs_exist_ok=True)
        lines = [f"{L(-1)} {pre} BLOCK [prod-build] example-private-command | the reason"] * 5
        lines += [f"{L(1)} {pre} BLOCK [push-default-branch] example-private-command | reason one",
                  f"{L(1)} sid=s2 tool=Bash cwd=C:/work/my example project level=standard BLOCK [push-default-branch] example-private-command",
                  f"{L(2)} {pre} level=strict BLOCK [push-default-branch] example-private-command",
                  f"{L(2)} {pre} ASK [installer-run] example-private-command | reason",
                  f"{L(2)} {pre} level=standard ASK [installer-run] (relaxed from deny at the standard level) example-private-command",
                  f"{L(3)} {pre} level=strict BLOCK [installer-run] example-private-command",
                  f"{L(3)} {pre} BLOCK [secret-path] echo BLOCK [fake-id] ~/example-person/example_key | reason",
                  f"{L(3)} {pre} BLOCK [secret-path] example-private-command",
                  f"{L(4)} {pre} ASK [backdate] x", f"{L(4)} {pre} BLOCK [browser-cli] x", f"{L(4)} {pre} ASK [msys-path] x",
                  f"{L(4)} {pre} BLOCK [nest-cap] x", f"{L(4)} {pre} ASK [tls-verify-off] x",
                  # id-shaped text that is not a rule id: an ERROR line quoting one, a PASS line in a folder that looks like a deny, the
                  # real decision after such a folder name, and ids the guard cannot emit
                  f"{L(4)} {pre} ERROR rule crashed on ASK [{FAKE_DOMAIN}-4471-secret] example-private-command",
                  f"{L(4)} sid=s9 tool=Bash cwd=C:/work/Project BLOCK [Quarterly] AGH plan level=standard PASS [relaxed-rule] example-private-command",
                  f"{L(4)} sid=s9 tool=Bash cwd=C:/work/Project BLOCK [Quarterly] AGH plan level=standard BLOCK [nest-cap] example-private-command",
                  f"{L(4)} {pre} BLOCK [mystery-rule] x", f"{L(4)} {pre} level=strict ASK [Another-Mystery] x",
                  f"{L(4)} {pre} level=standard PASS [relaxed-rule] (relaxed from ask at the standard level) example-private-command",
                  f"{L(4)} {pre} ERROR rule crashed: example-private-command",
                  "not a log line at all, example-private-command", ""]
        d = Path(where) if where else self.wb / "logs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "guards.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return d

    BUSIEST = ("10 deny, 6 ask since the update; busiest rules: installer-run (1 deny, 2 ask); push-default-branch (3 deny); "
               "nest-cap (2 deny); other (1 deny, 1 ask); secret-path (2 deny)")

    def test_guard_activity_counts_deny_and_ask_per_rule_since_the_update_and_shows_only_the_five_busiest_rule_ids(self):
        self.guard_log()
        row = self.rows()[0]["guard-activity"]
        self.assertEqual((row["status"], row["detail"]), ("PASS", self.BUSIEST), "5 old lines, PASS and ERROR lines and noise not counted")
        self.assertEqual(row["public"], row["detail"])
        self.assertFalse(row["kit"], "never a kit defect")
        for gone in ("msys-path", "tls-verify-off", "backdate", "browser-cli", "prod-build", "fake-id", "relaxed-rule", "Quarterly", "AGH",
                     "mystery", "4471", FAKE_DOMAIN):
            self.assertNotIn(gone, row["detail"])

    def test_guard_activity_reads_the_rotated_log_a_new_log_dir_and_every_line_without_a_marker(self):
        d = self.guard_log()
        (d / "guards.log").rename(d / "guards.log.1")                                     # the engine keeps one rotated file
        self.assertEqual(self.rows()[0]["guard-activity"]["detail"], self.BUSIEST)
        elsewhere = self.tmp / "elsewhere"
        self.guard_log(elsewhere)
        with mock.patch.dict(os.environ, {"GUARDS_LOG_DIR": str(elsewhere)}):               # the engine's own override
            (d / "guards.log.1").unlink()
            self.assertEqual(self.rows()[0]["guard-activity"]["detail"], self.BUSIEST)
        (self.state / S.MARKER).unlink()                                                  # no marker: everything in the log
        with mock.patch.dict(os.environ, {"GUARDS_LOG_DIR": str(elsewhere)}):
            row = self.rows()[0]["guard-activity"]
        self.assertTrue(row["detail"].startswith("15 deny, 6 ask in the guard log; busiest rules: prod-build (5 deny); "), row["detail"])

    def test_a_decision_is_read_only_when_its_id_is_one_the_guard_can_emit_and_nothing_in_a_folder_name_or_an_error_line_shifts_it(self):
        ids = K.guard_rule_ids(REPO)
        for rest, want in [
                ("C:/work ERROR rule crashed on ASK [%s-4471-secret] example-private-command" % FAKE_DOMAIN, None),       # an ERROR line quoting an id
                ("C:/work/Project BLOCK [Quarterly] AGH plan level=standard PASS [relaxed-rule] x", None),                # a folder that looks like a deny
                ("C:/work/Project BLOCK [Quarterly] AGH plan level=standard BLOCK [nest-cap] x", ("BLOCK", "nest-cap")),  # ... before the real one
                ("C:/work/Project ASK [Quarterly] plan level=strict BLOCK [retired-rule] x", ("BLOCK", "other")),
                ("C:/work level=standard ASK [push-default-branch] BLOCK [secret-path] echo", ("ASK", "push-default-branch")),
                (" BLOCK [secret-path] x", ("BLOCK", "secret-path")),                                                         # an empty folder name
                ("C:/work level=standard BLOCK [Quarterly] x", ("BLOCK", "other")),
                ("C:/work level=standard ASK [%s-4471-secret] x" % FAKE_DOMAIN, ("ASK", "other")),
                ("C:/work no decision here", None), ("C:/work READFLOOD ASK [backdate]", None)]:
            self.assertEqual(K.guard_decision(rest, ids), want, rest)
        self.assertEqual(K.guard_decision(" BLOCK [secret-path] x", frozenset()), ("BLOCK", "other"), "no guard source: nothing is a known id")

    @staticmethod
    def ids_the_guard_tests_expect():
        """Every rule id test_guards.py asserts, read from its syntax tree: the guard argument of blocked(cmd, id, ..), the id of
        assertEqual(gid(out), id, ..) and the ("ask" | "deny", id) pairs. Only constants in those positions, never a loose string."""
        tree = ast.parse((REPO / "plugins" / "workbench-core" / "scripts" / "guards" / "tests" / "test_guards.py").read_text(encoding="utf-8"))
        const = lambda n: n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None       # noqa: E731
        found = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "blocked" and len(n.args) > 1:
                found.add(const(n.args[1]))
            elif isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "assertEqual" and len(n.args) > 1 \
                    and isinstance(n.args[0], ast.Call) and getattr(n.args[0].func, "id", "") == "gid":
                found.add(const(n.args[1]))
            elif isinstance(n, ast.Tuple) and len(n.elts) == 2 and const(n.elts[0]) in ("ask", "deny"):
                found.add(const(n.elts[1]))
        return found - {None}

    def test_the_rule_id_set_is_read_from_the_engine_and_rulepacks_and_holds_every_id_the_guard_tests_expect(self):
        ids = K.guard_rule_ids(REPO)
        expected = self.ids_the_guard_tests_expect()
        self.assertGreaterEqual(len(expected), 25, "the scan of the guard tests found the ids they assert")
        self.assertEqual(sorted(expected - ids), [], "an id the guard tests expect is missing from the set read from the source")
        for real in ("push-default-branch", "installer-run", "secret-path", "nest-cap", "backdate", "env-write", "browser-cli",
                     "guard-config-write", "tokensave-rewrite", "encoded-command", "no-verify", "force-push-main"):
            self.assertIn(real, ids)
        for fake in ("other", "Quarterly", "mystery-rule", "retired-rule", "relaxed-rule", "cache", "plugins"):
            self.assertNotIn(fake, ids)
        self.assertEqual(K.guard_rule_ids(self.tmp / "no-such-kit"), frozenset())
        g = self.tmp / "kit" / "plugins" / "workbench-core" / "scripts" / "guards"            # a test file next to the source is never read
        (g / "tests").mkdir(parents=True)
        (g / "engine.py").write_text('def f():\n    block("reason", "only-in-engine", "d")\n    relaxed("onlyrelaxed")\n    E.ask("reason", "singleword")\n', encoding="utf-8")
        (g / "tests" / "test_x.py").write_text('def t():\n    block("reason", "only-in-tests", "d")\n    return "also-in-tests"\n', encoding="utf-8")
        self.assertEqual(K.guard_rule_ids(self.tmp / "kit"), frozenset({"only-in-engine", "onlyrelaxed", "singleword"}))

    def test_the_real_engines_log_lines_are_read_back_as_the_decision_it_made(self):
        """The format check: the actual guard (pretooluse.py of this tree, in a scratch home) writes the lines, the row reads them."""
        home, logs = self.tmp / "eng-home", self.tmp / "eng-logs"
        (home / ".claude").mkdir(parents=True)
        env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"), "GUARDS_LOG_DIR": str(logs)}
        for k in [k for k in env if k.startswith(("WORKBENCH_", "WB_"))]:
            del env[k]
        want = []
        for cmd, expect in [("git push --force origin main", ("BLOCK", "force-push-main")),
                            ("py -3 kit_update.py --repo example-org/example-kit", ("ASK", "installer-run")),
                            ("git commit --no-verify -m x", ("ASK", "no-verify"))]:           # a soft rule: asks instead of refusing at the standard level
            ev = {"tool_name": "Bash", "tool_input": {"command": cmd}, "session_id": "s1", "cwd": str(self.tmp)}
            r = subprocess.run([sys.executable, "-B", "-I", str(REPO / "plugins" / "workbench-core" / "scripts" / "guards" / "pretooluse.py")],
                               input=json.dumps(ev).encode(), capture_output=True, env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            want.append(expect)
        ids = K.guard_rule_ids(REPO)
        got = []
        for ln in (logs / "guards.log").read_text(encoding="utf-8").splitlines():
            m = K.GUARD_PREFIX.match(ln)
            self.assertIsNotNone(m, ln)
            self.assertIn(" level=", ln, "the engine writes its level field")
            got.append(K.guard_decision(m.group(2), ids))
        self.assertEqual([g for g in got if g], want)

    def test_guard_activity_is_information_when_there_is_no_log_and_never_fails_the_verify(self):
        row = self.rows()[0]["guard-activity"]
        self.assertEqual((row["status"], row["detail"]), ("INFO", "not measured: no guard log yet"))
        self.assertEqual(self.verify()[0], 0)
        S.jwrite(self.state / S.MARKER, {"version": NEW, "time": "2026-01-01T00:00:00Z", "from_version": OLD})      # the verify cleared it
        self.guard_log()
        code, text = self.verify()
        self.assertEqual(code, 0, "many denies are the guard working: still a clean verify")
        self.assertRegex(text, r"guard activity\s+PASS\s+10 deny, 6 ask since the update")

    def test_nothing_from_the_guard_log_but_counts_and_rule_ids_reaches_the_screen_or_the_saved_report(self):
        self.guard_log()
        code, text = self.verify()
        saved = (self.state / K.REPORT).read_text(encoding="utf-8")
        for out in (text, saved):
            self.assertIn("installer-run (1 deny, 2 ask)", out.replace("\n" + " " * 41, " "))
            for private in ("example-private-command", "my example project", "example-person", "example_key", "the reason", "reason one",
                            "Quarterly", "AGH", "4471", "mystery", "Mystery", FAKE_DOMAIN, "<company>-"):
                self.assertNotIn(private, out)

    def test_it_asks_are_one_deduplicated_needs_it_row_and_never_a_kit_defect(self):
        S.jwrite(self.state / "setup-state.json", {"ask_it": [{"item": "a", "text": "Please allow  host-x."}]})
        S.jwrite(self.state / "knowledge-verify.json", {"steps": [{"id": "D10", "status": "WARN", "ask_it": "please allow host-x."},
                                                                   {"id": "D13", "status": "FAIL", "ask_it": "Please allow host-x."}]})
        r, asks = self.rows()
        self.assertEqual(len(asks), 1, "one blocked host, one ask, whoever raised it")
        self.assertEqual((r["it-asks"]["status"], r["it-asks"]["kit"]), ("NEEDS-IT", False))
        code, text = self.verify()
        self.assertEqual(text.count("Please allow  host-x.".replace("  ", " ")), 1)
        box = text.split("FOR THE KIT AUTHOR")[1]
        self.assertNotIn("host-x", box)
        self.assertEqual(code, 0, "an IT ask alone is not a failure")

    def test_the_exit_code_is_2_for_a_fail_1_for_a_warn_and_0_otherwise(self):
        self.assertEqual(self.verify()[0], 0)
        S.jwrite(self.state / S.MARKER, {"version": NEW, "time": "2026-01-01T00:00:00Z"})
        (self.state / "issues.jsonl").write_text(json.dumps({"time": "2026-02-01T09:00:00Z", "tool": "Bash", "error": ["x"]}) + "\n")
        self.assertEqual(self.verify()[0], 1)
        S.jwrite(self.state / S.MARKER, {"version": NEW, "time": "2026-01-01T00:00:00Z"})
        S.jwrite(self.state / "guard-heartbeat.json", {"last_fired": "2025-12-01T07:00:00Z"})
        self.assertEqual(self.verify()[0], 2)

    # ── the marker, the saved file and the author box ──
    def test_the_verify_clears_the_marker_and_saves_the_report(self):
        self.assertIsNotNone(self.marker())
        code, text = self.verify()
        self.assertIsNone(self.marker(), "the verify ran: the marker is gone")
        saved = (self.state / K.REPORT).read_text(encoding="utf-8")
        self.assertIn("FOR THE KIT AUTHOR", saved)
        self.assertIn("Saved:", text)
        self.assertIn("kit_update.py record guard-live", text)

    def test_the_marker_is_cleared_even_when_a_row_fails(self):
        # a session started after the update but the guard did not fire in it: a real failure, and the verify has run
        S.jwrite(self.state / "guard-heartbeat.json", {"last_start": "2026-02-02T08:00:00Z", "last_fired": "2026-02-01T09:00:00Z"})
        self.assertEqual(self.verify()[0], 2)
        self.assertIsNone(self.marker())

    def test_a_verify_before_the_restart_reports_but_keeps_the_marker_until_a_session_has_started(self):
        for hb in ({"last_fired": "2025-12-01T07:00:00Z"},                                      # no session start recorded
                   {"last_start": "2025-12-31T08:00:00Z", "last_fired": "2026-02-01T09:00:00Z"}):   # the last one is from before the update
            S.jwrite(self.state / "guard-heartbeat.json", hb)
            code, text = self.verify()
            self.assertEqual(code, 2)
            self.assertIsNotNone(self.marker(), "no session has started since the update: the next one must still run the verify")
            self.assertIn("marker stays", text)
            self.assertIn("FOR THE KIT AUTHOR", (self.state / K.REPORT).read_text(encoding="utf-8"), "the report is still written")
        S.jwrite(self.state / "guard-heartbeat.json", {"last_start": "2026-02-02T08:00:00Z", "last_fired": "2026-02-02T08:00:01Z"})
        code, text = self.verify()                                                                # after the restart
        self.assertEqual(code, 0, text)
        self.assertIsNone(self.marker())
        self.assertNotIn("marker stays", text)

    def test_the_author_box_lists_only_kit_defects_with_id_command_three_lines_and_the_versions(self):
        self.settings({"enabledPlugins": {"workbench-core@workbench": True, "workbench-kb@workbench": True}, "pluginConfigs": {}})
        self.debug_log("\n".join(f"Hook failed to run: line {i}" for i in range(6)))
        self.run.rows = [{"check": "backup", "status": "WARN", "detail": "never backed up"},
                         {"check": "knowledge index", "status": "WARN", "detail": "no index yet"}]
        S.jwrite(self.state / "setup-state.json", {"ask_it": [{"item": "a", "text": "Please allow host-x."}]})
        code, text = self.verify()
        box = text.split("FOR THE KIT AUTHOR")[1]
        self.assertIn(f"kit v{OLD} · Claude Code 9.8.7 ·", box)
        self.assertRegex(box, r"\[plugin-python:workbench-core\] plugin python: workbench-core · FAIL\n  command: claude plugin install")
        self.assertIn("[hook-errors] hook errors · FAIL", box)
        self.assertEqual(box.count("> Hook failed to run"), 3, "the first three lines, no more")
        self.assertIn("[doctor:knowledge index]", box)
        self.assertNotIn("backup", box)
        self.assertNotIn("host-x", box)
        self.assertNotIn("[it-asks]", box)
        self.assertRegex(text, r"hook errors\s+FAIL")

    def test_the_users_own_kb_index_and_capture_rows_stay_out_of_the_author_box(self):
        self.settings({"enabledPlugins": {"workbench-core@workbench": True, "workbench-kb@workbench": True},
                       "pluginConfigs": {}})
        self.run.rows = [{"check": "knowledge: kb-index", "status": "WARN", "detail": "D5 built (fts5); kb_health WARN: dead-links"},
                         {"check": "knowledge: capture", "status": "WARN", "detail": "D17 the InfoSec acknowledgement is not recorded"},
                         {"check": "knowledge: kb-machinery", "status": "FAIL", "detail": "D3 1 failure(s)/error(s): test_x"}]
        code, text = self.verify()        # the row names are the doctor's own: setup.py doctor --json prefixes knowledge rows
        box = text.split("FOR THE KIT AUTHOR")[1]
        self.assertNotIn("kb-index", box)
        self.assertNotIn("capture", box)
        self.assertIn("[doctor:knowledge: kb-machinery]", box, "a kit defect still reaches the author")
        self.assertRegex(text, r"doctor: knowledge: kb-index\s+WARN", "the user still sees their own row")
        self.run.rows = [{"check": "knowledge: kb-index", "status": "FAIL", "detail": "D5 kb_index.py build exit 1"}]
        code, text = self.verify()
        self.assertIn("[doctor:knowledge: kb-index]", text.split("FOR THE KIT AUTHOR")[1], "the kit's indexer crashing is the kit's")

    def test_every_knowledge_row_the_filters_name_is_a_real_doctor_row(self):
        import knowledge_verify as KV
        real = {"knowledge: " + name for _id, name, _fn in KV.STEPS}
        named = {n for n in K.NOT_KIT | K.IT_ROWS | K.OWN_ROWS if n.startswith("knowledge")}
        self.assertTrue(named, "the filters name knowledge rows")
        self.assertEqual(named - real, set(), "a filter names a row the doctor never prints")

    def test_an_entry_in_the_box_never_has_more_than_three_lines_and_a_doctor_row_without_an_ask_is_listed(self):
        rows = [K.R("x-1", "check one", "FAIL", "detail", "cmd one", [f"line {i}" for i in range(8)]),
                K.R("x-2", "check two", "WARN", "one; two; three; four; five")]
        text = K.render(rows, [], {"claude": "1.2.3", "os": "TestOS 1"})
        box = text.split("FOR THE KIT AUTHOR")[1]
        self.assertEqual([x for x in box.splitlines() if x.startswith("  > ")],
                         ["  > line 0", "  > line 1", "  > line 2", "  > one", "  > two", "  > three"])
        self.assertIn("[x-1] check one · FAIL\n  command: cmd one", box)
        self.assertIn("  command: py -3 <KIT>/bootstrap/kit_update.py verify", box, "a row without a command still names how to re-run")

    def test_nothing_to_report_says_so(self):
        self.assertIn("none: every check passed, or needs IT.", self.verify()[1])

    def test_the_author_box_and_the_saved_file_carry_no_names_hosts_addresses_or_credentials(self):
        lines = [f"error at C:\\Users\\{FAKE_USER}\\AppData\\x on {FAKE_HOST} in {FAKE_DOMAIN}\\{FAKE_USER}",  # scrub-ok: fictional user
                 f"GET https://intranet.example.test/api and https://github.com/x failed, token {TOKEN}, mail {FAKE_USER}@corp.example.test",
                 f"\\\\{FAKE_HOST}.corp.example.test\\share {IP} version 9.9.9 settings.json"]
        self.debug_log("\n".join("Hook failed to run: " + x for x in lines))
        code, text = self.verify()
        saved = (self.state / K.REPORT).read_text(encoding="utf-8")
        box = text.split("FOR THE KIT AUTHOR")[1]
        for blob in (box, saved):
            for secret in (FAKE_USER, FAKE_HOST, FAKE_DOMAIN, "intranet.example.test", "corp.example.test", TOKEN, IP):
                self.assertNotIn(secret, blob, secret)
            self.assertIn("<user>", blob)
            self.assertIn("<host>", blob)
            self.assertIn("[REDACTED]", blob)
            self.assertIn("github.com", blob, "a host in the kit's own package table stays")
            self.assertIn("settings.json", blob)

    def test_scrub_replaces_the_domain_the_host_and_the_user_in_that_order_and_keeps_files_versions_and_package_hosts(self):
        ids = K.identity()
        self.assertEqual({FAKE_USER} <= ids["user"], True)
        out = K.scrub(f"{FAKE_DOMAIN}\\{FAKE_USER}@{FAKE_HOST} {FAKE_HOST.lower()}-2 kit_update.py v0.3.2 pypi.org files.pythonhosted.org "
                      f"cdn.winget.microsoft.com setup.json 3.13.15")
        self.assertEqual(out, "<domain>\\<user>@<host> <host>-2 kit_update.py v0.3.2 pypi.org files.pythonhosted.org "
                              "cdn.winget.microsoft.com setup.json 3.13.15")
        self.assertEqual(K.scrub("see https://corp.internal.example.test/path"), "see https://<host>/path")
        self.assertEqual(K.scrub("a@b.example.test"), "<email>")
        self.assertEqual(K.scrub("C:/x/OneDrive - Example Holdings Ltd/Workbench/kb"), "C:/x/OneDrive - <company>/Workbench/kb")
        self.assertEqual(K.scrub("sharepoint - Example Team\\docs"), "sharepoint - <company>\\docs")
        self.assertEqual(K.scrub("OneDrive is fine and OneDrive-less too"), "OneDrive is fine and OneDrive-less too")

    def test_a_redaction_that_cannot_load_withholds_the_text(self):
        (self.kit / "plugins" / "workbench-core" / "scripts" / "secretscan.py").unlink()
        for m in ("secretscan", "_wb"):
            sys.modules.pop(m, None)
        with mock.patch.object(sys, "path", [p for p in sys.path if "scripts" not in p]):
            out = K.redact(f"token {TOKEN}")
        self.assertIn("withheld", out)
        self.assertNotIn(TOKEN, out)

    def test_record_adds_the_live_guard_row_scrubbed_and_a_failure_gets_a_box_entry(self):
        self.verify()
        K.cmd_record(self.ctx(), "guard-live", "PASS", f"blocked by push-default-branch on {FAKE_HOST}")
        K.cmd_record(self.ctx(), "guard-live", "FAIL", f"not blocked: {TOKEN}", "git push --force origin main in a scratch repo")
        saved = (self.state / K.REPORT).read_text(encoding="utf-8")
        self.assertEqual(saved.count("## Added after the script"), 1)
        self.assertIn("[guard-live] PASS: blocked by push-default-branch on <host>", saved)
        self.assertIn("[guard-live] FAIL: not blocked: [REDACTED]", saved)
        self.assertIn("command: git push --force origin main in a scratch repo", saved)
        self.assertNotIn(FAKE_HOST, saved)
        self.assertNotIn(TOKEN, saved)

    # ── scrub: the saved report, identity, proxies, cutting ──
    def test_it_asks_in_the_saved_report_are_scrubbed_and_on_the_screen_they_are_not(self):
        ask = f"Please allow https://intranet.example.test/pkg for {FAKE_HOST} (user {FAKE_USER}), token {TOKEN}."
        S.jwrite(self.state / "setup-state.json", {"ask_it": [{"item": "a", "text": ask}]})
        code, text = self.verify()
        saved = (self.state / K.REPORT).read_text(encoding="utf-8")
        self.assertIn(FAKE_HOST, text.split("FOR THE KIT AUTHOR")[0], "the user's own screen shows the ask as it is")
        self.assertIn("1. Please allow https://<host>/pkg for <host> (user <user>), token [REDACTED].", saved)
        for secret in (FAKE_HOST, FAKE_USER, "intranet.example.test", TOKEN):
            self.assertNotIn(secret, saved, secret)

    def test_the_identity_holds_the_dns_domain_and_its_labels_the_onedrive_tenant_and_a_profile_folder_that_differs_from_the_user_name(self):
        prof = self.tmp / "jdoe.ZETADOM"
        (prof / "OneDrive - Zeta Holdings Ltd").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"USERDNSDOMAIN": "emea.zetaworks.test", "USERPROFILE": str(prof)}), \
                mock.patch.object(Path, "home", return_value=prof):
            ids = K.identity()
            users = "C:" + chr(92) + "Users" + chr(92)
            out = K.scrub(users + "jdoe.ZETADOM" + chr(92) + "OneDrive - Zeta Holdings Ltd" + chr(92) + "Workbench" + chr(92) + "ZetaSales-kb"
                          + chr(92) + "n.txt via zetaworks-gw.emea.zetaworks.test and HoldingsFiles")
        self.assertTrue({"jdoe.ZETADOM", FAKE_USER} <= ids["user"])
        self.assertIn("emea.zetaworks.test", ids["domain"])
        self.assertTrue({"emea", "zetaworks"} <= {x.lower() for x in ids["company"]})
        self.assertTrue({"Zeta Holdings Ltd", "Zeta", "Holdings"} <= ids["company"])
        self.assertNotIn("Ltd", ids["company"], "a word every company has says nothing")
        for secret in ("jdoe", "ZETADOM", "Zeta", "Holdings", "zetaworks", "emea"):
            self.assertNotIn(secret.lower(), out.lower(), secret)
        self.assertIn("<user>", out)
        self.assertIn("<company>Sales-kb", out, "a path component that holds the company name is scrubbed inside the component")
        self.assertTrue(out.endswith("<company>Files"))

    def test_a_proxy_named_by_one_label_and_a_port_is_scrubbed_and_code_locations_are_not(self):
        self.assertEqual(K.scrub("via zproxy-acmeg:8080 and proxy01:3128, not localhost:8080, setup.py:123, line:45, exit:3, D10:2"),
                         "via <host>:8080 and <host>:3128, not localhost:8080, setup.py:123, line:45, exit:3, D10:2")

    def test_text_is_scrubbed_before_it_is_cut_so_no_first_letters_of_a_name_survive_the_cut(self):
        with mock.patch.dict(os.environ, {"USERDNSDOMAIN": "corp.zetaworks.test"}):
            rows = [K.R("x-1", "check one", "FAIL", "a" * 104 + " zetaworks rest of the row", "cmd", ["y" * 293 + " zetaworks"])]
            box = K.render(rows, [], {"claude": "1.2.3", "os": "TestOS 1"}).split("FOR THE KIT AUTHOR")[1]
            filed = K.render(rows, [], {"claude": "1.2.3", "os": "TestOS 1"}, public=True)
        for blob in (box, filed):
            self.assertNotIn("zeta", blob.lower())
        self.assertIn("<company>", filed.split("FOR THE KIT AUTHOR")[0])
        self.assertIn("y" * 293, box)

    def test_a_long_detail_wraps_on_the_screen_instead_of_being_cut(self):
        rows = [K.R("x-1", "check one", "WARN", " ".join(f"word{i:03d}" for i in range(40)))]
        text = K.render(rows, [], {"claude": None, "os": "TestOS 1"})
        self.assertIn("word039", text)
        self.assertIn("Claude Code not found", text)

    # ── the verify as a resumable stage ──
    def test_an_old_job_nobody_collected_is_not_trusted_the_check_runs_again(self):
        d = self.state / "kit-update"
        d.mkdir(parents=True)
        S.jwrite(d / "doctor-verify.json", {"started": "2020-01-01T00:00:00Z", "pid": 0})
        S.jwrite(d / "doctor-verify.out.json", {"rc": 2, "out": json.dumps({"rows": [{"check": "stale", "status": "FAIL", "detail": "old"}]}), "err": ""})
        code, text = self.verify()
        self.assertEqual(code, 0, text)
        self.assertNotIn("doctor: stale", text)
        self.assertEqual(self.spawned, ["doctor-verify.out.json"], "a fresh job ran")

    def test_a_doctor_job_still_running_makes_the_verify_exit_6_keep_the_marker_and_the_same_command_finishes_it(self):
        self.hold = True
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = K.cmd_verify(self.ctx(), self.run, budget=0)
        self.assertEqual(code, 6)
        self.assertIn("still running", out.getvalue())
        self.assertIsNotNone(self.marker(), "the verify has not run yet: the marker stays")
        self.assertFalse((self.state / K.REPORT).exists())
        self.hold = False
        K.doctor_job_main(self.ctx(), self.state / "kit-update" / "doctor-verify.out.json", self.run)
        code, text = self.verify()
        self.assertEqual(code, 0, text)
        self.assertIsNone(self.marker())
        self.assertEqual(self.spawned, ["doctor-verify.out.json"], "one job for both calls")


class ClaudeCli(Machine):
    """claude_version through a real (fake) claude program on the fake bin path: no mock of claude_version anywhere."""
    def setUp(self):
        super().setUp()
        self.bin = self.tmp / "fakebin"
        self.bin.mkdir()
        S.jwrite(self.state / S.MARKER, {"version": NEW, "time": "2026-01-01T00:00:00Z", "from_version": OLD})
        S.jwrite(self.state / "guard-heartbeat.json", {"last_start": "2026-02-01T08:59:00Z", "last_fired": "2026-02-01T09:00:00Z"})
        p = mock.patch.dict(os.environ, {"WORKBENCH_FAKE_BIN": str(self.bin), "PATH": str(self.wb / "bin") + os.pathsep + os.environ.get("PATH", "")})
        p.start()
        self.addCleanup(p.stop)

    def claude(self, text="9.9.9 (Claude Code)", rc=0):
        if os.name == "nt":
            (self.bin / "claude.cmd").write_text(f"@echo off\r\necho {text}\r\nexit /b {rc}\r\n")
        else:
            f = self.bin / "claude"
            f.write_text(f"#!/bin/sh\necho '{text}'\nexit {rc}\n")
            f.chmod(0o755)

    def test_claude_code_version_is_read_from_the_programs_own_text_and_the_verify_finishes_and_clears_the_marker(self):
        self.claude()
        self.assertEqual(K.claude_version(self.ctx()), "9.9.9")      # the crash: probe gives text, parse_version wanted bytes
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = K.cmd_verify(self.ctx(), Run(rows=[]))
        self.assertIn("Claude Code 9.9.9", out.getvalue())
        self.assertIsNone(self.marker(), "the verify ran to its end, so a session no longer retries it")
        self.assertIn("kit v0.3.1 · Claude Code 9.9.9 ·", (self.state / K.REPORT).read_text(encoding="utf-8"))
        self.assertIn(code, (0, 1, 2))

    def test_a_claude_that_fails_or_is_missing_is_not_found_and_never_a_crash(self):
        self.claude(rc=3)
        self.assertIsNone(K.claude_version(self.ctx()))
        (self.bin / ("claude.cmd" if os.name == "nt" else "claude")).unlink()
        self.assertIsNone(K.claude_version(self.ctx()))
        self.claude(text="no version in this text")
        self.assertIsNone(K.claude_version(self.ctx()))
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            K.cmd_verify(self.ctx(), Run(rows=[]))
        self.assertIn("Claude Code not found", out.getvalue())


class Docs(unittest.TestCase):
    """What the skill and IMPORT.md promise, checked against the script."""
    def test_the_skill_says_to_run_the_same_command_again_with_an_explicit_timeout_until_it_is_done(self):
        text = (REPO / "plugins" / "workbench-core" / "skills" / "kit-update" / "SKILL.md").read_text(encoding="utf-8")
        for want in ("600000", "exit 6", "same command", "--wait 90", "verify"):
            self.assertIn(want, text)

    def test_the_docs_say_the_first_update_trusts_the_repository_you_name_and_the_hash_shows_integrity_only(self):
        flat = lambda rel: " ".join((REPO / rel).read_text(encoding="utf-8").split())       # noqa: E731
        for rel, wants in (("IMPORT.md", ("name the repository in your message", "not who published it", "empty on purpose", "release signing is deferred")),
                           ("plugins/workbench-core/skills/kit-update/SKILL.md", ("the one the user names in their message", "not who published it")),
                           ("docs/known-limits.md", ("The first update trusts the repository you name", "not who published it", "empty `repo` on purpose",
                                                     "release signing is deferred"))):
            text = flat(rel)
            for want in wants:
                self.assertIn(want, text, f"{rel}: {want}")
        shipped = json.loads((REPO / "plugins/workbench-core/skills/kit-update/release-source.json").read_text(encoding="utf-8"))
        self.assertEqual(shipped["repo"], "", "the shipped file stays empty: the first update names the repository")
        self.assertIn("stays empty on purpose", shipped["_readme"])
        self.assertIn("names the repository in the user's message", shipped["_readme"])
        self.assertNotIn("Filled in", shipped["_readme"], "nothing fills it in when a release is cut")
        self.assertIn("(empty on purpose)", flat("docs/SETUP-RUNBOOK.md"))

    def test_import_md_updating_is_findable_by_the_owners_phrase_and_matches_the_script(self):
        text = (REPO / "IMPORT.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^#{2,4} .*check the new stuff and go.*$")
        sec = text.split("## Updating", 1)[1].split("## Removing everything", 1)[0]
        for want in ("<REPO>", "kit_repo", "`python` in `<WB>\\config.json`", "digest", "checksum table", "claude-workbench-v<ver>", "VERSION",
                     "exit code 5", "kit_update.py --repo <REPO>", "--new-repo"):
            self.assertIn(want, sec, want)
        self.assertNotIn("must equal the `digest` after `sha256:` and the value in the table", sec)


if __name__ == "__main__":
    unittest.main()
