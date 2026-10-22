"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { mainHeader, buttonStyle } from "../../components/styles";

const OTP_REQUEST_ENDPOINT = "/api/auth/request-email-otp";

type RequestOtpResponse = {
  challengeId?: string;
};

export default function LoginPage() {
  const formRef = useRef<HTMLFormElement>(null);
  const router = useRouter();

  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    function clearForm() {
      formRef.current?.reset();
      setError("");
      setIsSubmitting(false);
      sessionStorage.removeItem("emailOtpChallengeId");
    }

    clearForm();
    window.addEventListener("pageshow", clearForm);

    return () => {
      window.removeEventListener("pageshow", clearForm);
    };
  }, []);

  async function handleSubmit(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    const data = new FormData(event.currentTarget);
    const email = String(data.get("id") ?? "").trim();
    const password = String(data.get("password") ?? "");

    setError("");

    if (!email || !password) {
      setError("Please enter both your email and password.");
      return;
    }

    setIsSubmitting(true);

    try {
      const response = await fetch(OTP_REQUEST_ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email,
          password,
        }),
      });

      const result =
        (await response.json().catch(() => null)) as
          | RequestOtpResponse
          | { message?: string }
          | null;

      if (!response.ok) {
        setError(
          "Email or password is incorrect, or an OTP could not be sent."
        );
        return;
      }

      if (
        !result ||
        !("challengeId" in result) ||
        typeof result.challengeId !== "string" ||
        result.challengeId.length === 0
      ) {
        setError("The OTP service returned an invalid response.");
        return;
      }

      sessionStorage.setItem(
        "emailOtpChallengeId",
        result.challengeId
      );

      router.push("/verify");
    } catch (requestError) {
      console.error(requestError);
      setError(
        "Unable to start verification. Please try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-6 text-center`}>
          Enter Your Login Details
        </h1>

        <p className="mb-6 text-center text-[13px] text-slate-600">
          After your details are accepted, a verification code will be sent to
          your registered personal email address.
        </p>

        <form
          ref={formRef}
          onSubmit={handleSubmit}
          className="space-y-5"
        >
          <div>
            <label
              htmlFor="id"
              className="mb-1 block text-[18px] font-semibold"
            >
              Email address
            </label>

            <input
              id="id"
              name="id"
              type="email"
              autoComplete="email"
              autoFocus
              required
              onInvalid={(event) =>
                event.currentTarget.setCustomValidity(
                  "Email address must not be left empty."
                )
              }
              onInput={(event) =>
                event.currentTarget.setCustomValidity("")
              }
              className="w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="mb-1 block text-[18px] font-semibold"
            >
              Password
            </label>

            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              onInvalid={(event) =>
                event.currentTarget.setCustomValidity(
                  "Password must not be left empty."
                )
              }
              onInput={(event) =>
                event.currentTarget.setCustomValidity("")
              }
              className="w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]"
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
              ? "Sending verification code..."
              : "Continue"}
          </button>
        </form>

        <div className="mt-6 text-center">
          <Link
            href="/create_acct"
            className="text-[18px] text-[#1b4779] hover:underline"
          >
            No Account Yet? Click Here to Create One!
          </Link>
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-2">
          <Link
            href="/forgot_pw"
            className="text-[13px] capitalize text-orange-700 hover:underline"
          >
            Forgot password?
          </Link>

          <Link
            href="/"
            className="text-[13px] capitalize text-[#1b4779] hover:underline"
          >
            Back to home page
          </Link>
        </div>
      </div>
    </div>
  );
}