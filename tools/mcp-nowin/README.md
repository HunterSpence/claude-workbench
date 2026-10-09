# mcp-nowin

On Windows, a stdio tool server that is a console program, or that is started through a `cmd /c` wrapper, opens a console window
every time Claude Code starts it. This launcher starts the program with `CREATE_NO_WINDOW` under the windowless interpreter
instead.

```
command: <path to pythonw.exe>
args:    ["<KIT>/tools/mcp-nowin/mcp_nowin.py", "<program>", "<the program's own arguments>"]
```

- Try the same arguments under `python.exe` first; switch the command to `pythonw.exe` once the server answers.
- The program's standard handles are re-attached before it starts (`pythonw.exe` does not wire them), so the stdio pipe to
  Claude Code stays intact; its exit code is this script's exit code. A program that cannot start gives 127.
- It does not change which program runs or its arguments, and it adds no network access.
- `py -3 <KIT>/tools/mcp-nowin/mcp_nowin.py --self-test` is an offline one-line check.
