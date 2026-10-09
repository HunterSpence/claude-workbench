# model-sweep

A gate for "no repository still names the model id we are retiring". It lists every line that matches a pattern and is not
covered by a frozen allowlist, and it proves it can find what it must before it says the sweep is clean
(`docs/howto/49-sweep-repositories-for-a-retiring-model-id.md`).

```
py -3 <KIT>/tools/model-sweep/model_sweep.py --pattern "<regex>" --control "<one line the regex matches>" ^
    --allowlist <file.tsv> --repos <folder> [<folder> ...]
py -3 <KIT>/tools/model-sweep/model_sweep.py --self-test
```

- Output is `repo/path:line` for each unowned hit and nothing else; the matching text is never printed.
- Exit 0 = no unowned hit. Exit 1 = at least one. Exit 2 = the gate cannot give an answer (bad regex or allowlist, a folder that
  does not exist, nothing scanned, or the positive control failed).
- Positive control: `--control` must be a single line the pattern matches. The tool scans a throwaway folder holding that line
  and a clean one with an empty allowlist, and needs exactly one hit, or it exits 2.
- A git work-tree root is scanned through `git ls-files` (tracked files only); any other folder is walked.
- `allowlist.template.tsv` is the empty list to copy. Each row is `repo`, `path_glob`, `line_regex`, `reason`, tab-separated.
  A row covers a hit only when all three match; the reason is required. Freeze the list before the migration starts and
  review every row you add after it.
