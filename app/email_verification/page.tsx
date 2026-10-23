"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  onAuthStateChanged,
  reload,
  sendEmailVerification,
  signOut,
  User,
} from "firebase/auth";
import { auth } from "@/lib/firebase";
import {
  buttonStyle,
  mainHeader,
} from "@/components/styles";

const linkStyle =
  "text-[13px] text-[#1b4779] hover:underline";

export default function EmailVerificationPage() {
  const router = useRouter();

  const [user, setUser] =
    useState<User | null>(null);

  const [isChecking, setIsChecking] =
    useState(true);

  const [isResending, setIsResending] =
    useState(false);

  const [isRefreshing, setIsRefreshing] =
    useState(false);

  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(
      auth,
      (currentUser) => {
        if (!currentUser) {
          router.replace("/login");
          return;
        }

        setUser(currentUser);
        setIsChecking(false);
      }
    );

    return unsubscribe;
  }, [router]);

  async function handleResendEmail() {
    if (!user) {
      return;
    }

    setError("");
    setMessage("");
    setIsResending(true);

    try {
      await sendEmailVerification(user);

      setMessage(
        "A new verification email has been sent. Please check your inbox and spam folder."
      );
    } catch (firebaseError) {
      console.error(firebaseError);

      setError(
        "The verification email could not be sent. Please wait a moment and try again."
      );
    } finally {
      setIsResending(false);
    }
  }

  async function handleCheckVerification() {
    if (!user) {
      return;
    }

    setError("");
    setMessage("");
    setIsRefreshing(true);

    try {
      await reload(user);

      if (auth.currentUser?.emailVerified) {
        router.replace("/login");
        return;
      }

      setError(
        "Your email is not verified yet. Click the link in the email, then try again."
      );
    } catch (firebaseError) {
      console.error(firebaseError);

      setError(
        "We could not check your verification status. Please try again."
      );
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleLogout() {
    await signOut(auth);

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

  if (isChecking) {
    return (
      <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
        <section className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 text-center shadow-lg">
          <p className="text-slate-600">
            Checking your account...
          </p>
        </section>
      </main>
    );
  }

  return (
    <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <section className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-4 text-center`}>
          Verify Your Email
        </h1>

        <p className="mb-4 text-center text-slate-700">
          We sent a verification link to:
        </p>

        <p className="mb-6 break-words text-center font-semibold text-[#1f538d]">
          {user?.email}
        </p>

        <p className="mb-6 text-center text-sm text-slate-600">
          Open the email and click the verification
          link. After that, return here and click the
          button below.
        </p>

        {error && (
          <p
            role="alert"
            className="mb-4 rounded border border-red-300 bg-red-50 px-3 py-2 text-[13px] text-red-700"
          >
            {error}
          </p>
        )}

        {message && (
          <p
            role="status"
            className="mb-4 rounded border border-green-300 bg-green-50 px-3 py-2 text-[13px] text-green-700"
          >
            {message}
          </p>
        )}

        <div className="space-y-3">
          <button
            type="button"
            onClick={handleCheckVerification}
            disabled={isRefreshing}
            className={`${buttonStyle} w-full disabled:cursor-not-allowed disabled:opacity-60`}
          >
            {isRefreshing
              ? "Checking..."
              : "I have verified my email"}
          </button>

          <button
            type="button"
            onClick={handleResendEmail}
            disabled={isResending}
            className="w-full rounded border border-[#1f538d] px-4 py-2 text-[#1f538d] hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isResending
              ? "Sending..."
              : "Resend verification email"}
          </button>

          <button
            type="button"
            onClick={handleLogout}
            className="w-full text-center text-[13px] text-slate-600 hover:underline"
          >
            Use a different account
          </button>
        </div>

        <div className="mt-6 text-center">
          <Link
            href="/"
            className={linkStyle}
          >
            Back to home page
          </Link>
        </div>
      </section>
    </main>
  );
}