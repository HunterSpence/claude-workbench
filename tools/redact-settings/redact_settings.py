#!/usr/bin/env python3
"""redact_settings.py: copy a Claude Code settings.json (or .mcp.json / .claude.json fragment) with every value that
could be a secret masked, so you can share it with IT, a colleague or a bug report.

  redact_settings.py <src.json> <dst.json>

Masked: every value under an `env` or `headers` object (at any depth, so MCP server blocks are covered), and
`apiKeyHelper` / `awsAuthRefresh` / `awsCredentialExport` / `otelHeadersHelper` commands. A final pass with the kit's
secret scanner masks any credential-shaped string left anywhere else. Keys, hooks, permissions and models stay as
they are. The source file is never modified. Standard library only.
"""
import json
import sys
from pathlib import Path

SCANNER = Path(__file__).resolve().parent.parent.parent / "plugins" / "workbench-core" / "scripts"
MASK_OBJECTS = {"env", "headers"}
MASK_KEYS = {"apiKeyHelper", "awsAuthRefresh", "awsCredentialExport", "otelHeadersHelper"}


def redact(node, scan=None, key=None):
    if isinstance(node, dict):
        if key in MASK_OBJECTS:
            return {k: f"<REDACTED:{k}>" for k in node}
        return {k: f"<REDACTED:{k}>" if k in MASK_KEYS else redact(v, scan, k) for k, v in node.items()}
    if isinstance(node, list):
        return [redact(v, scan, key) for v in node]
    if isinstance(node, str) and scan and scan(node):
        return "<REDACTED:credential-shaped>"
    return node


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    src, dst = Path(a[0]), Path(a[1])
    if src.resolve() == dst.resolve():
        print("refusing to overwrite the source file", file=sys.stderr)
        return 2
    try:
        sys.path.insert(0, str(SCANNER))
        import secretscan
        scan = secretscan.scan_text
    except ImportError:
        scan = None
        print("WARNING: kit secret scanner not found; only env/headers/helper values are masked", file=sys.stderr)
    data = json.loads(src.read_text(encoding="utf-8-sig"))
    dst.write_text(json.dumps(redact(data, scan), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(dst.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
