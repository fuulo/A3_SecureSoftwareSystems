"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  PhoneAuthProvider,
  PhoneMultiFactorGenerator,
  signOut,
  type PhoneMultiFactorInfo,
} from "firebase/auth";
import { auth } from "@/lib/firebase";
import { ApiError } from "@/lib/api";
import { getDashboardPath } from "@/lib/dashboard";
import {
  ACCOUNT_LOCKED_REASON,
  createInvisibleRecaptcha,
  getMfaErrorMessage,
  getPendingMfa,
  getPendingMfaDeadline,
  getPendingMfaEmail,
  MFA_TIME_LIMIT_SECONDS,
  MFA_TIMEOUT_REASON,
  setPendingMfa,
  type InvisibleRecaptcha,
} from "@/lib/mfa";
import { attemptsLeftMessage, reportFailedSignIn, reportSuccessfulSignIn } from "@/lib/lockout";
import { mainHeader, buttonStyle } from "@/components/styles";

const CODE_LENGTH = 6;
// Shorter than the time limit, so a new code can still be requested in time
const RESEND_SECONDS = 30;

const inputStyle =
  "w-full rounded border border-slate-400 px-3 py-2 text-center text-[28px] font-semibold tracking-[0.4em] focus:outline-none focus:ring-2 focus:ring-[#1f538d]";

const linkStyle = "text-[16px] text-[#1b4779] hover:underline";

type Step = "send" | "code";

export default function AuthenticationCodePage() {
  const router = useRouter();

  const [step, setStep] = useState<Step>("send");
  const [code, setCode] = useState("");
  const [verificationId, setVerificationId] = useState("");
  const [maskedPhone, setMaskedPhone] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isVerified, setIsVerified] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [secondsToExpiry, setSecondsToExpiry] = useState(MFA_TIME_LIMIT_SECONDS);

  const recaptchaRef = useRef<InvisibleRecaptcha | null>(null);
  const recaptchaHostRef = useRef<HTMLDivElement>(null);

  // Ends the login attempt when the time limit has passed
  const expireLogin = useCallback(() => {
    setPendingMfa(null);
    signOut(auth).catch(() => {});
    router.replace(`/login?reason=${MFA_TIMEOUT_REASON}`);
  }, [router]);

  // If no first-step login is waiting (for example after a refresh),
  // go back to the login page
  useEffect(() => {
    if (!getPendingMfa()) {
      router.replace("/login");
    }
  }, [router]);

  // Count down to the time limit. A code that is being checked, or has been
  // accepted, is allowed to finish.
  useEffect(() => {
    const deadline = getPendingMfaDeadline();
    if (deadline === null || isSubmitting || isVerified) return;

    const timer = setInterval(() => {
      const remaining = Math.ceil((deadline - Date.now()) / 1000);
      if (remaining <= 0) {
        clearInterval(timer);
        expireLogin();
      } else {
        setSecondsToExpiry(remaining);
      }
    }, 250);
    return () => clearInterval(timer);
  }, [isSubmitting, isVerified, expireLogin]);

  // Count down for the "Send a new code" button
  useEffect(() => {
    if (secondsLeft <= 0) return;

    const timer = setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [secondsLeft]);

  // Next.js keeps this page mounted but hidden after navigating away
  // (cacheComponents), so clear the code and start over on every visit
  useLayoutEffect(() => {
    return () => {
      setStep("send");
      setCode("");
      setVerificationId("");
      setMaskedPhone("");
      setError("");
      setMessage("");
      setIsSending(false);
      setIsSubmitting(false);
      setIsVerified(false);
      setSecondsLeft(0);
      setSecondsToExpiry(MFA_TIME_LIMIT_SECONDS);
    };
  }, []);

  // Remove the reCAPTCHA when leaving the page
  useEffect(() => {
    return () => {
      recaptchaRef.current?.dispose();
      recaptchaRef.current = null;
    };
  }, []);

  function handleCodeChange(event: React.ChangeEvent<HTMLInputElement>) {
    const digitsOnly = event.target.value
      .replace(/\D/g, "")
      .slice(0, CODE_LENGTH);

    setCode(digitsOnly);
    setError("");
    setMessage("");
  }

  // Sends the text message (also used by "Send a new code")
  async function sendCode() {
    const resolver = getPendingMfa();

    if (!resolver) {
      router.replace("/login");
      return;
    }

    const hint = resolver.hints.find(
      (item) => item.factorId === PhoneMultiFactorGenerator.FACTOR_ID
    );

    if (!hint) {
      setError("No phone number is set up for this account.");
      return;
    }

    setError("");
    setMessage("");
    setIsSending(true);

    try {
      const recaptcha = createInvisibleRecaptcha(recaptchaHostRef.current);
      recaptchaRef.current = recaptcha;

      const id = await new PhoneAuthProvider(auth).verifyPhoneNumber(
        { multiFactorHint: hint, session: resolver.session },
        recaptcha.verifier
      );

      setVerificationId(id);
      setMaskedPhone((hint as PhoneMultiFactorInfo).phoneNumber ?? "");
      setCode("");
      setStep("code");
      setSecondsLeft(RESEND_SECONDS);
      setMessage("A code has been sent by text message.");
    } catch (firebaseError) {
      console.error("Sending the verification code failed:", firebaseError);
      setError(getMfaErrorMessage(firebaseError));
    } finally {
      // A reCAPTCHA token works only once, so start fresh next time
      recaptchaRef.current?.dispose();
      recaptchaRef.current = null;
      setIsSending(false);
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setError("");
    setMessage("");

    // Step 1: check the text message code with Firebase.
    // If this already worked and only the dashboard lookup failed,
    // the check is skipped and only the lookup is tried again.
    if (!isVerified) {
      const resolver = getPendingMfa();

      if (!resolver) {
        setError("Your login session has expired. Please log in again.");
        router.replace("/login");
        return;
      }

      const deadline = getPendingMfaDeadline();
      if (deadline === null || Date.now() >= deadline) {
        expireLogin();
        return;
      }

      if (code.length !== CODE_LENGTH) {
        setError(`Please enter the ${CODE_LENGTH}-digit authentication code.`);
        return;
      }

      setIsSubmitting(true);

      try {
        const credential = PhoneAuthProvider.credential(verificationId, code);
        const assertion = PhoneMultiFactorGenerator.assertion(credential);

        // Firebase completes the sign-in only now, after the second step
        await resolver.resolveSignIn(assertion);
      } catch (firebaseError) {
        const failure = getMfaErrorMessage(firebaseError);

        // A wrong code counts towards locking the account
        if ((firebaseError as { code?: string }).code === "auth/invalid-verification-code") {
          try {
            const lockout = await reportFailedSignIn(getPendingMfaEmail());
            if (lockout.locked) {
              setPendingMfa(null);
              signOut(auth).catch(() => {});
              router.replace(`/login?reason=${ACCOUNT_LOCKED_REASON}`);
              return;
            }
            setError(`${failure} ${attemptsLeftMessage(lockout)}`);
          } catch (reportError) {
            console.error("Unable to report the failed sign-in", reportError);
            setError(failure);
          }
        } else {
          setError(failure);
        }
        setIsSubmitting(false);
        return;
      }

      // Both factors passed, so the failed attempt count starts again
      await reportSuccessfulSignIn();
      setPendingMfa(null);
      setIsVerified(true);

      // Temporary: other pages may still look for this flag. It is only set
      // after the real check above. Replace those checks with a Firebase check
      // (see the notes) and then delete this line.
      sessionStorage.setItem("authenticationCodeVerified", "true");
    } else {
      setIsSubmitting(true);
    }

    // Step 2: work out which dashboard to open
    try {
      router.replace(await getDashboardPath());
    } catch (profileError) {
      if (profileError instanceof ApiError && profileError.status === 401) {
        sessionStorage.removeItem("authenticationCodeVerified");
        router.replace("/login");
        return;
      }

      console.error(profileError);
      setError(
        "You are signed in, but your account details could not be loaded. Please try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleBackToLogin() {
    setPendingMfa(null);
    router.push("/login");
  }

  return (
    <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <section className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-2 text-center`}>
          Authentication Code
        </h1>

        {!isVerified && (
          <p role="timer" className="mb-4 text-center text-[13px] text-slate-600">
            Time remaining:{" "}
            <span
              className={`font-semibold ${secondsToExpiry <= 10 ? "text-red-700" : "text-slate-800"}`}
            >
              {secondsToExpiry}s
            </span>
          </p>
        )}

        {step === "send" && (
          <>
            <p className="mb-8 text-center text-slate-600">
              We will send a {CODE_LENGTH}-digit code by text message to the
              phone number set up for your account.
            </p>

            <div className="space-y-5">
              {error && (
                <p
                  role="alert"
                  className="rounded border border-red-300 bg-red-50 px-3 py-2 text-[13px] text-red-700"
                >
                  {error}
                </p>
              )}

              <button
                type="button"
                onClick={sendCode}
                disabled={isSending}
                className={`${buttonStyle} w-full disabled:cursor-not-allowed disabled:opacity-60`}
              >
                {isSending ? "Sending..." : "Send code"}
              </button>
            </div>
          </>
        )}

        {step === "code" && (
          <>
            <p className="mb-4 text-center text-slate-600">
              Enter the {CODE_LENGTH}-digit code sent to {maskedPhone}.
            </p>

            <p className="mb-6 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-center text-[13px] text-amber-800">
              If you are using the testing phone number,<br />your verification code is{" "}
              <strong>123456</strong>.
            </p>

            <form onSubmit={handleSubmit} className="space-y-5">
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
                  className={`${inputStyle} ${error ? "border-red-500" : ""}`}
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
                {isSubmitting ? "Checking code..." : "Continue"}
              </button>
            </form>

            <div className="mt-6 text-center">
              <button
                type="button"
                onClick={sendCode}
                disabled={isSending || isSubmitting || isVerified || secondsLeft > 0}
                className={`${linkStyle} disabled:cursor-not-allowed disabled:text-slate-400 disabled:no-underline`}
              >
                {secondsLeft > 0
                  ? `Send a new code in ${secondsLeft}s`
                  : "Send a new code"}
              </button>
            </div>
          </>
        )}

        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={handleBackToLogin}
            className={linkStyle}
          >
            Back to login
          </button>
        </div>

        {/* Holds the invisible reCAPTCHA */}
        <div ref={recaptchaHostRef} />
      </section>
    </main>
  );
}
