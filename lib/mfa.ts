import {
  RecaptchaVerifier,
  signOut,
  type MultiFactorResolver,
  type User,
} from "firebase/auth";
import { auth } from "@/lib/firebase";

export type InvisibleRecaptcha = {
  verifier: RecaptchaVerifier;
  dispose: () => void;
};

// reCAPTCHA refuses to render twice into the same element, and Next.js keeps
// visited pages mounted, so each attempt to send a code gets a fresh element
// inside `host`. dispose() removes both the reCAPTCHA and its element.
export function createInvisibleRecaptcha(host: HTMLElement | null): InvisibleRecaptcha {
  const container = document.createElement("div");
  (host ?? document.body).appendChild(container);
  const verifier = new RecaptchaVerifier(auth, container, { size: "invisible" });
  let disposed = false;
  return {
    verifier,
    dispose: () => {
      if (disposed) return;
      disposed = true;
      verifier.clear();
      container.remove();
    },
  };
}

// The first-step sign-in result (the "resolver") has to travel from the login
// page to the verify page. It is an object, so it cannot go in sessionStorage.
// It stays in memory only, so a page refresh clears it on purpose.
let pendingResolver: MultiFactorResolver | null = null;
let pendingSince: number | null = null;
let pendingEmail = "";

// The whole second step has to be finished within this time, counted from
// the moment the password was accepted
export const MFA_TIME_LIMIT_SECONDS = 60;

// The email is kept so wrong codes can be counted against the account
export function setPendingMfa(resolver: MultiFactorResolver | null, email = "") {
  pendingResolver = resolver;
  pendingSince = resolver ? Date.now() : null;
  pendingEmail = resolver ? email : "";
}

export function getPendingMfa(): MultiFactorResolver | null {
  return pendingResolver;
}

export function getPendingMfaEmail(): string {
  return pendingEmail;
}

// When the pending login expires (in milliseconds), or null if there is none
export function getPendingMfaDeadline(): number | null {
  return pendingSince === null ? null : pendingSince + MFA_TIME_LIMIT_SECONDS * 1000;
}

// Added to the login page URL (?reason=...) to say why the user was sent back
export const MFA_TIMEOUT_REASON = "mfa-timeout";
export const MFA_REQUIRED_REASON = "mfa-required";
export const ACCOUNT_LOCKED_REASON = "account-locked";
export const SESSION_TIMEOUT_REASON = "session-timeout";

// A Map, so a crafted ?reason= cannot pick up built-in object properties
export const LOGIN_NOTICES = new Map<string, string>([
  [MFA_TIMEOUT_REASON, "Your verification timed out. Please log in again."],
  [MFA_REQUIRED_REASON, "Please log in and complete text message verification to continue."],
  [ACCOUNT_LOCKED_REASON, "Too many failed attempts. This account is temporarily locked."],
  [SESSION_TIMEOUT_REASON, "You were signed out after 2 minutes of inactivity."],
]);

// Voter pages need a sign-in that included the text message code. Firebase
// records this in the signed ID token, so unlike a sessionStorage flag it
// cannot be set by hand. Signs out a session that skipped the second step.
// Returns true if the user may stay on the page.
export async function requireSecondFactor(user: User): Promise<boolean> {
  const token = await user.getIdTokenResult();
  if (token.signInSecondFactor) return true;

  await signOut(auth).catch(() => {});
  return false;
}

// Turns 0412 345 678 or +61 412 345 678 into +61412345678.
// Returns null if the number is not a valid Australian number.
export function toE164AU(input: string): string | null {
  const digits = input.replace(/[\s()-]/g, "");

  let e164 = "";
  if (digits.startsWith("+61")) {
    e164 = digits;
  } else if (digits.startsWith("61")) {
    e164 = `+${digits}`;
  } else if (digits.startsWith("0")) {
    e164 = `+61${digits.slice(1)}`;
  }

  return /^\+61[2-478]\d{8}$/.test(e164) ? e164 : null;
}

// One place for the messages shown to the user.
export function getMfaErrorMessage(error: unknown): string {
  const code =
    typeof error === "object" && error !== null && "code" in error
      ? String((error as { code?: unknown }).code ?? "")
      : "";

  switch (code) {
    case "auth/invalid-phone-number":
    case "auth/missing-phone-number":
      return "Please enter a valid phone number.";
    case "auth/invalid-verification-code":
    case "auth/missing-verification-code":
      return "The code is incorrect.";
    case "auth/code-expired":
      return "The code has expired. Please request a new one.";
    case "auth/too-many-requests":
    case "auth/quota-exceeded":
      return "Too many attempts. Please wait a while and try again.";
    case "auth/requires-recent-login":
      return "For your security, please log out, log in again, and then return to this page.";
    case "auth/unverified-email":
      return "Please verify your email address first.";
    case "auth/second-factor-already-in-use":
      return "This phone number is already set up for this account.";
    case "auth/captcha-check-failed":
      return "The security check failed. Please try again.";
    case "auth/user-disabled":
      return "This account is locked or disabled. Please try again later.";
    case "auth/network-request-failed":
      return "Network error. Please check your connection and try again.";
    case "auth/operation-not-allowed":
      return "Text message verification is not enabled for this project or region.";
    default:
      // The code lets a user's report be traced to the actual Firebase error
      return code
        ? `Something went wrong (${code}). Please try again.`
        : "Something went wrong. Please try again.";
  }
}
