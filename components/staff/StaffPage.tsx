"use client";

import { ReactNode } from "react";
import RequireStaff from "@/components/requirestaff";
import { StaffProfile } from "@/lib/api";

export function StaffPage({
  roles,
  children,
}: {
  roles: StaffProfile["role"][];
  children: ReactNode;
}) {
  return <RequireStaff allowedRoles={roles}>{children}</RequireStaff>;
}
