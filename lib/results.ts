import resultPackage from "../public/result-package.json";

// Mock data for the public audit pages.
// TODO: replace with data from the backend once results are published there.

export type CandidateResult = {
  name: string;
  party: string;
  votes: number;
};

export type Contest = {
  id: string;
  title: string;
  seats: number;
  informal: number;
  candidates: CandidateResult[];
};

export type ResultPackage = {
  packageVersion: number;
  election: {
    id: string;
    name: string;
    status: string;
    publishedAt: string;
    enrolledVoters: number;
    ballotsCast: number;
  };
  contests: Contest[];
};

export const publishedResults: ResultPackage = resultPackage;

// Where voters can download the official result package
export const RESULT_PACKAGE_URL = "/result-package.json";

// SHA-256 fingerprint of public/result-package.json.
// If the file changes, this value MUST be recalculated (e.g. `sha256sum public/result-package.json`).
// The file is kept on one line so Git line-ending conversion cannot change its bytes.
export const RESULT_PACKAGE_SHA256 =
  "6163a6ac237a0eb6dc24c456fc30da2ad9b64be9bcb2d50d65ce929570fc1a00";

// Formats a number with thousands separators, e.g. 9450 -> "9,450"
export function formatNumber(value: number) {
  return value.toLocaleString("en-AU");
}

// Formats a share as a percentage with one decimal place
export function formatPercent(part: number, whole: number) {
  if (whole === 0) return "0.0%";
  return `${((part / whole) * 100).toFixed(1)}%`;
}

// Formats an ISO date for display in Australian style
export function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString("en-AU", {
    dateStyle: "long",
    timeStyle: "short",
    timeZone: "Australia/Melbourne",
  });
}
