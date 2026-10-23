"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  mainHeader,
  buttonStyle,
} from "@/components/styles";

const CODE_LENGTH = 6;
const NEXT_PAGE = "/voter/dashboard";

const inputStyle =
  "w-full rounded border border-slate-400 px-3 py-2 text-center text-[28px] font-semibold tracking-[0.4em] focus:outline-none focus:ring-2 focus:ring-[#1f538d]";

const linkStyle =
  "text-[13px] text-[#1b4779] hover:underline";

export default function AuthenticationCodePage() {
  const router = useRouter();

  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [isSubmitting, setIsSubmitting] =
    useState(false);

  useEffect(() => {
    const pendingUid = sessionStorage.getItem(
      "pendingAuthCodeUid"
    );

    if (!pendingUid) {
      router.replace("/login");
    }
  }, [router]);

  function handleCodeChange(
    event: React.ChangeEvent<HTMLInputElement>
  ) {
    const digitsOnly = event.target.value
      .replace(/\D/g, "")
      .slice(0, CODE_LENGTH);

    setCode(digitsOnly);
    setError("");
    setMessage("");
  }

  async function handleSubmit(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    setError("");
    setMessage("");

    const pendingUid = sessionStorage.getItem(
      "pendingAuthCodeUid"
    );

    if (!pendingUid) {
      setError(
        "Your login session has expired. Please log in again."
      );
      router.replace("/login");
      return;
    }

    if (code.length !== CODE_LENGTH) {
      setError(
        `Please enter the ${CODE_LENGTH}-digit authentication code.`
      );
      return;
    }

    setIsSubmitting(true);

    try {
      /*
       * DEMO MODE:
       * The code is accepted after the correct number of
       * digits has been entered.
       *
       * Replace this block with server-side or Firebase
       * MFA verification before using this application
       * in production.
       */

      sessionStorage.removeItem(
        "pendingAuthCodeUid"
      );

      sessionStorage.removeItem(
        "pendingAuthCodeEmail"
      );

      sessionStorage.setItem(
        "authenticationCodeVerified",
        "true"
      );

      router.push(NEXT_PAGE);
    } catch (verificationError) {
      console.error(verificationError);
      setError(
        "The authentication code could not be processed."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleBackToLogin() {
    sessionStorage.removeItem(
      "pendingAuthCodeUid"
    );

    sessionStorage.removeItem(
      "pendingAuthCodeEmail"
    );

    router.push("/login");
  }

  return (
    <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <section className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-2 text-center`}>
          Authentication Code
        </h1>

        <p className="mb-8 text-center text-slate-600">
          Enter the authentication code to continue.
        </p>

        <form
          onSubmit={handleSubmit}
          className="space-y-5"
        >
          <div>
            <label
              htmlFor="authenticationCode"
              className="mb-1 block font-semibold"
            >
              Authentication code
            </label>

            <input
              id="authenticationCode"
              name="authenticationCode"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]*"
              maxLength={CODE_LENGTH}
              required
              autoFocus
              value={code}
              onChange={handleCodeChange}
              aria-invalid={error ? true : undefined}
              className={`${inputStyle} ${
                error ? "border-red-500" : ""
              }`}
            />

            <p className="mt-2 text-center text-xs text-slate-500">
              Enter exactly {CODE_LENGTH} numbers.
            </p>
          </div>

          {error && (
            <p
              role="alert"
              className="rounded border border-red-300 bg-red-50 px-3 py-2 text-[13px] text-red-700"
            >
              {error}
            </p>
          )}

          {message && (
            <p
              role="status"
              className="rounded border border-green-300 bg-green-50 px-3 py-2 text-[13px] text-green-700"
            >
              {message}
            </p>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className={`${buttonStyle} w-full disabled:cursor-not-allowed disabled:opacity-60`}
          >
            {isSubmitting
              ? "Checking code..."
              : "Continue"}
          </button>
        </form>

        <div className="mt-6 text-center">
          <button
            type="button"
            onClick={handleBackToLogin}
            className={linkStyle}
          >
            Back to login
          </button>
        </div>
      </section>
    </main>
  );
}