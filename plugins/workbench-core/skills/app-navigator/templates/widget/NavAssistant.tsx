// "Where do I find it?" panel for a signed-in React app. Streams from the nav-assist endpoint (same origin, your session
// cookie) and renders answers as text plus in-app links only (links.ts). Usage, with your router's navigate function:
//   <NavAssistant navigate={(path) => router.push(path)} supportRoute="/help" />
// Unstyled on purpose: add your design system's classes.
import { useState, type FormEvent, type MouseEvent } from "react";
import { parseAnswer } from "./links";

type Turn = { role: "user" | "assistant"; content: string };
type Props = {
  navigate: (path: string) => void;
  endpoint?: string;
  supportRoute?: string;
  headers?: Record<string, string>; // for example your CSRF header
  maxTurns?: number; // history sent per question; the server accepts at most 12
};

export function NavAssistant({ navigate, endpoint = "/api/nav-assist", supportRoute = "/help", headers = {},
  maxTurns = 11 }: Props) {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function go(e: MouseEvent, href: string) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; // let the browser open a new tab
    e.preventDefault();
    setOpen(false);
    navigate(href);
  }

  async function ask(e: FormEvent) {
    e.preventDefault();
    const q = draft.trim();
    if (!q || busy) return;
    const history: Turn[] = [...turns, { role: "user" as const, content: q }].slice(-maxTurns);
    while (history.length && history[0].role !== "user") history.shift();
    setTurns([...turns, { role: "user", content: q }, { role: "assistant", content: "" }]);
    setDraft("");
    setBusy(true);
    setError("");
    let answer = "";
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify({ messages: history }),
      });
      if (!res.ok || !res.body) {
        throw new Error(res.status === 429 ? "You have reached today's question limit." : "The assistant is not available right now.");
      }
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buf = "";
      let done = false;
      while (!done) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buf += chunk.value;
        for (let i = buf.indexOf("\n\n"); i >= 0; i = buf.indexOf("\n\n")) {
          const event = buf.slice(0, i);
          buf = buf.slice(i + 2);
          if (!event.startsWith("data: ")) continue;
          const data = JSON.parse(event.slice(6));
          if (data.error) throw new Error("I could not answer that. Try rephrasing, or contact support.");
          if (data.done) done = true;
          if (data.text) {
            answer += data.text;
            setTurns((t) => [...t.slice(0, -1), { role: "assistant", content: answer }]);
          }
        }
      }
      if (!done) throw new Error("The answer was cut off. Please ask again.");
    } catch (err) {
      // a failed or partial answer never joins the history sent back; the question returns to the box
      setTurns((t) => t.slice(0, -2));
      setDraft(q);
      setError(err instanceof SyntaxError ? "The assistant is not available right now." : (err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="nav-assist">
      <button type="button" aria-expanded={open} aria-controls="nav-assist-panel" onClick={() => setOpen(!open)}>
        Where do I find it?
      </button>
      {open && (
        <div id="nav-assist-panel" role="dialog" aria-label="Help assistant"
          onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
          <div aria-live="polite">
            {turns.map((t, i) => (
              <p key={i} className={t.role}>
                {t.role === "user" ? t.content : parseAnswer(t.content).map((s, j) => s.href
                  ? <a key={j} href={s.href} onClick={(e) => go(e, s.href!)}>{s.text}</a>
                  : <span key={j}>{s.text}</span>)}
              </p>
            ))}
            {error && <p role="alert">{error}</p>}
          </div>
          <form onSubmit={ask}>
            <label htmlFor="nav-assist-q">Your question</label>
            <input id="nav-assist-q" value={draft} maxLength={1000} disabled={busy} autoFocus
              onChange={(e) => setDraft(e.target.value)} />
            <button type="submit" disabled={busy || !draft.trim()}>Ask</button>
          </form>
          <a href={supportRoute} onClick={(e) => go(e, supportRoute)}>Contact support</a>
        </div>
      )}
    </div>
  );
}
