"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { signOut } from "firebase/auth";
import { auth } from "../lib/firebase";

// Pages that belong to the voter area. The user can move between them
// without logging in again. Add the vote page here if it is outside /voter.
const VOTER_AREA = ["/voter"];

function inVoterArea(path: string | null) {
  if (!path) return false;
  return VOTER_AREA.some((p) => path === p || path.startsWith(`${p}/`));
}

export default function SignOutOnLeave() {
  const pathname = usePathname();
  const previous = useRef<string | null>(pathname);

  useEffect(() => {
    // Sign out when the user moves from the voter area to any other page
    if (inVoterArea(previous.current) && !inVoterArea(pathname)) {
      signOut(auth).catch(() => {});
    }
    previous.current = pathname;
  }, [pathname]);

  return null;
}