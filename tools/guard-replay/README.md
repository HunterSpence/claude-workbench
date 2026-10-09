# guard-replay

Before you ship a change to a guard rule, find out what it would have done to the work you already did. The tool reads your own
Claude Code transcripts, judges every tool call in them twice (the shipped rule packs, then your candidate pack) and lists the
calls whose answer changed (`docs/howto/50-write-and-test-a-guard-rule.md`).

```
py -3 <KIT>/tools/guard-replay/guard_replay.py --rules my_corporate.py [--transcripts DIR] [--strict] [--json]
py -3 <KIT>/tools/guard-replay/guard_replay.py --self-test
```

- `--rules FILE.py` is the candidate pack. A file named `generic.py` or `corporate.py` replaces that pack for the second run; any other
  name is added to the shipped packs. The file's code is run, so replay only packs you wrote or read.
- `looser` means the candidate lets through something the baseline asked about or denied: the number to read first. `--strict` exits 1
  on any.
- Output is counts, tool_use ids and guard ids. Command text is never printed.
- Nothing is executed and the live guard log is never written: the engine logs to a temporary folder that is deleted afterwards.
  The corporate pack reads your live allowlist, read only.
- Replaying runs the real engine, which starts a shell syntax check for some Bash commands: expect about a tenth of a second per call.
  `--max-calls` (default 1000) and `--max-files` (200) bound it, newest transcripts first.
- Exit 0 = replay done, 1 = `--strict` and a call got looser, 2 = unusable input (no transcripts, a pack that will not load).
