"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { mainHeader } from "../../components/styles";
import {
  algorithmForFingerprint,
  fetchPublishedResults,
  fingerprintAlgorithm,
  FINGERPRINT_ALGORITHMS,
  formatNumber,
  resultPackageUrl,
  type FingerprintAlgorithm,
} from "../../lib/results";

// Settings (change them here)
const MAX_FILE_MB = 2;
const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;

type Check = {
  label: string;
  passed: boolean;
  detail: string;
};

type Outcome = {
  fileName: string;
  computedHash: string;
  checks: Check[];
};

// Hashes the file in the browser. The file is never uploaded anywhere.
async function fingerprintHex(buffer: ArrayBuffer, algorithm: FingerprintAlgorithm) {
  const digest = await crypto.subtle.digest(algorithm.label, buffer);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

// Checks the package's structure and that its numbers add up
function checkContents(text: string): Check[] {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return [{ label: "Readable package", passed: false, detail: "The file is not valid JSON." }];
  }

  const election = isRecord(data) ? data.election : undefined;
  const contests = isRecord(data) ? data.contests : undefined;

  const wellFormed =
    isRecord(election) &&
    typeof election.id === "string" &&
    isCount(election.ballotsCast) &&
    isCount(election.enrolledVoters) &&
    isCount(election.receiptsIssued) &&
    (election.senateBallotsCast === undefined || isCount(election.senateBallotsCast)) &&
    (election.votersMarkedVoted === undefined || isCount(election.votersMarkedVoted)) &&
    Array.isArray(contests) &&
    contests.length > 0 &&
    contests.every(
      (c) =>
        isRecord(c) &&
        typeof c.title === "string" &&
        (c.chamber === "house" || c.chamber === "senate") &&
        isCount(c.ballotsCast) &&
        isCount(c.informal) &&
        Array.isArray(c.candidates) &&
        c.candidates.every((cand) => isRecord(cand) && isCount(cand.votes))
    );

  if (!wellFormed) {
    return [
      {
        label: "Readable package",
        passed: false,
        detail: "The file is missing fields expected in a result package.",
      },
    ];
  }

  const ballotsCast = election.ballotsCast as number;
  const enrolled = election.enrolledVoters as number;
  const receiptsIssued = election.receiptsIssued as number;
  // Added in package version 3; older packages are checked without them
  const senateBallotsCast = isCount(election.senateBallotsCast)
    ? election.senateBallotsCast
    : ballotsCast;
  const votersMarkedVoted = isCount(election.votersMarkedVoted)
    ? election.votersMarkedVoted
    : null;
  const typedContests = contests as {
    title: string;
    chamber: "house" | "senate";
    ballotsCast: number;
    informal: number;
    candidates: { votes: number }[];
  }[];

  const checks: Check[] = [
    {
      label: "Readable package",
      passed: true,
      detail: `Election ${election.id as string}, ${contests.length} contests.`,
    },
    {
      label: "Turnout is possible",
      passed: ballotsCast <= enrolled,
      detail: `${formatNumber(ballotsCast)} ballots cast from ${formatNumber(enrolled)} enrolled voters.`,
    },
    {
      label: "Every ballot has a receipt",
      passed: receiptsIssued === ballotsCast,
      detail: `${formatNumber(receiptsIssued)} receipts issued for ${formatNumber(ballotsCast)} ballots.`,
    },
  ];

  // Each voter who voted cast exactly one House and one Senate ballot
  if (votersMarkedVoted !== null) {
    checks.push({
      label: "One ballot per voter who voted",
      passed: votersMarkedVoted === ballotsCast && votersMarkedVoted === senateBallotsCast,
      detail: `${formatNumber(votersMarkedVoted)} voters marked voted, ${formatNumber(ballotsCast)} House ballots, ${formatNumber(senateBallotsCast)} Senate ballots.`,
    });
  }

  // Each chamber's contests together must account for every ballot exactly once
  for (const [chamber, label, cast] of [
    ["house", "House", ballotsCast],
    ["senate", "Senate", senateBallotsCast],
  ] as const) {
    const total = typedContests
      .filter((c) => c.chamber === chamber)
      .reduce((sum, c) => sum + c.ballotsCast, 0);
    checks.push({
      label: `Every ballot in one contest: ${label}`,
      passed: total === cast,
      detail: `${formatNumber(total)} ${label} ballots across contests, ${formatNumber(cast)} ballots cast.`,
    });
  }

  // Every ballot in a contest is counted once (formal + informal)
  for (const contest of typedContests) {
    const total = contest.candidates.reduce((sum, c) => sum + c.votes, 0) + contest.informal;
    checks.push({
      label: `Totals add up: ${contest.title}`,
      passed: total === contest.ballotsCast,
      detail: `${formatNumber(total)} votes counted, ${formatNumber(contest.ballotsCast)} ballots cast.`,
    });
  }

  return checks;
}

export default function VerifyPackagePage() {
  const formRef = useRef<HTMLFormElement>(null);
  const publishedHash = useRef("");
  const [file, setFile] = useState<File | null>(null);
  const [expectedHash, setExpectedHash] = useState("");
  // Name of the published fingerprint's algorithm, for the field label
  const [publishedLabel, setPublishedLabel] = useState("");
  const [hashNotice, setHashNotice] = useState("Loading the published fingerprint...");
  const [error, setError] = useState("");
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [checking, setChecking] = useState(false);

  // Fill in the fingerprint recorded when the results were published
  useEffect(() => {
    let active = true;
    fetchPublishedResults()
      .then((published) => {
        if (!active) return;
        if (!published) {
          setHashNotice("No results have been published yet.");
          return;
        }
        publishedHash.current = published.fingerprint;
        setExpectedHash((current) => current || published.fingerprint);
        setPublishedLabel(fingerprintAlgorithm(published.algorithm)?.label ?? published.algorithm);
        setHashNotice("");
      })
      .catch(() => {
        if (active) {
          setHashNotice(
            "The published fingerprint could not be loaded. Paste one from a trusted source."
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);

  // Clear the form when the page is shown again by back/forward navigation
  useEffect(() => {
    function clearForm() {
      formRef.current?.reset();
      setFile(null);
      setExpectedHash(publishedHash.current);
      setError("");
      setOutcome(null);
    }

    window.addEventListener("pageshow", clearForm);
    return () => window.removeEventListener("pageshow", clearForm);
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setOutcome(null);

    const expected = expectedHash.trim().toLowerCase();

    if (!file) {
      setError("Please choose the result package file to verify.");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".json")) {
      setError("The result package must be a .json file.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError(`The file is too large. Result packages are smaller than ${MAX_FILE_MB} MB.`);
      return;
    }
    // The fingerprint's length shows which algorithm made it
    const algorithm = /^[0-9a-f]+$/.test(expected) ? algorithmForFingerprint(expected) : undefined;
    if (!algorithm) {
      const lengths = FINGERPRINT_ALGORITHMS.map((a) => a.hexLength).join(", ");
      setError(`The expected fingerprint must be ${lengths} characters long (0-9 and a-f).`);
      return;
    }
    if (!window.crypto?.subtle) {
      setError("Your browser cannot calculate fingerprints on this connection. Use HTTPS.");
      return;
    }
    setError("");
    setChecking(true);

    try {
      const buffer = await file.arrayBuffer();
      const computedHash = await fingerprintHex(buffer, algorithm);
      const text = new TextDecoder().decode(buffer);

      setOutcome({
        fileName: file.name,
        computedHash,
        checks: [
          {
            label: "Fingerprint matches",
            passed: computedHash === expected,
            detail:
              computedHash === expected
                ? "The file is identical to the officially published package."
                : "The file differs from the published package. It may have been changed.",
          },
          ...checkContents(text),
        ],
      });
    } catch {
      setError("The file could not be read. Please try again.");
    } finally {
      setChecking(false);
    }
  }

  const allPassed = outcome?.checks.every((c) => c.passed);

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-2xl rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-2 text-center`}>Verify Result Package</h1>
        <p className="mb-1 text-center">
          Check that a result package is genuine and that its totals add up.
        </p>
        <p className="mb-6 text-center text-[13px] text-slate-600">
          The check runs in your browser. Your file is not uploaded.
        </p>

        <form ref={formRef} onSubmit={handleSubmit} noValidate className="space-y-5">
          <div>
            <label htmlFor="package" className="mb-1 block font-semibold text-[18px]">
              Result package file
            </label>
            <input
              id="package"
              name="package"
              type="file"
              accept=".json,application/json"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setOutcome(null);
                setError("");
              }}
              className="w-full rounded border border-slate-400 px-3 py-2 text-[14px] file:mr-4 file:rounded file:border-0 file:bg-[#1f538d] file:px-4 file:py-2 file:font-semibold file:text-white hover:file:bg-[#1b4779] focus:outline-none focus:ring-2 focus:ring-[#1f538d]"
            />
            <p className="mt-1 text-[13px] text-slate-600">
              Don&apos;t have it?{" "}
              <a href={resultPackageUrl()} download className="text-[#1b4779] hover:underline">
                Download the official result package
              </a>
              .
            </p>
          </div>

          <div>
            <label htmlFor="expected" className="mb-1 block font-semibold text-[18px]">
              Expected {publishedLabel ? `${publishedLabel} ` : ""}fingerprint
            </label>
            <input
              id="expected"
              name="expected"
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={expectedHash}
              onChange={(e) => {
                setExpectedHash(e.target.value);
                setOutcome(null);
              }}
              aria-describedby="expected-help"
              className="w-full rounded border border-slate-400 px-3 py-2 font-mono text-[13px] focus:outline-none focus:ring-2 focus:ring-[#1f538d]"
            />
            <p id="expected-help" className="mt-1 text-[13px] text-slate-600">
              {hashNotice ||
                "Filled in with the fingerprint published on the results page. You can paste one from another trusted source instead."}
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

          <button
            type="submit"
            disabled={checking}
            className="w-full rounded-lg bg-[#1f538d] px-6 py-3 text-[24px] font-bold text-white shadow-[0_8px_20px_rgba(0,0,0,0.35)] transition duration-200 hover:-translate-y-1 hover:bg-[#1b4779] hover:shadow-[0_14px_28px_rgba(0,0,0,0.4)] active:translate-y-0 active:shadow-[0_4px_10px_rgba(0,0,0,0.3)] disabled:cursor-not-allowed disabled:opacity-70"
          >
            {checking ? "Checking..." : "Verify"}
          </button>
        </form>

        {outcome && (
          <div className="mt-6" role="status">
            <div
              className={`rounded border px-4 py-3 ${
                allPassed
                  ? "border-green-300 bg-green-50 text-green-800"
                  : "border-red-300 bg-red-50 text-red-700"
              }`}
            >
              <p className="font-bold">
                {allPassed
                  ? "✔ This result package is genuine and consistent."
                  : "✖ This result package failed verification."}
              </p>
              <p className="mt-1 break-all text-[13px]">
                {outcome.fileName}: <span className="font-mono">{outcome.computedHash}</span>
              </p>
            </div>

            <ul className="mt-4 space-y-2">
              {outcome.checks.map((check) => (
                <li
                  key={check.label}
                  className="flex gap-3 rounded border border-slate-200 px-3 py-2"
                >
                  <span
                    aria-hidden="true"
                    className={`font-bold ${check.passed ? "text-green-700" : "text-red-700"}`}
                  >
                    {check.passed ? "✔" : "✖"}
                  </span>
                  <div>
                    <p className="font-semibold">
                      <span className="sr-only">{check.passed ? "Passed: " : "Failed: "}</span>
                      {check.label}
                    </p>
                    <p className="text-[13px] text-slate-600">{check.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-6 flex items-center justify-between">
          <Link
            href="/results"
            className="text-[13px] capitalize text-[#1b4779] hover:underline"
          >
            View published results
          </Link>
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
