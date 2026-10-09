"""runner_claude.py: one headless Claude Code call per task, in an empty temp cwd.

  claude -p --safe-mode --tools "" --strict-mcp-config --no-session-persistence --output-format json
         --setting-sources project,local --model M --append-system-prompt TEXT      (the task prompt arrives on stdin)

All flags are listed by `claude --help` (checked on 2.1.294). This module never reads, copies or writes a login file.
Isolation comes from the flags; the config dir is the user's own, unless CLAUDE_CODE_OAUTH_TOKEN is already set (a setup
token the user created), in which case the child gets an empty throwaway config dir. API-key variables are removed from
the child environment unless keep_api_key is set. SKILL_BENCH_CLAUDE overrides the binary (a path, or a JSON list).
"""
import json
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
LIMIT_WORDS = ("usage limit", "rate limit", "limit reached", "rate_limit", "quota", "too many requests", "overloaded")
NESTED = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")
API_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def _kill_tree(p):
    """Stop p and everything it started. npm installs Claude Code behind a .cmd shim that runs claude as a child holding the
    pipes open: killing only the shim leaves the call waiting for the child."""
    try:
        if os.name == "nt":
            subprocess.run([os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe"), "/T", "/F", "/PID", str(p.pid)],
                           capture_output=True, timeout=30)
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        p.kill()


def run_tree(argv, input_text, timeout, cwd, env):
    """(stdout, stderr). Past the timeout the whole process tree is killed and reaped, then TimeoutExpired is raised."""
    kw = {} if os.name == "nt" else {"start_new_session": True}
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace", cwd=cwd, env=env, **kw)
    try:
        return p.communicate(input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        try:
            p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise


class UsageLimit(Exception):
    """The route refused for quota or rate reasons: every later call would fail the same way, so the run stops."""


def binary():
    b = os.environ.get("SKILL_BENCH_CLAUDE")
    if b:
        return json.loads(b) if b.lstrip().startswith("[") else [b]
    return [shutil.which("claude") or "claude"]


def command(model, system):
    return binary() + ["-p", "--safe-mode", "--tools", "", "--strict-mcp-config", "--no-session-persistence",
                       "--output-format", "json", "--setting-sources", "project,local", "--model", model,
                       "--append-system-prompt", system]


def child_env(cfg=None, keep_api_key=False):
    """The child environment; cfg (a throwaway dir) replaces the config dir only when given."""
    drop = NESTED + (() if keep_api_key else API_KEYS)
    env = {k: v for k, v in os.environ.items() if k not in drop}
    if cfg:
        env["CLAUDE_CONFIG_DIR"] = str(cfg)
    return env


def _norm(u):
    return {k: int((u or {}).get(k) or 0) for k in USAGE_KEYS}


def parse(stdout):
    """A result object (dict) or an event list. Usage counts once per message id: streamed events repeat it."""
    d = json.loads(stdout)
    if not isinstance(d, list):
        return {"result": d.get("result"), "usage": _norm(d.get("usage")), "cost_usd": d.get("total_cost_usd"),
                "duration_ms": d.get("duration_ms"), "is_error": bool(d.get("is_error")), "raw": d}
    by_id, final = {}, {}
    for ev in d:
        if ev.get("type") == "assistant" and (ev.get("message") or {}).get("usage"):
            by_id[ev["message"].get("id") or f"anon{len(by_id)}"] = ev["message"]["usage"]
        if ev.get("type") == "result":
            final = ev
    usage = {k: sum(_norm(u)[k] for u in by_id.values()) for k in USAGE_KEYS} if by_id else _norm(final.get("usage"))
    return {"result": final.get("result"), "usage": usage, "cost_usd": final.get("total_cost_usd"),
            "duration_ms": final.get("duration_ms"), "is_error": bool(final.get("is_error")), "raw": final}


class ClaudeRunner:
    def __init__(self, keep_api_key=False, timeout=900):
        self.keep_api_key, self.timeout = keep_api_key, timeout
        self.tmp = Path(tempfile.mkdtemp(prefix="skillbench-"))
        self.cwd = self.tmp / "cwd"
        self.cwd.mkdir()
        self.cfg = None
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):       # a setup token needs no login file: use an empty config dir
            self.cfg = self.tmp / "cfg"
            self.cfg.mkdir()

    def call(self, model, system, prompt, **_):
        env = child_env(self.cfg, self.keep_api_key)
        try:
            out, err = run_tree(command(model, system), prompt, self.timeout, self.cwd, env)
        except subprocess.TimeoutExpired:
            return {"is_error": True, "error": "timeout"}
        try:
            r = parse(out)
        except (json.JSONDecodeError, AttributeError):
            r = {"is_error": True, "result": None, "raw": (out or "")[-500:]}
        if r["is_error"] or not r.get("result"):
            msg = (json.dumps(r.get("raw"))[:600] + " | " + (err or "")[-300:]).lower()
            if any(w in msg for w in LIMIT_WORDS):
                raise UsageLimit(msg[:300])
            return {"is_error": True, "error": msg[:400]}
        r.pop("raw", None)
        return r

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
