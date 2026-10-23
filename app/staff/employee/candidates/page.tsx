"use client";

import { StaffPage } from "@/components/staff/StaffPage";
import StaffTools from "@/components/staff/StaffTools";

export default function CandidatesPage() {
  return <StaffPage roles={["commissionerDelegate"]}><StaffTools /></StaffPage>;
}
