"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  onAuthStateChanged,
  User,
} from "firebase/auth";
import {
  doc,
  getDoc,
  serverTimestamp,
  setDoc,
  updateDoc,
} from "firebase/firestore";
import { auth, db } from "@/lib/firebase";
import {
  buttonStyle,
  mainHeader,
} from "@/components/styles";

type VoterProfile = {
  enrolmentStatus?: string;
  eligibilityStatus?: string;
  hasVoted?: boolean;
};

type Candidate = {
  id: string;
  name: string;
  party: string;
};

const candidates: Candidate[] = [
  {
    id: "candidate-1",
    name: "Candidate One",
    party: "Example Party",
  },
  {
    id: "candidate-2",
    name: "Candidate Two",
    party: "Example Party",
  },
  {
    id: "candidate-3",
    name: "Candidate Three",
    party: "Example Party",
  },
];

export default function VoterBallotPage() {
  const router = useRouter();

  const [user, setUser] =
    useState<User | null>(null);

  const [profile, setProfile] =
    useState<VoterProfile | null>(null);

  const [selectedCandidate, setSelectedCandidate] =
    useState("");

  const [isLoading, setIsLoading] =
    useState(true);

  const [isSubmitting, setIsSubmitting] =
    useState(false);

  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(
      auth,
      async (currentUser) => {
        if (!currentUser) {
          router.replace("/login");
          return;
        }

        try {
          const userSnapshot = await getDoc(
            doc(db, "users", currentUser.uid)
          );

          if (!userSnapshot.exists()) {
            setError(
              "Your voter profile could not be found."
            );
            setIsLoading(false);
            return;
          }

          setUser(currentUser);
          setProfile(
            userSnapshot.data() as VoterProfile
          );
        } catch (profileError) {
          console.error(profileError);

          setError(
            "Unable to load your voter information."
          );
        } finally {
          setIsLoading(false);
        }
      }
    );

    return unsubscribe;
  }, [router]);

  const isEnrolled =
    profile?.enrolmentStatus === "enrolled";

  const isEligible =
    profile?.eligibilityStatus === "eligible";

  const hasVoted =
    profile?.hasVoted === true;

  const canVote =
    isEnrolled &&
    isEligible &&
    !hasVoted;

  async function handleSubmitVote(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    setError("");
    setMessage("");

    if (!user || !profile) {
      setError(
        "Your voter information is unavailable."
      );
      return;
    }

    if (!isEnrolled) {
      setError(
        "You cannot vote because you are not enrolled."
      );
      return;
    }

    if (!isEligible) {
      setError(
        "You cannot vote because your eligibility has not been approved."
      );
      return;
    }

    if (hasVoted) {
      setError(
        "You have already submitted your vote."
      );
      return;
    }

    if (!selectedCandidate) {
      setError(
        "Please select a candidate before submitting."
      );
      return;
    }

    setIsSubmitting(true);

    try {
      const userRef = doc(
        db,
        "users",
        user.uid
      );

      const latestUserSnapshot =
        await getDoc(userRef);

      if (!latestUserSnapshot.exists()) {
        throw new Error(
          "Voter profile does not exist."
        );
      }

      const latestProfile =
        latestUserSnapshot.data() as VoterProfile;

      if (
        latestProfile.enrolmentStatus !==
        "enrolled"
      ) {
        setError(
          "You cannot vote because you are not enrolled."
        );
        return;
      }

      if (
        latestProfile.eligibilityStatus !==
        "eligible"
      ) {
        setError(
          "You cannot vote because your eligibility has not been approved."
        );
        return;
      }

      if (latestProfile.hasVoted === true) {
        setError(
          "You have already submitted your vote."
        );
        return;
      }

      await setDoc(
        doc(
          db,
          "votes",
          user.uid
        ),
        {
          voterUid: user.uid,
          candidateId: selectedCandidate,
          submittedAt: serverTimestamp(),
        }
      );

      await updateDoc(userRef, {
        hasVoted: true,
        votedAt: serverTimestamp(),
      });

      setProfile((previous) => ({
        ...previous,
        hasVoted: true,
      }));

      setMessage(
        "Your vote has been submitted successfully."
      );

      setSelectedCandidate("");
    } catch (voteError) {
      console.error(voteError);

      setError(
        "Your vote could not be submitted. Please try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading) {
    return (
      <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
        <p className="text-slate-600">
          Loading ballot...
        </p>
      </main>
    );
  }

  if (hasVoted) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-12">
        <section className="rounded-lg border border-green-300 bg-white p-8 text-center shadow-lg">
          <h1 className={`${mainHeader} mb-4`}>
            Vote Already Submitted
          </h1>

          <p className="mb-6 text-slate-700">
            You have already submitted your vote.
          </p>

          <button
            type="button"
            onClick={() =>
              router.push("/voter/status")
            }
            className={buttonStyle}
          >
            View voting status
          </button>
        </section>
      </main>
    );
  }

  if (!canVote) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-12">
        <section className="rounded-lg border border-amber-300 bg-white p-8 shadow-lg">
          <h1 className={`${mainHeader} mb-4`}>
            Voting Unavailable
          </h1>

          <p className="mb-6 text-slate-700">
            You cannot vote until your enrolment and
            eligibility have been approved.
          </p>

          <div className="mb-6 space-y-3 rounded bg-slate-50 p-4">
            <StatusRow
              label="Enrolment status"
              value={
                profile?.enrolmentStatus ??
                "Not available"
              }
            />

            <StatusRow
              label="Eligibility status"
              value={
                profile?.eligibilityStatus ??
                "Not available"
              }
            />
          </div>

          <button
            type="button"
            onClick={() =>
              router.push("/voter/dashboard")
            }
            className={buttonStyle}
          >
            Back to dashboard
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <section className="rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-2`}>
          Current Ballot
        </h1>

        <p className="mb-6 text-slate-600">
          Select one candidate and submit your vote.
        </p>

        {error && (
          <p
            role="alert"
            className="mb-4 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            {error}
          </p>
        )}

        {message && (
          <p
            role="status"
            className="mb-4 rounded border border-green-300 bg-green-50 px-4 py-3 text-sm text-green-700"
          >
            {message}
          </p>
        )}

        <form
          onSubmit={handleSubmitVote}
          className="space-y-4"
        >
          {candidates.map((candidate) => (
            <label
              key={candidate.id}
              className={`block cursor-pointer rounded-lg border p-4 transition ${
                selectedCandidate === candidate.id
                  ? "border-[#1f538d] bg-blue-50"
                  : "border-slate-300 hover:border-[#1f538d]"
              }`}
            >
              <div className="flex items-start gap-3">
                <input
                  type="radio"
                  name="candidate"
                  value={candidate.id}
                  checked={
                    selectedCandidate === candidate.id
                  }
                  onChange={(event) =>
                    setSelectedCandidate(
                      event.target.value
                    )
                  }
                  className="mt-1"
                />

                <div>
                  <p className="font-semibold text-slate-900">
                    {candidate.name}
                  </p>

                  <p className="text-sm text-slate-600">
                    {candidate.party}
                  </p>
                </div>
              </div>
            </label>
          ))}

          <button
            type="submit"
            disabled={isSubmitting}
            className={`${buttonStyle} w-full disabled:cursor-not-allowed disabled:opacity-60`}
          >
            {isSubmitting
              ? "Submitting vote..."
              : "Submit vote"}
          </button>
        </form>

        <button
          type="button"
          onClick={() =>
            router.push("/voter/dashboard")
          }
          className="mt-4 w-full text-sm text-[#1b4779] hover:underline"
        >
          Back to dashboard
        </button>
      </section>
    </main>
  );
}

function StatusRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div>
      <p className="text-sm font-semibold text-slate-600">
        {label}
      </p>

      <p className="capitalize text-slate-900">
        {value.replace(/-/g, " ")}
      </p>
    </div>
  );
}