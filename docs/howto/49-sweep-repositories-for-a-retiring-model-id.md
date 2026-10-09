# Sweep your repositories for a retiring model id

Automates it: none (a script does the scan: `tools/model-sweep/model_sweep.py`)

## When to use
A model id your code relies on is being retired or replaced, and you need proof, not a hope, that no repository still names the
old one. The sweep lists every line that does, minus the few you decided to keep, and it refuses to say "clean" if it could not
have found a hit. `<KIT>` is the kit folder (guide 01).

## Steps
1. Write one pattern that covers every spelling: the API id, the provider-prefixed ids, a date-suffixed form, an alias, a
   constant such as an upper-case name with underscores, and the human name in docs. Example for an invented retiring id:
   `claude-oldmodel-4|CLAUDE_OLDMODEL_4|OldModel 4`. It is a Python regular expression.
2. Pick the control: one real line from your code that the pattern must match, such as `model: claude-oldmodel-4`.
3. Copy `<KIT>/tools/model-sweep/allowlist.template.tsv` to `allow.tsv`. It starts empty: no hit is excused yet.
4. Run the gate over every repository folder at once:
   `py -3 <KIT>/tools/model-sweep/model_sweep.py --pattern "claude-oldmodel-4|CLAUDE_OLDMODEL_4" --control "model: claude-oldmodel-4" --allowlist allow.tsv --repos <folder> <folder>`
5. Read the result by its exit code. 0 means no unowned hit. 1 means the lines printed as `repo/path:line` still name the id.
   2 means the gate itself could not give an answer, and the message says why.
6. Change the live hits first: code, configuration, CI files, tests and fixtures, prompts, and docs that tell people what to
   run. Accept only history that must keep the old name, such as a dated changelog entry or a record of what was run. Add one row
   to `allow.tsv` per accepted case: repository name, a path glob, a regular expression that finds the line, and the reason. A row
   covers a hit only when all three match.
7. Rerun step 4 until it exits 0.
8. Freeze the allowlist when the migration starts. A row added later needs a second person's review, because a growing list is how
   a sweep stops meaning anything.
9. Put the command in your CI for each repository, so a new mention of the old id fails the build.

## Verify
- The final run exits 0 and prints nothing but the one-line summary.
- Break it on purpose once: add a line with the old id to a scratch file and rerun. The run must exit 1 and name that file and line.
- `py -3 <KIT>/tools/model-sweep/model_sweep.py --self-test` prints one line and exits 0.

## Common failures
- **Exit 2, "the positive control failed" or "the control must be one line":** the control does not match your pattern, or it spans
  lines. A gate that cannot find its own control would report a clean sweep for the wrong reason, so fix the pattern or the control.
- **Exit 0 but you still see the id somewhere:** the file is not tracked (a work-tree root is scanned through its tracked files),
  it is a binary or a generated file, or the id is spelled in a way the pattern misses, for example built from two strings.
  Widen the pattern, rerun, and check the control still matches.
- **Exit 2, "no such folder" or "no file was scanned":** a path is wrong or the folder is empty. The gate never passes on nothing.
- **A hit you thought was allowlisted still prints:** a row needs the repository name, the path glob and the line regular
  expression to all match. Match the repository name to the folder's own name, and use `/` in globs.
- **The matching text is not shown:** by design, so a secret on the same line is never copied into a log. Open the file at the
  printed line.
