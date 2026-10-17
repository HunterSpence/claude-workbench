# Keep each client or project in its own profile

Automates it: `py -3 <KIT>/bootstrap/profile.py create <name>`

## When to use
You work for more than one organisation or project, and nothing from one may appear in another's sessions: its own
settings, knowledge base and search index. `<KIT>` is the kit folder (guide 01).

## Steps
1. Create a profile. Options after `--` go to the installer:
   `py -3 <KIT>/bootstrap/profile.py create project-a -- --profile corporate`
   The names are `[a-z0-9-]` and at most 32 characters. It creates `<HOME>/.claude-profiles/project-a/config` and
   `.../kb`, installs the kit into `config`, and gives the profile its own index.
2. The knowledge base stays local. To use an approved cloud folder, add `--kb <folder>` before the `--`. Never put a
   git repository inside OneDrive.
3. List what exists: `py -3 <KIT>/bootstrap/profile.py list`
4. Start Claude Code in that profile: `py -3 <KIT>/bootstrap/profile.py launch project-a`
   Arguments for `claude` go after `--`.
5. Remove one: `py -3 <KIT>/bootstrap/profile.py remove project-a`. It uninstalls that copy and keeps the knowledge base
   unless you add `--purge-kb`.

## Verify
- `list` shows the profile and `<WB>/profiles.json` records it.
- In the launched session, a knowledge-base search for a word that exists only in another profile's notes finds nothing.

## Common failures
- **The session acts as if the kit were missing:** `CLAUDE_CONFIG_DIR` points at another folder. Start the profile
  with `launch`, not by setting the variable by hand.
- **Name rejected:** use lowercase letters, digits and hyphens only.
- **Cross-client leakage:** it came from a shared folder, not the profile. Keep each client's files, repos and
  tokens inside that client's profile and approved storage.
- **Exit code from the installer:** 3 means your organisation's policy blocked a step; use guide 03.
