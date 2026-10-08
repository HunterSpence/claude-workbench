#!/usr/bin/env sh
# Reverse claude-workbench installs, newest first. DRY RUN by default; --apply to change files. Keeps the KB.
#   bash bootstrap/uninstall.sh [--apply] [--no-cli] [--purge-backups]
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$here/_findpython.sh"
py=$(find_workbench_python) || { echo "Python 3.10 or newer was not found (set WORKBENCH_PYTHON)." >&2; exit 2; }
exec "$py" "$here/install.py" --uninstall "$@"
