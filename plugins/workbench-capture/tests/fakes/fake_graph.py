"""A fake Microsoft Graph and sign-in server on localhost for the SHOULD-level Graph client. Invented people on example.com.
`calls` records every request; `mode` switches behaviours: transcripts = ok | disabled | speaker | none | throttle."""
import base64
import json
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

JOIN = "https://teams.example.com/l/meetup-join/19%3ameeting_fake123/0?context=hidden"
VTT = "WEBVTT\n\n1\n00:00:03.000 --> 00:00:06.000\n<v Alice Example>Graph transcript line about the launch plan.</v>\n\n2\n00:00:07.000 --> 00:00:09.000\n<v Bob Sample>Agreed.</v>\n"


def event(eid, subject, start, end, online=True, join=JOIN, cancelled=False):
    return {"id": eid, "subject": subject, "start": {"dateTime": start + ".0000000", "timeZone": "UTC"}, "end": {"dateTime": end + ".0000000", "timeZone": "UTC"},
            "isOnlineMeeting": online, "isCancelled": cancelled, "onlineMeeting": {"joinUrl": join} if online else None,
            "organizer": {"emailAddress": {"name": "Alice Example", "address": "alice@example.com"}},
            "attendees": [{"emailAddress": {"name": "Bob Sample", "address": "bob@example.com"}}]}


class FakeGraph:
    def __init__(self):
        self.calls, self.mode = [], {"transcripts": "ok", "device": "ok", "throttle_left": 0, "pending": 1}
        self.events = [event("ev-1", "Launch Planning", "2026-10-08T08:30:00", "2026-10-08T09:30:00"),
                       event("ev-2", "Just Ended", "2026-10-08T11:00:00", "2026-10-08T11:55:00", join=JOIN + "x"),
                       event("ev-3", "No Meeting Link", "2026-10-07T08:30:00", "2026-10-07T09:30:00", online=False),
                       event("ev-4", "Cancelled", "2026-10-07T10:30:00", "2026-10-07T11:30:00", cancelled=True)]
        self.meetings = {JOIN: "mtg-1", JOIN + "x": "mtg-2"}
        self.transcripts = {"mtg-1": [{"id": "t1", "createdDateTime": "2026-10-08T09:40:00Z"}], "mtg-2": [{"id": "t2", "createdDateTime": "2026-10-08T11:56:00Z"}]}
        self.messages = [{"id": "gm1", "conversationId": "gc1", "subject": "Launch notes", "receivedDateTime": "2026-10-07T09:00:00Z",
                          "lastModifiedDateTime": "2026-10-07T09:00:00Z", "from": {"emailAddress": {"name": "Alice Example", "address": "alice@example.com"}},
                          "toRecipients": [{"emailAddress": {"name": "Bob Sample", "address": "bob@example.com"}}], "ccRecipients": [],
                          "body": {"contentType": "html", "content": "<p>Graph mail body about the launch.</p>"}, "internetMessageId": "<gm1@example.com>",
                          "hasAttachments": True},
                         {"id": "gm2", "conversationId": "gc2", "subject": "Labelled note", "receivedDateTime": "2026-10-07T10:00:00Z",
                          "lastModifiedDateTime": "2026-10-07T10:00:00Z", "from": {"emailAddress": {"name": "Alice Example", "address": "alice@example.com"}},
                          "toRecipients": [], "ccRecipients": [], "body": {"contentType": "text", "content": "GRAPHSECRET"}, "internetMessageId": "<gm2@example.com>",
                          "hasAttachments": False, "internetMessageHeaders": [{"name": "msip_labels", "value": "MSIP_Label_aaaa-1_Enabled=true; MSIP_Label_aaaa-1_Name=Confidential;"}]}]
        self.access, self.refresh, self.n_tokens, self.expires_in = None, None, 0, 3600
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, status, body, ctype="application/json", extra=None):
                data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                form = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
                outer.calls.append(("POST", self.path.split("?")[0], {k: v[0] for k, v in form.items() if k in ("grant_type", "client_id", "scope")}))
                if self.path.endswith("/devicecode"):
                    return self.send(200, {"device_code": "dc-1", "user_code": "ABCD-1234", "verification_uri": f"{outer.base}/devicelogin", "expires_in": 900,
                                           "interval": 1, "message": f"To sign in, open {outer.base}/devicelogin and enter the code ABCD-1234"})
                if "device_code" in form.get("grant_type", [""])[0]:
                    if outer.mode["device"] == "consent":
                        return self.send(400, {"error": "invalid_grant", "error_description": "AADSTS90094: Need admin approval for this app"})
                    if outer.mode["pending"] > 0:
                        outer.mode["pending"] -= 1
                        return self.send(400, {"error": "authorization_pending"})
                elif form.get("refresh_token", [""])[0] != outer.refresh:
                    return self.send(400, {"error": "invalid_grant"})
                outer.n_tokens += 1
                outer.access, outer.refresh = f"FAKE-ACCESS-{outer.n_tokens}", f"FAKE-REFRESH-{outer.n_tokens}"
                self.send(200, {"access_token": outer.access, "refresh_token": outer.refresh, "expires_in": outer.expires_in, "scope": form.get("scope", [""])[0]})

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                path, q = urllib.parse.unquote(u.path), urllib.parse.parse_qs(u.query)
                outer.calls.append(("GET", path + ("?" + urllib.parse.unquote(u.query) if u.query else ""), {"accept": self.headers.get("Accept")}))
                if self.headers.get("Authorization") != f"Bearer {outer.access}":
                    return self.send(401, {"error": {"code": "InvalidAuthenticationToken", "message": "expired"}})
                p = path.removeprefix("/v1.0")
                if p == "/me/calendarView/delta":
                    if q.get("page") == ["2"]:
                        return self.send(200, {"value": outer.events[2:], "@odata.deltaLink": f"{outer.base}/v1.0/me/calendarView/delta?token=x"})
                    return self.send(200, {"value": outer.events[:2], "@odata.nextLink": f"{outer.base}/v1.0/me/calendarView/delta?page=2"})
                if p == "/me/onlineMeetings":
                    join = q["$filter"][0].split("'", 1)[1].rsplit("'", 1)[0].replace("''", "'")
                    mid = outer.meetings.get(join)
                    return self.send(200, {"value": [{"id": mid}] if mid else []})
                m = urllib.parse.urlsplit(p).path.split("/")
                if p.startswith("/me/onlineMeetings/") and p.endswith("/transcripts"):
                    return self.send(200, {"value": [] if outer.mode["transcripts"] == "none" else outer.transcripts.get(m[3], [])})
                if p.startswith("/me/onlineMeetings/") and p.endswith("/content"):
                    mode = outer.mode["transcripts"]
                    if mode == "disabled":
                        return self.send(403, {"error": {"code": "Forbidden", "message": "denied", "innerError": {"code": "GraphAccessToTranscriptsDisabled"}}})
                    if mode == "throttle" and outer.mode["throttle_left"] > 0:
                        outer.mode["throttle_left"] -= 1
                        return self.send(429, {"error": {"code": "TooManyRequests"}}, extra={"Retry-After": "7"})
                    if mode == "speaker" and "text/vtt" in (self.headers.get("Accept") or ""):
                        return self.send(403, {"error": {"code": "Forbidden", "message": "SpeakerAttributionNotAllowed"}})
                    if mode == "speaker":
                        return self.send(200, "Unattributed line one.\nUnattributed line two.\n", "text/plain")
                    return self.send(200, VTT, "text/vtt")
                if p == "/me/mailFolders":
                    return self.send(200, {"value": [{"id": "f-inbox", "displayName": "Inbox"}, {"id": "f-sent", "displayName": "Sent Items"}]})
                if p.endswith("/childFolders"):
                    return self.send(200, {"value": []})
                if p == "/me/mailFolders/f-inbox/messages/delta":
                    if q.get("deltatoken"):
                        return self.send(200, {"value": [], "@odata.deltaLink": f"{outer.base}/v1.0/me/mailFolders/f-inbox/messages/delta?deltatoken=2"})
                    return self.send(200, {"value": outer.messages, "@odata.deltaLink": f"{outer.base}/v1.0/me/mailFolders/f-inbox/messages/delta?deltatoken=1"})
                if p == "/me/mailFolders/f-sent/messages/delta":
                    return self.send(200, {"value": [], "@odata.deltaLink": f"{outer.base}/v1.0/me/mailFolders/f-sent/messages/delta?deltatoken=1"})
                if p == "/me/messages/gm1/attachments":
                    return self.send(200, {"value": [{"id": "a1", "name": "notes.txt", "size": 14, "isInline": False}]})
                if p == "/me/messages/gm1/attachments/a1":
                    return self.send(200, {"contentBytes": base64.b64encode(b"Attached notes").decode()})
                self.send(404, {"error": {"code": "NotFound"}})

        class Srv(ThreadingHTTPServer):  # listen on the address family "localhost" resolves to first: a refused first try costs 2 s on Windows
            address_family = socket.getaddrinfo("localhost", 0, type=socket.SOCK_STREAM)[0][0]

        self.server = Srv(("localhost", 0), H)
        self.base = f"http://localhost:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def gets(self, prefix=""):
        return [c for c in self.calls if c[0] == "GET" and c[1].startswith(prefix)]
