"use client";

import Link from "next/link";
import { StaffProfile } from "@/lib/api";

const employeeLinks = [
  { href: "/staff/employee/dashboard", label: "Dashboard" },
  { href: "/staff/employee/enrolments", label: "Enrolments" },
  { href: "/staff/employee/voters/new", label: "Register voter" },
  { href: "/staff/employee/voters/lookup", label: "Voter lookup" },
  { href: "/staff/employee/candidates", label: "Candidates" },
];
const adminLinks = [
  { href: "/staff/admin/dashboard", label: "Dashboard" },
  { href: "/staff/admin/staff", label: "Staff" },
  { href: "/staff/admin/ip-whitelist", label: "IP allowlist" },
  { href: "/staff/admin/audit-log", label: "Audit log" },
  { href: "/staff/admin/elections", label: "Elections" },
];

export function StaffNav({ profile, onLogout }: {
  profile: StaffProfile;
  onLogout: () => void;
}) {
  const links = profile.role === "admin"
    ? adminLinks
    : profile.role === "aecEmployee"
      ? employeeLinks.filter((item) => item.href !== "/staff/employee/candidates")
      : employeeLinks.filter((item) => item.href === "/staff/employee/dashboard" ||
        item.href === "/staff/employee/candidates");
  return (
    <header className="rounded-lg border border-slate-300 bg-white p-5 shadow">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="font-semibold">{profile.name}</p>
          <p className="text-sm text-slate-600">{profile.role} · {profile.stateId}</p>
        </div>
        <button type="button" onClick={onLogout} className="rounded bg-slate-700 px-4 py-2 text-white hover:bg-slate-800">Log out</button>
      </div>
      <nav aria-label="Staff navigation" className="mt-4 flex flex-wrap gap-2 border-t pt-4">
        {links.map((item) => (
          <Link key={item.href} href={item.href} className="rounded border border-slate-300 px-3 py-2 text-sm font-medium text-[#1f538d] hover:bg-slate-50">
            {item.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
