"""Ingest: the classic-Outlook source over a fake object model (no Outlook, no mailbox), the policy reader, label parsing."""
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import harness as H  # noqa: E402,F401  (puts scripts/ on sys.path)
from fakes import fake_com as F  # noqa: E402
import mailsource  # noqa: E402
import outlook_com  # noqa: E402

try:
    import pywintypes
except ImportError:  # pywin32 is pinned for Windows; a missing module is a failure when everything is required
    pywintypes = None

UTC = timezone.utc


def com_error(hr, text):
    return pywintypes.com_error(hr, text, None, None)


class Denied(F.Obj):
    @property
    def Body(self):
        raise com_error(-2147024891, "Access is denied.")


def world():
    inbox_rows = [F.mail("e1", "c1", "First", datetime(2026, 10, 1, 9, 0, tzinfo=UTC), datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
                         props={outlook_com.P_HEADERS: "Received: x\r\nmsip_labels: MSIP_Label_0000-aaaa_Enabled=true; MSIP_Label_0000-aaaa_Name=Confidential;\r\n MSIP_Label_0000-aaaa_SetDate=2026;\r\nSubject: y", outlook_com.P_MSGID: "<e1@example.com>"}),
                  F.mail("e2", "c1", "Second", datetime(2026, 10, 1, 10, 0, tzinfo=UTC), datetime(2026, 10, 2, 10, 0, tzinfo=UTC),
                         props={outlook_com.P_HEADERS: com_error(-2147352567, "The property is unknown or could not be found."), outlook_com.P_MSGID: com_error(-2147352567, "unknown")}),
                  F.mail("e3", "c2", "A meeting", datetime(2026, 10, 3, 9, 0, tzinfo=UTC), datetime(2026, 10, 3, 9, 0, tzinfo=UTC), MessageClass="IPM.Schedule.Meeting.Request")]
    projects = F.Folder("Projects", "f-proj", rows=[F.mail("e4", "c3", "Nested", datetime(2026, 10, 4, 9, 0, tzinfo=UTC), datetime(2026, 10, 4, 9, 0, tzinfo=UTC))])
    inbox = F.Folder("Inbox", "f-inbox", children=[projects], rows=inbox_rows)
    cal = F.Folder("Calendar", "f-cal", kind=1)
    return F.Namespace([F.Store("s1", "Mailbox A", True, 0, [inbox, cal]), F.Store("s2", "Online Archive", False, 0), F.Store("s3", "Public Folders", False, 3)])


class OutlookComTests(unittest.TestCase):
    def setUp(self):
        if pywintypes is None and REQUIRE:
            self.fail("pywin32 is required: pip install -r requirements.txt")
        self.skipTest("pywin32 not installed") if pywintypes is None else None
        self.ns = world()
        self.com = outlook_com.OutlookCom(self.ns)

    def test_only_cached_exchange_stores_are_offered_and_only_mail_folders_listed(self):
        self.assertEqual([(s.name, s.cached) for s in self.com.stores()], [("Mailbox A", True), ("Online Archive", False), ("Public Folders", False)])
        self.assertEqual([f.path for f in self.com.folders(self.com.stores()[0])], ["Inbox", "Inbox/Projects"])

    def test_items_are_mail_only_ordered_and_bounded_by_the_checkpoint(self):
        (store, *_) = self.com.stores()
        inbox = self.com.folders(store)[0]
        got = list(self.com.items(inbox, None, set()))
        self.assertEqual([(i.entry_id, i.modified) for i in got], [("e1", "2026-10-01T09:00:00Z"), ("e2", "2026-10-02T10:00:00Z")])
        self.assertEqual(got[0].received, "2026-10-01T09:00:00Z")
        later = list(self.com.items(inbox, "2026-10-01T09:00:00Z", {"e1"}))
        self.assertEqual([i.entry_id for i in later], ["e2"])
        self.assertEqual([i.entry_id for i in self.com.items(inbox, "2026-10-01T09:00:00Z", set())], ["e1", "e2"])
        self.assertEqual([i.entry_id for i in self.com.items(inbox, "2026-10-02T00:00:00Z", set())], ["e2"])

    def test_the_restrict_filter_uses_the_documented_date_format(self):
        seen = []
        orig = F.Items.Restrict
        F.Items.Restrict = lambda self, spec: (seen.append(spec), orig(self, spec))[1]
        self.addCleanup(setattr, F.Items, "Restrict", orig)
        inbox = self.com.folders(self.com.stores()[0])[0]
        list(self.com.items(inbox, "2026-10-02T10:00:00Z", set()))
        self.assertRegex(seen[0], r"^\[LastModificationTime\] >= '\d\d/\d\d/2026 \d\d:\d\d (AM|PM)'$")

    def test_body_returns_the_sender_recipients_and_message_id_and_headers_only_skips_the_text(self):
        inbox = self.com.folders(self.com.stores()[0])[0]
        a, b = list(self.com.items(inbox, None, set()))
        full = self.com.body(a)
        self.assertEqual((full["text"], full["html"], full["from"], full["to"], full["message_id"]),
                         ("plain body", "<p>html body</p>", "Alice Example <alice@example.com>", ["Bob Sample", "Carol Test"], "<e1@example.com>"))
        hdr = self.com.body(a, headers_only=True)
        self.assertEqual((hdr["text"], hdr["html"], hdr["from"]), (None, None, "Alice Example <alice@example.com>"))
        self.assertIsNone(self.com.body(b)["message_id"])  # a missing id is common and is not a stop

    def test_a_refused_body_read_is_a_policy_block(self):
        item = list(self.com.items(self.com.folders(self.com.stores()[0])[0], None, set()))[0]
        item.ref.__class__ = Denied
        with self.assertRaises(mailsource.PolicyBlock):
            self.com.body(item)

    def test_labels_come_from_the_transport_headers_and_a_refusal_is_a_stop(self):
        a, b = list(self.com.items(self.com.folders(self.com.stores()[0])[0], None, set()))
        self.assertEqual(self.com.labels(a), ["Confidential"])
        self.assertEqual(self.com.labels(b), [])  # no headers on this item
        a.ref.PropertyAccessor.values[outlook_com.P_HEADERS] = com_error(-2147024891, "Access is denied.")
        with self.assertRaises(mailsource.PolicyBlock):
            self.com.labels(a)

    def test_attachments_are_listed_and_a_failed_save_is_a_stop(self):
        saved = []

        class Att:
            FileName, Size = "agenda.txt", 12

            def SaveAsFile(self, path):
                saved.append(path)

        a = list(self.com.items(self.com.folders(self.com.stores()[0])[0], None, set()))[0]
        a.ref.Attachments = [Att()]
        (att,) = self.com.attachments(a)
        self.assertEqual((att.name, att.size, saved), ("agenda.txt", 12, []))  # listing writes nothing
        att.save("x.txt")
        self.assertEqual(saved, ["x.txt"])
        Att.SaveAsFile = lambda self, p: (_ for _ in ()).throw(com_error(-2147467260, "Operation aborted"))
        with self.assertRaises(mailsource.PolicyBlock):
            att.save("y.txt")

    def test_probe_summary(self):
        s = self.com.probe_summary()
        self.assertEqual((s["classic_outlook"], s["inbox_count"], s["subject_read"]), (True, 3, True))


class HelperTests(unittest.TestCase):
    def test_parse_labels(self):
        h = "X: 1\r\nmsip_labels: MSIP_Label_aaaa-1_Enabled=true; MSIP_Label_aaaa-1_Name=Highly Confidential;\r\n MSIP_Label_aaaa-1_Method=Standard;\r\nY: 2"
        self.assertEqual(outlook_com.parse_labels(h), ["Highly Confidential"])
        self.assertEqual(outlook_com.parse_labels("msip_labels: MSIP_Label_bbbb-2_Enabled=true;"), ["bbbb-2"])
        self.assertEqual(outlook_com.parse_labels("Subject: none\r\n"), [])
        self.assertEqual(outlook_com.parse_labels(None), [])

    def test_naive_com_times_are_local_times(self):
        naive = datetime(2026, 10, 1, 9, 0)
        self.assertEqual(outlook_com._utc(naive), naive.astimezone().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_the_policy_reader_only_opens_keys_for_reading(self):
        class Reg:
            HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, KEY_READ = "HKCU", "HKLM", 0x20019
            opened = []

            @classmethod
            def OpenKey(cls, hive, path, res, access):
                cls.opened.append((hive, path, access))
                if hive == "HKLM":
                    raise OSError
                return cls()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            @staticmethod
            def QueryValueEx(key, name):
                if name in ("PromptOOMSend", "AdminSecurityMode"):
                    return ({"PromptOOMSend": 2, "AdminSecurityMode": 3}[name], 4)
                raise OSError

        pol = outlook_com.read_policy(Reg)
        self.assertEqual(pol, {"HKCU:AdminSecurityMode": 3, "HKCU:PromptOOMSend": 2})
        self.assertTrue(all(a == Reg.KEY_READ and p == outlook_com.POLICY_KEY for _, p, a in Reg.opened))
        self.assertEqual(outlook_com.auto_denied(pol), ["HKCU:PromptOOMSend"])


if __name__ == "__main__":
    unittest.main()
