"use client";

import { StaffPage } from "@/components/staff/StaffPage";
import StaffTools from "@/components/staff/StaffTools";

export default function EmployeeDashboardPage() {
  return <StaffPage roles={["aecEmployee", "commissionerDelegate"]}><StaffTools /></StaffPage>;
}
