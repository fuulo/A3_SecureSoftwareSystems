"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { onAuthStateChanged } from "firebase/auth";
import { auth } from "../lib/firebase";

export default function RequireAuth({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    // Runs now and every time the login state changes
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      if (user) {
        setAllowed(true);
      } else {
        setAllowed(false);
        router.replace("/login");
      }
    });

    // If the browser restores the page from its back/forward cache,
    // reload it so the check above runs again
    function handlePageShow(event: PageTransitionEvent) {
      if (event.persisted) window.location.reload();
    }
    window.addEventListener("pageshow", handlePageShow);

    return () => {
      unsubscribe();
      window.removeEventListener("pageshow", handlePageShow);
    };
  }, [router]);

  // Show nothing until we know the user is signed in
  if (!allowed) return null;
  return <>{children}</>;
}