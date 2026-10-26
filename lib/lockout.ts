import { ApiError, apiRequest, publicApiRequest } from "@/lib/api";

// Account lockout after repeated failed sign-ins (see backend/routers/auth_lockout.py).
// Sign-in itself happens with Firebase, so the login and verify pages report
// each attempt to the API, which locks the account after 3 failures in a row.

export type LockoutStatus = {
  locked: boolean;
  retryAfterSeconds: number;
  attemptsRemaining: number;
};

function post(path: string, email: string) {
  return publicApiRequest<LockoutStatus>(path, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

// Asks whether the account is locked, before trying to sign in
export function checkLockout(email: string) {
  return post("/api/auth/lockout/check", email);
}

// Reports a wrong password or text message code
export function reportFailedSignIn(email: string) {
  return post("/api/auth/lockout/failure", email);
}

// Resets the count after a complete sign-in. Needs the new sign-in's ID token,
// so it cannot be used to reset someone else's count.
export async function reportSuccessfulSignIn() {
  try {
    await apiRequest<LockoutStatus>("/api/auth/lockout/success", { method: "POST" });
  } catch (error) {
    // The sign-in itself worked; a failed reset only means the count stays
    console.error("Unable to reset the failed sign-in count", error);
  }
}

export function lockedMessage(retryAfterSeconds: number): string {
  const minutes = Math.max(1, Math.ceil(retryAfterSeconds / 60));
  return `Too many failed attempts. This account is locked. Please try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`;
}

export function attemptsLeftMessage(status: LockoutStatus): string {
  const attempts = status.attemptsRemaining;
  return `${attempts} attempt${attempts === 1 ? "" : "s"} left before the account is locked.`;
}

// Reports a failed attempt and returns what to tell the user: the lock, or the
// original message with the attempts left
export async function failedSignInMessage(email: string, message: string): Promise<string> {
  try {
    const status = await reportFailedSignIn(email);
    return status.locked ? lockedMessage(status.retryAfterSeconds) : `${message} ${attemptsLeftMessage(status)}`;
  } catch (error) {
    console.error("Unable to report the failed sign-in", error);
    return message;
  }
}

// For errors from checkLockout: too many requests from this network, or the API is down
export function lockoutCheckErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) {
    return "Too many sign-in attempts from your network. Please wait a minute and try again.";
  }
  return "Login is unavailable right now. Please try again later.";
}
