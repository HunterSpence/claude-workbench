# memcap

Run a heavy command (a big test suite, a fuzz run, an eval, a model job) with a memory ceiling, which keeps a
runaway job from exhausting memory.

```bash
py -3 tools/memcap/memcap.py --mb 2048 -- py -3 -m pytest -x        # Windows
python3 tools/memcap/memcap.py --mb 2048 -- npm test                  # Linux / WSL / macOS
```
- Windows: a job object caps every process in the job at `--mb` MB of committed memory and the job at twice that;
  closing memcap kills the whole tree. The peak is printed at the end.
- Linux, WSL, macOS: `RLIMIT_AS` on the child (address space: leave JIT runtimes such as Node or the JVM room to spare).
- Exit code is the command's. A capped process fails with an out-of-memory error; raise `--mb` only if the job
  really needs it, and run heavy jobs one at a time.

Test: `py -3 -m unittest discover -s tools/memcap` (allocates at most 400 MB under a 200 MB cap).
