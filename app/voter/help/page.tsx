"use client";

import { useRouter } from "next/navigation";
import { mainHeader } from "@/components/styles";

export default function VoterHelpPage() {
  const router = useRouter();

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <section className="rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-6`}>
          Help and Information
        </h1>

        <div className="space-y-6 text-slate-700">
          <div>
            <h2 className="mb-2 text-lg font-semibold text-[#1f538d]">
              How do I vote?
            </h2>

            <p>
              Select the Vote option from your
              dashboard, review the ballot, choose
              your candidates, and submit your vote.
            </p>
          </div>

          <div>
            <h2 className="mb-2 text-lg font-semibold text-[#1f538d]">
              I cannot access my account
            </h2>

            <p>
              Make sure you are using the email
              address and password associated with
              your account. You can use the password
              reset option from the login page if
              necessary.
            </p>
          </div>

          <div>
            <h2 className="mb-2 text-lg font-semibold text-[#1f538d]">
              My email is not verified
            </h2>

            <p>
              Check your inbox and spam folder for the
              verification email. You can request a
              new verification email from the email
              verification page.
            </p>
          </div>

          <div>
            <h2 className="mb-2 text-lg font-semibold text-[#1f538d]">
              Security reminder
            </h2>

            <p>
              Never share your password or
              authentication code with another person.
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() =>
            router.push("/voter/dashboard")
          }
          className="mt-8 rounded bg-[#1f538d] px-4 py-2 text-white hover:bg-[#173e6b]"
        >
          Back to dashboard
        </button>
      </section>
    </main>
  );
}