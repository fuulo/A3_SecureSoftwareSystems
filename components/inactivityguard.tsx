"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { onAuthStateChanged, signOut } from "firebase/auth";
import { auth } from "../lib/firebase";
import { SESSION_TIMEOUT_REASON } from "../lib/mfa";
import {
  clearSessionToken,
  endSessionOnSignOut,
  IDLE_LIMIT_SECONDS,
  IDLE_WARNING_SECONDS,
  lastActivity,
  recordActivity,
  renewSession,
  RENEW_INTERVAL_SECONDS,
  SESSION_ENDED_EVENT,
} from "../lib/session";

const PROTECTED_AREAS = ["/voter", "/staff"];
const ACTIVITY_EVENTS = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart", "scroll"];

function inProtectedArea(path: string | null) {
  if (!path) return false;
  return PROTECTED_AREAS.some((p) => path === p || path.startsWith(`${p}/`));
}

// Signs voters and staff out after IDLE_LIMIT_SECONDS without activity, with a
// warning first, and keeps the API's session token renewed while they are
// active. Activity in any open tab counts for all of them.
export default function InactivityGuard() {
  const pathname = usePathname();
  const router = useRouter();
  const [signedIn, setSignedIn] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const endingRef = useRef(false);
  const lastRenewRef = useRef(0);

  const active = signedIn && inProtectedArea(pathname);

  const endForInactivity = useCallback(() => {
    if (endingRef.current) return;
    endingRef.current = true;
    setSecondsLeft(null);
    // The API ends its side of the session too, revoking the sign-in
    clearSessionToken();
    signOut(auth)
      .catch(() => {})
      .finally(() => router.replace(`/login?reason=${SESSION_TIMEOUT_REASON}`));
  }, [router]);

  useEffect(() => {
    return onAuthStateChanged(auth, (user) => {
      setSignedIn(Boolean(user));
      if (user) {
        endingRef.current = false;
      } else if (!endingRef.current) {
        // An ordinary sign-out: close the session instead of leaving it to time out
        endSessionOnSignOut();
      }
    });
  }, []);

  // The API refused the session (expired, or ended in another tab)
  useEffect(() => {
    window.addEventListener(SESSION_ENDED_EVENT, endForInactivity);
    return () => window.removeEventListener(SESSION_ENDED_EVENT, endForInactivity);
  }, [endForInactivity]);

  // Activity resets the clock and renews the API session, at most every 30 s
  useEffect(() => {
    if (!active) return;
    recordActivity();
    let lastWrite = 0;

    function onActivity() {
      const now = Date.now();
      if (now - lastWrite < 1000) return;
      lastWrite = now;
      recordActivity(now);
      if (now - lastRenewRef.current >= RENEW_INTERVAL_SECONDS * 1000) {
        lastRenewRef.current = now;
        renewSession().catch(() => {});
      }
    }

    for (const name of ACTIVITY_EVENTS) {
      window.addEventListener(name, onActivity, { passive: true });
    }
    return () => {
      for (const name of ACTIVITY_EVENTS) {
        window.removeEventListener(name, onActivity);
      }
    };
  }, [active]);

  // Checks idle time every second, and as soon as a hidden tab is shown again
  useEffect(() => {
    if (!active) return;

    function check() {
      const idleSeconds = (Date.now() - (lastActivity() ?? Date.now())) / 1000;
      if (idleSeconds >= IDLE_LIMIT_SECONDS) {
        endForInactivity();
      } else if (idleSeconds >= IDLE_WARNING_SECONDS) {
        setSecondsLeft(Math.ceil(IDLE_LIMIT_SECONDS - idleSeconds));
      } else {
        setSecondsLeft(null);
      }
    }

    const timer = setInterval(check, 1000);
    document.addEventListener("visibilitychange", check);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
    };
  }, [active, endForInactivity]);

  if (!active || secondsLeft === null) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-6">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="inactivity-title"
        aria-describedby="inactivity-text"
        className="w-full max-w-sm rounded-lg border border-slate-300 bg-white p-6 text-center shadow-lg"
      >
        <h2 id="inactivity-title" className="mb-2 text-[20px] font-bold text-[#1f538d]">
          Are you still there?
        </h2>
        <p id="inactivity-text" className="mb-5 text-slate-700">
          To protect your personal information, you will be signed out in{" "}
          <span className="font-semibold text-red-700">{secondsLeft}s</span>.
        </p>
        <button
          type="button"
          autoFocus
          onClick={() => recordActivity()}
          className="w-full rounded-lg bg-[#1f538d] px-4 py-2 font-bold text-white hover:bg-[#1b4779] focus:outline-none focus:ring-2 focus:ring-[#1f538d] focus:ring-offset-2"
        >
          Stay signed in
        </button>
      </div>
    </div>
  );
}
