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

    if (authenticationCodeVerified !== "true") {
      router.replace("/login");
      return;
    }

    const unsubscribe = onAuthStateChanged(
      auth,
      async (currentUser) => {
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

        await currentUser.reload();

        if (!currentUser.emailVerified) {
          sessionStorage.removeItem(
            "authenticationCodeVerified"
          );

          router.replace("/email_verification");
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
        <section className="w-full max-w-4xl rounded-lg border border-slate-300 bg-white p-8 text-center shadow-lg">
          <h1 className={`${mainHeader} mb-2`}>
            Voter Dashboard
          </h1>

          <p className="text-slate-600">
            Loading your dashboard...
          </p>
        </section>
      </main>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-12">
      <section className="mb-8">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div>
            <h1 className={`${mainHeader} mb-2`}>
              Voter Dashboard
            </h1>

            <p className="text-slate-600">
              Welcome,{" "}
              <span className="font-semibold text-slate-900">
                {user.email}
              </span>
            </p>
          </div>

          <button
            type="button"
            onClick={handleLogout}
            className="rounded border border-slate-400 px-4 py-2 text-sm text-slate-700 hover:bg-slate-100"
          >
            Log out
          </button>
        </div>
      </section>

      <section className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <button
          type="button"
          onClick={() =>
            router.push("/voter/ballot")
          }
          className="rounded-lg border border-slate-300 bg-white p-6 text-left shadow-md transition hover:-translate-y-1 hover:border-[#1f538d] hover:shadow-lg"
        >
          <h2 className="mb-2 text-xl font-semibold text-[#1f538d]">
            Vote
          </h2>

          <p className="mb-4 text-sm text-slate-600">
            View the current ballot and submit your
            vote.
          </p>

          <span className="text-sm font-semibold text-[#1b4779]">
            Open ballot →
          </span>
        </button>

        <button
          type="button"
          onClick={() =>
            router.push("/voter/profile")
          }
          className="rounded-lg border border-slate-300 bg-white p-6 text-left shadow-md transition hover:-translate-y-1 hover:border-[#1f538d] hover:shadow-lg"
        >
          <h2 className="mb-2 text-xl font-semibold text-[#1f538d]">
            My profile
          </h2>

          <p className="mb-4 text-sm text-slate-600">
            View and manage your account information.
          </p>

          <span className="text-sm font-semibold text-[#1b4779]">
            View profile →
          </span>
        </button>

        <button
          type="button"
          onClick={() =>
            router.push("/voter/status")
          }
          className="rounded-lg border border-slate-300 bg-white p-6 text-left shadow-md transition hover:-translate-y-1 hover:border-[#1f538d] hover:shadow-lg"
        >
          <h2 className="mb-2 text-xl font-semibold text-[#1f538d]">
            Voting status
          </h2>

          <p className="mb-4 text-sm text-slate-600">
            Check your enrolment and voting status.
          </p>

          <span className="text-sm font-semibold text-[#1b4779]">
            View status →
          </span>
        </button>

        <button
          type="button"
          onClick={() =>
            router.push("/voter/help")
          }
          className="rounded-lg border border-slate-300 bg-white p-6 text-left shadow-md transition hover:-translate-y-1 hover:border-[#1f538d] hover:shadow-lg"
        >
          <h2 className="mb-2 text-xl font-semibold text-[#1f538d]">
            Help and information
          </h2>

          <p className="mb-4 text-sm text-slate-600">
            Find information about voting and using
            the system.
          </p>

          <span className="text-sm font-semibold text-[#1b4779]">
            Get help →
          </span>
        </button>

        <button
          type="button"
          onClick={() =>
            router.push("/forgot_pw")
          }
          className="rounded-lg border border-slate-300 bg-white p-6 text-left shadow-md transition hover:-translate-y-1 hover:border-[#1f538d] hover:shadow-lg"
        >
          <h2 className="mb-2 text-xl font-semibold text-[#1f538d]">
            Change password
          </h2>

          <p className="mb-4 text-sm text-slate-600">
            Reset your password using your email
            address.
          </p>

          <span className="text-sm font-semibold text-[#1b4779]">
            Change password →
          </span>
        </button>
      </section>

      <section className="mt-8 rounded-lg border border-blue-200 bg-blue-50 p-5 text-sm text-blue-900">
        <h2 className="mb-2 font-semibold">
          Your account is ready
        </h2>

        <p>
          Choose an option above to continue. Your
          email, password, and authentication code
          have been accepted.
        </p>
      </section>
    </main>
  );
}