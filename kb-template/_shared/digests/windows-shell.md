---
title: Digest, Windows and shell
domain: _shared
status: active
---
# Windows and shell: lessons that keep recurring

Read this before writing a script, a hook or a scheduled task for a Windows laptop. Each bullet is a lesson, then the
habit that avoids it. The bug cards (`bug-cards.md`) hold the failures that have an error string.

## Paths
- **Git Bash and native programs see different worlds.** Git Bash's `/tmp` is invisible to a native Windows Python, and
  a `/c/...` path is rejected by a native `curl -F @file`. Write scratch output to a path both sides resolve, and give
  native programs `C:/...`.
- **Git Bash rewrites path-like arguments.** A leading-slash API endpoint or a `ref:path` pair becomes a filesystem
  path. Drop the slash, or set the path-conversion opt-out variable for that one command.
- **The legacy path limit is real.** Deep trees fail in Python, zip tools and git unless long paths are enabled in the
  operating system and the program opts in; prefix absolute paths in your own code and keep checkouts near the drive
  root. A profile walk must also skip junctions.
- **Spaces and non-ASCII in the profile path break tools.** Quote every path, test the installer with a user name that
  has a space and an accented letter, and never assume the Documents folder is local: it is often redirected into the
  work cloud.
- **Keep one repository on one filesystem.** Reaching a Linux-side tree from Windows (or the reverse) works but is
  slow and changes permissions and line endings; clone where you build.
- **Case and device names.** Windows paths ignore case, and names such as `con`, `nul` or `aux`, or a trailing dot or
  space, cannot be created by ordinary tools.

## Text, encoding and line endings
- **Text-mode writes translate line endings.** `open(p, "w")` turns LF into CRLF, which breaks Linux-bound shell
  scripts and inflates byte-counted caps. Write bytes, or pass `newline="\n"`, and commit a `.gitattributes`.
- **The console code page is not UTF-8.** Set `PYTHONUTF8=1` at user level, reconfigure stdout in entry scripts and
  pass an explicit encoding to every `open` and `subprocess` call.
- **PowerShell 5.1 reads a file without a byte-order mark in the ANSI code page.** Keep scripts for non-English systems
  pure ASCII (an em dash can break parsing) and use security identifiers, not localised group names.

## Exit codes and pipes
- **A pipeline reports its last command.** `cmd | tail` returns tail's status, and `cmd 2>&1 | Out-Null` in
  PowerShell drops a native command's exit code. A verify-then-delete chain must run as two steps, each checked.
- **A child writing to a small pipe while its parent polls without reading hangs.** The larger Linux buffer hides it.
  Send child output to a file, or use `communicate()`.
- **Killing a process does not stop its children.** Kill the tree (`taskkill /T`), and match processes by exact name so
  a check does not find itself.
- **`sleep N; cmd` is a guess.** Run long work in the background and poll a real condition.

## Quoting and the command line
- **Each shell has its own rules.** PowerShell expands `$` in double quotes, escapes with the backtick and (in 5.1)
  drops the inner quotes of a native-command argument; Git Bash treats single quotes as literal. Put payloads in a
  file, or send them on stdin, instead of nesting quotes.
- **Remote and nested commands:** `ssh host bash -s <<'EOF'` with a quoted marker keeps local expansion out. Use
  `$(...)`, never backticks.
- **The command line has a ceiling** (far lower in cmd.exe than in PowerShell). Pass big payloads by file.
- **Inline `-c` strings cannot be inspected** by a permission checker and will prompt; write a script file.

## Interpreters and tools
- **The Store's Python alias stub can hang** a hook that probes for an interpreter. Turn the aliases off and call the
  interpreter by full path or `py -3`.
- **Call the project's interpreter by path.** `python` may be a different one, and environments made by some tools
  have no pip.
- **A fresh PowerShell process costs seconds under load.** A hook that fires on every file read must not start one.
- **Two OpenSSH clients can live on one machine** (the Windows one and Git's). They share a config but not always an
  agent or key path; pin the identity file per host.
- **An empty environment variable is an unset one on Windows.** Isolate tests with an explicit sentinel path.
- **Symbolic links need a privilege or developer mode;** a junction does not, but a walk must not follow it blindly.

## Scheduled tasks
- **A `.cmd` target always opens a console window;** "Hidden" only hides the task from the list. Launch through a
  windowless interpreter.
- **A daily task missed while the machine slept needs the start-when-available setting,** and a named mutex stops a
  second copy when a wrapper dies and the next trigger fires.
- **Run as the user, not as a service account,** unless an administrator provisioned it: tasks the kit creates are
  per-user, no elevation, and removable by the uninstaller.

## Sleep and modern standby
- **A laptop that sleeps drops its network.** On modern-standby hardware Windows controls connectivity in sleep and, on
  battery power, quiesces network activity unless Remote Desktop or an app allowed to run in the background needs it.
  A long unattended run, an SSH session or a big download then dies when the lid closes or the idle timer fires, with
  no error of its own.
- **Prove it before you tune it.** `powercfg /availablesleepstates` lists the sleep states the machine has and why a
  state is missing; `powercfg /sleepstudy` writes a modern-standby report for the last three days to the current
  folder; `powercfg /requests` lists what is preventing sleep right now. `powercfg /systempowerreport` needs an
  elevated prompt, so skip it on a managed laptop.
- **Keep a long run awake in a supported way:** plug in, and lengthen the sleep timer on mains power with
  `powercfg /change standby-timeout-ac <minutes>`, or run the job where nothing sleeps. A managed power policy may
  override a local setting: then ask IT for the specific setting by name instead of using a keep-awake trick.

## Antivirus, sync clients and policy
- **Real-time scanning slows file-heavy work** (installs, builds, indexing). Measure first; a Dev Drive or a smaller
  working set helps. Never add a scanner exclusion yourself: ask IT for it by name and path.
- **A sync client locks and rescans files.** Keep repositories, environments and databases outside synced folders.
- **A denial is a decision.** When a policy blocks a tool, stop and report it verbatim; do not retry in another shell.
