# Code-graph routing

- **If a code-graph MCP is installed for the repo** (for example tokensave, see
  `{{WORKBENCH_HOME}}/kit/THIRD-PARTY.md`), prefer its search and callers tools over grep for symbol blast radius: search
  for the symbol, then ask for callers by node ID, not name. For
  repos it hasn't indexed, pass the repo root explicitly if the tool supports it.
- **Confirm with grep on TypeScript.** Some graph versions miss cross-file import calls and
  module top-level calls, so a TS blast-radius answer is not complete until grep agrees.
- **Before editing a function, find every caller.** One fix in the shared function beats a patch in
  each caller, and patching only the reported path leaves the siblings broken.
- **Markdown and notes:** use the KB search (`rules/memory-protocol.md`), never a code graph.
- **Vendor-owned files:** a code-graph installer may write its own hooks or its own
  `~/.claude/rules/<tool>.md`. Never run a code-graph tool's `install`, `setup`, `upgrade` or `doctor`
  without reading what it changes (`doctor` silently adds hooks); tokensave's install, reinstall, upgrade, doctor,
  uninstall and claude-install/claude-uninstall: never unasked. Both settings profiles exclude `rules/tokensave.md` through
  `claudeMdExcludes`, so this file stays the one owner of code-graph routing.
- A graph gap you hit repeatedly: suggest an upstream issue.
