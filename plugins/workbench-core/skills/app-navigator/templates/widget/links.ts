// Turns an answer into text and in-app links. Only an internal path (/x) becomes a link: //host, any scheme (a colon),
// backslashes (browsers read /\host as //host), whitespace and control characters (browsers drop tabs and newlines
// from URLs) stay plain text, so a coaxed answer cannot become an open redirect. Framework-free: reuse it outside React.
export type Segment = { text: string; href?: string };

const LINK = /\[([^\]\n]+)\]\(([^)\s]+)\)/g;
const SAFE_ROUTE = /^\/(?![/\\])[^\s\\:\u0000-\u001f\u007f]*$/;

export function safeRoute(href: string): string | null {
  return SAFE_ROUTE.test(href) ? href : null;
}

export function parseAnswer(text: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(LINK)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ text: text.slice(last, at) });
    const href = safeRoute(m[2]);
    out.push(href ? { text: m[1], href } : { text: m[1] });
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}
