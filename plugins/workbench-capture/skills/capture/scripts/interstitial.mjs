// Recognise a page that is not the content: sign-in, MFA, consent, conditional access, a DLP banner, a block page.
// A hit always stops the run (exit 3); nothing here retries, clicks or tries to get past the page.

const LOGIN_HOST = /(^|\.)(login\.microsoftonline\.com|login\.live\.com|login\.windows\.net|sts\.[^.]+\.[^.]+)$/i;
const LOGIN_PATH = /(^|\/)(login|log-in|logon|signin|sign-in|oauth2?|adfs|saml2?|openid)(\.[a-z]{2,5})?(\/|$)/i; // a whole path segment, so /sso-guide.html is fine

const RULES = [
  ['mfa', /verify your identity|approve sign.?in request|enter (the )?(verification )?code|two-step verification|multi-?factor|authenticator app|more information required|stay signed in\?/i],
  ['consent', /permissions requested|needs? your permission|need admin approval|approval required|let this app|accept to (grant|allow)|app would like to/i],
  ['dlp', /data loss prevention|policy tip|blocked (by|due to) (a |an |your organi[sz]ation.?s? )?(dlp|polic)|this (content|file|item) (is|has been) blocked|sharing (is )?(blocked|restricted)|restricted by (policy|your organi)/i],
  ['conditional-access', /you can.?t get there from here|does(n.?t| not) meet the criteria|conditional access|AADSTS\d+|device (is )?not (compliant|managed|registered)|blocked by your organi[sz]ation/i],
  ['block', /access denied|forbidden|too many requests|unusual traffic|request blocked|are you a robot|verify you are (a )?human|captcha/i],
];

export const ASK = {
  'sign-in': 'The saved sign-in is missing or expired. Run the login command and sign in again; capture does not retry.',
  mfa: 'A second sign-in step was asked for. Complete it yourself through the login command; capture does not retry.',
  consent: 'An approval or consent page appeared. Ask the administrator whether this access is allowed; capture will not accept it.',
  'conditional-access': 'A sign-in policy blocked this session. Ask IT whether automated reading is allowed on this device.',
  dlp: 'A data-protection notice appeared. Ask IT; capture stops here.',
  block: 'The server refused or throttled the request. Wait, check the scope, or ask the site owner; capture does not retry.',
  pacing: 'The hourly cap was reached. Run again once the window has moved (the time is in the report); nothing is lost.',
  'non-get': 'The page tried to send data, and capture allows no writes, so it stopped. Tell the site owner or IT; do not retry.',
  tenant: 'The signed-in account is not in the tenant named in the scope file. Sign in with the right account or fix the scope.',
  policy: 'A browser policy blocks automation here. Ask IT to allow it, or run only the sources that need no browser.',
};

// page = {url, status, title, text (top of the visible text), alerts (text of alert/dialog elements), password (bool)}
export function detect({ url = '', status = 200, title = '', text = '', alerts = '', password = false }) {
  let host = '';
  let pathname = '';
  try { ({ hostname: host, pathname } = new URL(url)); } catch { /* not a URL: judge the text only */ }
  const top = `${title}\n${alerts}\n${String(text).slice(0, 800)}`;
  if (password || LOGIN_HOST.test(host) || LOGIN_PATH.test(pathname) || /^\s*(sign in|log in|pick an account|sign in to your account)\b/i.test(title)) {
    return { kind: 'sign-in', reason: 'sign-in page' };
  }
  for (const [kind, re] of RULES) if (re.test(top) && (kind !== 'block' || status >= 400 || /captcha|are you a robot|verify you are/i.test(top))) return { kind, reason: `${kind} page` };
  if (status === 401 || status === 403 || status === 429 || status === 451 || status === 503) return { kind: 'block', reason: `HTTP ${status}` };
  return null;
}
