"""An in-memory MailSource for tests: invented people on example.com, counters for every read, hooks to refuse or block."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "ingest" / "scripts"))
from mailsource import Attachment, Folder, Item, MailSource, Store  # noqa: E402


class FakeMailSource(MailSource):
    def __init__(self):
        self.store_list, self.msgs = [], {}
        self.body_calls, self.label_calls, self.items_calls, self.saves = [], [], [], []
        self.on_body = None  # called before a body is returned; may raise PolicyBlock or block

    def add_store(self, sid, name, cached=True):
        self.store_list.append(Store(sid, name, cached))

    def add(self, store, folder, entry_id, conv, subject, received, modified=None, text="", html=None, sender="Alice Example <alice@example.com>",
            to=("bob@example.com",), cc=(), message_id=None, labels=(), message_class="IPM.Note", attachments=()):
        self.msgs.setdefault((store, folder), {})[entry_id] = dict(
            entry_id=entry_id, conv=conv, subject=subject, received=received, modified=modified or received, text=text, html=html,
            sender=sender, to=list(to), cc=list(cc), message_id=message_id or f"<{entry_id}@example.com>", labels=list(labels),
            message_class=message_class, attachments=list(attachments))

    def stores(self):
        return list(self.store_list)

    def folders(self, store):
        return [Folder(store.id, f"{store.id}:{f}", f) for (s, f) in self.msgs if s == store.id]

    def items(self, folder, since, after_entry_ids):
        assert any(s.id == folder.store_id and s.cached for s in self.store_list), "a store that is not cached was read"
        self.items_calls.append(folder.path)
        rows = sorted(self.msgs[(folder.store_id, folder.path)].values(), key=lambda m: (m["modified"], m["entry_id"]))
        for m in rows:
            if since and (m["modified"] < since or (m["modified"] == since and m["entry_id"] in after_entry_ids)):
                continue
            yield Item(m["entry_id"], m["conv"], m["subject"], m["received"], m["modified"], m["message_class"], ref=m)

    def labels(self, item):
        self.label_calls.append(item.entry_id)
        return list(item.ref["labels"])

    def body(self, item, headers_only=False):
        self.body_calls.append((item.entry_id, headers_only))
        if self.on_body:
            self.on_body(item)
        m = item.ref
        return {"text": None if headers_only else m["text"], "html": None if headers_only else m["html"], "from": m["sender"],
                "to": m["to"], "cc": m["cc"], "message_id": m["message_id"]}

    def attachments(self, item):
        def saver(name, data):
            def save(path):
                self.saves.append(name)
                Path(path).write_bytes(data)
            return save
        return [Attachment(n, len(d), saver(n, d)) for n, d in item.ref["attachments"]]

    def probe_summary(self):
        n = sum(len(v) for (s, f), v in self.msgs.items() if f == "Inbox" and any(x.id == s and x.cached for x in self.store_list))
        return {"classic_outlook": True, "inbox_count": n, "subject_read": n > 0, "stores": [{"name": s.name, "cached": s.cached} for s in self.store_list]}
