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
} from "firebase/firestore";
import { auth, db } from "@/lib/firebase";
import { mainHeader } from "@/components/styles";

type VoterStatus = {
  enrolmentStatus?: string;
  eligibilityStatus?: string;
  hasVoted?: boolean;
};

export default function VoterStatusPage() {
  const router = useRouter();

  const [status, setStatus] =
    useState<VoterStatus | null>(null);

  const [isLoading, setIsLoading] =
    useState(true);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(
      auth,
      async (currentUser: User | null) => {
        if (!currentUser) {
          router.replace("/login");
          return;
        }

        try {
          const userSnapshot = await getDoc(
            doc(db, "users", currentUser.uid)
          );

          if (userSnapshot.exists()) {
            setStatus(
              userSnapshot.data() as VoterStatus
            );
          }
        } catch (statusError) {
          console.error(statusError);
        } finally {
          setIsLoading(false);
        }
      }
    );

    return unsubscribe;
  }, [router]);

  if (isLoading) {
    return (
      <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
        <p className="text-slate-600">
          Loading your voting status...
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <section className="rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-6`}>
          Voting Status
        </h1>

        <div className="space-y-4">
          <StatusRow
            label="Enrolment status"
            value={
              status?.enrolmentStatus ??
              "Not available"
            }
          />

          <StatusRow
            label="Eligibility status"
            value={
              status?.eligibilityStatus ??
              "Not available"
            }
          />

          <StatusRow
            label="Voting status"
            value={
              status?.hasVoted
                ? "Vote submitted"
                : "You have not voted"
            }
          />
        </div>

        <button
          type="button"
          onClick={() =>
            router.push("/voter/dashboard")
          }
          className="mt-8 rounded bg-[#1f538d] px-4 py-2 text-white hover:bg-[#173e6b]"
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
    <div className="rounded border border-slate-200 bg-slate-50 p-4">
      <p className="text-sm font-semibold text-slate-600">
        {label}
      </p>

      <p className="mt-1 capitalize text-slate-900">
        {value.replace(/-/g, " ")}
      </p>
    </div>
  );
}