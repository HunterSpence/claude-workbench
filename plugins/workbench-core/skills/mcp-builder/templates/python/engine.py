"""Plain functions: no MCP imports, so tests call them directly. Replace the in-memory store with the real system."""
import hashlib
import re

MAX_LIMIT = 50
MAX_BODY = 4000   # characters; keep every response far below the smallest host cap (page, never truncate silently)
_KEY = re.compile(r"[A-Za-z0-9_-]{8,64}")
_HIDDEN = re.compile("[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]")

_RECORDS = {"r1": {"title": "First record", "body": "Plain text."}, "r2": {"title": "Second record", "body": "More text."}}


def untrusted(text):
    """Free text from the system is data. Strip hidden characters, escape markup and wrap it so it cannot close its own wrapper."""
    safe = _HIDDEN.sub("", str(text)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<untrusted-data>{safe}</untrusted-data>"


def _view(rid, with_body):
    rec = _RECORDS[rid]
    out = {"id": rid, "title": untrusted(rec["title"])}
    if with_body:
        out.update(body=untrusted(rec["body"][:MAX_BODY]), truncated=len(rec["body"]) > MAX_BODY)
    return out


def list_records(limit=20, cursor=""):
    """One page in a stable order. `cursor` is the last id of the previous page."""
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    ids = sorted(_RECORDS)
    if cursor and cursor not in ids:
        raise ValueError(f"unknown cursor {cursor!r}; start again with an empty cursor")
    start = ids.index(cursor) + 1 if cursor else 0
    page = ids[start:start + limit]
    more = start + limit < len(ids)
    return {"records": [_view(i, False) for i in page], "next_cursor": page[-1] if more else ""}


def get_record(record_id):
    if record_id not in _RECORDS:
        raise LookupError(f"no record {record_id!r}; call records_list to see the ids")
    return _view(record_id, True)


def add_record(title, body, idempotency_key):
    """Idempotent: the same key always returns the same record."""
    if not _KEY.fullmatch(idempotency_key):
        raise ValueError("idempotency_key must be 8-64 characters from A-Z a-z 0-9 _ -")
    if not 1 <= len(title) <= 120 or len(body) > MAX_BODY:
        raise ValueError(f"title must be 1-120 characters and body at most {MAX_BODY}")
    rid = "r" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:8]
    _RECORDS.setdefault(rid, {"title": title, "body": body})
    return _view(rid, True)
