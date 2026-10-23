"use client";

import { StaffPage } from "@/components/staff/StaffPage";
import StaffTools from "@/components/staff/StaffTools";

export default function AdminIpPage() {
  return <StaffPage roles={["admin"]}><StaffTools /></StaffPage>;
}
