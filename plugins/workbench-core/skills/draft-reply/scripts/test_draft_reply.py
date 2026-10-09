import json, os, re, shutil, sys, tempfile, unittest
from email import message_from_bytes, policy
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import draft_reply as dr  # noqa: E402

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "draft_reply.py"), encoding="utf-8").read()
REPLY = {"greeting": "Hi Sam,", "answer": ["Yes, Friday works.", "The <script>alert(1)</script> test passed."],
         "points": [{"lead": "Scope", "text": "API only"}],
         "asks": [{"owner": "Sam", "ask": "confirm the window", "due": "Thu 9 Oct"}, {"owner": "Me", "ask": "send notes"}],
         "signature": "<Your name>"}


class DraftReplyTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        m = EmailMessage()
        m["From"] = "Sam Example <sam@example.com>"
        m["To"] = "me@example.com, ari@example.com"
        m["Cc"] = "kim@example.com"
        m["Subject"] = "Re: Cut-over plan"
        m["Date"] = "Wed, 09 Oct 2024 14:05:00 +0000"
        m["Message-ID"] = "<abc@example.com>"
        m["References"] = "<first@example.com>"
        m.set_content("plain fallback")
        m.add_alternative("<html><body><p>Can we do <b>Friday</b>?</p><style>x{}</style></body></html>", subtype="html")
        # html-preferred body: make the plain part absent so the reader must convert HTML
        m.get_body(("plain",)).set_content("")
        self.eml = os.path.join(self.d, "t.eml")
        with open(self.eml, "wb") as f:
            f.write(bytes(m))
        self.reply = os.path.join(self.d, "reply.json")
        with open(self.reply, "w", encoding="utf-8") as f:
            json.dump(REPLY, f)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_read_eml(self):
        t = dr.read_thread(self.eml)
        self.assertEqual(t["from_addr"], "sam@example.com")
        self.assertEqual(t["message_id"], "<abc@example.com>")
        self.assertEqual(dr.html_to_text("<p>Can we do <b>Friday</b>?</p><style>x{}</style>"), "Can we do Friday?")

    def test_compose_order_quote_and_escaping(self):
        t = {"from_name": "Sam Example", "date": "Wed, 09 Oct 2024 14:05:00 +0000", "body": "Can we do Friday?\n<b>x</b>"}
        text, body = dr.compose(REPLY, t)
        self.assertLess(text.index("Yes, Friday works."), text.index("Next steps:"), "answer comes before asks")
        self.assertIn("- Sam: confirm the window (by Thu 9 Oct)", text)
        self.assertIn("On Wed, 9 Oct 2024 at 14:05 UTC, Sam Example wrote:\n> Can we do Friday?", text)
        self.assertTrue(body.startswith('<div>'))
        self.assertIn("<li>Sam: confirm the window (by Thu 9 Oct)</li>", body)
        self.assertIn("<li>Scope: API only</li>", body)
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", body, "quoted text is escaped too")
        self.assertIn("&lt;Your name&gt;", body)
        chat, _ = dr.compose(REPLY, t, chat=True)
        self.assertNotIn("wrote:", chat)
        self.assertNotIn("Hi Sam", chat)

    def test_render_eml_draft(self):
        out = os.path.join(self.d, "out")
        self.assertEqual(dr.main(["render", self.reply, "--out", out, "--thread", self.eml, "--eml"]), 0)
        with open(os.path.join(out, "reply.eml"), "rb") as f:
            m = message_from_bytes(f.read(), policy=policy.default)
        self.assertEqual(m["Subject"], "Re: Cut-over plan", "no doubled Re:")
        self.assertEqual(m["In-Reply-To"], "<abc@example.com>")
        self.assertEqual(m["References"], "<first@example.com> <abc@example.com>")
        self.assertEqual(m["X-Unsent"], "1")
        self.assertEqual(m["To"], "sam@example.com")
        self.assertIsNone(m["Cc"], "plain reply goes to the sender only")
        self.assertEqual(m.get_content_type(), "multipart/alternative")
        self.assertEqual([p.get_content_type() for p in m.iter_parts()], ["text/plain", "text/html"])

    def test_reply_all_only_when_asked(self):
        t = dr.read_thread(self.eml)
        to, cc = dr.recipients({}, t)
        self.assertEqual((to, cc), (["sam@example.com"], []))
        to, cc = dr.recipients({}, t, reply_all=True, me="me@example.com")
        self.assertEqual(to, ["sam@example.com"])
        self.assertEqual(sorted(cc), ["ari@example.com", "kim@example.com"])

    def test_reply_to_and_followup_to(self):
        t = {"from_addr": "sam@example.com", "reply_to": "Help Desk <help@example.com>",
             "to": "me@example.com, ari@example.com", "cc": "kim@example.com"}
        self.assertEqual(dr.recipients({}, t), (["help@example.com"], []), "a plain reply honours Reply-To")
        to, cc = dr.recipients({}, t, reply_all=True, me="ME@example.com")
        self.assertEqual(to, ["help@example.com"])
        self.assertEqual(cc, ["sam@example.com", "ari@example.com", "kim@example.com"], "sender kept, me left out")
        t["followup_to"] = "list@example.com, me@example.com"
        self.assertEqual(dr.recipients({}, t, reply_all=True, me="me@example.com"), (["list@example.com"], []),
                         "reply-all follows Mail-Followup-To")
        self.assertEqual(dr.recipients({}, t), (["help@example.com"], []), "Mail-Followup-To is only for reply-all")
        self.assertEqual(dr.recipients({"to": ["x@example.com"]}, t), (["x@example.com"], []), "explicit to wins")
        m = EmailMessage()
        m["From"], m["Reply-To"], m["Mail-Followup-To"] = "sam@example.com", "help@example.com", "list@example.com"
        m["Subject"], m["Date"] = "Q", "Wed, 09 Oct 2024 14:05:00 +0530"
        m.set_content("hi")
        p = os.path.join(self.d, "rt.eml")
        with open(p, "wb") as f:
            f.write(bytes(m))
        r = dr.read_thread(p)
        self.assertEqual((r["reply_to"], r["followup_to"]), ("help@example.com", "list@example.com"))
        out = os.path.join(self.d, "o2")
        self.assertEqual(dr.main(["render", self.reply, "--out", out, "--thread", p, "--eml"]), 0)
        with open(os.path.join(out, "reply.eml"), "rb") as f:
            self.assertEqual(message_from_bytes(f.read(), policy=policy.default)["To"], "help@example.com")

    def test_quote_header_keeps_the_zone(self):
        q = lambda d: dr.quote_header({"from_name": "Sam", "date": d}, {})
        self.assertEqual(q("Wed, 09 Oct 2024 14:05:00 +0530"), "On Wed, 9 Oct 2024 at 14:05 UTC+05:30, Sam wrote:")
        self.assertEqual(q("Wed, 09 Oct 2024 14:05:00 -0400"), "On Wed, 9 Oct 2024 at 14:05 UTC-04:00, Sam wrote:")
        self.assertEqual(q("Wed, 09 Oct 2024 14:05:00 -0000"), "On Wed, 9 Oct 2024 at 14:05, Sam wrote:")
        self.assertEqual(q("not a date"), "On not a date, Sam wrote:")

    def test_never_sends(self):
        self.assertIsNone(re.search(r"\.send\s*\(", SRC, re.I), "no Send call anywhere")
        for banned in ("smtplib", "DeferredDeliveryTime", "send_message", "sendmail"):
            self.assertNotIn(banned.lower(), SRC.lower())
        self.assertIn("$m.Save()", dr.outlook_script())
        self.assertNotIn("ReplyAll", dr.outlook_script())
        self.assertIn("$src.ReplyAll()", dr.outlook_script(reply_all=True))
        with self.assertRaises(SystemExit):
            dr.main(["render", self.reply, "--out", self.d, "--send"])

    def test_msg_fields_from_stub(self):
        class Stub:
            def __init__(self, streams):
                self.s = streams

            def exists(self, n):
                return n in self.s

            def openstream(self, n):
                import io
                return io.BytesIO(self.s[n])
        u = lambda s: s.encode("utf-16-le")
        t = dr._msg_fields(Stub({
            "__substg1.0_0037001F": u("Cut-over plan"), "__substg1.0_0C1A001F": u("Sam Example"),
            "__substg1.0_0C1F001F": u("sam@example.com"), "__substg1.0_1000001F": u("Body text\x00"),
            "__substg1.0_007D001F": u("Date: Wed, 09 Oct 2024 14:05:00 +0000\r\nMessage-ID: <abc@example.com>\r\n\r\n"),
        }))
        self.assertEqual((t["subject"], t["from_addr"], t["body"]), ("Cut-over plan", "sam@example.com", "Body text"))
        self.assertEqual(t["message_id"], "<abc@example.com>")


if __name__ == "__main__":
    unittest.main()
