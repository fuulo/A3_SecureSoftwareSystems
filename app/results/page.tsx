"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { mainHeader, subHeader } from "../../components/styles";
import {
  fetchPublishedResults,
  formatDateTime,
  formatNumber,
  formatPercent,
  receiptListUrl,
  resultPackageUrl,
  type Contest,
  type PublishedResults,
} from "../../lib/results";

function ContestResults({ contest }: { contest: Contest }) {
  // Highest votes first; the top "seats" candidates are shown as elected
  const ranked = [...contest.candidates].sort((a, b) => b.votes - a.votes);
  const formalVotes = ranked.reduce((sum, c) => sum + c.votes, 0);

  return (
    <section id={contest.id} className="mb-8">
      <h2 className={`${subHeader} mb-1`}>{contest.title}</h2>
      <p className="mb-3 text-[13px] text-slate-600">
        {contest.seats} {contest.seats === 1 ? "seat" : "seats"} &middot;{" "}
        {formatNumber(formalVotes)} formal votes &middot;{" "}
        {formatNumber(contest.informal)} informal
      </p>

      <div className="overflow-x-auto rounded-lg border border-slate-300 shadow-lg">
        <table className="w-full min-w-[520px] text-left">
          <caption className="sr-only">First preference results for {contest.title}</caption>
          <thead className="bg-[#1f538d] text-white">
            <tr>
              <th scope="col" className="px-4 py-2 font-semibold">Candidate</th>
              <th scope="col" className="px-4 py-2 font-semibold">Party</th>
              <th scope="col" className="px-4 py-2 text-right font-semibold">Votes</th>
              <th scope="col" className="w-[30%] px-4 py-2 font-semibold">Share</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((candidate, index) => {
              const elected = index < contest.seats;
              const share = formatPercent(candidate.votes, formalVotes);
              return (
                <tr
                  key={candidate.id}
                  className="border-t border-slate-200 odd:bg-white even:bg-slate-50"
                >
                  <td className="px-4 py-3">
                    <span className="font-semibold">{candidate.name}</span>
                    {elected && (
                      <span className="ml-2 rounded bg-green-50 px-2 py-0.5 text-[12px] font-semibold text-green-800 ring-1 ring-green-300">
                        Elected
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">{candidate.party}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {formatNumber(candidate.votes)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="h-3 flex-1 rounded bg-slate-200" aria-hidden="true">
                        <div
                          className="h-3 rounded bg-[#1f538d]"
                          style={{ width: share }}
                        />
                      </div>
                      <span className="w-14 text-right tabular-nums">{share}</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// Shown while loading, when nothing is published yet, or when the API cannot be reached
function Notice({ title, message }: { title: string; message: string }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-lg rounded-lg border border-slate-300 bg-white p-8 text-center shadow-lg">
        <h1 className={`${mainHeader} mb-2`}>{title}</h1>
        <p className="mb-6">{message}</p>
        <Link href="/" className="text-[13px] capitalize text-[#1b4779] hover:underline">
          Back to start page
        </Link>
      </div>
    </div>
  );
}

export default function ResultsPage() {
  const [results, setResults] = useState<PublishedResults | null>(null);
  const [state, setState] = useState<"loading" | "loaded" | "error">("loading");

  useEffect(() => {
    let active = true;
    fetchPublishedResults()
      .then((published) => {
        if (!active) return;
        setResults(published);
        setState("loaded");
      })
      .catch(() => {
        if (active) setState("error");
      });
    return () => {
      active = false;
    };
  }, []);

  if (state === "loading") {
    return <Notice title="Published Results" message="Loading the published results..." />;
  }
  if (state === "error") {
    return (
      <Notice
        title="Results Unavailable"
        message="The published results could not be loaded. Please try again later."
      />
    );
  }
  if (!results) {
    return (
      <Notice
        title="Published Results"
        message="No results have been published yet. Results appear here once the count is final."
      />
    );
  }

  const { election, contests } = results.package;

  const summary = [
    { label: "Status", value: election.status },
    { label: "Ballots cast", value: formatNumber(election.ballotsCast) },
    {
      label: "Turnout",
      value: formatPercent(election.ballotsCast, election.enrolledVoters),
    },
    { label: "Published", value: formatDateTime(election.publishedAt) },
  ];

  return (
    <div className="mx-auto grid max-w-6xl gap-8 px-6 pb-4 pt-8 min-[900px]:grid-cols-[1fr_minmax(240px,320px)]">
      <main className="min-w-0">
        <h1 className={`${mainHeader} mb-1`}>Published Results</h1>
        <p className="mb-6">{election.name}</p>

        <dl className="mb-8 grid grid-cols-2 gap-4 min-[600px]:grid-cols-4">
          {summary.map((item) => (
            <div
              key={item.label}
              className="rounded-lg border border-slate-300 bg-white p-4 shadow-lg"
            >
              <dt className="text-[13px] text-slate-600">{item.label}</dt>
              <dd className="mt-1 text-[18px] font-bold text-[#1f538d]">{item.value}</dd>
            </div>
          ))}
        </dl>

        {contests.map((contest) => (
          <ContestResults key={contest.id} contest={contest} />
        ))}

        <p className="mb-8 text-[13px] text-slate-600">
          Counts show first preference votes only (Senate votes by group). Distribution
          of preferences is not modelled in this mock system.
        </p>

        <section id="result-package" className="mb-0">
          <h2 className={`${subHeader} mb-2`}>Official Result Package</h2>
          <p className="mb-3 pl-4">
            &#9654; Download the result package to keep an independent copy of these results
          </p>
          <p className="mb-3 pl-4">
            &#9654; Compare its SHA-256 fingerprint with the one published below
          </p>
          <p className="mb-3 pl-4">
            &#9654; Use “Verify result package” to check it automatically
          </p>

          <div className="mt-4 rounded-lg border border-slate-300 bg-slate-50 p-4">
            <p className="mb-1 text-[13px] font-semibold">Published SHA-256 fingerprint</p>
            <p className="break-all font-mono text-[13px]">{results.sha256}</p>
          </div>

          {results.archive && (
            <p className="mt-4 text-[13px] text-slate-600">
              The package and the receipt list are archived in write-once storage and cannot be
              deleted or changed until {formatDateTime(results.archive.retainUntil)} (
              {results.archive.retentionMode} retention).
            </p>
          )}

          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2">
            <a
              href={resultPackageUrl()}
              download
              className="inline-block text-[13px] capitalize text-[#1b4779] hover:underline"
            >
              Download result package (JSON)
            </a>
            {results.package.election.receiptsSha256 && (
              <a
                href={receiptListUrl()}
                download
                className="inline-block text-[13px] capitalize text-[#1b4779] hover:underline"
              >
                Download receipt list (TXT)
              </a>
            )}
          </div>
        </section>
      </main>

      {/* Verification actions on the right */}
      <aside>
        <div className="rounded-lg bg-[#1f538d] p-8 text-center shadow-lg">
          <h2 className="mb-3 text-[28px] font-bold text-white">Check for yourself</h2>
          <p className="mb-6 text-white">
            Confirm your ballot was counted, or verify the published results.
          </p>
          <div className="flex flex-col gap-4">
            <Link
              href="/verify-receipt"
              className="inline-block rounded-lg bg-white px-6 py-3 text-[20px] font-bold text-[#1f538d] shadow-[0_8px_20px_rgba(0,0,0,0.35)] transition duration-200 hover:-translate-y-1 hover:bg-slate-100 hover:shadow-[0_14px_28px_rgba(0,0,0,0.4)] active:translate-y-0 active:shadow-[0_4px_10px_rgba(0,0,0,0.3)]"
            >
              Verify receipt
            </Link>
            <Link
              href="/verify-package"
              className="inline-block rounded-lg bg-white px-6 py-3 text-[20px] font-bold text-[#1f538d] shadow-[0_8px_20px_rgba(0,0,0,0.35)] transition duration-200 hover:-translate-y-1 hover:bg-slate-100 hover:shadow-[0_14px_28px_rgba(0,0,0,0.4)] active:translate-y-0 active:shadow-[0_4px_10px_rgba(0,0,0,0.3)]"
            >
              Verify result package
            </Link>
          </div>
        </div>
      </aside>
    </div>
  );
}
