"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { signOut } from "firebase/auth";
import { auth } from "../lib/firebase";

const PROTECTED_AREAS = ["/voter", "/staff"];

function inProtectedArea(path: string | null) {
  if (!path) return false;
  return PROTECTED_AREAS.some((p) => path === p || path.startsWith(`${p}/`));
}

export default function SignOutOnLeave() {
  const pathname = usePathname();
  const previous = useRef<string | null>(pathname);

  useEffect(() => {
    if (inProtectedArea(previous.current) && !inProtectedArea(pathname)) {
      signOut(auth).catch(() => {});
    }
    previous.current = pathname;
  }, [pathname]);

  return null;
}