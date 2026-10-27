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
    // Added in package version 4: fingerprint of the published receipt list
    // and its algorithm (one of FINGERPRINT_ALGORITHMS)
    receiptsFingerprint?: string;
    receiptsHashAlgorithm?: string;
    // Added in package version 5: ballots that failed their integrity check
    // (R-15) and were left out of every contest. Included in the counts above.
    excludedHouseBallots?: number;
    excludedSenateBallots?: number;
  };
  contests: Contest[];
};

// Where the package and receipt list are archived, locked for 7 years (backend/archive.py)
export type ResultArchive = {
  provider: string;
  bucket: string;
  retentionMode: "compliance" | "governance";
  retainUntil: string;
  files: { name: string; fileId: string; fingerprint: string; hashAlgorithm: string; size: number }[];
};

// Digital signature of the exact package bytes (backend/security/signing.py)
export type ResultSignature = {
  algorithm: "Ed25519";
  keyId: string;
  // 64 bytes as hex
  value: string;
};

// The public key that checks result signatures, read from the server's key file
export type SigningKey = {
  algorithm: "Ed25519";
  keyId: string;
  publicKeyPem: string;
};

export type PublishedResults = {
  // Fingerprint recorded when the package was published, and the hash
  // algorithm that made it (backend/security/hashing.py)
  fingerprint: string;
  algorithm: string;
  package: ResultPackage;
  // Missing or null for results published before signing was added
  signature?: ResultSignature | null;
  // Missing for results published before archiving was added
  archive?: ResultArchive | null;
};

// Algorithms results can be published with: all available to the browser's
// Web Crypto API (label is its name for them), and told apart by length
export const FINGERPRINT_ALGORITHMS = [
  { name: "sha256", label: "SHA-256", hexLength: 64 },
  { name: "sha384", label: "SHA-384", hexLength: 96 },
  { name: "sha512", label: "SHA-512", hexLength: 128 },
] as const;

export type FingerprintAlgorithm = (typeof FINGERPRINT_ALGORITHMS)[number];

export function fingerprintAlgorithm(name: string): FingerprintAlgorithm | undefined {
  return FINGERPRINT_ALGORITHMS.find((algorithm) => algorithm.name === name);
}

// Which algorithm a hex fingerprint was made with, judged by its length
export function algorithmForFingerprint(hex: string): FingerprintAlgorithm | undefined {
  return FINGERPRINT_ALGORITHMS.find((algorithm) => algorithm.hexLength === hex.length);
}

// Where voters can download the official result package (the exact published bytes)
export function resultPackageUrl() {
  return publicApiUrl("/api/public/results/package.json");
}

// The package's raw signature, for checking with tools such as openssl
export function packageSignatureUrl() {
  return publicApiUrl("/api/public/results/package.sig");
}

// Every receipt hash for the published election, one per line
export function receiptListUrl() {
  return publicApiUrl("/api/public/results/receipts.txt");
}

// The current results signing key, or null if the server has none
export async function fetchSigningKey(): Promise<SigningKey | null> {
  try {
    return await publicApiRequest<SigningKey>("/api/public/results/signing-key");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
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
