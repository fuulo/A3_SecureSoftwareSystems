import type { MultiFactorResolver } from "firebase/auth";

// The first-step sign-in result (the "resolver") has to travel from the login
// page to the verify page. It is an object, so it cannot go in sessionStorage.
// It stays in memory only, so a page refresh clears it on purpose.
let pendingResolver: MultiFactorResolver | null = null;

export function setPendingMfa(resolver: MultiFactorResolver | null) {
  pendingResolver = resolver;
}

export function getPendingMfa(): MultiFactorResolver | null {
  return pendingResolver;
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
    case "auth/network-request-failed":
      return "Network error. Please check your connection and try again.";
    case "auth/operation-not-allowed":
      return "Text message verification is not enabled for this project or region.";
    default:
      return "Something went wrong. Please try again.";
  }
}
