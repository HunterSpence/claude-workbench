#!/usr/bin/env python3
"""live_controls.py: prove, on THIS Windows machine and reversibly, the traps setup.py relies on (stdlib only).

  live_controls.py run [--apply] [--json] [--out DIR]

Without --apply it prints the four steps and changes nothing. --apply also needs WB_LIVE=1 in the environment.
  1 schtasks  create \\claude-workbench-test\\live-<rand> from setup.py's task XML (disabled), read it back as XML
              (exit 0, our description present), delete it, query again (must fail); the empty test folder goes too
  2 RunOnce   HKCU ...\\RunOnce value wb-live-<rand> = a command of exactly 260 characters built from the real profile
              path by setup.py; read back equal, delete, absent
  3 winget    the first of jqlang.jq, sharkdp.fd, junegunn.fzf that `winget list -e --id` reports absent (exit code):
              user-scope install, PATH re-read, --version parses, uninstall, gone from WinGet Links. Refused when WinGet
              Links is not already on the user Path (the install would change PATH).
              From an elevated session both winget calls run through a one-shot LeastPrivilege task in the test
              folder: winget refuses user-scope removals from an admin context (0x8A15007D).
  4 wsl       raw bytes of `wsl --status`, `wsl -l -v`, `wsl --version` (read-only) through setup.py's decoder and
              parser; a neutralised copy (versions -> 9.9.9, unknown distribution names -> Distro) goes to
              <out>/wsl-bytes.txt for the unit-test fixture
Every step cleans up in `finally` and checks the cleanup. Ledger: <out>/live-ledger.json. Exit 0 only when every step
passed and every cleanup was verified. <out> = --out, else WB_LIVE_OUT, else <temp>/wb-live. Exit 2 = refused.
"""
import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install as I  # noqa: E402
import setup as S  # noqa: E402

FOLDER = "claude-workbench-test"
CANDIDATES = (("jqlang.jq", "jq"), ("sharkdp.fd", "fd"), ("junegunn.fzf", "fzf"))
KNOWN_DISTROS = re.compile(r"(?i)^(ubuntu(-\d+\.\d+)?|debian|docker-desktop(-data)?)$")


def runonce_260(pyw, home, total=S.RUNONCE_MAX):
    """A setup.py resume command of exactly `total` characters: <home>/<padding>/bootstrap/setup.py."""
    fixed = len(S.runonce_command(pyw, Path(home) / "bootstrap" / "setup.py", limit=10 ** 6))
    pad, parts = total - fixed - 1, []
    while pad > 0:                       # each path segment stays well under the 255-character name limit
        n = min(pad, 120)
        n = n - 1 if pad - n == 1 else n  # never leave a 1-character remainder (it would need a 0-length name)
        parts.append("p" * n)
        pad -= n + 1
    script = Path(home).joinpath(*parts, "bootstrap", "setup.py")
    return S.runonce_command(pyw, script, limit=total)


def neutralise(text, distros):
    """Version runs -> 9.9.9 (three parts, never four), other digits -> 9, unknown distribution names -> Distro."""
    for d in distros:
        if not KNOWN_DISTROS.match(d):
            text = re.sub(rf"(?<![\w-]){re.escape(d)}(?![\w-])", "Distro", text)
    text = re.sub(r"\d+(?:[.,]\d+)+", "9.9.9", text)
    return re.sub(r"\d", "9", text)


def ps(script):
    """Exit code of a one-line read/clean-up PowerShell command (no profile, no execution-policy change)."""
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                          timeout=120).returncode


def folder_gone():
    """Delete the test folder when it is empty, then 0 if it no longer exists (Task Scheduler COM API, user level)."""
    return ps("$s=New-Object -ComObject Schedule.Service;$s.Connect();$r=$s.GetFolder('\\');"
              f"try{{$f=$r.GetFolder('{FOLDER}');if($f.GetTasks(1).Count -eq 0){{$r.DeleteFolder('{FOLDER}',0)}}}}catch{{}};"
              f"try{{$r.GetFolder('{FOLDER}')|Out-Null;exit 1}}catch{{exit 0}}") == 0


def step_schtasks(ctx, rand, out):
    st = {"step": "schtasks", "ok": False, "cleanup": "failed", "detail": {}}
    name, marker = f"\\{FOLDER}\\live-{rand}", f"claude-workbench live control {rand}"
    f = out / f"live-{rand}.xml"
    f.write_text(S.task_xml(marker, [("cmd.exe", "/c exit 0")], enabled=False), encoding="utf-16")
    created = False
    try:
        rc, _ = ctx.run(["schtasks", "/Create", "/XML", str(f), "/TN", name, "/F"], timeout=60)
        created = rc == 0
        rq, xml = ctx.run(["schtasks", "/Query", "/TN", name, "/XML"], timeout=60)
        rd, _ = ctx.run(["schtasks", "/Delete", "/TN", name, "/F"], timeout=60)
        ra, _ = ctx.run(["schtasks", "/Query", "/TN", name], timeout=60)
        st["detail"] = {"create": rc, "query_xml": rq, "description_present": marker in S.decode(xml),
                        "battery_settings": "<DisallowStartIfOnBatteries>true" in S.decode(xml), "delete": rd,
                        "query_after_delete": ra}
        st["ok"] = created and rq == 0 and st["detail"]["description_present"] and rd == 0 and ra != 0
    finally:
        if created and ctx.run(["schtasks", "/Query", "/TN", name], timeout=60)[0] == 0:
            ctx.run(["schtasks", "/Delete", "/TN", name, "/F"], timeout=60)
        gone = ctx.run(["schtasks", "/Query", "/TN", name], timeout=60)[0] != 0
        st["detail"]["test_folder_removed"] = folder_gone()
        st["cleanup"] = "verified" if gone and st["detail"]["test_folder_removed"] else "failed"
        f.unlink(missing_ok=True)
    return st


def step_runonce(ctx, rand):
    st = {"step": "runonce", "ok": False, "cleanup": "failed", "detail": {}}
    name = f"wb-live-{rand}"
    cmd = runonce_260(S.pythonw(), Path.home())
    try:
        S.reg_set(S.RUNONCE_KEY, name, cmd, 1)
        back = I.reg_get(S.RUNONCE_KEY, name)
        S.reg_delete(S.RUNONCE_KEY, name)
        st["detail"] = {"length": len(cmd), "read_back_equal": bool(back) and back[0] == cmd and back[1] == 1,
                        "absent_after_delete": I.reg_get(S.RUNONCE_KEY, name) is None}
        st["ok"] = len(cmd) == S.RUNONCE_MAX and st["detail"]["read_back_equal"] and st["detail"]["absent_after_delete"]
    finally:
        if I.reg_get(S.RUNONCE_KEY, name) is not None:
            S.reg_delete(S.RUNONCE_KEY, name)
        st["cleanup"] = "verified" if I.reg_get(S.RUNONCE_KEY, name) is None else "failed"
    return st


def elevated():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def as_user(ctx, argv, out, tag, timeout=900):
    """Exit code of argv run with the signed-in user's limited token: directly when this process is not elevated, else
    through a one-shot LeastPrivilege task in the test folder. winget refuses to remove a user-scope package from an
    elevated process (0x8A15007D), and setup itself runs unelevated, so this is the path it takes."""
    if not elevated():
        return ctx.run(argv, timeout=timeout)[0]
    rc_file, cmd, xml, name = out / f"rc-{tag}.txt", out / f"{tag}.cmd", out / f"{tag}.xml", f"\\{FOLDER}\\{tag}"
    rc_file.unlink(missing_ok=True)
    # `>"file" echo %errorlevel%`: written the other way round, a one-digit code would become a handle redirect
    cmd.write_text(f'@"{ctx.which(argv[0])}" {subprocess.list2cmdline(argv[1:])}\r\n@>"{rc_file}" echo %errorlevel%\r\n',
                   encoding="utf-8")
    xml.write_text(S.task_xml(f"claude-workbench live control {tag}", [("cmd.exe", f'/c "{cmd}"')]), encoding="utf-16")
    try:
        if ctx.run(["schtasks", "/Create", "/XML", str(xml), "/TN", name, "/F"], timeout=60)[0] != 0 or \
                ctx.run(["schtasks", "/Run", "/TN", name], timeout=60)[0] != 0:
            return None
        end = time.time() + timeout
        while time.time() < end and not (rc_file.exists() and rc_file.read_text().strip()):
            time.sleep(1)
        txt = rc_file.read_text().strip() if rc_file.exists() else ""
        return int(txt) & 0xFFFFFFFF if re.fullmatch(r"-?\d+", txt) else None
    finally:
        ctx.run(["schtasks", "/Delete", "/TN", name, "/F"], timeout=60)
        for f in (rc_file, cmd, xml):
            f.unlink(missing_ok=True)


def winget_absent(ctx, wid):
    rc, _ = ctx.run(["winget", "list", "-e", "--id", wid, "--accept-source-agreements", "--disable-interactivity"],
                    timeout=300)
    return rc == S.NOT_FOUND


def step_winget(ctx, out):
    st = {"step": "winget", "ok": False, "cleanup": "failed", "detail": {"elevated_session": elevated()}}
    links = I.lad() / "Microsoft" / "WinGet" / "Links"
    path_before = I.reg_get(S.ENV_KEY, "Path")
    on_path = any(x.strip().rstrip("\\").lower() == str(links).lower()
                  for x in os.path.expandvars(str((path_before or ("",))[0])).split(";"))
    if not on_path:
        st["detail"]["refused"] = "WinGet Links is not on the user Path: an install would change PATH"
        st["cleanup"] = "verified"
        return st
    pick = next(((w, c) for w, c in CANDIDATES if winget_absent(ctx, w)), None)
    if not pick:
        st["detail"]["refused"] = "all three candidates are already installed"
        st["cleanup"] = "verified"
        return st
    wid, cmd = pick
    exe = links / f"{cmd}.exe"
    st["detail"]["package"] = wid
    installed = False
    try:
        rc = as_user(ctx, ["winget", "install", "--id", wid, "-e", "--source", "winget", "--scope", "user",
                           "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"],
                     out, "w-install")
        installed = rc == 0 or rc in S.ALREADY
        found = ctx.which(cmd)                     # PATH re-read from the registry, as setup does after an install
        rv, vout = ctx.run([found or cmd, "--version"], timeout=60)
        ver = re.search(r"\d+\.\d+(?:\.\d+)?", S.decode(vout)) if rv == 0 else None
        ru = as_user(ctx, ["winget", "uninstall", "--id", wid, "-e", "--source", "winget", "--scope", "user",
                           "--accept-source-agreements", "--disable-interactivity"], out, "w-uninstall")
        st["detail"].update(install=S.hx(rc), resolved=("links" if found and I.under(found, links) else
                                                         "package folder on PATH" if found else None),
                            version=ver.group(0) if ver else None, uninstall=S.hx(ru),
                            gone_from_links=not exe.exists(), listed_absent=winget_absent(ctx, wid))
        st["ok"] = (installed and bool(found) and bool(ver) and ru == 0
                    and st["detail"]["gone_from_links"] and st["detail"]["listed_absent"])
    finally:
        if exe.exists() or not winget_absent(ctx, wid):     # absent before the install, so any copy is ours
            as_user(ctx, ["winget", "uninstall", "--id", wid, "-e", "--source", "winget", "--scope", "user",
                          "--accept-source-agreements", "--disable-interactivity"], out, "w-cleanup")
        now_path = I.reg_get(S.ENV_KEY, "Path")
        if path_before and now_path != path_before and [x for x in str(now_path[0]).split(";") if x] == \
                [x for x in str(path_before[0]).split(";") if x]:
            S.reg_set(S.ENV_KEY, "Path", path_before[0], path_before[1])   # winget leaves a separator behind
            S.broadcast_env()
            st["detail"]["path_separator_restored"] = True
        path_same = I.reg_get(S.ENV_KEY, "Path") == path_before
        st["detail"]["user_path_unchanged"] = path_same
        st["detail"]["test_folder_removed"] = folder_gone() if elevated() else True
        st["cleanup"] = "verified" if (not exe.exists() and winget_absent(ctx, wid) and path_same
                                       and st["detail"]["test_folder_removed"]) else "failed"
    return st


def step_wsl(out):
    st = {"step": "wsl", "ok": False, "cleanup": "n/a", "detail": {}}
    exe = shutil.which("wsl")
    if not exe:
        st["detail"]["refused"] = "wsl.exe is not on PATH"
        return st
    raw = {}
    for args in (["--status"], ["-l", "-v"], ["--version"]):
        r = subprocess.run([exe, *args], capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        raw[" ".join(args)] = (r.returncode & 0xFFFFFFFF, (r.stdout or b"") + (r.stderr or b""))   # piped: on stderr
    text = {k: S.decode(b) for k, (_, b) in raw.items()}
    distros = S.parse_wsl_list(raw["-l -v"][1]) if raw["-l -v"][0] == 0 else []
    st["detail"] = {"exit": {k: S.hx(rc) for k, (rc, _) in raw.items()},
                    "utf16": {k: b"\0" in b for k, (_, b) in raw.items()},
                    "clean_decode": all("�" not in t for t in text.values()),
                    "installed": raw["--status"][0] == 0, "distros": len(distros),
                    "version_found": S.parse_version(raw["--version"][1]) is not None if raw["--version"][0] == 0 else None}
    names = [d["name"] for d in distros]
    with open(out / "wsl-bytes.txt", "w", encoding="utf-8") as f:
        f.write("# Neutralised wsl.exe output captured by live_controls.py (encode with utf-16-le in tests)\n")
        for k, (rc, _) in raw.items():
            f.write(f"# wsl {k} -> exit {S.hx(rc)}\n{neutralise(text[k], names)!r}\n")
    st["ok"] = st["detail"]["clean_decode"] and (st["detail"]["installed"] or not distros)
    return st


def main(argv=None):
    ap = argparse.ArgumentParser(description="KILL2 live controls (see the module docstring)")
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = Path(a.out or os.environ.get("WB_LIVE_OUT") or Path(tempfile.gettempdir()) / "wb-live")
    if not a.apply:
        print(__doc__)
        return 0
    if os.name != "nt" or os.environ.get("WB_LIVE") != "1" or any(
            os.environ.get(k) for k in ("WORKBENCH_FAKE_BIN", "WORKBENCH_FAKE_REGISTRY")):
        print("refused: --apply needs Windows, WB_LIVE=1 and no WORKBENCH_FAKE_* variables")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_CONFIG_DIR"] = str(out / "config")       # setup's own log and state stay in <out>
    ctx = S.Ctx()
    rand = secrets.token_hex(4)
    steps = []
    for name, fn in (("schtasks", lambda: step_schtasks(ctx, rand, out)), ("runonce", lambda: step_runonce(ctx, rand)),
                     ("winget", lambda: step_winget(ctx, out)), ("wsl", lambda: step_wsl(out))):
        try:
            steps.append(fn())
        except Exception as e:      # a crash in one step is a failed step, never an abort that skips the others
            steps.append({"step": name, "ok": False, "cleanup": "failed",
                          "detail": {"error": f"{type(e).__name__}: {e}"}})
    ok = all(s["ok"] and s["cleanup"] in ("verified", "n/a") for s in steps)
    ledger = {"version": 1, "generated": S.now(), "rand": rand, "ok": ok, "steps": steps}
    S.jwrite(out / "live-ledger.json", ledger)
    print(json.dumps(ledger, indent=2) if a.json else "\n".join(f"{s['step']:<9} ok={s['ok']} cleanup={s['cleanup']}"
                                                                for s in steps))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
