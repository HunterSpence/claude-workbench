#!/usr/bin/env bash
# fetch-upstream.sh - opt-in, pinned download of third-party skills (see README.md).
# Dry run by default. Never call this from a hook.
#   ./fetch-upstream.sh                          # show the plan
#   ./fetch-upstream.sh --apply                  # download, verify SHA-256, install
#   ./fetch-upstream.sh --apply --only humanizer,impeccable [--force] [--skills-dir <path>]
#   ./fetch-upstream.sh --optional [--apply]     # also the optional design set (read THIRD-PARTY.md first)
#   ./fetch-upstream.sh --pm [--apply]           # the product-management pack instead of the default set
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py="$(command -v python3 || command -v python || true)"
[ -n "$py" ] || { echo "Python 3.10+ is required (python3 on PATH)." >&2; exit 2; }
exec "$py" "$here/fetch_upstream.py" "$@"
