"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { sendEmailVerification, signOut } from "firebase/auth";
import { auth } from "../../lib/firebase";
import { mainHeader, buttonStyle } from "../../components/styles";

export default function VerifyPage() {
  const router = useRouter();

  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isChecking, setIsChecking] = useState(false);

  useEffect(() => {
    async function checkVerificationStatus() {
      const user = auth.currentUser;

      if (!user) {
        setError("Please sign in before verifying your email address.");
        return;
      }

      try {
        await user.reload();

        if (user.emailVerified) {
          setMessage(
            "Your email address is already verified. You may now sign in.",
          );
        }
      } catch (firebaseError) {
        console.error(firebaseError);
        setError("Unable to check your verification status.");
      }
    }

    void checkVerificationStatus();
  }, []);

  async function handleResend() {
    setError("");
    setMessage("");

    const user = auth.currentUser;

    if (!user) {
      setError("Please sign in before requesting a verification email.");
      return;
    }

    if (user.emailVerified) {
      setMessage("Your email address has already been verified.");
      return;
    }

    setIsSending(true);

    try {
      await sendEmailVerification(user);

      setMessage(
        "A new verification link has been sent. Check your inbox and spam folder.",
      );
    } catch (firebaseError) {
      console.error(firebaseError);
      setError("Unable to send the verification email. Please try again.");
    } finally {
      setIsSending(false);
    }
  }

  async function handleCheckVerification() {
    setError("");
    setMessage("");

    const user = auth.currentUser;

    if (!user) {
      setError("Please sign in before checking your verification status.");
      return;
    }

    setIsChecking(true);

    try {
      await user.reload();

      if (user.emailVerified) {
        setMessage("Your email address is verified. You may now sign in.");
      } else {
        setError(
          "Your email is not verified yet. Click the verification link in the email first.",
        );
      }
    } catch (firebaseError) {
      console.error(firebaseError);
      setError("Unable to check your verification status.");
    } finally {
      setIsChecking(false);
    }
  }

  async function handleSignOut() {
    try {
      await signOut(auth);
      router.replace("/login");
    } catch (firebaseError) {
      console.error(firebaseError);
      setError("Unable to sign out. Please try again.");
    }
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-2 text-center`}>
          Verify Your Email
        </h1>

        <p className="mb-6 text-center">
          Open the verification email sent to your address and click the
          verification link. This page does not use a numeric code.
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
            className="mb-4 rounded border border-green-300 bg-green-50 px-3 py-2 text-[13px] text-green-800"
          >
            {message}
          </p>
        )}

        <div className="space-y-4">
          <button
            type="button"
            onClick={handleCheckVerification}
            disabled={isChecking}
            className={`${buttonStyle} w-full disabled:cursor-not-allowed disabled:opacity-60`}
          >
            {isChecking ? "Checking..." : "I have verified my email"}
          </button>

          <button
            type="button"
            onClick={handleResend}
            disabled={isSending}
            className="w-full text-[13px] text-[#1b4779] hover:underline disabled:cursor-not-allowed disabled:text-slate-400"
          >
            {isSending ? "Sending..." : "Resend verification email"}
          </button>

          <button
            type="button"
            onClick={handleSignOut}
            className="w-full text-[13px] text-orange-700 hover:underline"
          >
            Sign out
          </button>
        </div>

        <div className="mt-6 text-center">
          <Link
            href="/login"
            className="text-[13px] text-[#1b4779] hover:underline"
          >
            Back to login
          </Link>
        </div>
      </div>
    </div>
  );
}