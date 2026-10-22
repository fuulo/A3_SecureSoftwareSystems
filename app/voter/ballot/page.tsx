"use client";

import { useState } from "react";
import Link from "next/link";

type Candidate = {
  id: string;
  name: string;
  description: string;
};

const candidates: Candidate[] = [
  {
    id: "candidate-a",
    name: "Candidate A",
    description: "Demo candidate for the academic prototype.",
  },
  {
    id: "candidate-b",
    name: "Candidate B",
    description: "Demo candidate for the academic prototype.",
  },
  {
    id: "candidate-c",
    name: "Candidate C",
    description: "Demo candidate for the academic prototype.",
  },
];

export default function BallotPage() {
  const [selectedCandidate, setSelectedCandidate] = useState("");
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedCandidate) {
      return;
    }

    setSubmitted(true);
  }

  if (submitted) {
    return (
      <main className="min-h-screen bg-[#f7f8f6] px-5 py-10 text-[#202923] sm:px-8 sm:py-16">
        <div className="mx-auto max-w-2xl">
          <section className="rounded-3xl border border-[#e5eae5] bg-white p-8 text-center shadow-[0_8px_30px_rgba(31,52,39,0.04)] sm:p-10">
            <div
              aria-hidden="true"
              className="mx-auto mb-5 flex size-14 items-center justify-center rounded-full bg-[#e6f1e8] text-2xl text-[#28613e]"
            >
              ✓
            </div>

            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#728077]">
              Demo submission
            </p>

            <h1 className="text-3xl font-semibold tracking-tight">
              Ballot submitted
            </h1>

            <p className="mx-auto mt-4 max-w-md text-sm leading-6 text-[#758078]">
              Your demo selection was recorded on this page only. It was not
              sent to Firebase and cannot be used as an official vote.
            </p>

            <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
              <Link
                href="/voter/dashboard"
                className="inline-flex min-h-12 items-center justify-center rounded-xl border border-[#cfd9d0] px-6 py-3 text-sm font-semibold text-[#173f32] transition-colors hover:bg-[#f3f6f2]"
              >
                Return to dashboard
              </Link>

              <Link
                href="/voter/ballot"
                className="inline-flex min-h-12 items-center justify-center rounded-xl bg-[#173f32] px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#245640]"
              >
                Start again
              </Link>
            </div>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f7f8f6] px-5 py-10 text-[#202923] sm:px-8 sm:py-16">
      <div className="mx-auto max-w-3xl">
        <header className="mb-8">
          <Link
            href="/voter/dashboard"
            className="text-sm font-semibold text-[#245640] hover:underline"
          >
            ← Back to dashboard
          </Link>

          <p className="mt-8 text-xs font-semibold uppercase tracking-[0.16em] text-[#728077]">
            Academic prototype ballot
          </p>

          <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
            Make your selection
          </h1>

          <p className="mt-3 max-w-2xl text-sm leading-6 text-[#758078]">
            Select one candidate below. This is a demonstration ballot only.
            Your selection will not be stored or submitted to an election
            authority.
          </p>
        </header>

        <section className="rounded-3xl border border-[#e5eae5] bg-white p-6 shadow-[0_8px_30px_rgba(31,52,39,0.04)] sm:p-10">
          <form onSubmit={handleSubmit}>
            <fieldset>
              <legend className="text-lg font-semibold">
                Demo election candidates
              </legend>

              <div className="mt-5 space-y-4">
                {candidates.map((candidate) => (
                  <label
                    key={candidate.id}
                    className={`block cursor-pointer rounded-2xl border p-5 transition-colors ${
                      selectedCandidate === candidate.id
                        ? "border-[#173f32] bg-[#f3f6f2]"
                        : "border-[#e5eae5] hover:bg-[#fafcf9]"
                    }`}
                  >
                    <span className="flex items-start gap-4">
                      <input
                        type="radio"
                        name="candidate"
                        value={candidate.id}
                        checked={selectedCandidate === candidate.id}
                        onChange={(event) =>
                          setSelectedCandidate(event.target.value)
                        }
                        className="mt-1 size-4 accent-[#173f32]"
                      />

                      <span>
                        <span className="block font-semibold">
                          {candidate.name}
                        </span>
                        <span className="mt-1 block text-sm text-[#758078]">
                          {candidate.description}
                        </span>
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="mt-8 border-t border-[#edf0ed] pt-6">
              <p className="mb-4 text-xs leading-5 text-[#89938c]">
                This prototype does not yet verify eligibility, prevent
                duplicate voting, or persist ballot selections.
              </p>

              <button
                type="submit"
                disabled={!selectedCandidate}
                className="inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-[#173f32] px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#245640] disabled:cursor-not-allowed disabled:opacity-50"
              >
                Review and submit demo ballot
              </button>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
}