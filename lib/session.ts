import { auth } from "@/lib/firebase";

// Inactivity timeout. The API issues a session token after sign-in that expires
// unless it is renewed (see backend/sessions.py); the browser renews it while
// the user is active and signs out after IDLE_LIMIT_SECONDS without activity
// (components/inactivityguard.tsx). Both are kept in localStorage so every open
// tab shares one session and one activity clock.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
const TOKEN_KEY = "a3.sessionToken";
const ACTIVITY_KEY = "a3.lastActivity";

export const SESSION_HEADER = "X-Session-Token";
export const IDLE_WARNING_SECONDS = 90;
export const IDLE_LIMIT_SECONDS = 120;
export const RENEW_INTERVAL_SECONDS = 30;
// Dispatched on window when the API says the session is over
export const SESSION_ENDED_EVENT = "session-ended";

// The API's messages for a missing, invalid or expired session
const SESSION_FAILURES = new Set(["Session invalid", "Session expired"]);

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Storage blocked: the session then lasts only as long as this page
  }
}

export function recordActivity(now = Date.now()) {
  write(ACTIVITY_KEY, String(now));
}

export function lastActivity(): number | null {
  const value = Number(read(ACTIVITY_KEY));
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function clearSessionToken() {
  write(TOKEN_KEY, null);
}

export function isSessionFailure(detail: unknown): boolean {
  return typeof detail === "string" && SESSION_FAILURES.has(detail);
}

export function notifySessionEnded() {
  clearSessionToken();
  window.dispatchEvent(new Event(SESSION_ENDED_EVENT));
}

// The claims of a session token, read without checking it (the API does that)
function tokenClaims(token: string): { sub?: string; auth_time?: number } {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(payload));
  } catch {
    return {};
  }
}

async function startSession(): Promise<string> {
  const user = auth.currentUser;
  if (!user || !API_BASE_URL) throw new Error("Sign in to continue.");
  const response = await fetch(`${API_BASE_URL}/api/session/start`, {
    method: "POST",
    headers: { Authorization: `Bearer ${await user.getIdToken()}` },
    cache: "no-store",
  });
  if (response.status === 401) {
    // Too long since signing in: the user has to sign in again
    notifySessionEnded();
    throw new Error("Your session has ended. Please sign in again.");
  }
  if (!response.ok) throw new Error("The session could not be started.");
  const { sessionToken } = (await response.json()) as { sessionToken: string };
  write(TOKEN_KEY, sessionToken);
  recordActivity();
  return sessionToken;
}

let starting: Promise<string> | null = null;

// The session token for the current sign-in, starting one if needed. A token
// left over from an earlier sign-in is discarded instead of being sent.
export async function ensureSessionToken(): Promise<string> {
  const user = auth.currentUser;
  const stored = read(TOKEN_KEY);
  if (user && stored) {
    const claims = tokenClaims(stored);
    const signIn = await user.getIdTokenResult();
    if (claims.sub === user.uid && String(claims.auth_time) === String(signIn.claims.auth_time)) {
      return stored;
    }
    clearSessionToken();
  }
  starting ??= startSession().finally(() => {
    starting = null;
  });
  return starting;
}

// Extends the session; called while the user is active
export async function renewSession(): Promise<void> {
  const user = auth.currentUser;
  if (!user || !API_BASE_URL) return;
  const response = await fetch(`${API_BASE_URL}/api/session/renew`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${await user.getIdToken()}`,
      [SESSION_HEADER]: await ensureSessionToken(),
    },
    cache: "no-store",
  });
  if (response.status === 401) {
    notifySessionEnded();
    return;
  }
  if (response.ok) {
    const { sessionToken } = (await response.json()) as { sessionToken: string };
    write(TOKEN_KEY, sessionToken);
  }
}

// Closes the session when the user signs out, so it is not later treated as idle
export function endSessionOnSignOut() {
  const token = read(TOKEN_KEY);
  clearSessionToken();
  if (!token || !API_BASE_URL) return;
  fetch(`${API_BASE_URL}/api/session/end`, {
    method: "POST",
    headers: { [SESSION_HEADER]: token },
    keepalive: true,
  }).catch(() => {});
}
