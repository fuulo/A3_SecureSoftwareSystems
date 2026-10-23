"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  onAuthStateChanged,
  signOut,
  User,
} from "firebase/auth";
import { auth } from "@/lib/firebase";
import {
  buttonStyle,
  mainHeader,
} from "@/components/styles";

export default function VoterDashboardPage() {
  const router = useRouter();

  const [user, setUser] =
    useState<User | null>(null);

  const [isCheckingAuth, setIsCheckingAuth] =
    useState(true);

  useEffect(() => {
    let isMounted = true;

    const authenticationCodeVerified =
      sessionStorage.getItem(
        "authenticationCodeVerified"
      );

    /*
     * Firebase login and authentication-code login
     * are separate checks.
     *
     * The user must have both:
     * 1. A valid Firebase session.
     * 2. A successful authentication-code session.
     */
    if (authenticationCodeVerified !== "true") {
      router.replace("/login");
      return;
    }

    const unsubscribe = onAuthStateChanged(
      auth,
      (currentUser) => {
        if (!isMounted) {
          return;
        }

        if (!currentUser) {
          sessionStorage.removeItem(
            "authenticationCodeVerified"
          );

          router.replace("/login");
          return;
        }

        setUser(currentUser);
        setIsCheckingAuth(false);
      }
    );

    return () => {
      isMounted = false;
      unsubscribe();
    };
  }, [router]);

  async function handleLogout() {
    try {
      await signOut(auth);
    } finally {
      sessionStorage.removeItem(
        "authenticationCodeVerified"
      );

      sessionStorage.removeItem(
        "pendingAuthCodeUid"
      );

      sessionStorage.removeItem(
        "pendingAuthCodeEmail"
      );

      router.replace("/login");
    }
  }

  if (isCheckingAuth) {
    return (
      <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
        <section className="w-full max-w-3xl rounded-lg border border-slate-300 bg-white p-8 text-center shadow-lg">
          <h1 className={`${mainHeader} mb-2`}>
            Voter Dashboard
          </h1>

          <p className="text-slate-600">
            Checking your authentication...
          </p>
        </section>
      </main>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <section className="rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-4`}>
          Voter Dashboard
        </h1>

        <p className="mb-2">
          Welcome, {user.email}.
        </p>

        <p className="mb-6 text-sm text-slate-600">
          Your password and authentication code have
          been accepted.
        </p>

        <div className="mb-6 rounded border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
          You have successfully entered the voter
          dashboard.
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() =>
              router.push("/voter/ballot")
            }
            className={buttonStyle}
          >
            Go to ballot
          </button>

          <button
            type="button"
            onClick={handleLogout}
            className="rounded bg-slate-600 px-4 py-2 text-white hover:bg-slate-700"
          >
            Log out
          </button>
        </div>
      </section>
    </main>
  );
}