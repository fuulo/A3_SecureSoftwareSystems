"use client";

import { StaffPage } from "@/components/staff/StaffPage";
import StaffTools from "@/components/staff/StaffTools";

export default function VoterLookupPage() {
  return <StaffPage roles={["aecEmployee"]}><StaffTools /></StaffPage>;
}
