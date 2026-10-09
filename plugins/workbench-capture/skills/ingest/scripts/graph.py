"""A thin, read-only Microsoft Graph client (standard library only) for meeting transcripts and mail. SHOULD-level.

Sign-in is the device-code flow with the user's OWN tenant app registration (graph_client_id, graph_tenant_id); a
built-in or first-party client ID is refused. The refresh token lives only DPAPI-encrypted in
<WB>/state/ingest/graph-token.bin and is never printed. Every Graph data call is a GET; the only POSTs go to the sign-in
endpoints. A tenant gate (transcripts off, admin consent missing) is a hard stop with the ask-IT text, never a workaround.
WB_GRAPH_BASE (a http://localhost URL only) points the client at a fake server in tests."""
import base64
import ctypes
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import common
from common import Stop, atomic_write, inline, iso, load_json, safe_join, safe_name
from mailsource import Attachment, Folder, Item, MailSource, Store

LOGIN, GRAPH = "https://login.microsoftonline.com", "https://graph.microsoft.com/v1.0"
SCOPES_MEET = "offline_access Calendars.Read OnlineMeetings.Read OnlineMeetingTranscript.Read.All"
SCOPES_MAIL = SCOPES_MEET + " Mail.Read"
# Well-known first-party client ids (public in Microsoft's documentation). Never used, and refused when configured.
FIRST_PARTY = {"14d82eec-204b-4c2f-b7e8-296a70dab67e", "de8bc8b5-d9f9-48b1-a8ad-b748da725064", "04b07795-8ddb-461a-bbee-02f9e1bf7b46",
               "1950a258-227b-4e31-a9cf-717495945fc2", "d3590ed6-52b3-4102-aeff-aad2292ab01c", "1fec8e78-bce4-4aaf-ab1b-5451cc387264"}
BACKOFF_MIN = (15, 60, 240, 1440, 4320)  # between attempts to fetch a meeting's transcript; give up 7 days after it ended
MAIL_SELECT = "id,conversationId,subject,receivedDateTime,lastModifiedDateTime,from,toRecipients,ccRecipients,body,internetMessageId,hasAttachments,internetMessageHeaders"


class NotFound(Exception):
    pass


class SpeakerAttribution(Exception):
    pass


# ---- DPAPI token cache ------------------------------------------------------------------------------------------
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt(fn, data):
    if os.name != "nt":
        raise RuntimeError("the token cache needs Windows (DPAPI); Graph sign-in is not available on this system")
    buf = ctypes.create_string_buffer(data, len(data))
    inb, out = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    f = getattr(ctypes.windll.crypt32, fn)
    f.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_Blob)]
    f.restype = ctypes.c_int
    if not f(ctypes.byref(inb), None, None, None, None, 1, ctypes.byref(out)):  # 1 = no UI
        raise OSError("DPAPI refused the request")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def protect(data):
    return _crypt("CryptProtectData", data)


def unprotect(data):
    return _crypt("CryptUnprotectData", data)


def load_token(P):
    f = P.state / "graph-token.bin"
    try:
        return json.loads(unprotect(f.read_bytes()))
    except (OSError, ValueError, RuntimeError):
        return None


def save_token(P, tok):
    f = P.state / "graph-token.bin"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(protect(json.dumps(tok).encode()))


# ---- http -------------------------------------------------------------------------------------------------------
def endpoints(env):
    base = env.get("WB_GRAPH_BASE")
    if not base:
        return LOGIN, GRAPH
    u = urllib.parse.urlsplit(base)
    if u.scheme != "http" or u.hostname != "localhost":
        raise ValueError("WB_GRAPH_BASE may only point at http://localhost (it exists for tests)")
    return f"{base.rstrip('/')}/login", f"{base.rstrip('/')}/v1.0"


def _send(method, url, headers=None, form=None, timeout=60):
    """(status, headers, body bytes). HTTP errors are returned, not raised."""
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _err(body):
    try:
        e = json.loads(body).get("error") or {}
        return " ".join([str(e.get("code", "")), str(e.get("message", "")), str((e.get("innerError") or {}).get("code", ""))]) if isinstance(e, dict) else str(e)
    except (ValueError, AttributeError):
        return ""


class Graph:
    """Signed-in, read-only client. `get` is the only data call."""

    def __init__(self, P, S, env, hooks, scopes):
        self.P, self.S, self.scopes = P, S, scopes
        self.login, self.base = endpoints(env)
        self.sleep, self.say = hooks.get("sleep", time.sleep), hooks.get("say", print)
        self.pacer = hooks.get("pacer") or common.Pacer(gap=0.1, pause=1.0, sleep=self.sleep)
        self.calls = 0
        cid, tenant = S["graph_client_id"], S["graph_tenant_id"]
        if not (cid and tenant):
            raise ValueError("set graph_client_id and graph_tenant_id first (ingest.py config set ...): the app registration must be your own, made in your own tenant")
        if cid.lower() in FIRST_PARTY:
            raise ValueError("graph_client_id is a built-in or first-party client ID, which is refused: register your own single-tenant app")
        self.cid, self.tenant = cid, tenant
        self.tok = load_token(P)
        if not (self.tok and self.tok.get("client_id") == cid and self.tok.get("tenant") == tenant and set(scopes.split()) <= set(self.tok.get("scopes", "").split())):
            self.tok = None
        self.token()  # sign in now, so a refusal surfaces before any data call

    def _grant(self, form):
        st, _, b = _send("POST", f"{self.login}/{self.tenant}/oauth2/v2.0/token", form={"client_id": self.cid, **form})
        return st, json.loads(b or b"{}")

    def _store(self, j):
        self.tok = {"client_id": self.cid, "tenant": self.tenant, "scopes": self.scopes, "access_token": j["access_token"],
                    "refresh_token": j.get("refresh_token") or (self.tok or {}).get("refresh_token"), "expires_at": time.time() + int(j.get("expires_in", 3600))}
        save_token(self.P, self.tok)

    def _denied(self, j):
        text = f"{j.get('error', '')} {j.get('error_description', '')}"
        if re.search(r"AADSTS65001|AADSTS90094|AADSTS650057|consent_required|admin approval|need admin", text, re.I):
            raise Stop("consent", "the tenant requires administrator approval for this app", "admin-consent")

    def token(self):
        if self.tok and self.tok["expires_at"] - 60 > time.time():
            return self.tok["access_token"]
        if self.tok and self.tok.get("refresh_token"):
            st, j = self._grant({"grant_type": "refresh_token", "refresh_token": self.tok["refresh_token"], "scope": self.scopes})
            if st == 200:
                self._store(j)
                return self.tok["access_token"]
            self._denied(j)
            (self.P.state / "graph-token.bin").unlink(missing_ok=True)  # revoked or expired: sign in again
            self.tok = None
        return self._device_code()

    def _device_code(self):
        st, _, b = _send("POST", f"{self.login}/{self.tenant}/oauth2/v2.0/devicecode", form={"client_id": self.cid, "scope": self.scopes})
        d = json.loads(b or b"{}")
        if st != 200:
            self._denied(d)
            raise RuntimeError(f"sign-in could not start: {d.get('error', st)}")
        self.say(d.get("message") or f"To sign in, open {d['verification_uri']} and enter the code {d['user_code']}")
        deadline, interval = time.time() + int(d.get("expires_in", 900)), int(d.get("interval", 5))
        while time.time() < deadline:
            self.sleep(interval)
            st, j = self._grant({"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "device_code": d["device_code"]})
            if st == 200:
                self._store(j)
                return self.tok["access_token"]
            err = j.get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            self._denied(j)
            raise RuntimeError(f"sign-in failed: {err}")
        raise RuntimeError("sign-in timed out: the code was not entered in time")

    def get(self, path, accept="application/json", headers=None, raw=False):
        """GET a Graph path (or a full @odata link). Throttling honours Retry-After; a tenant gate is a Stop."""
        url = path if path.startswith("http") else self.base + path
        for attempt in range(4):
            self.pacer.tick()
            self.calls += 1
            st, h, b = _send("GET", url, {"Authorization": f"Bearer {self.token()}", "Accept": accept, **(headers or {})})
            if st == 200:
                return b.decode("utf-8-sig") if raw else json.loads(b)
            msg = _err(b)
            if st == 401 and attempt == 0:
                self.tok["expires_at"] = 0  # the token was refused: force a refresh once
                continue
            if st in (429, 503):
                self.sleep(min(int(h.get("Retry-After") or 30), 300))
                continue
            if st == 403:
                if "GraphAccessToTranscriptsDisabled" in msg:
                    raise Stop("tenant", "Graph access to meeting transcripts is turned off in this tenant", "transcripts-disabled")
                if "SpeakerAttributionNotAllowed" in msg:
                    raise SpeakerAttribution()
                if re.search(r"admin|consent", msg, re.I):
                    raise Stop("consent", "the tenant requires administrator approval for this app", "admin-consent")
                raise Stop("forbidden", f"Graph answered 403 ({msg.strip()[:80] or 'no detail'})", "admin-consent")
            if st == 404:
                raise NotFound(url)
            raise RuntimeError(f"Graph answered {st} {msg.strip()[:80]}")
        raise RuntimeError("Graph kept throttling or refusing the token; try again later")


# ---- transcripts ------------------------------------------------------------------------------------------------
def _utc(s):
    d = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", str(s)).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _addr(p):
    e = (p or {}).get("emailAddress") or {}
    return f"{e['name']} <{e['address']}>" if e.get("name") and e.get("address") else e.get("address") or e.get("name") or ""


def _write_drop(P, ev, n, vtt_text, unattributed):
    start, end = _utc(ev["start"]["dateTime"]), _utc(ev["end"]["dateTime"])
    title = inline(ev.get("subject") or "Meeting")[:120]
    # the subject is set by whoever sent the invite: only a cleaned copy goes into the file name, and the target must resolve inside the drop folder
    uid = hashlib.sha1(str(ev.get("id")).encode()).hexdigest()[:6]  # two meetings with one cleaned name and start time must not share a file
    stem = f"{safe_name(ev.get('subject'))}-{start.strftime('%Y%m%d_%H%M%S')}-{uid}-Meeting Transcript{f'-t{n}' if n > 1 else ''}"
    vtt_f, meta_f = safe_join(P.drop, f"{stem}.vtt"), safe_join(P.drop, f"{stem}.meta.json")
    side = {"title": title, "start": iso(start), "end": iso(end), "organizer": _addr(ev.get("organizer")) or None,
            "attendees": [x for x in (_addr(a) for a in ev.get("attendees") or []) if x][:200], "transcript_source": "graph-api"}
    if unattributed:
        side["speakers"] = "unknown"
    atomic_write(vtt_f, vtt_text)
    atomic_write(meta_f, json.dumps(side, indent=1) + "\n")


def _unattributed_vtt(text):
    """The format without speakers carries no cue structure we rely on: each non-empty line becomes one untimed cue."""
    cues = "".join(f"{i}\n00:00:00.000 --> 00:00:00.000\n{ln.strip()}\n\n" for i, ln in enumerate((x for x in text.splitlines() if x.strip()), 1))
    return "WEBVTT\n\n" + cues


def fetch_transcripts(P, S, rep, env, hooks):
    """Calendar events of the last 7 days that ended more than 15 minutes ago: resolve the online meeting by its join URL (kept in
    memory only), list its transcripts, and drop each one as a .vtt plus sidecar. Back-off per meeting; give up after 7 days."""
    now = common.clock()
    state_f = P.state / "graph-meetings.json"
    st = load_json(state_f, {"events": {}, "blocked_until": None})
    if st.get("blocked_until") and now < _utc(st["blocked_until"]):
        raise Stop("tenant", "Graph access to meeting transcripts was found turned off less than a day ago", "transcripts-disabled")
    g = Graph(P, S, env, hooks, SCOPES_MEET)
    url = (f"/me/calendarView/delta?startDateTime={urllib.parse.quote(iso(now - timedelta(days=7)))}&endDateTime={urllib.parse.quote(iso(now))}"
           "&$select=subject,start,end,organizer,attendees,onlineMeeting,isOnlineMeeting,isCancelled")
    events = []
    while url:  # ponytail: the delta token is not kept; the 7-day window is read again each run (a few pages)
        page = g.get(url, headers={"Prefer": 'outlook.timezone="UTC", odata.maxpagesize=50'})
        events += [e for e in page.get("value", []) if "@removed" not in e]
        url = page.get("@odata.nextLink")
    seen = 0
    try:
        for ev in events:
            join = (ev.get("onlineMeeting") or {}).get("joinUrl")
            if not (ev.get("isOnlineMeeting") and join) or ev.get("isCancelled"):
                continue
            end = _utc(ev["end"]["dateTime"])
            key = hashlib.sha256(ev["id"].encode()).hexdigest()[:16]
            rec = st["events"].setdefault(key, {"attempts": 0, "next": None, "state": "waiting"})
            if rec["state"] != "waiting" or now < end + timedelta(minutes=15) or (rec["next"] and now < _utc(rec["next"])):
                continue
            if now - end > timedelta(days=7):
                rec["state"] = "lost"
                rep["skipped"].append({"item": inline(ev.get("subject") or "meeting"), "reason": "no transcript within 7 days: gave up"})
                continue
            seen += 1
            n = _fetch_one(g, P, ev, join, rep)
            rec["attempts"] += 1
            if n:
                rec["state"] = "done"
                rep["counts"]["transcripts-fetched"] = rep["counts"].get("transcripts-fetched", 0) + n
            else:
                rec["next"] = iso(now + timedelta(minutes=BACKOFF_MIN[min(rec["attempts"] - 1, len(BACKOFF_MIN) - 1)]))
    except Stop as s:
        if s.kind == "tenant":
            st["blocked_until"] = iso(now + timedelta(days=1))  # do not ask again today
        atomic_write(state_f, json.dumps(st, indent=1) + "\n")
        raise
    atomic_write(state_f, json.dumps(st, indent=1) + "\n")
    rep["counts"]["graph-meetings-checked"] = seen
    rep["counts"]["graph-calls"] = g.calls


def _fetch_one(g, P, ev, join, rep):
    q = urllib.parse.quote("JoinWebUrl eq '" + join.replace("'", "''") + "'", safe="")
    meetings = g.get(f"/me/onlineMeetings?$filter={q}").get("value") or []
    if not meetings:
        return 0
    try:
        listing = g.get(f"/me/onlineMeetings/{meetings[0]['id']}/transcripts").get("value") or []
    except NotFound:
        return 0
    n = 0
    for t in sorted(listing, key=lambda x: x.get("createdDateTime") or ""):
        path = f"/me/onlineMeetings/{meetings[0]['id']}/transcripts/{t['id']}/content"
        try:
            text, plain = g.get(path, accept="text/vtt", raw=True), False
        except SpeakerAttribution:  # one retry, without speakers
            text, plain = _unattributed_vtt(g.get(path, accept="application/vnd.microsoft.graph.transcript+text", raw=True)), True
        n += 1
        _write_drop(P, ev, n, text, plain)
    return n


# ---- mail -------------------------------------------------------------------------------------------------------
class GraphMail(MailSource):
    """Mail.Read over per-folder messages/delta, feeding the same thread writer as the classic Outlook source."""

    def __init__(self, P, S, env, hooks):
        self.g, self.P = Graph(P, S, env, hooks, SCOPES_MAIL), P
        self.links_f = P.state / "graph-mail-delta.json"
        self.links = load_json(self.links_f, {})

    def stores(self):
        return [Store("graph", "Mailbox (Microsoft Graph)", True)]

    def folders(self, store):
        out = [Folder("graph", f["id"], f["displayName"]) for f in self.g.get("/me/mailFolders?$top=100&$select=id,displayName").get("value", [])]
        inbox = next((f for f in out if f.path.lower() == "inbox"), None)
        if inbox:
            out += [Folder("graph", f["id"], f"{inbox.path}/{f['displayName']}")
                    for f in self.g.get(f"/me/mailFolders/{inbox.id}/childFolders?$top=100&$select=id,displayName").get("value", [])]
        return out

    def items(self, folder, since, after_entry_ids):
        url = self.links.get(folder.id) or (f"/me/mailFolders/{folder.id}/messages/delta?$select={MAIL_SELECT}"
                                            + (f"&$filter=receivedDateTime ge {since}" if since else ""))
        link = None
        while url:
            page = self.g.get(url, headers={"Prefer": "odata.maxpagesize=50"})
            for m in page.get("value", []):
                if "@removed" in m:
                    continue
                it = Item(m["id"], m.get("conversationId") or "", m.get("subject") or "", iso(_utc(m["receivedDateTime"])),
                          iso(_utc(m["lastModifiedDateTime"])), "IPM.Note", m)
                if not since or self.folder_delta(folder) or it.modified > since or (it.modified == since and it.entry_id not in after_entry_ids):
                    yield it
            url, link = page.get("@odata.nextLink"), page.get("@odata.deltaLink") or link
        if link:  # reached only when the consumer read every page
            self.links[folder.id] = link
            atomic_write(self.links_f, json.dumps(self.links, indent=1) + "\n")

    def folder_delta(self, folder):
        return folder.id in self.links  # a delta link already says what changed: no timestamp filter on top

    def body(self, item, headers_only=False):
        m = item.ref
        b = m.get("body") or {}
        return {"text": None if headers_only or b.get("contentType") == "html" else b.get("content"),
                "html": None if headers_only or b.get("contentType") != "html" else b.get("content"),
                "from": _addr(m.get("from")), "to": [_addr(r) for r in m.get("toRecipients", [])], "cc": [_addr(r) for r in m.get("ccRecipients", [])],
                "message_id": m.get("internetMessageId")}

    def labels(self, item):
        import outlook_com
        for h in item.ref.get("internetMessageHeaders") or []:
            if str(h.get("name", "")).lower() == "msip_labels":
                return outlook_com.parse_labels("msip_labels: " + str(h.get("value", "")))
        return []

    def attachments(self, item):
        if not item.ref.get("hasAttachments"):
            return []
        out = []
        for a in self.g.get(f"/me/messages/{item.entry_id}/attachments?$select=id,name,size,isInline").get("value", []):
            if a.get("isInline"):
                continue
            out.append(Attachment(a.get("name") or "attachment", int(a.get("size") or 0), self._saver(item.entry_id, a["id"])))
        return out

    def _saver(self, mid, aid):
        def save(path):
            data = self.g.get(f"/me/messages/{mid}/attachments/{aid}").get("contentBytes") or ""
            with open(path, "wb") as f:
                f.write(base64.b64decode(data))
        return save
