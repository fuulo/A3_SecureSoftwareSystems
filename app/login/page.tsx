"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { mainHeader, buttonStyle } from "../../components/styles";
import { useRouter } from "next/navigation";
import { 
  signInWithEmailAndPassword,
  setPersistence,
  inMemoryPersistence,
} from "firebase/auth";
import { auth } from "../../lib/firebase";

export default function LoginPage() {
  const formRef = useRef<HTMLFormElement>(null);
  const router = useRouter();
  const [error, setError] = useState("");

  // Clear the form when the page is shown, including back/forward navigation
  useEffect(() => {
    function clearForm() {
      formRef.current?.reset();
      setError("");
    }

    clearForm();
    window.addEventListener("pageshow", clearForm);
    return () => window.removeEventListener("pageshow", clearForm);
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const data = new FormData(event.currentTarget);
    const email = String(data.get("id") ?? "").trim();
    const password = String(data.get("password") ?? "");

    if (!email || !password) {
      setError("Please enter both your ID and password.");
      return;
    }

    try {
      await setPersistence(auth, inMemoryPersistence);
      await signInWithEmailAndPassword(auth, email, password);
      setError("");
      router.push("/verify");
    } catch {
      // One general message for every failure, so it does not reveal which part was wrong
      setError("ID or password is incorrect.");
    }
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-6 text-center`}>Enter Your Login Details</h1>

        <form ref={formRef} onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="id" className="mb-1 block font-semibold text-[18px]">
              Log In ID
            </label>
            <input
              id="id"
              name="id"
              type="text"
              autoComplete="off"
              autoFocus
              required
              onInvalid={(e) =>
                e.currentTarget.setCustomValidity("Log In ID must not be left empty.")
              }
              onInput={(e) => e.currentTarget.setCustomValidity("")}
              className="w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1 block font-semibold text-[18px]">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="new-password"
              required
              onInvalid={(e) =>
                e.currentTarget.setCustomValidity("Password must not be left empty.")
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

          <button type="submit" className={buttonStyle}>
            Submit
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