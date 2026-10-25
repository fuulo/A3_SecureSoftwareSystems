import { ApiError, publicApiRequest, publicApiUrl } from "./api";

// Result package format, built by backend/results.py when results are published.

export type CandidateResult = {
  id: string;
  name: string;
  party: string;
  votes: number;
};

export type Contest = {
  id: string;
  chamber: "house" | "senate";
  title: string;
  seats: number;
  ballotsCast: number;
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
    // House ballots
    ballotsCast: number;
    // Added in package version 3
    senateBallotsCast?: number;
    votersMarkedVoted?: number;
    receiptsIssued: number;
  };
  contests: Contest[];
};

export type PublishedResults = {
  // SHA-256 fingerprint recorded when the package was published
  sha256: string;
  package: ResultPackage;
};

// Where voters can download the official result package (the exact published bytes)
export function resultPackageUrl() {
  return publicApiUrl("/api/public/results/package.json");
}

// Latest published results, or null if nothing has been published yet
export async function fetchPublishedResults(): Promise<PublishedResults | null> {
  try {
    return await publicApiRequest<PublishedResults>("/api/public/results");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

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
