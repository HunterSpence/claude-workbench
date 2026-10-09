# Write and test a guard rule

Automates it: py -3 <KIT>/tools/guard-replay/guard_replay.py (the replay step)

## When to use
You want the guards to refuse or question one more thing, or a rule fires too often or misses a spelling, and you want to ship
the change knowing what it does to the work you already did. The worked example is the browser-command rule in the corporate
pack, which asks before `playwright-cli` attaches to a running browser or opens a real browser profile, loads saved logins,
calls a tool the page registered, or prints or saves stored cookies and storage.
The reasoning behind each step is in `docs/AUTHORING.md` section 4. `<KIT>` is the kit folder (guide 01).

## Steps
1. Write the rule as one sentence: "ask when X" or "refuse when X". Refuse only when no legitimate use exists. Ask when a
   person might well mean it. Attaching to a browser, loading logins and calling a page's tool all have legitimate uses, so the
   rule asks. It deliberately leaves `route` alone: that command only changes what pages in the CLI's own browser receive and
   prints no stored session value.
2. Take the exact command words from the tool's own help, never from memory. For the example, `playwright-cli --help` lists
   `attach [name]`, `state-load <filename>`, `webmcp-call <name>` and the `cookie-*`, `localstorage-*`, `sessionstorage-*` and
   `state-save` commands, and `playwright-cli open --help` lists `--persistent` and `--profile` (version 0.1.22 of the npm
   package `@playwright/cli`).
   Write down which options take a value: an option the rule does not know about makes its value look like the command.
3. Find the closest existing rule in `plugins/workbench-core/scripts/guards/rulepacks/corporate.py` (rules driven by your
   organisation's allowlist) or `plugins/workbench-core/scripts/guards/rulepacks/generic.py` (rules that mean the same
   everywhere). In the example it is the browser-command function and its sets of command words. Add your words to the set
   and give each one its own message that says what to do.
4. Write the tests before the rule, with the file-writing tool and not a shell heredoc (`docs/AUTHORING.md` section 4). In
   `plugins/workbench-core/scripts/guards/tests/test_guards.py` add, for each command word:
   - **positive controls**: the plain form, a session option before the command, `npx` and the `.cmd` suffix, a leading
     `cd x &&`, an environment-variable prefix, the PowerShell call operator, capital letters, and for an option the same call
     with it before and after the command;
   - **negative controls**: the command named in an `echo`, a `grep` and a commit message; a different command that is
     similar (`detach`, `state-save`); and an argument that spells the word (`fill e3 attach`);
   - a case for the pack switched off, which must have no opinion.
   Assert the guard id as well as the decision, so another rule cannot make the test pass for you.
5. Run the guard tests:
   ```
   python -m unittest discover -s plugins/workbench-core/scripts/guards/tests
   ```
6. Test the test. In a scratch copy of the kit, delete one command word from the set and run the same tests: the matching
   test must fail. Put it back. A test that survives the deletion proves nothing about that word.
7. Replay your history through the candidate. Copy the changed pack to a scratch folder under its own name, then:
   ```
   py -3 <KIT>/tools/guard-replay/guard_replay.py --rules <scratch folder>/corporate.py --strict
   ```
   A pack named `generic.py` or `corporate.py` replaces that pack for the second run; any other name is added. Read
   `looser` first: a new rule should make it 0, and `--strict` exits 1 if it is not. Then read `stricter`: each id is a past
   call that would now be asked about or refused. Look the id up in the transcript yourself, since the tool never prints
   command text. If many of them are things you wanted, narrow the rule or change a refusal to an ask.
8. Add the rule's guard id and one line about it to the header comment of the pack, put the pack in place of the kit's copy,
   and start a new session: hooks load at session start. The next kit release replaces the pack, so keep your change where
   you keep other local changes and re-apply it after an upgrade.

## Verify
- The guard tests pass, and the deletion in step 6 made one of them fail.
- The replay reports `looser 0` and a `stricter` list you have looked at.
- A call the rule judges returns the message you wrote, naming the guard id, and a call it does not cover returns nothing.
- The pack switched off (`"enabled": false` in `<WB>/corporate-allowlist.json`) gives no opinion on the same calls.

## Common failures
- **The rule fires on prose:** it matched the text, not the statement. Use the engine's statement splitting as the browser rule
  does, so `echo "playwright-cli attach"` and a commit message pass.
- **The rule misses a spelling:** add the form to the positive controls first (`npx`, `.cmd`, a full path, a leading `cd x &&`,
  capital letters), then fix the matching.
- **A value is read as the command:** an option that takes a value is missing from the rule's list of such options. Compare
  the list with the tool's help again.
- **The test passes for the wrong reason:** a second rule judges the same call. The corporate pack's remote rule also refuses a
  push, for example. Choose a command only your rule covers, and assert the guard id.
- **The replay shows no change for a pack you edited:** the header line says `adds` instead of `replaces`, so the file name
  differs from `generic` or `corporate`. Rename the scratch copy.
- **The replay finds no transcripts:** the default folder is the `projects` folder of your Claude configuration folder. Pass
  `--transcripts <folder>`.
