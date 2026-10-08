#!/usr/bin/env sh
# Install claude-workbench (Linux, WSL, macOS, or Git Bash on Windows). DRY RUN by default: prints the plan.
#   sh bootstrap/install.sh [--apply] [--profile corporate|permissive] [--upstream-plugins]
#                           [--upstream-plugins-optional] [--kb-root PATH] [--git-hosts h1,h2] [--force] [--no-cli]
# Windows (PowerShell or cmd): run  py -3 bootstrap\install.py  instead; nothing here needs an execution-policy change.
# Needs Python 3.10+ (WORKBENCH_PYTHON picks one). All logic lives in install.py. No root, no network.
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$here/_findpython.sh"
py=$(find_workbench_python) || { echo "Python 3.10 or newer was not found (set WORKBENCH_PYTHON)." >&2; exit 2; }
exec "$py" "$here/install.py" "$@"
