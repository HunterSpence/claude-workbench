# How-to library

Fifty-five short task guides for things you do at work with Claude Code and this kit. Read one when you need it; nothing
here is loaded into a session by itself.

## How to use it
- **Ask Claude.** Setup registers this folder as the search root `howto`, so a plain question finds the right guide:
  "how do I run a task every night?". By hand:
  `py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py search "<your question>" --root howto`
- **Every guide has the same shape:** `## When to use`, `## Steps`, `## Verify`, `## Common failures`, and one line
  `Automates it:` naming the skill or command that does the work for you (or `none`).
- **Locations.** `<KIT>` is the kit folder (the unpacked release, or `<CH>/workbench/kit` after install), `<CH>` is
  `CLAUDE_CONFIG_DIR` or `~/.claude`, `<WB>` is `<CH>/workbench`.
- **A guide states only commands and paths that exist in the kit.** When a policy blocks a step, the guide tells you to
  stop and ask IT (guide 03), never to work around it.

## Setup and environment
- [01 Set up Claude Code and the kit on your first day](01-setup-first-day.md)
- [02 Read the capability report](02-read-the-capability-report.md)
- [03 Ask IT for access, the right way](03-ask-it-for-access.md)
- [04 Work behind a proxy that re-signs HTTPS](04-proxies-and-tls-inspection.md)
- [05 Set up WSL2 and resume after the reboot](05-wsl-setup-and-resume.md)
- [06 Upgrade the kit, or remove it completely](06-upgrade-and-uninstall.md)
- [07 Keep each client or project in its own profile](07-client-profiles.md)
- [44 Update the tools setup installed](44-update-the-tools.md)
- [55 Run Claude Code on a virtual desktop](55-claude-code-on-a-virtual-desktop.md)

## Working with Claude Code
- [08 Understand permission modes and cut the prompts you can](08-permission-modes-and-prompts.md)
- [09 Hand work to subagents and pick the model](09-spawn-subagents-and-pick-models.md)
- [10 Save what a session learned](10-save-session-knowledge.md)
- [11 Keep token use low](11-keep-token-use-low.md)
- [12 Run Claude without you at the keyboard, and schedule it](12-headless-and-scheduled-runs.md)
- [13 Run the doctor and keep a tested backup](13-run-the-doctor-and-backups.md)
- [14 Write your own skill or hook, with a test](14-write-a-skill-or-hook.md)
- [43 Fix a red error message in Claude Code](43-fix-a-red-error-in-claude-code.md)
- [49 Sweep your repositories for a retiring model id](49-sweep-repositories-for-a-retiring-model-id.md)
- [50 Write and test a guard rule](50-write-and-test-a-guard-rule.md)
- [51 Check that skills fire and rules hold](51-check-that-skills-fire-and-rules-hold.md)
- [53 Audit your setup and clean up dead code](53-audit-and-clean-up.md)

## Code and GitHub
- [15 Connect a read-only GitHub MCP server](15-connect-the-github-mcp-server.md)
- [16 Use GitHub Enterprise hosts with gh](16-github-enterprise-hosts.md)
- [17 Review code you did not write, safely](17-review-an-unfamiliar-repo-safely.md)
- [18 Fix a bug with the bug playbook](18-fix-a-bug-with-the-playbook.md)
- [19 Add Claude to a repository's CI](19-ci-with-claude-code-action.md)
- [20 Push code only to approved git hosts](20-push-only-to-approved-hosts.md)
- [42 Add an in-app navigation assistant](42-add-an-in-app-navigation-assistant.md)
- [48 Build an eval for a feature that calls Claude](48-build-an-eval.md)

## Web, UI and diagrams
- [45 Drive a browser from the command line, headless](45-browser-headless.md)
- [46 Draw a diagram for a document, deck or pull request](46-draw-a-diagram-offline.md)
- [47 Lock a brand spec, then build and review a UI against it](47-lock-a-brand-spec-and-review-a-ui.md)

## Plugins and MCP
- [21 Scaffold a plugin](21-scaffold-a-plugin.md)
- [22 Build an MCP server](22-build-an-mcp-server.md)
- [23 Wrap an API as an MCP server](23-wrap-an-api-as-mcp.md)
- [24 Review a plugin or skill](24-review-a-plugin-or-skill.md)
- [25 Package a skill for the web](25-package-a-skill-for-the-web.md)
- [26 Enable an enterprise MCP server](26-enable-an-enterprise-mcp-server.md)

## Knowledge
- [27 Find a file or an answer](27-find-a-file-or-an-answer.md)
- [28 Add a library to find](28-add-a-library-to-find.md)
- [29 Keep the index fresh](29-keep-the-index-fresh.md)
- [30 Capture intranet pages](30-capture-intranet-pages.md)
- [31 Capture shared files](31-capture-shared-files.md)
- [32 Purge indexed or captured data](32-purge-indexed-or-captured-data.md)
- [41 Unlock meeting transcripts and mail](41-unlock-meeting-transcripts-and-mail.md)
- [54 Which knowledge tool for which question](54-which-knowledge-tool-for-which-question.md)

## Business deliverables
- [33 Turn requirements into user stories](33-requirements-to-stories.md)
- [34 Turn meeting notes into actions](34-meeting-notes-to-actions.md)
- [35 Write a status report](35-status-report.md)
- [36 Scrub a document before sending it](36-scrub-a-document-before-sending.md)

## Security and compliance
- [37 Labelled and confidential files](37-labelled-and-confidential-files.md)
- [38 What leaves this machine](38-what-leaves-this-machine.md)
- [39 When a policy blocks you](39-when-a-policy-blocks-you.md)
- [40 First steps in an incident](40-incident-first-steps.md)
- [52 Check a document for hidden text](52-check-a-document-for-hidden-text.md)
