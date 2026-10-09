"""runner_mock.py: a model stand-in for offline self-tests. It answers with the task's reference answer and follows the
trailer instruction in the system text exactly as a model that received the arm would.

WB_MOCK is a JSON object that injects faults and effects:
  {"drop": ["arm"]}          the arm text silently never reaches the model (no trailer comes back)
  {"bad": ["arm"]}           the arm answers with the task's failing reference answer
  {"scale": {"arm": 0.5}}    the arm's output tokens are scaled by 0.5
  {"limit_after": 2}         the third call raises a usage-limit error
"""
import hashlib
import json
import os
import re

from runner_claude import UsageLimit


class MockRunner:
    def __init__(self):
        self.spec = json.loads(os.environ.get("WB_MOCK") or "{}")
        self.calls = 0

    def call(self, model, system, prompt, ref=None, arm="", rep=0, **_):
        self.calls += 1
        if self.calls > self.spec.get("limit_after", 10 ** 9):
            raise UsageLimit("mock: usage limit reached")
        text = (ref or {}).get("bad" if arm in self.spec.get("bad", []) else "good", "mock answer")
        m = re.search(r"\[bench:([0-9a-f]{10})\]", system)
        if m and arm not in self.spec.get("drop", []):
            text += f"\n[bench:{m.group(1)}]"
        jitter = 0.9 + int(hashlib.sha256(f"{arm}|{prompt}|{rep}".encode()).hexdigest()[:4], 16) / 0xFFFF * 0.2
        out = max(1, round(len(text) / 4 * self.spec.get("scale", {}).get(arm, 1.0) * jitter))
        inp = (len(system) + len(prompt)) // 4
        return {"result": text, "usage": {"input_tokens": inp, "output_tokens": out, "cache_creation_input_tokens": 0,
                                           "cache_read_input_tokens": 0}, "cost_usd": (inp + out) * 1e-6,
                "duration_ms": 5, "is_error": False}

    def close(self):
        pass
