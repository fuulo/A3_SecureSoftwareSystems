"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { onAuthStateChanged } from "firebase/auth";
import { auth } from "@/lib/firebase";
import { ApiError } from "@/lib/api";
import {
  cleanBoxValue,
  fetchBallotPaper,
  rankBoxes,
  startVoting,
  submitBallot,
  type BallotCandidate,
  type BallotChoices,
  type BallotPaper,
  type CastReceipt,
} from "@/lib/ballot";
import { MFA_REQUIRED_REASON, requireSecondFactor } from "@/lib/mfa";
import { formatDateTime } from "@/lib/results";
import { buttonStyle, mainHeader, subHeader } from "@/components/styles";

type Step =
  | "loading"
  | "unavailable"
  | "voted"
  | "intro"
  | "ballot"
  | "review"
  | "expired"
  | "receipt";

type SenateMode = "above" | "below";
type Boxes = Record<string, string>;

const secondaryButton =
  "w-full rounded-lg border-2 border-[#1f538d] bg-white px-6 py-3 text-[24px] font-bold text-[#1f538d] transition duration-200 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60";
const cardStyle = "rounded-lg border border-slate-300 bg-white p-6 shadow-lg sm:p-8";
const boxStyle =
  "h-12 w-14 shrink-0 rounded border-2 border-slate-500 bg-white text-center text-[22px] font-bold text-[#1f538d] focus:border-[#1f538d] focus:outline-none focus:ring-2 focus:ring-[#1f538d]";

function minutesAndSeconds(ms: number) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function apiMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

export default function VoterBallotPage() {
  const router = useRouter();

  const [step, setStep] = useState<Step>("loading");
  const [paper, setPaper] = useState<BallotPaper | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [houseBoxes, setHouseBoxes] = useState<Boxes>({});
  const [senateMode, setSenateMode] = useState<SenateMode>("above");
  const [aboveBoxes, setAboveBoxes] = useState<Boxes>({});
  const [belowBoxes, setBelowBoxes] = useState<Boxes>({});
  const [receipt, setReceipt] = useState<CastReceipt | null>(null);
  const [copied, setCopied] = useState(false);

  const loadPaper = useCallback(async () => {
    setStep("loading");
    setError("");
    try {
      const loaded = await fetchBallotPaper();
      setPaper(loaded);
      if (loaded.voter.hasVoted) {
        setStep("voted");
      } else if (loaded.voter.sessionExpiresAt) {
        // A session started earlier (for example before a refresh) is still open
        setExpiresAt(Date.parse(loaded.voter.sessionExpiresAt));
        setStep("ballot");
      } else {
        setStep("intro");
      }
      if (loaded.senate && loaded.senate.groups.length === 0) {
        setSenateMode("below");
      }
    } catch (loadError) {
      setNotice(
        loadError instanceof ApiError && loadError.status === 404
          ? "Voting is not open right now. Please come back during the voting period."
          : apiMessage(loadError, "Your ballot could not be loaded. Please try again.")
      );
      setStep("unavailable");
    }
  }, []);

  // Signed in with both factors, then load this voter's ballot paper
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (currentUser) => {
      if (!currentUser) {
        router.replace("/login");
        return;
      }
      if (!(await requireSecondFactor(currentUser))) {
        router.replace(`/login?reason=${MFA_REQUIRED_REASON}`);
        return;
      }
      void loadPaper();
    });
    return unsubscribe;
  }, [loadPaper, router]);

  // Count down the voting session while the ballot is open
  useEffect(() => {
    if (expiresAt === null || (step !== "ballot" && step !== "review")) return;
    const timer = setInterval(() => {
      const current = Date.now();
      setNow(current);
      if (current >= expiresAt) {
        setStep("expired");
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [expiresAt, step]);

  // Warn before leaving a ballot that has not been submitted
  useEffect(() => {
    if (step !== "ballot" && step !== "review") return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [step]);

  async function handleStart() {
    if (!paper) return;
    setBusy(true);
    setError("");
    try {
      const session = await startVoting(paper.election.id);
      setExpiresAt(Date.parse(session.expiresAt));
      setNow(Date.now());
      setStep("ballot");
    } catch (startError) {
      if (startError instanceof ApiError && startError.status === 409) {
        // Already voted, or a session is open: the ballot paper says which
        await loadPaper();
        setError(startError.message);
        return;
      }
      setError(apiMessage(startError, "Your voting session could not be started. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  if (step === "loading") {
    return (
      <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
        <p role="status" className="text-slate-600">Loading your ballot...</p>
      </main>
    );
  }

  if (step === "unavailable" || !paper) {
    return (
      <Notice
        tone="amber"
        title="Voting Unavailable"
        message={notice || "Your ballot could not be loaded."}
        onRetry={() => void loadPaper()}
      />
    );
  }

  if (step === "voted") {
    return (
      <Notice
        tone="green"
        title="You Have Voted"
        message={`A ballot has already been recorded for you in the ${paper.election.name}. Each voter can vote once.`}
        showVerifyLink
      />
    );
  }

  if (step === "receipt" && receipt) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-12">
        <section className="rounded-lg border border-green-300 bg-white p-8 shadow-lg" aria-labelledby="receipt-title">
          <h1 id="receipt-title" className={`${mainHeader} mb-2 text-center`}>
            ✔ Your Vote Has Been Recorded
          </h1>
          <p className="mb-6 text-center text-slate-700">
            Recorded {formatDateTime(receipt.recordedAt)} in the {paper.election.name}.
          </p>

          <div className="mb-4 rounded-lg border-2 border-dashed border-[#1f538d] bg-[#EAF3FC] p-6 text-center">
            <p className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-slate-600">
              Your receipt code
            </p>
            <p className="break-all font-mono text-[28px] font-bold tracking-[0.15em] text-[#1f538d]">
              {receipt.receipt}
            </p>
            <button
              type="button"
              onClick={() => {
                navigator.clipboard
                  ?.writeText(receipt.receipt)
                  .then(() => setCopied(true))
                  .catch(() => setCopied(false));
              }}
              className="mt-3 text-[14px] font-semibold text-[#1b4779] hover:underline"
            >
              {copied ? "Copied" : "Copy code"}
            </button>
          </div>

          <ul className="mb-6 space-y-2 text-[14px] text-slate-700">
            <li>&#9654; Write this code down or copy it now. It is shown only once and cannot be recovered.</li>
            <li>&#9654; Use it to check that your ballot was recorded and counted. It never shows how you voted.</li>
          </ul>

          <div className="flex flex-col gap-3 sm:flex-row">
            <Link href="/verify-receipt" className={`${buttonStyle} text-center`}>
              Verify my receipt
            </Link>
            <Link href="/voter/dashboard" className={`${secondaryButton} text-center`}>
              Back to dashboard
            </Link>
          </div>
        </section>
      </main>
    );
  }

  if (step === "intro") {
    return (
      <main className="mx-auto max-w-3xl px-6 py-12">
        <section className={cardStyle}>
          <h1 className={`${mainHeader} mb-1`}>{paper.election.name}</h1>
          <p className="mb-6 text-slate-600">
            {paper.house && `Division of ${paper.house.divisionName}`}
            {paper.senate && ` · ${paper.senate.regionName}`}
            {paper.election.closeAt && ` · Voting closes ${formatDateTime(paper.election.closeAt)}`}
          </p>

          <h2 className={`${subHeader} mb-2`}>Before you start</h2>
          <ul className="mb-6 space-y-2 pl-1">
            <li>&#9654; You will complete two ballot papers: the House of Representatives and the Senate.</li>
            <li>&#9654; Write numbers in the boxes in the order of your choice, starting from 1.</li>
            <li>&#9654; You have 15 minutes once you start. You can check your choices before you submit.</li>
            <li>&#9654; Your ballot is encrypted and never linked to your name. You can vote only once.</li>
          </ul>

          {error && <Alert message={error} />}

          <button type="button" onClick={handleStart} disabled={busy} className={`${buttonStyle} disabled:cursor-not-allowed disabled:opacity-60`}>
            {busy ? "Starting..." : "Start voting"}
          </button>
          <Link href="/voter/dashboard" className="mt-4 block text-center text-[14px] text-[#1b4779] hover:underline">
            Back to dashboard
          </Link>
        </section>
      </main>
    );
  }

  if (step === "expired") {
    return (
      <main className="mx-auto max-w-3xl px-6 py-12">
        <section className="rounded-lg border border-amber-300 bg-white p-8 text-center shadow-lg">
          <h1 className={`${mainHeader} mb-3`}>Your Voting Session Ended</h1>
          <p className="mb-6 text-slate-700">
            Your 15 minutes ran out before your ballot was submitted, so nothing was recorded.
            Start again to vote; the numbers you entered are kept.
          </p>
          {error && <Alert message={error} />}
          <button type="button" onClick={handleStart} disabled={busy} className={`${buttonStyle} disabled:cursor-not-allowed disabled:opacity-60`}>
            {busy ? "Starting..." : "Start again"}
          </button>
        </section>
      </main>
    );
  }

  return (
    <BallotForm
      paper={paper}
      step={step}
      remaining={expiresAt === null ? null : expiresAt - now}
      houseBoxes={houseBoxes}
      setHouseBoxes={setHouseBoxes}
      senateMode={senateMode}
      setSenateMode={setSenateMode}
      aboveBoxes={aboveBoxes}
      setAboveBoxes={setAboveBoxes}
      belowBoxes={belowBoxes}
      setBelowBoxes={setBelowBoxes}
      onReview={() => setStep("review")}
      onChange={() => setStep("ballot")}
      onSubmitted={(cast) => {
        // Nothing about the choices stays in the page once the vote is recorded
        setHouseBoxes({});
        setAboveBoxes({});
        setBelowBoxes({});
        setExpiresAt(null);
        setReceipt(cast);
        setStep("receipt");
      }}
      onExpired={() => setStep("expired")}
      onAlreadyVoted={() => void loadPaper()}
    />
  );
}

type BallotFormProps = {
  paper: BallotPaper;
  step: Step;
  remaining: number | null;
  houseBoxes: Boxes;
  setHouseBoxes: (boxes: Boxes) => void;
  senateMode: SenateMode;
  setSenateMode: (mode: SenateMode) => void;
  aboveBoxes: Boxes;
  setAboveBoxes: (boxes: Boxes) => void;
  belowBoxes: Boxes;
  setBelowBoxes: (boxes: Boxes) => void;
  onReview: () => void;
  onChange: () => void;
  onSubmitted: (receipt: CastReceipt) => void;
  onExpired: () => void;
  onAlreadyVoted: () => void;
};

function BallotForm(props: BallotFormProps) {
  const { paper, step, remaining, senateMode } = props;
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const house = paper.house;
  const senate = paper.senate;
  const houseCandidates = house?.candidates ?? [];
  const groups = senate?.groups ?? [];
  const belowCandidates = [...groups.flatMap((group) => group.candidates), ...(senate?.ungrouped ?? [])];

  const houseRank = rankBoxes(props.houseBoxes);
  const aboveRank = rankBoxes(props.aboveBoxes);
  const belowRank = rankBoxes(props.belowBoxes);
  const senateRank = senateMode === "above" ? aboveRank : belowRank;
  const aboveTarget = Math.min(senate?.minimumAbove ?? 6, groups.length);
  const belowTarget = Math.min(senate?.minimumBelow ?? 6, belowCandidates.length);

  // Parts of the ballot that the count would treat as informal
  const warnings: string[] = [];
  if (houseRank.order.length === 0) {
    warnings.push("You have not numbered any House boxes, so your House vote will not count.");
  } else if (houseRank.order.length < houseCandidates.length) {
    warnings.push(
      `Your House vote will not count unless you number every box (${houseRank.order.length} of ${houseCandidates.length} numbered).`
    );
  }
  if (senateRank.order.length === 0) {
    warnings.push("You have not numbered any Senate boxes, so your Senate vote will not count.");
  } else if (senateMode === "below" && senateRank.order.length < belowTarget) {
    warnings.push(
      `Below the line, your Senate vote counts only if you number at least ${belowTarget} boxes (${senateRank.order.length} numbered).`
    );
  } else if (senateMode === "above" && senateRank.order.length < aboveTarget) {
    warnings.push(
      `You were asked to number at least ${aboveTarget} boxes above the line. Your vote still counts, but only ${senateRank.order.length} preference(s) can be used.`
    );
  }

  function handleReview(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = houseRank.problem ?? senateRank.problem;
    if (problem) {
      setError(houseRank.problem ? `House of Representatives: ${houseRank.problem}` : `Senate: ${senateRank.problem}`);
      return;
    }
    setError("");
    props.onReview();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleSubmit() {
    const choices: BallotChoices = {
      house: { preferences: houseRank.order },
      senate: {
        aboveTheLine: senateMode === "above" ? aboveRank.order : [],
        belowTheLine: senateMode === "below" ? belowRank.order : [],
      },
    };
    setSubmitting(true);
    setError("");
    try {
      props.onSubmitted(await submitBallot(paper.election.id, choices));
    } catch (submitError) {
      if (submitError instanceof ApiError && submitError.status === 409) {
        if (/session/i.test(submitError.message)) {
          props.onExpired();
          return;
        }
        if (/already been recorded/i.test(submitError.message)) {
          props.onAlreadyVoted();
          return;
        }
      }
      setError(apiMessage(submitError, "Your vote could not be submitted. Please try again."));
    } finally {
      setSubmitting(false);
    }
  }

  const names = new Map<string, string>();
  for (const candidate of [...houseCandidates, ...belowCandidates]) {
    names.set(candidate.id, `${candidate.name} (${candidate.party})`);
  }
  for (const group of groups) {
    names.set(group.id, `Group ${group.letter}: ${group.name}`);
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-8">
      <div className="sticky top-0 z-20 mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-300 bg-white/95 px-4 py-3 shadow backdrop-blur">
        <div>
          <p className="font-bold text-[#1f538d]">{paper.election.name}</p>
          <p className="text-[13px] text-slate-600">
            {step === "review" ? "Step 2 of 2: check and submit" : "Step 1 of 2: complete your ballot papers"}
          </p>
        </div>
        {remaining !== null && (
          <p
            role="timer"
            aria-live="off"
            className={`rounded px-3 py-1 font-mono text-[18px] font-bold ${
              remaining < 2 * 60 * 1000 ? "bg-red-50 text-red-700" : "bg-[#EAF3FC] text-[#1f538d]"
            }`}
          >
            {minutesAndSeconds(remaining)} left
          </p>
        )}
      </div>

      {error && <Alert message={error} />}

      {step === "review" ? (
        <section className={cardStyle} aria-labelledby="review-title">
          <h1 id="review-title" className={`${mainHeader} mb-4`}>Check Your Vote</h1>

          <ReviewList
            title={`House of Representatives: Division of ${house?.divisionName ?? ""}`}
            order={houseRank.order}
            names={names}
          />
          <ReviewList
            title={`Senate: ${senate?.regionName ?? ""} (${senateMode === "above" ? "above the line" : "below the line"})`}
            order={senateRank.order}
            names={names}
          />

          {warnings.length > 0 && (
            <div role="alert" className="mb-6 rounded border border-amber-300 bg-amber-50 px-4 py-3 text-[14px] text-amber-900">
              {warnings.map((warning) => (
                <p key={warning}>&#9888; {warning}</p>
              ))}
            </div>
          )}

          <p className="mb-4 text-[14px] text-slate-600">
            Once you submit, your vote cannot be changed.
          </p>
          <div className="flex flex-col gap-3 sm:flex-row">
            <button type="button" onClick={props.onChange} disabled={submitting} className={secondaryButton}>
              Change my vote
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={submitting}
              className={`${buttonStyle} disabled:cursor-not-allowed disabled:opacity-60`}
            >
              {submitting ? "Submitting..." : "Submit my vote"}
            </button>
          </div>
        </section>
      ) : (
        <form onSubmit={handleReview} noValidate className="space-y-6">
          {house && (
            <section className={cardStyle} aria-labelledby="house-title">
              <h2 id="house-title" className={`${subHeader} mb-1`}>
                House of Representatives: Division of {house.divisionName}
              </h2>
              <p className="mb-4 text-slate-700">
                Number <strong>every</strong> box from 1 to {house.candidates.length} in the order of your choice.
              </p>
              <ul className="space-y-2">
                {house.candidates.map((candidate) => (
                  <CandidateBox
                    key={candidate.id}
                    candidate={candidate}
                    value={props.houseBoxes[candidate.id] ?? ""}
                    onChange={(value) => props.setHouseBoxes({ ...props.houseBoxes, [candidate.id]: value })}
                  />
                ))}
              </ul>
              {houseRank.problem && <FieldProblem message={houseRank.problem} />}
            </section>
          )}

          {senate && (
            <section className={cardStyle} aria-labelledby="senate-title">
              <h2 id="senate-title" className={`${subHeader} mb-1`}>Senate: {senate.regionName}</h2>
              <p className="mb-4 text-slate-700">
                {senate.senatorsToElect > 0 && `Electing ${senate.senatorsToElect} senators. `}
                Vote either above the line (for groups) or below the line (for candidates).
              </p>

              <fieldset className="mb-5">
                <legend className="sr-only">How do you want to vote for the Senate?</legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {(["above", "below"] as const).map((mode) => {
                    const disabled = mode === "above" && groups.length === 0;
                    return (
                      <label
                        key={mode}
                        className={`flex cursor-pointer items-center gap-3 rounded-lg border-2 px-4 py-3 ${
                          senateMode === mode ? "border-[#1f538d] bg-[#EAF3FC]" : "border-slate-300"
                        } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
                      >
                        <input
                          type="radio"
                          name="senateMode"
                          value={mode}
                          checked={senateMode === mode}
                          disabled={disabled}
                          onChange={() => props.setSenateMode(mode)}
                        />
                        <span>
                          <span className="block font-semibold">
                            {mode === "above" ? "Above the line" : "Below the line"}
                          </span>
                          <span className="block text-[13px] text-slate-600">
                            {mode === "above"
                              ? `Number at least ${aboveTarget} group boxes`
                              : `Number at least ${belowTarget} candidate boxes`}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>

              {senateMode === "above" ? (
                <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {groups.map((group) => (
                    <li key={group.id} className="flex items-center gap-3 rounded-lg border border-slate-300 p-3">
                      <NumberBox
                        label={`Preference number for group ${group.letter}, ${group.name}`}
                        value={props.aboveBoxes[group.id] ?? ""}
                        onChange={(value) => props.setAboveBoxes({ ...props.aboveBoxes, [group.id]: value })}
                      />
                      <span>
                        <span className="block text-[13px] font-semibold text-slate-500">Group {group.letter}</span>
                        <span className="block font-semibold">{group.name}</span>
                        <span className="block text-[13px] text-slate-600">{group.party}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {[
                    ...groups.map((group) => ({ key: group.id, heading: `Group ${group.letter}: ${group.name}`, candidates: group.candidates })),
                    ...(senate.ungrouped.length > 0
                      ? [{ key: "ungrouped", heading: "Ungrouped candidates", candidates: senate.ungrouped }]
                      : []),
                  ].map((column) => (
                    <div key={column.key} className="rounded-lg border border-slate-300 p-3">
                      <p className="mb-2 border-b border-slate-200 pb-2 font-semibold text-[#1f538d]">{column.heading}</p>
                      <ul className="space-y-2">
                        {column.candidates.map((candidate) => (
                          <CandidateBox
                            key={candidate.id}
                            candidate={candidate}
                            value={props.belowBoxes[candidate.id] ?? ""}
                            onChange={(value) => props.setBelowBoxes({ ...props.belowBoxes, [candidate.id]: value })}
                          />
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
              {senateRank.problem && <FieldProblem message={senateRank.problem} />}
            </section>
          )}

          <button type="submit" className={buttonStyle}>
            Review my vote
          </button>
        </form>
      )}
    </main>
  );
}

function NumberBox({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <input
      type="text"
      inputMode="numeric"
      autoComplete="off"
      aria-label={label}
      value={value}
      onChange={(event) => onChange(cleanBoxValue(event.target.value))}
      className={boxStyle}
    />
  );
}

function CandidateBox({
  candidate,
  value,
  onChange,
}: {
  candidate: BallotCandidate;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <li className="flex items-center gap-3 rounded border border-slate-200 p-2">
      <NumberBox label={`Preference number for ${candidate.name}`} value={value} onChange={onChange} />
      <span>
        <span className="block font-semibold">{candidate.name}</span>
        <span className="block text-[13px] text-slate-600">{candidate.party}</span>
      </span>
    </li>
  );
}

function ReviewList({ title, order, names }: { title: string; order: string[]; names: Map<string, string> }) {
  return (
    <div className="mb-6">
      <h2 className={`${subHeader} mb-2 text-[20px]`}>{title}</h2>
      {order.length === 0 ? (
        <p className="text-slate-600">No boxes numbered.</p>
      ) : (
        <ol className="space-y-1">
          {order.map((id, index) => (
            <li key={id} className="flex gap-3">
              <span className="w-8 shrink-0 text-right font-mono font-bold text-[#1f538d]">{index + 1}</span>
              <span>{names.get(id) ?? id}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function FieldProblem({ message }: { message: string }) {
  return (
    <p role="alert" className="mt-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-[14px] text-red-700">
      {message}
    </p>
  );
}

function Alert({ message }: { message: string }) {
  return (
    <p role="alert" className="mb-4 rounded border border-red-300 bg-red-50 px-4 py-3 text-[14px] text-red-700">
      {message}
    </p>
  );
}

function Notice({
  tone,
  title,
  message,
  onRetry,
  showVerifyLink = false,
}: {
  tone: "amber" | "green";
  title: string;
  message: string;
  onRetry?: () => void;
  showVerifyLink?: boolean;
}) {
  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <section
        className={`rounded-lg border bg-white p-8 text-center shadow-lg ${
          tone === "green" ? "border-green-300" : "border-amber-300"
        }`}
      >
        <h1 className={`${mainHeader} mb-3`}>{title}</h1>
        <p className="mb-6 text-slate-700">{message}</p>
        <div className="flex flex-col gap-3 sm:flex-row">
          {showVerifyLink && (
            <Link href="/verify-receipt" className={`${buttonStyle} text-center`}>
              Verify my receipt
            </Link>
          )}
          {onRetry && (
            <button type="button" onClick={onRetry} className={secondaryButton}>
              Try again
            </button>
          )}
          <Link href="/voter/dashboard" className={`${secondaryButton} text-center`}>
            Back to dashboard
          </Link>
        </div>
      </section>
    </main>
  );
}
