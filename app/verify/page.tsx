"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { mainHeader } from "../../components/styles";

// Settings (change them here)
const CODE_LENGTH = 6;
const RESEND_SECONDS = 60;
const EXPIRY_MINUTES = 1;

export default function VerifyPage() {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [secondsLeft, setSecondsLeft] = useState(RESEND_SECONDS);
  const [warning, setWarning] = useState("");

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
    const timer = setTimeout (() => setWarning(""), 3000);
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




    // TODO: send the code to the backend to check it.
    // On success, go to the voting page (needs: const router = useRouter();)
    // On failure, show ONE general message, e.g.:
    //   setError("The code is incorrect or has expired.");
  


}

  function handleResend() {
    if (secondsLeft > 0) return;

    setCode("");
    setError("");




    // TODO: backend to send a new code to [email / SMS].




    setMessage("A new code has been sent to you.");
    setSecondsLeft(RESEND_SECONDS);
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-2 text-center`}>Verify Your Identity</h1>
        <p className="mb-1 text-center">
          Enter the {CODE_LENGTH}-digit verification code we sent to you in the box below.
        </p>
        <p className="mb-6 text-center">
          The code expires in {EXPIRY_MINUTES} minute.
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
              maxLength={CODE_LENGTH}
              value={code}
              onChange={(e) => {
                const raw = e.target.value;
                setCode(raw.replace(/\D/g, "").slice(0, CODE_LENGTH));
                setWarning(/\D/.test(raw) ? "Only numbers are allowed." : "")
              }}
              aria-invalid={error ? true : undefined}
              className="w-full rounded border border-slate-400 px-3 py-2 text-center text-[28px] font-semibold tracking-[0.4em] focus:outline-none focus:ring-2 focus:ring-[#1f538d]"
            />
            {warning && (
            <p
              role = "status"
              className = "mt-2 rounded border-amber-300 bg-amber-50 px-3 py-2 text-[13px] text-amber-800"
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

          <button
            type="submit"
            className="w-full rounded-lg bg-[#1f538d] px-6 py-3 text-[24px] font-bold text-white shadow-[0_8px_20px_rgba(0,0,0,0.35)] transition duration-200 hover:-translate-y-1 hover:bg-[#1b4779] hover:shadow-[0_14px_28px_rgba(0,0,0,0.4)] active:translate-y-0 active:shadow-[0_4px_10px_rgba(0,0,0,0.3)]"
          >
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
