"""A stand-in for the `mail probe` body-read child: ok | denied | block."""
import sys
import time

mode = sys.argv[1]
if mode == "denied":
    sys.exit("access denied")
if mode == "block":
    time.sleep(60)
print('{"ok": true}')
