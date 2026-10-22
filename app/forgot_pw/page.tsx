"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { mainHeader,buttonStyle } from "../../components/styles";

// Settings for reset code and min password length 
const CODE_LENGTH = 6;
const MIN_PASSWORD_LENGTH = 6;

type Step = "request" | "reset";

// Reusable styles
const inputStyle =
  "w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]";
const linkStyle = "text-[13px] capitalize text-[#1b4779] hover:underline";

export default function ForgotPasswordPage() {
  const [step, setStep] = useState<Step>("request");
  const [id, setId] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  // Go back to the first step when the page is shown again by back/forward
  // navigation, so no ID, code or password stays on screen
  useEffect(() => {
    function resetPage() {
      setStep("request");
      setId("");
      setCode("");
      setNewPassword("");
      setConfirmPassword("");
      setError("");
      setMessage("");
    }

    window.addEventListener("pageshow", resetPage);
    return () => window.removeEventListener("pageshow", resetPage);
  }, []);

  function handleRequest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!id.trim()) {
      setError("Please enter your ID.");
      return;
    }
    setError("");

    setMessage(
      "If this ID is registered, reset instructions would be sent in a live service. This demo does not send email."
    );
    setStep("reset");
  }

  function handleReset(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");

    if (code.length !== CODE_LENGTH) {
      setError(`Please enter the ${CODE_LENGTH}-digit code.`);
      return;
    }
    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setError(
        `Your new password must have at least ${MIN_PASSWORD_LENGTH} characters.`
      );
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("The two passwords do not match.");
      return;
    }
    setError("");

    setError("The code is incorrect or has expired.");
    setCode("");
    setNewPassword("");
    setConfirmPassword("");
  }

  function handleChangeId() {
    setCode("");
    setNewPassword("");
    setConfirmPassword("");
    setError("");
    setMessage("");
    setStep("request");
  }

  // Error and status messages (shared by both forms)
  const feedback = (
    <>
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
    </>
  );

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        {/* Step 1: enter ID */}
        {step === "request" && (
          <>
            <h1 className={`${mainHeader} mb-2 text-center`}>
              Forgot Your Password?
            </h1>
            <p className="mb-6 text-center">
              Enter your ID to see the simulated reset flow. This demo does not
              send email or change passwords.
            </p>

            <form onSubmit={handleRequest} noValidate className="space-y-5">
              <div>
                <label htmlFor="id" className="mb-1 block font-semibold">
                  ID
                </label>
                <input
                  id="id"
                  name="id"
                  type="text"
                  autoComplete="username"
                  value={id}
                  onChange={(e) => setId(e.target.value)}
                  aria-invalid={error ? true : undefined}
                  className={inputStyle}
                />
              </div>

              {feedback}

              <button type="submit" className={buttonStyle}>
                Send reset code
              </button>
            </form>
          </>
        )}

        {/* Step 2: enter code and new password */}
        {step === "reset" && (
          <>
            <h1 className={`${mainHeader} mb-2 text-center`}>
              Reset Your Password
            </h1>
            <p className="mb-6 text-center">
              In a live service, enter the {CODE_LENGTH}-digit code and choose a
              new password with at least {MIN_PASSWORD_LENGTH} characters. This
              demo does not verify codes or change passwords.
            </p>

            <form onSubmit={handleReset} noValidate className="space-y-5">
              <div>
                <label htmlFor="code" className="mb-1 block font-semibold">
                  Reset code
                </label>
                <input
                  id="code"
                  name="code"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={CODE_LENGTH}
                  value={code}
                  onChange={(e) =>
                    setCode(
                      e.target.value.replace(/\D/g, "").slice(0, CODE_LENGTH)
                    )
                  }
                  className={`${inputStyle} text-center text-[28px] font-semibold tracking-[0.4em]`}
                />
              </div>

              <div>
                <label
                  htmlFor="new-password"
                  className="mb-1 block font-semibold"
                >
                  New password
                </label>
                <input
                  id="new-password"
                  name="new-password"
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className={inputStyle}
                />
              </div>

              <div>
                <label
                  htmlFor="confirm-password"
                  className="mb-1 block font-semibold"
                >
                  Confirm new password
                </label>
                <input
                  id="confirm-password"
                  name="confirm-password"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className={inputStyle}
                />
              </div>

              {feedback}

              <button type="submit" className={buttonStyle}>
                Reset password
              </button>
            </form>
          </>
        )}

        {/* Bottom links */}
        <div
          className={`mt-6 flex items-center ${
            step === "reset" ? "justify-between" : "justify-center"
          }`}
        >
          {step === "reset" && (
            <button
              type="button"
              onClick={handleChangeId}
              className={linkStyle}
            >
              Use a different ID
            </button>
          )}
          <Link href="/login" className={linkStyle}>
            Back to login
          </Link>
        </div>
      </div>
    </div>
  );
}
