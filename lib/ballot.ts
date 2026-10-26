import { apiRequest } from "./api";

// Ballot paper and voting calls (backend/routers/voter_ballot_session.py).
// The ballot is encrypted by the API before it is stored.

export type BallotCandidate = {
  id: string;
  name: string;
  party: string;
};

export type SenateGroup = {
  id: string;
  letter: string;
  name: string;
  party: string;
  candidates: BallotCandidate[];
};

export type BallotPaper = {
  election: { id: string; name: string; openAt?: string | null; closeAt?: string | null };
  voter: { hasVoted: boolean; sessionExpiresAt: string | null };
  // Both null once the voter has voted in this election
  house: { divisionId: string; divisionName: string; candidates: BallotCandidate[] } | null;
  senate: {
    stateId: string;
    regionName: string;
    senatorsToElect: number;
    minimumAbove: number;
    minimumBelow: number;
    groups: SenateGroup[];
    ungrouped: BallotCandidate[];
  } | null;
};

export type BallotChoices = {
  house: { preferences: string[] };
  senate: { aboveTheLine: string[]; belowTheLine: string[] };
};

export type CastReceipt = {
  receipt: string;
  recordedAt: string;
  electionId: string;
};

const path = (electionId: string, action: string) =>
  `/api/voter/ballots/${encodeURIComponent(electionId)}/${action}`;

export function fetchBallotPaper() {
  return apiRequest<BallotPaper>("/api/voter/ballots/current");
}

// Starts the 15-minute voting session; returns when it ends
export function startVoting(electionId: string) {
  return apiRequest<{ electionId: string; voting: boolean; expiresAt: string }>(
    path(electionId, "start"),
    { method: "POST" }
  );
}

export function submitBallot(electionId: string, choices: BallotChoices) {
  return apiRequest<CastReceipt>(path(electionId, "submit"), {
    method: "POST",
    body: JSON.stringify(choices),
  });
}

// Keeps only digits, as typed in a ballot box (at most 3)
export function cleanBoxValue(value: string) {
  return value.replace(/\D/g, "").slice(0, 3);
}

export type Ranking = {
  // Choice IDs in preference order (index 0 = number 1)
  order: string[];
  // Why the numbers cannot be used as they are, or null
  problem: string | null;
};

// Turns the numbers written in ballot boxes into a preference order. Numbers
// must start at 1 and run on with no repeats or gaps, as on a paper ballot.
export function rankBoxes(numbers: Record<string, string>): Ranking {
  const filled = Object.entries(numbers).filter(([, value]) => value.trim() !== "");
  const byNumber = new Map<number, string[]>();

  for (const [id, value] of filled) {
    const number = Number(value);
    if (!Number.isInteger(number) || number < 1) {
      return { order: [], problem: "Use whole numbers starting from 1." };
    }
    byNumber.set(number, [...(byNumber.get(number) ?? []), id]);
  }

  const repeated = [...byNumber.entries()].filter(([, ids]) => ids.length > 1).map(([n]) => n);
  if (repeated.length > 0) {
    return { order: [], problem: `Each number can be used only once (${repeated.sort((a, b) => a - b).join(", ")} used more than once).` };
  }

  const order: string[] = [];
  for (let number = 1; number <= filled.length; number++) {
    const ids = byNumber.get(number);
    if (!ids) {
      return { order: [], problem: `Numbers must run on from 1 with no gaps (${number} is missing).` };
    }
    order.push(ids[0]);
  }
  return { order, problem: null };
}
