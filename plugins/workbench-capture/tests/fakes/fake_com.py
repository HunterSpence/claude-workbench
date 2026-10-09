"""A minimal fake of the Outlook object model, just enough for OutlookCom: stores, folders, Items.Sort/Restrict/GetFirst,
mail items with protected properties that can be made to fail, attachments."""
import re
from datetime import datetime


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Prop:
    def __init__(self, values):
        self.values = values

    def GetProperty(self, tag):
        v = self.values[tag]
        if isinstance(v, Exception):
            raise v
        return v


class Items:
    def __init__(self, rows):
        self.rows, self.i, self.restrict_calls = list(rows), 0, []

    @property
    def Count(self):
        return len(self.rows)

    def Sort(self, spec):
        self.rows.sort(key=lambda x: x.LastModificationTime)

    def Restrict(self, spec):
        self.restrict_calls.append(spec)
        m = re.search(r"'(\d\d)/(\d\d)/(\d{4}) (\d\d):(\d\d) (AM|PM)'", spec)
        lo = datetime.strptime(" ".join(m.groups()[:3]) + f" {m.group(4)}:{m.group(5)} {m.group(6)}", "%m %d %Y %I:%M %p")
        out = Items([x for x in self.rows if x.LastModificationTime.astimezone().replace(tzinfo=None) >= lo])
        out.restrict_calls = self.restrict_calls
        return out

    def GetFirst(self):
        self.i = 0
        return self.GetNext()

    def GetNext(self):
        self.i += 1
        return self.rows[self.i - 1] if self.i <= len(self.rows) else None


class Folder:
    def __init__(self, name, entry_id, kind=0, children=(), rows=()):
        self.Name, self.EntryID, self.DefaultItemType, self.Folders, self.Items = name, entry_id, kind, list(children), Items(rows)


class Store:
    def __init__(self, sid, name, cached=True, kind=0, folders=()):
        self.StoreID, self.DisplayName, self.IsCachedExchange, self.ExchangeStoreType = sid, name, cached, kind
        self.root = Folder("root", "root-" + sid, children=folders)

    def GetRootFolder(self):
        return self.root


class Namespace:
    def __init__(self, stores):
        self.Stores = stores

    def GetFolderFromID(self, fid, store_id):
        def walk(f):
            if f.EntryID == fid:
                return f
            for c in f.Folders:
                r = walk(c)
                if r:
                    return r
        return walk(next(s for s in self.Stores if s.StoreID == store_id).root)

    def GetDefaultFolder(self, which):
        return next(c for c in self.Stores[0].root.Folders if c.Name == "Inbox")


def mail(entry_id, conv, subject, received, modified, props=None, **kw):
    base = dict(EntryID=entry_id, ConversationID=conv, Subject=subject, ReceivedTime=received, LastModificationTime=modified, MessageClass="IPM.Note",
                SenderName="Alice Example", SenderEmailAddress="alice@example.com", SenderEmailType="SMTP", To="Bob Sample; Carol Test", CC="",
                Body="plain body", HTMLBody="<p>html body</p>", Attachments=[], PropertyAccessor=Prop(props or {}))
    base.update(kw)
    return Obj(**base)
