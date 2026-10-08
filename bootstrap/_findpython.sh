# Shared by install.sh and uninstall.sh. Prints the first interpreter that RUNS as Python 3.10+ (a Windows Store
# "python3" stub found on PATH under Git Bash fails the run and is skipped). No newline: Windows Python ends lines
# with CR LF, and dash keeps the CR in $(...).
find_workbench_python() {
    for c in "${WORKBENCH_PYTHON:-}" python3 python py; do
        [ -n "$c" ] || continue
        command -v "$c" >/dev/null 2>&1 || continue
        out=$("$c" -c 'import sys; sys.stdout.write("ok" if sys.version_info >= (3, 10) else "")' 2>/dev/null) || continue
        [ "$out" = "ok" ] && { echo "$c"; return 0; }
    done
    return 1
}
