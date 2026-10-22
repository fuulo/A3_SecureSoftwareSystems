"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { mainHeader, buttonStyle } from "../../components/styles";
import { useRouter } from "next/navigation";

// Settings (change them here)
const CODE_LENGTH = 6;
const RESEND_SECONDS = 60;
const NEXT_PAGE = "/voter/dashboard";

export default function VerifyPage() {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [secondsLeft, setSecondsLeft] = useState(RESEND_SECONDS);
  const [warning, setWarning] = useState("");
  const router = useRouter();

  // Clear the form when the page is shown again by back/forward navigation
  useEffect(() => {
    function clearForm() {
      setCode("");
      setError("");
      setMessage("");
      setWarning("");
    }

    window.addEventListener("pageshow", clearForm);
    return () => window.removeEventListener("pageshow", clearForm);
  }, []);

  // Count down for the "Resend code" button
  useEffect(() => {
    if (secondsLeft <= 0) return;
    const timer = setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [secondsLeft]);

  // Hide the warning after 3 seconds
  useEffect(() => {
    if (!warning) return;
    const timer = setTimeout(() => setWarning(""), 3000);
    return () => clearTimeout(timer);
  }, [warning]);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");

    if (code.length !== CODE_LENGTH) {
      setError(`Please enter the ${CODE_LENGTH}-digit MFA code.`);
      return;
    }
    setError("");

    // In this demo we don't verify MFA
    // setError("The code is incorrect or has expired.");
    // setCode("");
    router.push(NEXT_PAGE);
  }

  function handleResend() {
    if (secondsLeft > 0) return;

    setCode("");
    setError("");

    setMessage("Demo only: no verification code was sent.");
    setSecondsLeft(RESEND_SECONDS);
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-2 text-center`}>Verify Your Identity</h1>
        <p className="mb-1 text-center">
          Enter a {CODE_LENGTH}-digit verification code below.
        </p>
        <p className="mb-1 text-[10px] text-center">
          (This demo does not send or verify codes.
        </p>
        <p className="mb-6 text-[10px] text-center">
          Verification is simulated - no identity is verified.)
        </p>

        <form onSubmit={handleSubmit} noValidate className="space-y-5">
          <div>
            <label htmlFor="code" className="mb-1 block font-semibold">
              Verification code
            </label>
            <input
              id="code"
              name="code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              maxLength={CODE_LENGTH}
              value={code}
              onChange={(e) => {
                const raw = e.target.value;
                setCode(raw.replace(/\D/g, "").slice(0, CODE_LENGTH));
                setWarning(/\D/.test(raw) ? "Only numbers are allowed." : "");
              }}
              aria-invalid={error ? true : undefined}
              className="w-full rounded border border-slate-400 px-3 py-2 text-center text-[28px] font-semibold tracking-[0.4em] focus:outline-none focus:ring-2 focus:ring-[#1f538d]"
            />
            {warning && (
              <p
                role="status"
                className="mt-2 rounded border-amber-300 bg-amber-50 px-3 py-2 text-[13px] text-amber-800"
              >
                {warning}
              </p>
            )}
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
              className="rounded border border-green-300 bg-green-50 px-3 py-2 text-[13px] text-green-800"
            >
              {message}
            </p>
          )}

          <button type="submit" className={buttonStyle}>
            Verify
          </button>
        </form>

        <div className="mt-6 flex items-center justify-between">
          <button
            type="button"
            onClick={handleResend}
            disabled={secondsLeft > 0}
            className="text-[13px] capitalize text-[#1b4779] hover:underline disabled:cursor-not-allowed disabled:text-slate-400 disabled:no-underline"
          >
            {secondsLeft > 0 ? `Resend code in ${secondsLeft}s` : "Resend code"}
          </button>
          <Link
            href="/login"
            className="text-[13px] capitalize text-[#1b4779] hover:underline"
          >
            Back to login
          </Link>
        </div>
      </div>
    </div>
  );
}
