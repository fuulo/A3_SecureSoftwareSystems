"use client";

import Link from "next/link";
import { useState } from "react";
import {
  getMultiFactorResolver,
  signInWithEmailAndPassword,
  type MultiFactorError,
} from "firebase/auth";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/firebase";
import {
  mainHeader,
  buttonStyle,
} from "@/components/styles";
import { setPendingMfa } from "@/lib/mfa";

const inputStyle =
  "w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]";

const linkStyle =
  "text-[13px] text-[#1b4779] hover:underline";

function getLoginErrorMessage(
  firebaseError: unknown
): string {
  if (
    typeof firebaseError === "object" &&
    firebaseError !== null &&
    "code" in firebaseError
  ) {
    const code = String(
      (firebaseError as { code?: unknown }).code ??
        ""
    );

    if (
      code === "auth/invalid-credential" ||
      code === "auth/user-not-found" ||
      code === "auth/wrong-password"
    ) {
      return "The email address or password is incorrect.";
    }

    if (code === "auth/invalid-email") {
      return "Please enter a valid email address.";
    }

    if (code === "auth/too-many-requests") {
      return "Too many login attempts. Please try again later.";
    }

    if (code === "auth/user-disabled") {
      return "This account has been disabled.";
    }
  }

  return "Unable to log in. Please try again.";
}

export default function LoginPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] =
    useState("");

  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] =
    useState(false);

  async function handleSubmit(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    setError("");

    const cleanEmail = email.trim().toLowerCase();

    if (!cleanEmail || !password) {
      setError("Please enter your email address and password.");
      return;
    }

    setIsSubmitting(true);

    try {
      await signInWithEmailAndPassword(auth, cleanEmail, password);

      // The password was enough, so this account has no phone set up yet
      setEmail("");
      setPassword("");
      router.replace("/mfa_setup");
    } catch (firebaseError) {
      // This is expected for accounts with a phone set up:
      // Firebase asks for the second step
      if (
        (firebaseError as { code?: string }).code ===
        "auth/multi-factor-auth-required"
      ) {
        setPendingMfa(
          getMultiFactorResolver(auth, firebaseError as MultiFactorError)
        );
        setEmail("");
        setPassword("");
        console.log("Pending login saved:", true)
        router.replace("/verify");
        return;
      }

      console.error(firebaseError);
      setError(getLoginErrorMessage(firebaseError));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <section className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-2 text-center`}>
          Login
        </h1>

        <p className="mb-8 text-center text-slate-600">
          Enter your email address and password.
        </p>

        <form
          onSubmit={handleSubmit}
          noValidate
          className="space-y-5"
        >
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
              autoComplete="off"
              autoFocus
              required
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
                setError("");
              }}
              className={inputStyle}
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="mb-1 block font-semibold"
            >
              Password
            </label>

            <input
              id="password"
              name="password"
              type="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                setError("");
              }}
              className={inputStyle}
            />
          </div>

          {error && (
            <p
              role="alert"
              className="rounded border border-red-300 bg-red-50 px-3 py-2 text-[13px] text-red-700"
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className={`${buttonStyle} w-full disabled:cursor-not-allowed disabled:opacity-60`}
          >
            {isSubmitting
              ? "Logging in..."
              : "Login"}
          </button>
        </form>

        <div className="mt-6 flex flex-wrap justify-between gap-3">
          <Link
            href="/forgot_pw"
            className={linkStyle}
          >
            Forgot password?
          </Link>

          <Link
            href="/create_acct"
            className={linkStyle}
          >
            Create account
          </Link>
        </div>

        <div className="mt-3 text-center">
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