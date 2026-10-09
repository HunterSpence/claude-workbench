"""Classic Outlook over COM (pywin32), read-only, for the cached window only.

Rules this module keeps: only stores with IsCachedExchange true are offered; every call reads (nothing is sent, moved,
deleted, flagged or saved into the mailbox); a protected read that raises, is denied or waits on a security prompt is a
PolicyBlock, which ends the run. There is no prompt-bypass library, no registry write, no retry by another route.
Run as a script (`python outlook_com.py --body-probe`) it is the child process of `mail probe`."""
import json
import re
import sys
from datetime import datetime, timezone

from common import iso
from mailsource import Attachment, Folder, Item, MailSource, PolicyBlock, Store

POLICY_KEY = r"Software\Policies\Microsoft\Office\16.0\Outlook\Security"
POLICY_NAMES = ("AdminSecurityMode", "PromptOOMAddressInformationAccess", "PromptOOMAddressBookAccess", "PromptOOMSend",
                "PromptOOMSaveAs", "PromptOOMFormulaAccess", "PromptOOMMeetingTaskRequestResponse", "PromptOOMCustomAction")
P_HEADERS = "http://schemas.microsoft.com/mapi/proptag/0x007D001E"
P_MSGID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
OL_INBOX = 6


def read_policy(winreg=None):
    """{'HKCU:Name': value, ...} for the Outlook security policy values that are set. Read-only (KEY_READ)."""
    if winreg is None:
        try:
            import winreg
        except ImportError:
            return {}
    out = {}
    for label, hive in (("HKCU", winreg.HKEY_CURRENT_USER), ("HKLM", winreg.HKEY_LOCAL_MACHINE)):
        try:
            key = winreg.OpenKey(hive, POLICY_KEY, 0, winreg.KEY_READ)
        except OSError:
            continue
        with key:
            for name in POLICY_NAMES:
                try:
                    out[f"{label}:{name}"] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    pass
    return out


def auto_denied(policy):
    """The programmatic-access prompts a policy sets to 'automatically deny' (2)."""
    return sorted(k for k, v in policy.items() if ":PromptOOM" in k and v == 2)


def _denied(exc):
    code = getattr(exc, "hresult", None)
    return (code is not None and (code & 0xFFFFFFFF) in (0x80070005, 0x80004004)) or bool(re.search(r"denied|security|blocked|not allowed|prompt|abort", str(exc), re.I))


def _utc(dt):
    return iso(dt if dt.tzinfo else dt.astimezone())  # a naive COM time is local time


def _names(s):
    return [x.strip() for x in str(s or "").split(";") if x.strip()]


def parse_labels(headers):
    """Sensitivity label names from a msip_labels header (falls back to the label id when no name is given)."""
    m = re.search(r"(?im)^msip_labels:\s*(.*(?:\r?\n[ \t].*)*)", headers or "")
    if not m:
        return []
    blob = re.sub(r"\r?\n[ \t]+", "", m.group(1))
    named = {g.lower(): n.strip() for g, n in re.findall(r"MSIP_Label_([0-9a-f-]+)_Name=([^;]*)", blob, re.I)}
    enabled = {g.lower() for g in re.findall(r"MSIP_Label_([0-9a-f-]+)_Enabled=true", blob, re.I)}
    return sorted({n or g for g, n in named.items()} | {g for g in enabled if g not in named})


class OutlookCom(MailSource):
    def __init__(self, ns=None):
        if ns is None:
            import win32com.client  # pywin32; classic Outlook only (the new Outlook has no object model)
            ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        self.ns = ns

    def _store(self, store_id):
        return next(s for s in self.ns.Stores if s.StoreID == store_id)

    def stores(self):
        return [Store(s.StoreID, s.DisplayName, bool(getattr(s, "IsCachedExchange", False)) and getattr(s, "ExchangeStoreType", 0) != 3)
                for s in self.ns.Stores]

    def folders(self, store):
        out = []

        def walk(f, prefix):
            for sub in f.Folders:
                if sub.DefaultItemType == 0:  # mail folders only
                    out.append(Folder(store.id, sub.EntryID, prefix + sub.Name))
                    walk(sub, f"{prefix}{sub.Name}/")
        walk(self._store(store.id).GetRootFolder(), "")
        return out

    def items(self, folder, since, after_entry_ids):
        its = self.ns.GetFolderFromID(folder.id, folder.store_id).Items
        its.Sort("[LastModificationTime]")
        if since:
            local = datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
            its = its.Restrict("[LastModificationTime] >= '%s'" % local.strftime("%m/%d/%Y %I:%M %p"))  # minute resolution
        x = its.GetFirst()
        while x is not None:
            cls = str(x.MessageClass or "")
            if cls.startswith("IPM.Note"):
                it = Item(x.EntryID, x.ConversationID or "", x.Subject or "", _utc(x.ReceivedTime), _utc(x.LastModificationTime), cls, x)
                if not since or it.modified > since or (it.modified == since and it.entry_id not in after_entry_ids):
                    yield it
            x = its.GetNext()

    def _sender(self, x):
        name, addr = x.SenderName, x.SenderEmailAddress
        if x.SenderEmailType != "SMTP":
            try:
                u = x.Sender.GetExchangeUser()
                addr = u.PrimarySmtpAddress if u else None
            except Exception as e:
                if _denied(e):
                    raise
                addr = None
        return f"{name} <{addr}>" if addr else str(name or "")

    def body(self, item, headers_only=False):
        x = item.ref
        try:  # any failure of a protected read ends the run: a refusal and a prompt look alike from here
            sender, to, cc = self._sender(x), _names(x.To), _names(x.CC)
            text, html = (None, None) if headers_only else (x.Body, x.HTMLBody)
        except Exception as e:
            raise PolicyBlock(f"a protected mail property could not be read ({type(e).__name__})") from e
        try:  # ponytail: a missing Internet Message-ID is common (drafts); only a refusal stops the run
            mid = x.PropertyAccessor.GetProperty(P_MSGID) or None
        except Exception as e:
            if _denied(e):
                raise PolicyBlock("the message id could not be read (access refused)") from e
            mid = None
        return {"text": text, "html": html, "from": sender, "to": to, "cc": cc, "message_id": mid}

    def attachments(self, item):
        out = []
        try:
            for a in item.ref.Attachments:
                out.append(Attachment(a.FileName, int(a.Size or 0), self._saver(a)))
        except Exception as e:
            raise PolicyBlock(f"attachments could not be listed ({type(e).__name__})") from e
        return out

    @staticmethod
    def _saver(a):
        def save(path):
            try:
                a.SaveAsFile(path)
            except Exception as e:
                raise PolicyBlock(f"an attachment could not be saved ({type(e).__name__})") from e
        return save

    def labels(self, item):
        try:
            return parse_labels(item.ref.PropertyAccessor.GetProperty(P_HEADERS))
        except Exception as e:
            if _denied(e):
                raise PolicyBlock("the message headers could not be read (access refused)") from e
            return []  # no transport headers (a sent or draft item): nothing to read

    def probe_summary(self):
        inbox = self.ns.GetDefaultFolder(OL_INBOX)
        n = int(inbox.Items.Count)
        first = inbox.Items.GetFirst() if n else None
        return {"classic_outlook": True, "inbox_count": n, "subject_read": bool(first is not None and first.Subject is not None),
                "stores": [{"name": s.name, "cached": s.cached} for s in self.stores()]}


def _body_probe():
    """Child process of `mail probe`: read one body from the Inbox and print only that it worked."""
    ns = OutlookCom().ns
    first = ns.GetDefaultFolder(OL_INBOX).Items.GetFirst()
    n = len(first.Body) if first is not None else 0  # a security prompt, if any, appears here and blocks
    print(json.dumps({"ok": True, "chars": n}))


if __name__ == "__main__":
    if sys.argv[1:] == ["--body-probe"]:
        _body_probe()
    else:
        sys.exit("usage: outlook_com.py --body-probe")
