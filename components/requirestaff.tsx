"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { onAuthStateChanged, signOut, User } from "firebase/auth";
import { useRouter } from "next/navigation";
import { ApiError, getStaffProfile, StaffProfile } from "@/lib/api";
import { auth } from "@/lib/firebase";
import { StaffNav } from "@/components/staff/StaffNav";

const StaffContext = createContext<StaffProfile | null>(null);

export function useStaff() {
  return useContext(StaffContext);
}

export default function RequireStaff({
  children,
  allowedRoles,
}: {
  children: React.ReactNode;
  allowedRoles: StaffProfile["role"][];
}) {
  const router = useRouter();
  const [profile, setProfile] = useState<StaffProfile | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");

  const logout = useCallback(async () => {
    try {
      await signOut(auth);
    } finally {
      sessionStorage.removeItem("authenticationCodeVerified");
      sessionStorage.removeItem("pendingAuthCodeUid");
      sessionStorage.removeItem("pendingAuthCodeEmail");
      sessionStorage.removeItem("staffSessionId");
      router.replace("/login");
    }
  }, [router]);

  useEffect(() => {
    const handleUnauthorized = () => { void logout(); };
    window.addEventListener("staff-api-unauthorized", handleUnauthorized);
    if (sessionStorage.getItem("authenticationCodeVerified") !== "true") {
      router.replace("/login");
      return () => window.removeEventListener("staff-api-unauthorized", handleUnauthorized);
    }

    const unsubscribe = onAuthStateChanged(auth, async (currentUser) => {
      if (!currentUser) {
        sessionStorage.removeItem("authenticationCodeVerified");
        router.replace("/login");
        return;
      }
      setUser(currentUser);
      try {
        const staff = await getStaffProfile();
        if (!allowedRoles.includes(staff.role)) {
          router.replace(staff.role === "admin"
            ? "/staff/admin/dashboard"
            : "/staff/employee/dashboard");
          return;
        }
        setProfile(staff);
      } catch (requestError) {
        if (requestError instanceof ApiError &&
            (requestError.status === 403 || requestError.status === 404)) {
          await logout();
          return;
        }
        setError("Unable to verify staff access. Please try again.");
      }
    });
    return () => {
      unsubscribe();
      window.removeEventListener("staff-api-unauthorized", handleUnauthorized);
    };
  }, [allowedRoles, logout, router]);

  useEffect(() => {
    if (!profile || !user) return;
    let timeout: ReturnType<typeof setTimeout>;
    const reset = () => {
      clearTimeout(timeout);
      timeout = setTimeout(() => {
        void logout();
      }, 15 * 60 * 1000);
    };
    const events: (keyof WindowEventMap)[] = [
      "pointerdown", "keydown", "mousemove", "scroll", "touchstart",
    ];
    events.forEach((event) => window.addEventListener(event, reset, { passive: true }));
    reset();
    return () => {
      clearTimeout(timeout);
      events.forEach((event) => window.removeEventListener(event, reset));
    };
  }, [logout, profile, user]);

  if (!profile) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-12">
        <section className="rounded-lg border border-slate-300 bg-white p-8 text-center shadow-lg">
          <p role={error ? "alert" : "status"} className={error ? "text-red-700" : "text-slate-600"}>
            {error || "Checking staff access..."}
          </p>
          {error && <button type="button" onClick={() => window.location.reload()} className="mt-4 underline">Try again</button>}
        </section>
      </main>
    );
  }

  return (
    <StaffContext.Provider value={profile}>
      <div className="mx-auto max-w-6xl px-6 py-8">
        <StaffNav profile={profile} onLogout={logout} />
        <div className="mt-6">{children}</div>
      </div>
    </StaffContext.Provider>
  );
}
