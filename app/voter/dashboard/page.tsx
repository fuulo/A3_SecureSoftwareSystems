import Link from "next/link";
import type { Metadata } from "next";
import RequireAuth from "../../../components/requireauth";

export const metadata: Metadata = {
  title: "Voter dashboard",
  description: "Secure academic prototype voter dashboard.",
};

const voterDetails = [
  { label: "Division", value: "Demo Division" },
  { label: "Enrolment status", value: "Enrolled" },
  { label: "Eligibility status", value: "Eligible" },
  { label: "Voting status", value: "Not voted" },
  { label: "Election status", value: "Open" },
];

export default function VoterDashboardPage() {
  return (
    <RequireAuth>
      <main className="min-h-screen bg-[#f7f8f6] px-5 py-10 text-[#202923] sm:px-8 sm:py-16">
        <div className="mx-auto max-w-4xl">
          <header className="mb-8 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span
                aria-hidden="true"
                className="flex size-10 items-center justify-center rounded-xl bg-[#173f32] text-lg font-semibold text-white"
              >
                C
              </span>
              <div>
                <p className="font-semibold tracking-tight">Common</p>
                <p className="text-xs text-[#77817a]">Academic voter prototype</p>
              </div>
            </div>
            
          </header>

          <section className="rounded-3xl border border-[#e5eae5] bg-white p-6 shadow-[0_8px_30px_rgba(31,52,39,0.04)] sm:p-10">
            <div className="mb-8 border-b border-[#edf0ed] pb-7">
              <p className="mb-2 text-xs font-semibold tracking-[0.16em] text-[#728077] uppercase">
                Voter portal
              </p>
              <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
                Voter dashboard
              </h1>
              <p className="mt-2 text-sm leading-6 text-[#758078]">
                Review your demo voter information and current election status.
              </p>
            </div>

            <div className="mb-7 rounded-2xl bg-[#f3f6f2] p-5 sm:p-6">
              <p className="text-xs font-semibold tracking-[0.12em] text-[#728077] uppercase">
                Voter name
              </p>
              <p className="mt-2 text-2xl font-semibold tracking-tight">
                C**** K****
              </p>
              <p className="mt-1 text-xs text-[#89938c]">
                Name is masked for this academic prototype.
              </p>
            </div>

            <dl className="grid gap-3 sm:grid-cols-2">
              {voterDetails.map(({ label, value }) => (
                <div
                  key={label}
                  className="rounded-2xl border border-[#e8ece8] p-4 sm:p-5"
                >
                  <dt className="text-sm text-[#758078]">{label}</dt>
                  <dd className="mt-2 flex items-center gap-2 font-semibold">
                    {label === "Election status" && (
                      <span
                        aria-hidden="true"
                        className="size-2 rounded-full bg-[#56816a]"
                      />
                    )}
                    {value}
                  </dd>
                </div>
              ))}
            </dl>

            <div className="mt-8 flex flex-col gap-3 border-t border-[#edf0ed] pt-7 sm:flex-row sm:items-center sm:justify-between">
              <p className="max-w-md text-xs leading-5 text-[#89938c]">
                This interface is an academic prototype and does not verify voter
                identity or submit an official ballot.
              </p>
              <Link
                href="/voter/ballot"
                className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-[#173f32] px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#245640] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#173f32]"
              >
                Start voting <span aria-hidden="true">→</span>
              </Link>
            </div>
          </section>

          <p className="mt-5 text-center text-xs text-[#89938c]">
            For demonstration purposes only.
          </p>
        </div>
      </main>
    </RequireAuth>
  );
}
