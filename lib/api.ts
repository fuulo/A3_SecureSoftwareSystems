import { auth } from "@/lib/firebase";
import {
  ensureSessionToken,
  isSessionFailure,
  notifySessionEnded,
  SESSION_HEADER,
} from "@/lib/session";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");

function requestLoginRedirect() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("staff-api-unauthorized"));
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  if (!API_BASE_URL) {
    throw new Error("Staff API is not configured.");
  }
  const user = auth.currentUser;
  if (!user) {
    requestLoginRedirect();
    throw new ApiError(401, "Sign in to continue.");
  }
  const token = await user.getIdToken();
  // Required by every signed-in endpoint for the inactivity timeout
  let sessionToken: string;
  try {
    sessionToken = await ensureSessionToken();
  } catch (error) {
    throw new ApiError(401, error instanceof Error ? error.message : "Sign in to continue.");
  }
  let sessionId: string | undefined;
  if (typeof window !== "undefined") {
    sessionId = sessionStorage.getItem("staffSessionId") ?? undefined;
    if (!sessionId) {
      sessionId = crypto.randomUUID();
      sessionStorage.setItem("staffSessionId", sessionId);
    }
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
      Authorization: `Bearer ${token}`,
      [SESSION_HEADER]: sessionToken,
      ...(sessionId ? { "X-Session-Id": sessionId } : {}),
    },
    cache: "no-store",
  });
  if (response.status === 401) {
    const detail = await response
      .clone()
      .json()
      .then((body: { detail?: unknown }) => body?.detail)
      .catch(() => undefined);
    if (isSessionFailure(detail)) {
      notifySessionEnded();
      throw new ApiError(401, "Your session has ended. Please sign in again.");
    }
    requestLoginRedirect();
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }
  return readResponse<T>(response);
}

// Full URL of a public API path, for links such as file downloads
export function publicApiUrl(path: string) {
  return `${API_BASE_URL ?? ""}${path}`;
}

// Calls a public endpoint that needs no sign-in (results and verification pages)
export async function publicApiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  if (!API_BASE_URL) {
    throw new Error("The voting API is not configured.");
  }
  const response = await fetch(publicApiUrl(path), {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
    cache: "no-store",
  });
  return readResponse<T>(response);
}

async function readResponse<T>(response: Response): Promise<T> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    if (response.ok) throw new Error("The API returned an invalid response.");
    payload = null;
  }
  if (!response.ok) {
    let message = "The request could not be completed.";
    if (typeof payload === "object" && payload !== null && "detail" in payload) {
      const detail = payload.detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (typeof detail === "object" && detail !== null &&
          "message" in detail && typeof detail.message === "string") {
        const missing = "missing" in detail && Array.isArray(detail.missing)
          ? detail.missing.filter((item): item is string => typeof item === "string")
          : [];
        message = missing.length ? `${detail.message}: ${missing.join("; ")}` : detail.message;
      }
    }
    throw new ApiError(response.status, message);
  }
  return payload as T;
}

export type StaffProfile = {
  staffId: string;
  name: string;
  role: "admin" | "aecEmployee" | "commissionerDelegate";
  stateId: string;
};

export function getStaffProfile() {
  return apiRequest<StaffProfile>("/api/me");
}

export type ChangeRequest = {
  requestId: string;
  action: string;
  status: "pending" | "approved" | "rejected";
  summary: string;
  targetId?: string | null;
  payload?: unknown;
  before?: unknown;
  requestedBy: string;
  requestedByName?: string | null;
  requestedAt?: string | null;
  reviewedBy?: string | null;
  reviewedByName?: string | null;
  reviewedAt?: string | null;
  reviewReason?: string | null;
};

export type ChangeRequestList = { pending: ChangeRequest[]; recent: ChangeRequest[] };
