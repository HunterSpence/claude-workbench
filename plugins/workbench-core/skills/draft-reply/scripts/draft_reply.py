#!/usr/bin/env python3
"""draft_reply.py: read an email thread and turn a reply you wrote (JSON) into plain text, HTML, an
optional .eml draft file, or an optional Outlook draft. It has no way to send anything.

  python draft_reply.py read <thread.eml|thread.msg|thread.txt>
  python draft_reply.py render <reply.json> --out DIR [--thread FILE] [--eml] [--chat] [--reply-all --me ADDR]
  python draft_reply.py outlook <reply.json> [--thread FILE] [--reply-all]     opt-in; saves a draft, never sends

reply.json:
{
  "to": ["sam@example.com"], "cc": [],        optional; default = the thread's Reply-To, else its sender
  "subject": "...",                           optional; default = "Re: <thread subject>"
  "greeting": "Hi Sam,",
  "answer": ["The answer first, in one or two short paragraphs."],
  "points": [{"lead": "Scope", "text": "the point itself"}],  optional; "lead" optional too
  "asks": [{"owner": "Sam", "ask": "confirm the cut-over window", "due": "Fri 10 Oct"}],  optional
  "closing": "Thanks,", "signature": "<Your name>",
  "quote_name": "...", "quote_date": "..."    only for a pasted .txt thread (no headers to read)
}
Recipients follow the thread's headers: a reply goes to Reply-To when the thread sets it, else to the
sender; a reply-all goes to Mail-Followup-To when set, else to the sender plus To and Cc. You are left out.
.msg files need olefile (BSD); everything else is the Python standard library.
"""
import argparse, html, json, os, re, subprocess, sys, tempfile
from email import message_from_binary_file, policy
from email.message import EmailMessage
from email.parser import HeaderParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

RE_PREFIX = re.compile(r"^\s*(re|aw|sv|vs|antw|ref)\s*:", re.I)


class _Text(HTMLParser):
    """HTML -> readable text: block tags become newlines, script/style dropped."""
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(s):
    p = _Text()
    p.feed(s)
    text = re.sub(r"[ \t\xa0]+", " ", "".join(p.out))
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def _msg_fields(ole):
    """Read the MAPI properties we need from an olefile.OleFileIO of a .msg file."""
    def prop(code):
        for suffix, enc in (("001F", "utf-16-le"), ("001E", "cp1252")):
            name = f"__substg1.0_{code}{suffix}"
            if ole.exists(name):
                return ole.openstream(name).read().decode(enc, "replace").rstrip("\x00")
        return ""
    headers = HeaderParser().parsestr(prop("007D")) if prop("007D") else {}
    body = prop("1000") or html_to_text(prop("1013"))
    return {"subject": prop("0037"), "from_name": prop("0C1A"), "from_addr": prop("0C1F") or prop("5D01"),
            "date": headers.get("Date", "") if headers else "", "message_id": headers.get("Message-ID", "") if headers else "",
            "references": headers.get("References", "") if headers else "",
            "reply_to": headers.get("Reply-To", "") if headers else "",
            "followup_to": headers.get("Mail-Followup-To", "") if headers else "",
            "to": prop("0E04"), "cc": prop("0E03"), "body": body}


def read_thread(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".msg":
        try:
            import olefile
        except ImportError:
            raise SystemExit(".msg needs olefile: pip install --user -r requirements.txt (or save the mail as .eml)")
        ole = olefile.OleFileIO(path)
        try:
            return _msg_fields(ole)
        finally:
            ole.close()
    if ext == ".eml":
        with open(path, "rb") as f:
            m = message_from_binary_file(f, policy=policy.default)
        part = m.get_body(preferencelist=("plain", "html"))
        body = "" if part is None else part.get_content()
        if part is not None and part.get_content_type() == "text/html":
            body = html_to_text(body)
        (name, addr), = getaddresses([str(m.get("From", ""))]) or [("", "")]
        return {"subject": str(m.get("Subject", "")), "from_name": name, "from_addr": addr, "date": str(m.get("Date", "")),
                "message_id": str(m.get("Message-ID", "")), "references": str(m.get("References", "")),
                "reply_to": str(m.get("Reply-To", "")), "followup_to": str(m.get("Mail-Followup-To", "")),
                "to": str(m.get("To", "")), "cc": str(m.get("Cc", "")), "body": body.strip()}
    with open(path, encoding="utf-8", errors="replace") as f:
        return {"subject": "", "from_name": "", "from_addr": "", "date": "", "message_id": "", "references": "",
                "reply_to": "", "followup_to": "", "to": "", "cc": "", "body": f.read().strip()}


def quote_header(t, reply):
    name = reply.get("quote_name") or t.get("from_name") or t.get("from_addr") or "<name>"
    when = reply.get("quote_date") or t.get("date") or "<date>"
    try:
        d = parsedate_to_datetime(when)
        when = f"{d:%a}, {d.day} {d:%b %Y} at {d:%H:%M}" + _zone(d)
    except (TypeError, ValueError, IndexError):
        pass
    return f"On {when}, {name} wrote:"


def _zone(d):
    """' UTC' or ' UTC+05:30' from the message's own offset; nothing when the date carries none (-0000)."""
    off = d.utcoffset()
    if off is None:
        return ""
    mins = int(off.total_seconds() // 60)
    if not mins:
        return " UTC"
    sign, mins = ("+" if mins > 0 else "-"), abs(mins)
    return f" UTC{sign}{mins // 60:02d}:{mins % 60:02d}"


def compose(reply, thread=None, chat=False):
    """-> (text, html). The answer comes first, then points, then asks with owners and dates."""
    t = thread or {}
    esc = html.escape
    tx, hx = [], ['<div>']
    if reply.get("greeting") and not chat:
        tx.append(reply["greeting"])
        hx.append(f"<p>{esc(reply['greeting'])}</p>")
    for para in reply.get("answer", []):
        tx.append(para)
        hx.append(f"<p>{esc(para)}</p>")
    if reply.get("points"):
        def lead(p):
            return f"{p['lead']}: " if p.get("lead") else ""
        tx.append("\n".join(f"- {lead(p)}{p['text']}" for p in reply["points"]))
        hx.append("<ul>" + "".join(f"<li>{esc(lead(p) + p['text'])}</li>" for p in reply["points"]) + "</ul>")
    if reply.get("asks"):
        def due(a):
            return f" (by {a['due']})" if a.get("due") else ""
        tx.append("Next steps:\n" + "\n".join(f"- {a['owner']}: {a['ask']}{due(a)}" for a in reply["asks"]))
        hx.append("<p>Next steps:</p><ul>" + "".join(
            f"<li>{esc(a['owner'])}: {esc(a['ask'])}{esc(due(a))}</li>" for a in reply["asks"]) + "</ul>")
    if not chat:
        sig = reply.get("signature") or "<Your name>"
        closing = reply.get("closing", "Thanks,")
        tx.append(f"{closing}\n{sig}")
        hx.append(f"<p>{esc(closing)}<br>{esc(sig)}</p>")
    hx.append("</div>")
    text, body = "\n\n".join(tx), "\n".join(hx)
    if t.get("body") and not chat:
        qh = quote_header(t, reply)
        text += f"\n\n{qh}\n" + "\n".join("> " + ln for ln in t["body"].splitlines())
        body += (f'\n<div class="quote"><p>{esc(qh)}</p><blockquote>'
                 f'{esc(t["body"]).replace(chr(10), "<br>")}</blockquote></div>')
    return text, body


def _addrs(header):
    return [a for _, a in getaddresses([header or ""]) if a]


def recipients(reply, t, reply_all=False, me=""):
    """Explicit `to`/`cc` in reply.json win. Otherwise: Reply-To, else the sender; for reply-all,
    Mail-Followup-To when the thread sets it (the sender's own list of who should get follow-ups),
    else the sender plus the thread's To and Cc. Your own address is always left out."""
    mine = me.lower()
    if reply.get("to"):
        to = list(reply["to"])
    elif reply_all and t.get("followup_to"):
        to = [a for a in _addrs(t["followup_to"]) if a.lower() != mine]
    else:
        to = _addrs(t.get("reply_to")) or ([t["from_addr"]] if t.get("from_addr") else [])
    cc = list(reply.get("cc") or [])
    if reply_all and not (t.get("followup_to") and not reply.get("to")):
        seen = {a.lower() for a in [me] + to + cc if a}
        for addr in _addrs(t.get("from_addr")) + _addrs(t.get("to")) + _addrs(t.get("cc")):
            if addr.lower() not in seen:
                cc.append(addr)
                seen.add(addr.lower())
    return to, cc


def subject_for(reply, t):
    s = reply.get("subject") or t.get("subject") or ""
    return s if RE_PREFIX.match(s) or not s else "Re: " + s


def eml_draft(reply, t, text, body, reply_all=False, me=""):
    m = EmailMessage()
    to, cc = recipients(reply, t, reply_all, me)
    if to:
        m["To"] = ", ".join(to)
    if cc:
        m["Cc"] = ", ".join(cc)
    m["Subject"] = subject_for(reply, t)
    if t.get("message_id"):
        m["In-Reply-To"] = t["message_id"]
        m["References"] = " ".join(x for x in (t.get("references", ""), t["message_id"]) if x)
    m["X-Unsent"] = "1"   # Outlook and other clients open the file as an unsent draft to edit
    m.set_content(text)
    m.add_alternative(body, subtype="html")
    return m


# The Outlook path saves a draft and nothing else. There is deliberately no send, no deferred
# delivery and no reply-all unless asked; tests check this file for those calls.
OUTLOOK_PS = r"""
$o = New-Object -ComObject Outlook.Application
$ours = Get-Content -Raw -Encoding UTF8 -LiteralPath $env:DR_HTML
if ($env:DR_THREAD) {
  $src = $o.Session.OpenSharedItem($env:DR_THREAD)
  $m = $src.{REPLY}()
  $h = $m.HTMLBody; $i = $h.IndexOf('<body', [StringComparison]::OrdinalIgnoreCase)
  if ($i -ge 0) { $j = $h.IndexOf('>', $i) + 1; $m.HTMLBody = $h.Insert($j, $ours) } else { $m.HTMLBody = $ours + $h }
} else {
  $m = $o.CreateItem(0)
  $m.Subject = $env:DR_SUBJECT
  if ($env:DR_TO) { $m.To = $env:DR_TO }
  if ($env:DR_CC) { $m.CC = $env:DR_CC }
  $m.HTMLBody = $ours
}
$m.Save()
"saved to Drafts: " + $m.Subject
"""


def outlook_script(reply_all=False):
    return OUTLOOK_PS.replace("{REPLY}", "ReplyAll" if reply_all else "Reply")


def outlook_draft(reply, t, thread_path, text, body, reply_all=False, me=""):
    if os.name != "nt":
        raise SystemExit("Outlook drafts need Windows with classic Outlook; use --eml instead")
    msg_thread = thread_path if thread_path and thread_path.lower().endswith(".msg") else ""
    if msg_thread:
        _, body = compose(reply, None)          # Outlook's own reply carries the quoted thread
    to, cc = recipients(reply, t, reply_all, me)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(body)
    env = dict(os.environ, DR_HTML=f.name, DR_THREAD=os.path.abspath(msg_thread) if msg_thread else "",
               DR_SUBJECT=subject_for(reply, t), DR_TO="; ".join(to), DR_CC="; ".join(cc))
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", outlook_script(reply_all)],
                           env=env, capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(f.name)
    if r.returncode != 0:
        raise SystemExit("Outlook automation failed (it may be blocked by policy, or this is the new Outlook, "
                         f"which has no COM): {(r.stderr or r.stdout).strip()[:300]}. Use --eml instead.")
    print(r.stdout.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draft replies. Never sends.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rd = sub.add_parser("read")
    rd.add_argument("thread")
    for name in ("render", "outlook"):
        p = sub.add_parser(name)
        p.add_argument("reply")
        p.add_argument("--thread")
        p.add_argument("--reply-all", action="store_true", help="only when the user explicitly asked to reply to all")
        p.add_argument("--me", default="", help="your own address, left out of reply-all")
        if name == "render":
            p.add_argument("--out", required=True)
            p.add_argument("--eml", action="store_true")
            p.add_argument("--chat", action="store_true", help="short chat reply: no greeting, signature or quote")
    a = ap.parse_args(argv)
    if a.cmd == "read":
        t = read_thread(a.thread)
        for k in ("subject", "from_name", "from_addr", "date", "to", "cc", "message_id"):
            if t.get(k):
                print(f"{k}: {t[k]}")
        print("\n" + t["body"])
        return 0
    with open(a.reply, encoding="utf-8") as f:
        reply = json.load(f)
    t = read_thread(a.thread) if a.thread else {}
    text, body = compose(reply, t, chat=getattr(a, "chat", False))
    if a.cmd == "outlook":
        outlook_draft(reply, t, a.thread, text, body, a.reply_all, a.me)
        return 0
    os.makedirs(a.out, exist_ok=True)
    paths = [os.path.join(a.out, "reply.txt"), os.path.join(a.out, "reply.html")]
    for p, content in zip(paths, (text, body)):
        with open(p, "w", encoding="utf-8") as f:
            f.write(content + "\n")
    if a.eml:
        paths.append(os.path.join(a.out, "reply.eml"))
        with open(paths[-1], "wb") as f:
            f.write(bytes(eml_draft(reply, t, text, body, a.reply_all, a.me)))
    print("\n".join(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
