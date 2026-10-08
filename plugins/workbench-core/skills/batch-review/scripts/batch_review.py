#!/usr/bin/env python3
"""batch_review.py: run non-interactive Claude passes through the Message Batches API (50% off).

  python batch_review.py "prompt one" "prompt two"                 # submit, poll, print
  python batch_review.py --file review.md --system-file sys.md     # prompts from files
  python batch_review.py --no-poll --file big.md                   # submit and print the batch id
  python batch_review.py --check msgbatch_...                      # fetch a submitted batch

Needs an Anthropic API key from the Claude Console in ANTHROPIC_API_KEY. A Claude.ai or Claude Code
subscription seat is not an API key: your organisation must provide one. ANTHROPIC_BASE_URL is
honoured for an approved gateway. Model: --model, else $BATCH_REVIEW_MODEL, else the default below.
"""
import argparse, os, sys, time
from pathlib import Path

DEFAULT_MODEL = os.environ.get("BATCH_REVIEW_MODEL", "claude-opus-5-5")


def build_requests(prompts, model, max_tokens, effort=None, system=None):
    reqs = []
    for i, p in enumerate(prompts):
        params = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": p}]}
        if effort:
            params["output_config"] = {"effort": effort}
        if system:
            params["system"] = system
        reqs.append({"custom_id": f"req-{i}", "params": params})
    return reqs


def print_results(client, batch_id):
    for r in client.messages.batches.results(batch_id):
        print(f"\n===== {r.custom_id}: {r.result.type} =====")
        if r.result.type != "succeeded":
            print(r.result)
            continue
        msg = r.result.message
        for block in msg.content:
            if block.type == "text":
                print(block.text)
        print(f"[usage in={msg.usage.input_tokens} out={msg.usage.output_tokens} stop={msg.stop_reason}]")


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompts", nargs="*")
    ap.add_argument("--file", action="append", default=[], help="file whose text becomes one prompt (repeatable)")
    ap.add_argument("--system-file")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="omit to use the model default")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--check", metavar="BATCH_ID")
    ap.add_argument("--no-poll", action="store_true")
    ap.add_argument("--timeout", type=int, default=3600, help="seconds to poll before giving up")
    a = ap.parse_args(argv)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Batches need a Console API key your organisation provides; a chat seat is not one.")
    import anthropic   # imported late so --help works without the SDK
    client = anthropic.Anthropic()
    if a.check:
        batch_id = a.check
    else:
        prompts = list(a.prompts) + [Path(f).read_text(encoding="utf-8") for f in a.file]
        if not prompts:
            ap.error("no prompts given")
        system = Path(a.system_file).read_text(encoding="utf-8") if a.system_file else None
        batch = client.messages.batches.create(requests=build_requests(prompts, a.model, a.max_tokens, a.effort, system))
        batch_id = batch.id
        print(f"batch: {batch_id} ({len(prompts)} request(s), {a.model})")
        if a.no_poll:
            print(f"fetch later: python batch_review.py --check {batch_id}")
            return 0
    deadline = time.time() + a.timeout
    while True:
        b = client.messages.batches.retrieve(batch_id)
        if b.processing_status == "ended":
            break
        if time.time() > deadline:
            sys.exit(f"timeout; still {b.processing_status}. Re-run with --check {batch_id}")
        print(f"  {b.processing_status} ({b.request_counts.processing} processing)", flush=True)
        time.sleep(20)
    print_results(client, batch_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
