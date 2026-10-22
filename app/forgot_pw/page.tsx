"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { sendPasswordResetEmail } from "firebase/auth";
import { auth } from "../../lib/firebase";
import { mainHeader, buttonStyle } from "../../components/styles";

const inputStyle =
  "w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]";

const linkStyle =
  "text-[13px] capitalize text-[#1b4779] hover:underline";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    function resetPage() {
      setEmail("");
      setError("");
      setMessage("");
      setIsSubmitting(false);
    }

    window.addEventListener("pageshow", resetPage);

    return () => {
      window.removeEventListener("pageshow", resetPage);
    };
  }, []);

  async function handleRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedEmail = email.trim();

    setError("");
    setMessage("");

    if (!trimmedEmail) {
      setError("Please enter your email address.");
      return;
    }

    setIsSubmitting(true);

    try {
      await sendPasswordResetEmail(auth, trimmedEmail);

      setMessage(
        "If an account exists for this email address, password-reset instructions have been sent."
      );
      setEmail("");
    } catch (firebaseError) {
      console.error(firebaseError);

      // Use the same message for all outcomes so the page does not reveal
      // whether a particular email address is registered.
      setMessage(
        "If an account exists for this email address, password-reset instructions have been sent."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-2 text-center`}>
          Forgot Your Password?
        </h1>

        <p className="mb-6 text-center">
          Enter the email address associated with your account. If an account
          exists, password-reset instructions will be sent to that address.
        </p>

        <form onSubmit={handleRequest} noValidate className="space-y-5">
          <div>
            <label
              htmlFor="email"
              className="mb-1 block font-semibold"
            >
              Email address
            </label>

            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
                setError("");
                setMessage("");
              }}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "reset-error" : undefined}
              className={inputStyle}
            />
          </div>

          {error && (
            <p
              id="reset-error"
              role="alert"
              className="rounded border border-red-300 bg-red-50 px-3 py-2 text-[13px] text-red-700"
            >
              {error}
            </p>
          )}

          {message && (
            <p
              role="status"
              className="rounded border border-green-300 bg-green-50 px-3 py-2 text-[13px] text-green-800"
            >
              {message}
            </p>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className={`${buttonStyle} disabled:cursor-not-allowed disabled:opacity-60`}
          >
            {isSubmitting ? "Sending instructions..." : "Send reset instructions"}
          </button>
        </form>

        <div className="mt-6 flex justify-center">
          <Link href="/login" className={linkStyle}>
            Back to login
          </Link>
        </div>
      </div>
    </div>
  );
}
