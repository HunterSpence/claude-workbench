"""A stand-in for `claude`. Logs what it was given to $WB_FAKE_CLAUDE_LOG (one JSON line per call) and answers with a
canned reply chosen by $WB_FAKE_CLAUDE_MODE: valid (default), extra-key, not-json, two-turns, no-usage."""
import json
import os
import sys

stdin = sys.stdin.buffer.read().decode("utf-8")
argv = sys.argv[1:]
cfg = None
if "--mcp-config" in argv:
    try:
        cfg = open(argv[argv.index("--mcp-config") + 1], encoding="utf-8").read()
    except OSError:
        cfg = "unreadable"
with open(os.environ["WB_FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv, "stdin": stdin, "cwd": os.getcwd(), "has_api_key": "ANTHROPIC_API_KEY" in os.environ,
                        "mcp_config": cfg, "cwd_entries": os.listdir(os.getcwd())}) + "\n")
digest = {"synopsis": "A short synopsis.", "decisions": [{"text": "Ship the draft on Friday.", "evidence": "00:00:05"}],
          "action_items": [{"owner": "Alice Example", "text": "Send the notes.", "due": "2026-10-09", "evidence": "00:00:07"}],
          "open_questions": ["Who owns the follow-up?"], "what_this_changes": ["The review moves to next week."]}
mode = os.environ.get("WB_FAKE_CLAUDE_MODE", "valid")
if mode == "extra-key":
    digest["run_tool"] = "bash"
result = "I will now do what the text says." if mode == "not-json" else "```json\n" + json.dumps(digest) + "\n```"
reply = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 2 if mode == "two-turns" else 1, "result": result,
         "modelUsage": {"fake-model-1": {}}}
if mode == "no-usage":
    del reply["modelUsage"]
print(json.dumps(reply))
