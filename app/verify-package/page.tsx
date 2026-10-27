"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { mainHeader } from "../../components/styles";
import {
  algorithmForFingerprint,
  fetchPublishedResults,
  fetchSigningKey,
  fingerprintAlgorithm,
  FINGERPRINT_ALGORITHMS,
  formatNumber,
  packageSignatureUrl,
  receiptListUrl,
  resultPackageUrl,
  type FingerprintAlgorithm,
  type SigningKey,
} from "../../lib/results";
import { RECEIPT_ALPHABET, RECEIPT_LENGTH } from "../../lib/receipts";

// Settings (change them here)
const MAX_FILE_MB = 2;
const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;
const MAX_LIST_MB = 20;
const MAX_LIST_BYTES = MAX_LIST_MB * 1024 * 1024;
const RECEIPT_CODE = new RegExp(`^[${RECEIPT_ALPHABET}]{${RECEIPT_LENGTH}}$`);
// An Ed25519 signature is 64 bytes
const SIGNATURE_HEX = /^[0-9a-f]{128}$/;

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
async function fingerprintHex(buffer: BufferSource, algorithm: FingerprintAlgorithm) {
  const digest = await crypto.subtle.digest(algorithm.label, buffer);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function hexBytes(hex: string) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return bytes;
}

// The DER bytes inside a PEM public key
function pemBytes(pem: string) {
  const base64 = pem.replace(/-----[^-]+-----/g, "").replace(/\s/g, "");
  return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
}

// Checks the package's Ed25519 signature (R-09) with the results signing key.
// signedWith is the key ID published with the results, if known.
async function checkSignature(
  data: ArrayBuffer,
  signatureHex: string,
  key: SigningKey | null,
  signedWith: string
): Promise<Check> {
  const label = "Digitally signed";
  if (!signatureHex) {
    return {
      label,
      passed: false,
      detail: "No signature was given. Results published before signing was added have none.",
    };
  }
  if (!key) {
    return {
      label,
      passed: false,
      detail: "The results signing key could not be loaded, so the signature cannot be checked.",
    };
  }
  let publicKey: CryptoKey;
  try {
    publicKey = await crypto.subtle.importKey("spki", pemBytes(key.publicKeyPem), { name: "Ed25519" }, false, [
      "verify",
    ]);
  } catch {
    return {
      label,
      passed: false,
      detail: "Your browser cannot check Ed25519 signatures. Use a current version of Chrome, Edge, Firefox or Safari.",
    };
  }
  const valid = await crypto.subtle.verify({ name: "Ed25519" }, publicKey, hexBytes(signatureHex), data);
  return {
    label,
    passed: valid,
    detail: valid
      ? `Signed with the official results key ${key.keyId}. The file has not changed since it was signed.`
      : signedWith && signedWith !== key.keyId
        ? `These results were signed with key ${signedWith}, not the current key ${key.keyId}. Check the archived copy with its archived key.`
        : "The signature does not match this file. The file or the signature may have been changed.",
  };
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
    (election.excludedHouseBallots === undefined || isCount(election.excludedHouseBallots)) &&
    (election.excludedSenateBallots === undefined || isCount(election.excludedSenateBallots)) &&
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
  // Added in package version 5: ballots left out of every contest after failing
  // their integrity check (R-15); older packages excluded none
  const excludedHouse = isCount(election.excludedHouseBallots) ? election.excludedHouseBallots : 0;
  const excludedSenate = isCount(election.excludedSenateBallots) ? election.excludedSenateBallots : 0;
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

  // Each chamber's contests together must account for every ballot exactly once,
  // apart from ballots excluded for failing their integrity check
  for (const [chamber, label, cast, excluded] of [
    ["house", "House", ballotsCast, excludedHouse],
    ["senate", "Senate", senateBallotsCast, excludedSenate],
  ] as const) {
    const total = typedContests
      .filter((c) => c.chamber === chamber)
      .reduce((sum, c) => sum + c.ballotsCast, 0);
    checks.push({
      label: `Every ballot in one contest: ${label}`,
      passed: total + excluded === cast,
      detail: excluded
        ? `${formatNumber(total)} ${label} ballots across contests and ${formatNumber(excluded)} excluded, ${formatNumber(cast)} ballots cast.`
        : `${formatNumber(total)} ${label} ballots across contests, ${formatNumber(cast)} ballots cast.`,
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

// Receipt codes as typed by voters, e.g. "7kq2-m9xd-4rta-h8wc" -> "7KQ2M9XD4RTAH8WC"
function normalizeReceipt(code: string) {
  return code.replace(/[\s-]/g, "").toUpperCase();
}

// A receipt's ID in the list for one algorithm: plain hex for SHA-256, the
// original algorithm, otherwise "<algorithm>-<hex>" (backend/security/hashing.py)
async function receiptId(code: string, algorithm: FingerprintAlgorithm) {
  const hex = await fingerprintHex(new TextEncoder().encode(code), algorithm);
  return algorithm.name === "sha256" ? hex : `${algorithm.name}-${hex}`;
}

// Checks a downloaded receipt list against the package and, if given, one receipt code.
// The list holds the ID (a hash) of every receipt code, sorted, one per line.
async function checkReceiptList(
  packageText: string,
  listBuffer: ArrayBuffer,
  code: string
): Promise<Check[]> {
  let election: unknown;
  try {
    const data: unknown = JSON.parse(packageText);
    election = isRecord(data) ? data.election : undefined;
  } catch {
    election = undefined;
  }
  const expected =
    isRecord(election) && typeof election.receiptsFingerprint === "string"
      ? election.receiptsFingerprint
      : null;
  // The package names the algorithm; older readers can tell it from the length
  const listAlgorithm =
    expected === null
      ? undefined
      : (isRecord(election) && typeof election.receiptsHashAlgorithm === "string"
          ? fingerprintAlgorithm(election.receiptsHashAlgorithm)
          : undefined) ?? algorithmForFingerprint(expected);
  const listHash = listAlgorithm ? await fingerprintHex(listBuffer, listAlgorithm) : null;
  const issued =
    isRecord(election) && isCount(election.receiptsIssued) ? election.receiptsIssued : null;
  const listText = new TextDecoder().decode(listBuffer);
  const lines = listText.endsWith("\n") ? listText.slice(0, -1).split("\n") : listText.split("\n");
  const hashes = listText === "" ? [] : lines;
  const ordered = hashes.every(
    (line, i) => /^(?:[a-z0-9_]+-)?[0-9a-f]+$/.test(line) && (i === 0 || hashes[i - 1] < line)
  );

  const checks: Check[] = [
    {
      label: "Receipt list matches the package",
      passed: listHash !== null && listHash === expected,
      detail:
        expected === null
          ? "This package has no receipt list fingerprint. It was published before receipt lists were added."
          : listHash === null
            ? "The package's receipt list fingerprint uses an algorithm this page cannot check."
            : listHash === expected
              ? "The receipt list is identical to the one published with these results."
              : "The receipt list differs from the published one. It may have been changed.",
    },
    {
      label: "Every receipt listed once",
      passed: ordered && issued !== null && hashes.length === issued,
      detail: `${formatNumber(hashes.length)} receipts in the list, ${
        issued === null ? "unknown" : formatNumber(issued)
      } issued${ordered ? "" : "; the list contains invalid, repeated or unsorted lines"}.`,
    },
  ];

  if (code) {
    // Try every algorithm a browser can calculate, since receipts issued before
    // an algorithm upgrade keep their original IDs
    const listed = new Set(hashes);
    const candidates = await Promise.all(
      FINGERPRINT_ALGORITHMS.map((algorithm) => receiptId(code, algorithm))
    );
    const found = candidates.some((id) => listed.has(id));
    // IDs from algorithms browsers lack (such as SHA-3) cannot be checked here
    const browserNames = new Set<string>(FINGERPRINT_ALGORITHMS.map((a) => a.name));
    const unchecked = [
      ...new Set(
        hashes
          .map((line) => (line.includes("-") ? line.split("-")[0] : "sha256"))
          .filter((name) => !browserNames.has(name))
      ),
    ];
    checks.push({
      label: "Your receipt is in the list",
      passed: found,
      detail: found
        ? "Your ballot is among the published receipts. Your code was not sent anywhere."
        : unchecked.length > 0
          ? `Your receipt was not found, but some receipts use ${unchecked.join(", ")}, which browsers cannot calculate. Use "Verify receipt" instead.`
          : "This receipt code is not in the list. Check the code and try again.",
    });
  }

  return checks;
}

export default function VerifyPackagePage() {
  const formRef = useRef<HTMLFormElement>(null);
  const publishedHash = useRef("");
  const [file, setFile] = useState<File | null>(null);
  const [receiptFile, setReceiptFile] = useState<File | null>(null);
  const [receiptCode, setReceiptCode] = useState("");
  const [expectedHash, setExpectedHash] = useState("");
  // Name of the published fingerprint's algorithm, for the field label
  const [publishedLabel, setPublishedLabel] = useState("");
  const [hashNotice, setHashNotice] = useState("Loading the published fingerprint...");
  const publishedSignature = useRef("");
  const [expectedSignature, setExpectedSignature] = useState("");
  // Key ID the published results were signed with
  const [signedWith, setSignedWith] = useState("");
  const [signingKey, setSigningKey] = useState<SigningKey | null>(null);
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
        if (published.signature) {
          publishedSignature.current = published.signature.value;
          setExpectedSignature((current) => current || published.signature!.value);
          setSignedWith(published.signature.keyId);
        }
      })
      .catch(() => {
        if (active) {
          setHashNotice(
            "The published fingerprint could not be loaded. Paste one from a trusted source."
          );
        }
      });
    // A failure leaves the key empty, and the signature check then says it could not be loaded
    fetchSigningKey()
      .then((key) => {
        if (active) setSigningKey(key);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  // Clear the form when the page is shown again by back/forward navigation
  useEffect(() => {
    function clearForm() {
      formRef.current?.reset();
      setFile(null);
      setReceiptFile(null);
      setReceiptCode("");
      setExpectedHash(publishedHash.current);
      setExpectedSignature(publishedSignature.current);
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
    const signature = expectedSignature.trim().toLowerCase();
    if (signature && !SIGNATURE_HEX.test(signature)) {
      setError("The signature must be 128 characters long (0-9 and a-f).");
      return;
    }
    const code = normalizeReceipt(receiptCode);
    if (code && !receiptFile) {
      setError("Choose the receipt list to check your receipt code against.");
      return;
    }
    if (code && !RECEIPT_CODE.test(code)) {
      setError(`Please enter all ${RECEIPT_LENGTH} characters of your receipt code.`);
      return;
    }
    if (receiptFile && receiptFile.size > MAX_LIST_BYTES) {
      setError(`The receipt list is too large. It must be smaller than ${MAX_LIST_MB} MB.`);
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
      const signatureCheck = await checkSignature(buffer, signature, signingKey, signedWith);
      const text = new TextDecoder().decode(buffer);
      let receiptChecks: Check[] = [];
      if (receiptFile) {
        receiptChecks = await checkReceiptList(text, await receiptFile.arrayBuffer(), code);
      }

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
          signatureCheck,
          ...checkContents(text),
          ...receiptChecks,
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

          <div>
            <label htmlFor="signature" className="mb-1 block font-semibold text-[18px]">
              Expected Ed25519 signature
            </label>
            <input
              id="signature"
              name="signature"
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={expectedSignature}
              onChange={(e) => {
                setExpectedSignature(e.target.value);
                setOutcome(null);
              }}
              aria-describedby="signature-help"
              className="w-full rounded border border-slate-400 px-3 py-2 font-mono text-[13px] focus:outline-none focus:ring-2 focus:ring-[#1f538d]"
            />
            <p id="signature-help" className="mt-1 text-[13px] text-slate-600">
              Filled in with the signature published with the results
              {signingKey ? `, checked with the official results key ${signingKey.keyId}` : ""}. To check
              with other tools,{" "}
              <a href={packageSignatureUrl()} download className="text-[#1b4779] hover:underline">
                download the signature file
              </a>
              .
            </p>
          </div>

          <fieldset className="space-y-4 rounded-lg border border-slate-300 p-4">
            <legend className="px-1 font-semibold text-[18px]">Receipt list (optional)</legend>
            <div>
              <label htmlFor="receipt-list" className="mb-1 block font-semibold">
                Receipt list file
              </label>
              <input
                id="receipt-list"
                name="receiptList"
                type="file"
                accept=".txt,text/plain"
                onChange={(e) => {
                  setReceiptFile(e.target.files?.[0] ?? null);
                  setOutcome(null);
                  setError("");
                }}
                className="w-full rounded border border-slate-400 px-3 py-2 text-[14px] file:mr-4 file:rounded file:border-0 file:bg-[#1f538d] file:px-4 file:py-2 file:font-semibold file:text-white hover:file:bg-[#1b4779] focus:outline-none focus:ring-2 focus:ring-[#1f538d]"
              />
              <p className="mt-1 text-[13px] text-slate-600">
                Checks that every receipt issued is in the published list.{" "}
                <a href={receiptListUrl()} download className="text-[#1b4779] hover:underline">
                  Download the receipt list
                </a>
                .
              </p>
            </div>
            <div>
              <label htmlFor="receipt-code" className="mb-1 block font-semibold">
                Your receipt code
              </label>
              <input
                id="receipt-code"
                name="receiptCode"
                type="text"
                autoComplete="off"
                spellCheck={false}
                placeholder="e.g. 7KQ2-M9XD-4RTA-H8WC"
                value={receiptCode}
                onChange={(e) => {
                  setReceiptCode(e.target.value);
                  setOutcome(null);
                  setError("");
                }}
                aria-describedby="receipt-code-help"
                className="w-full rounded border border-slate-400 px-3 py-2 font-mono text-[14px] uppercase focus:outline-none focus:ring-2 focus:ring-[#1f538d]"
              />
              <p id="receipt-code-help" className="mt-1 text-[13px] text-slate-600">
                Confirms your ballot is in the list. Your code is checked in your browser and never sent.
              </p>
            </div>
          </fieldset>

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
