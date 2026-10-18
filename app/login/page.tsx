"use client";

import { useEffect, useRef } from "react";
import { mainHeader } from "../../components/styles";
import Link from "next/link";

export default function LoginPage() {
  const formRef = useRef<HTMLFormElement>(null);

  // Clear the form when the page is shown, including back/forward navigation
  useEffect(() => {
    function clearForm() {
      formRef.current?.reset();
    }

    clearForm();
    window.addEventListener("pageshow", clearForm);
    return () => window.removeEventListener("pageshow", clearForm);
  }, []);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    // Stop the browser from sending the form by itself.
    // The real login logic will be added here later.
    event.preventDefault();
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

          <button
            type="submit"
              className="w-full rounded-lg bg-[#1f538d] px-6 py-3 text-[24px] font-bold text-white shadow-[0_8px_20px_rgba(0,0,0,0.35)] transition duration-200 hover:-translate-y-1 hover:bg-[#1b4779] hover:shadow-[0_14px_28px_rgba(0,0,0,0.4)] active:translate-y-0 active:shadow-[0_4px_10px_rgba(0,0,0,0.3)]"
          >
            Submit
          </button>
        </form>

        <div className="mt-6 text-center">
          <Link
            href="/"
            className="text-[13px] capitalize text-[#1b4779] hover:underline"
          >
            Back to start page
          </Link>
        </div>
      </div>
    </div>
  );
}