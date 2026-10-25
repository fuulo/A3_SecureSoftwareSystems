"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  multiFactor,
  onAuthStateChanged,
  PhoneAuthProvider,
  PhoneMultiFactorGenerator,
  RecaptchaVerifier,
  signOut,
  type User,
} from "firebase/auth";
import { auth } from "@/lib/firebase";
import { getDashboardPath } from "@/lib/dashboard";
import { getMfaErrorMessage, toE164AU } from "@/lib/mfa";
import { buttonStyle, mainHeader } from "@/components/styles";

const CODE_LENGTH = 6;

type Step = "checking" | "unverified" | "phone" | "code" | "done";

const inputStyle =
  "w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]";
const linkStyle = "text-[13px] text-[#1b4779] hover:underline";

export default function MfaSetupPage() {
  const router = useRouter();

  const [user, setUser] = useState<User | null>(null);
  const [step, setStep] = useState<Step>("checking");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [verificationId, setVerificationId] = useState("");
  const [error, setError] = useState("");
  const [isBusy, setIsBusy] = useState(false);

  const recaptchaRef = useRef<RecaptchaVerifier | null>(null);

  // Next.js keeps this page mounted but hidden after navigating away
  // (cacheComponents), so start over on every visit. The sign-in check
  // below runs again when the page is shown and picks the right step.
  useLayoutEffect(() => {
    return () => {
      setUser(null);
      setStep("checking");
      setPhone("");
      setCode("");
      setVerificationId("");
      setError("");
      setIsBusy(false);
    };
  }, []);

  // Check who is signed in, and whether they can set up a second step
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (currentUser) => {
      if (!currentUser) {
        router.replace("/login");
        return;
      }

      try {
        // Refresh the user, so a newly verified email is noticed
        await currentUser.reload();
      } catch {
        // Carry on with what we have
      }

      if (multiFactor(currentUser).enrolledFactors.length > 0) {
        // Already set up, so go to the right dashboard
        try {
          router.replace(await getDashboardPath());
        } catch {
          router.replace("/login");
        }
        return;
      }

      setUser(currentUser);
      setStep(currentUser.emailVerified ? "phone" : "unverified");
    });

    return () => {
      unsubscribe();
      recaptchaRef.current?.clear();
      recaptchaRef.current = null;
    };
  }, [router]);

  async function handleRecheckEmail() {
    if (!user) return;

    setError("");
    setIsBusy(true);

    try {
      await user.reload();

      if (user.emailVerified) {
        setStep("phone");
      } else {
        setError("Your email address is not verified yet.");
      }
    } catch (firebaseError) {
      console.error("Send code failed:", firebaseError);
      setError(getMfaErrorMessage(firebaseError));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSendCode(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user) return;

    const e164 = toE164AU(phone);
    if (!e164) {
      setError("Please enter a valid Australian phone number.");
      return;
    }

    setError("");
    setIsBusy(true);

    try {
      const session = await multiFactor(user).getSession();

      const recaptcha = new RecaptchaVerifier(auth, "recaptcha-container", {
        size: "invisible",
      });
      recaptchaRef.current = recaptcha;

      const id = await new PhoneAuthProvider(auth).verifyPhoneNumber(
        { phoneNumber: e164, session },
        recaptcha
      );

      setVerificationId(id);
      setCode("");
      setStep("code");
    } catch (firebaseError) {
      setError(getMfaErrorMessage(firebaseError));
    } finally {
      // A reCAPTCHA token works only once, so start fresh next time
      recaptchaRef.current?.clear();
      recaptchaRef.current = null;
      setIsBusy(false);
    }
  }

  async function handleEnrol(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user) return;

    if (code.length !== CODE_LENGTH) {
      setError(`Please enter the ${CODE_LENGTH}-digit code.`);
      return;
    }

    setError("");
    setIsBusy(true);

    try {
      const credential = PhoneAuthProvider.credential(verificationId, code);
      const assertion = PhoneMultiFactorGenerator.assertion(credential);

      await multiFactor(user).enroll(assertion, "Mobile phone");

      setPhone("");
      setCode("");
      setStep("done");
    } catch (firebaseError) {
      setError(getMfaErrorMessage(firebaseError));
    } finally {
      setIsBusy(false);
    }
  }

  // Sign out and load the login page fresh, so the next login uses the new step
  async function handleLoginAgain() {
    try {
      await signOut(auth);
    } finally {
      window.location.replace("/login");
    }
  }

  const errorBox = error ? (
    <p
      role="alert"
      className="rounded border border-red-300 bg-red-50 px-3 py-2 text-[13px] text-red-700"
    >
      {error}
    </p>
  ) : null;

  return (
    <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <section className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        {step === "checking" && (
          <>
            <h1 className={`${mainHeader} mb-2 text-center`}>
              Set Up Text Message Verification
            </h1>
            <p className="text-center text-slate-600">
              Checking your account...
            </p>
          </>
        )}

        {step === "unverified" && (
          <>
            <h1 className={`${mainHeader} mb-2 text-center`}>
              Verify Your Email First
            </h1>
            <p className="mb-6 text-center text-slate-600">
              Open the link in the email we sent you, then click the button
              below.
            </p>

            <div className="space-y-5">
              {errorBox}

              <button
                type="button"
                onClick={handleRecheckEmail}
                disabled={isBusy}
                className={`${buttonStyle} w-full disabled:cursor-not-allowed disabled:opacity-60`}
              >
                {isBusy ? "Checking..." : "I have verified my email"}
              </button>
            </div>
          </>
        )}

        {step === "phone" && (
          <>
            <h1 className={`${mainHeader} mb-2 text-center`}>
              Set Up Text Message Verification
            </h1>
            <p className="mb-4 text-center text-slate-600">
              Add the phone number that will receive your login codes.
            </p>

            <p className="mb-6 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-[13px] text-amber-800">
              This is a mock system. Use the test phone number given by your
              team.
            </p>

            <form onSubmit={handleSendCode} noValidate className="space-y-5">
              <div>
                <label htmlFor="phone" className="mb-1 block font-semibold">
                  Phone number
                </label>
                <input
                  id="phone"
                  name="phone"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  autoFocus
                  value={phone}
                  onChange={(event) => {
                    setPhone(event.target.value);
                    setError("");
                  }}
                  className={inputStyle}
                />
                <p className="mt-1 text-xs text-slate-500">
                  For example, 0412 345 678 or +61 412 345 678. We will send a
                  SMS with your verification vode to this number.
                </p>
              </div>

              {errorBox}

              <button
                type="submit"
                disabled={isBusy}
                className={`${buttonStyle} w-full disabled:cursor-not-allowed disabled:opacity-60`}
              >
                {isBusy ? "Sending..." : "Send code"}
              </button>
            </form>
          </>
        )}

        {step === "code" && (
          <>
            <h1 className={`${mainHeader} mb-2 text-center`}>
              Enter Your Code
            </h1>
            <p className="mb-6 text-center text-slate-600">
              Enter the {CODE_LENGTH}-digit code we sent by text message.
            </p>

            <form onSubmit={handleEnrol} noValidate className="space-y-5">
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
                  onChange={(event) => {
                    setCode(
                      event.target.value.replace(/\D/g, "").slice(0, CODE_LENGTH)
                    );
                    setError("");
                  }}
                  className={`${inputStyle} text-center text-[28px] font-semibold tracking-[0.4em]`}
                />
              </div>

              {errorBox}

              <button
                type="submit"
                disabled={isBusy}
                className={`${buttonStyle} w-full disabled:cursor-not-allowed disabled:opacity-60`}
              >
                {isBusy ? "Checking..." : "Confirm"}
              </button>
            </form>

            <div className="mt-6 text-center">
              <button
                type="button"
                onClick={() => {
                  setCode("");
                  setError("");
                  setStep("phone");
                }}
                className={linkStyle}
              >
                Use a different number
              </button>
            </div>
          </>
        )}

        {step === "done" && (
          <>
            <h1 className={`${mainHeader} mb-2 text-center`}>All Set!</h1>
            <p className="mb-1 text-center text-slate-600">
              Your phone number has been added.
            </p>
            <p className="mb-6 text-center text-slate-600">
              You will be asked for a 2-way verification code again when you log in.
            </p>
            <button
              type="button"
              onClick={handleLoginAgain}
              className={`${buttonStyle} w-full`}
            >
              Log in again
            </button>
          </>
        )}

        {step !== "done" && step !== "checking" && (
          <div className="mt-6 text-center">
            <button
              type="button"
              onClick={handleLoginAgain}
              className={linkStyle}
            >
              Log out
            </button>
          </div>
        )}

        {/* Used by the invisible reCAPTCHA */}
        <div id="recaptcha-container" />
      </section>
    </main>
  );
}
