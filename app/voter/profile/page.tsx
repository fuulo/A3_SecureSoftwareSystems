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

type UserProfile = {
  givenName?: string;
  surname?: string;
  dob?: string;
  govId?: string;
  address?: string;
  email?: string;
};

export default function VoterProfilePage() {
  const router = useRouter();

  const [user, setUser] =
    useState<User | null>(null);

  const [profile, setProfile] =
    useState<UserProfile | null>(null);

  const [isLoading, setIsLoading] =
    useState(true);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(
      auth,
      async (currentUser) => {
        if (!currentUser) {
          router.replace("/login");
          return;
        }

        try {
          const profileSnapshot = await getDoc(
            doc(db, "users", currentUser.uid)
          );

          if (profileSnapshot.exists()) {
            setProfile(
              profileSnapshot.data() as UserProfile
            );
          }

          setUser(currentUser);
        } catch (profileError) {
          console.error(profileError);
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
          Loading your profile...
        </p>
      </main>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <section className="rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-6`}>
          My Profile
        </h1>

        <div className="space-y-4">
          <ProfileRow
            label="First name"
            value={profile?.givenName}
          />

          <ProfileRow
            label="Last name"
            value={profile?.surname}
          />

          <ProfileRow
            label="Date of birth"
            value={profile?.dob}
          />

          <ProfileRow
            label="GovID"
            value={profile?.govId}
          />

          <ProfileRow
            label="Residential address"
            value={profile?.address}
          />

          <ProfileRow
            label="Email address"
            value={
              profile?.email ?? user.email
            }
          />

          <ProfileRow
            label="Email verified"
            value={
              user.emailVerified
                ? "Yes"
                : "No"
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

function ProfileRow({
  label,
  value,
}: {
  label: string;
  value?: string | null;
}) {
  return (
    <div className="border-b border-slate-200 pb-3">
      <p className="text-sm font-semibold text-slate-600">
        {label}
      </p>

      <p className="mt-1 text-slate-900">
        {value || "Not available"}
      </p>
    </div>
  );
}