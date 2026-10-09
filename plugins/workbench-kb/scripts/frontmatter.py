#!/usr/bin/env python3
"""frontmatter.py: read and set one top-level key of a note's `---` block without touching anything else.

Text goes in and comes out exactly as it was, except for the one line that holds the key: line endings (LF or CRLF),
a byte-order mark, the other keys, their order and the body are all preserved. A note with no `---` block at the top is
never given one (set_key returns None). Stdlib only; no state, so any script can import it.

    get(text, key)           -> the value as written (quotes stripped), or None
    set_key(text, key, value) -> the new text, or None when the note has no front matter
"""
import re


def _close(lines):
    """Index of the line that closes the block, or None when the text does not open with one."""
    if not lines or lines[0].lstrip("﻿").rstrip() != "---":
        return None
    return next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)


def _key(key):
    return re.compile(rf"{re.escape(key)}[ \t]*:(.*)$")   # column 0 only: a nested key of a mapping is not this key


def get(text, key):
    lines = text.split("\n")
    end = _close(lines)
    if end is None:
        return None
    for ln in lines[1:end]:
        m = _key(key).match(ln.rstrip("\r"))
        if m:
            return m.group(1).strip().strip("'\"")
    return None


def set_key(text, key, value):
    """Replace the value of `key` in place, else add `key: value` just before the closing line."""
    lines = text.split("\n")
    end = _close(lines)
    if end is None:
        return None
    cr = "\r" if lines[0].endswith("\r") else ""
    for i in range(1, end):
        if _key(key).match(lines[i].rstrip("\r")):
            lines[i] = f"{key}: {value}{cr}"
            return "\n".join(lines)
    lines.insert(end, f"{key}: {value}{cr}")
    return "\n".join(lines)
