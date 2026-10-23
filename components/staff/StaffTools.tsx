"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useParams, usePathname } from "next/navigation";
import { apiRequest } from "@/lib/api";
import { useStaff } from "@/components/requirestaff";
import { mainHeader, buttonStyle } from "@/components/styles";
import { Banner } from "@/components/staff/Banner";
import { ConfirmModal } from "@/components/staff/ConfirmModal";
import { DataColumn, DataTable } from "@/components/staff/DataTable";
import { StatusBadge } from "@/components/staff/StatusBadge";

type Row = {
  [key: string]: unknown;
  id?: string;
  voterId?: string;
  staffId?: string;
  candidateId?: string;
};
type CollectionResponse = { items: Row[]; nextCursor?: string | null };
const inputStyle = "w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]";
const buttonSecondary = "rounded border border-slate-300 px-3 py-2 text-sm font-semibold text-[#1f538d] hover:bg-slate-50 disabled:opacity-50";

function text(row: Row, key: string): string {
  const value = row[key];
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function PageHeading({ title, help }: { title: string; help?: string }) {
  return <div className="mb-6"><h1 className={mainHeader}>{title}</h1>{help && <p className="mt-2 text-slate-600">{help}</p>}</div>;
}

export default function StaffTools() {
  const path = usePathname();
  const params = useParams<{ voterId?: string }>();
  const profile = useStaff();
  const [rows, setRows] = useState<Row[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [record, setRecord] = useState<Row | null>(null);
  const [divisions, setDivisions] = useState<Row[]>([]);
  const [electionId, setElectionId] = useState("");
  const [electionName, setElectionName] = useState("");
  const [candidateOptions, setCandidateOptions] = useState<Row>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [searchMode, setSearchMode] = useState<"govId" | "name">("govId");
  const [search, setSearch] = useState({ govId: "", givenNames: "", surname: "" });
  const [pendingReject, setPendingReject] = useState<Row | null>(null);
  const [pendingApprove, setPendingApprove] = useState<Row | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [pendingCandidate, setPendingCandidate] = useState<Row | null>(null);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [editingCandidate, setEditingCandidate] = useState<Row | null>(null);
  const [editingStaff, setEditingStaff] = useState<Row | null>(null);
  const [pendingStaff, setPendingStaff] = useState<Row | null>(null);
  const [editingIp, setEditingIp] = useState<Row | null>(null);
  const [verification, setVerification] = useState<Row | null>(null);
  const [currentIp, setCurrentIp] = useState("");
  const [auditFilters, setAuditFilters] = useState({
    actorId: "", actorType: "", category: "", action: "", outcome: "",
    electionId: "", from: "", to: "",
  });
  const [candidateFilters, setCandidateFilters] = useState({
    chamber: "", divisionId: "", stateId: "",
  });
  const [form, setForm] = useState<Record<string, string>>({});
  const [phaseElection, setPhaseElection] = useState<Row | null>(null);
  const [phaseName, setPhaseName] = useState("");
  const [phaseTarget, setPhaseTarget] = useState("");
  const voterId = params.voterId;

  const displayError = (cause: unknown) => {
    setError(cause instanceof Error ? cause.message : "The request could not be completed.");
    setNotice("");
  };

  const load = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    setError("");
    try {
      if (path.endsWith("/enrolments")) {
        const result = await apiRequest<CollectionResponse>("/api/employee/enrolments?status=pending");
        setRows(result.items);
        setNextCursor(result.nextCursor ?? null);
        const list = await apiRequest<Row[]>("/api/elections/active/divisions");
        setDivisions(list);
      } else if (path.endsWith("/voters/lookup")) {
        setRows([]);
      } else if (path.includes("/voters/") && voterId) {
        const result = await apiRequest<Row>(`/api/employee/voters/${encodeURIComponent(voterId)}`);
        setRecord(result);
        const list = await apiRequest<Row[]>("/api/elections/active/divisions");
        setDivisions(list);
      } else if (path.endsWith("/candidates")) {
        const election = await apiRequest<Row>("/api/delegate/elections/active");
        const id = text(election, "electionId");
        setElectionId(id);
        setElectionName(text(election, "name"));
        const result = await apiRequest<Row[]>(`/api/delegate/elections/${encodeURIComponent(id)}/candidates`);
        setRows(result);
        setCandidateOptions(await apiRequest<Row>(`/api/delegate/elections/${encodeURIComponent(id)}/options`));
      } else if (path.endsWith("/admin/staff")) {
        setRows(await apiRequest<Row[]>("/api/admin/staff"));
      } else if (path.endsWith("/admin/ip-whitelist")) {
        setRows(await apiRequest<Row[]>("/api/admin/ip-ranges"));
        const myIp = await apiRequest<{ ipAddress: string }>("/api/admin/my-ip");
        setCurrentIp(myIp.ipAddress);
      } else if (path.endsWith("/admin/audit-log")) {
        const result = await apiRequest<CollectionResponse>("/api/admin/audit-logs?limit=50");
        setRows(result.items);
        setNextCursor(result.nextCursor ?? null);
      } else if (path.endsWith("/admin/elections")) {
        setRows(await apiRequest<Row[]>("/api/admin/elections"));
      }
    } catch (cause) {
      displayError(cause);
    } finally {
      setLoading(false);
    }
  }, [path, voterId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (path?.endsWith("/employee/dashboard") && profile?.role === "aecEmployee") {
      apiRequest<{ count: number }>("/api/employee/voters/enrolments/pending/count")
        .then((result) => setForm((current) => ({ ...current, pendingCount: String(result.count) })))
        .catch(displayError);
    }
  }, [path, profile]);

  const run = async (request: () => Promise<unknown>, success: string, reload = true) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await request();
      setNotice(success);
      if (reload) await load();
    } catch (cause) {
      displayError(cause);
    } finally {
      setBusy(false);
    }
  };

  const sendJson = <T,>(url: string, method: string, body: unknown) =>
    apiRequest<T>(url, { method, body: JSON.stringify(body) });

  const submitLookup = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const body = searchMode === "govId"
      ? { govId: search.govId.trim() }
      : { givenNames: search.givenNames.trim(), surname: search.surname.trim() };
    setBusy(true);
    setError("");
    try {
      const result = await sendJson<CollectionResponse>("/api/employee/voters/lookup", "POST", body);
      setRows(result.items);
      setNotice(`${result.items.length} result(s) found.`);
    } catch (cause) {
      displayError(cause);
    } finally {
      setBusy(false);
    }
  };

  const approve = async (row: Row) => {
    const selectedDivision = form[`division-${text(row, "voterId")}`];
    if (!selectedDivision) {
      setError("Select a division before approving the enrolment.");
      return;
    }
    await run(() => sendJson(`/api/employee/enrolments/${encodeURIComponent(text(row, "voterId"))}/approve`, "POST", { divisionId: selectedDivision }), "Enrolment approved.");
  };

  const submitApprove = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!pendingApprove) return;
    void approve(pendingApprove);
    setPendingApprove(null);
  };

  const submitReject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!pendingReject) return;
    await run(() => sendJson(`/api/employee/enrolments/${encodeURIComponent(text(pendingReject, "voterId"))}/reject`, "POST", { reason: rejectReason }), "Enrolment rejected.");
    setPendingReject(null);
    setRejectReason("");
  };

  const submitRegistration = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!profile) return;
    const payload = {
      givenNames: form.givenNames?.trim(),
      surname: form.surname?.trim(),
      dateOfBirth: form.dateOfBirth,
      govId: form.govId?.trim(),
      street: form.street?.trim(),
      suburb: form.suburb?.trim(),
      state: form.state,
      postcode: form.postcode,
      email: form.email?.trim(),
      divisionId: form.divisionId,
    };
    if (!/^[A-Za-z0-9]{6,20}$/.test(payload.govId ?? "")) {
      setError("Government ID must contain 6 to 20 letters or digits.");
      return;
    }
    await run(() => sendJson("/api/employee/voters", "POST", payload), "Voter account created. Password setup instructions were sent.");
    setForm({});
  };

  const submitAddress = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!record || !voterId) return;
    const currentAddress = (record.address ?? {}) as Record<string, unknown>;
    const nextAddress = {
      street: form.street ?? String(currentAddress.street ?? ""),
      unit: form.unit ?? String(currentAddress.unit ?? ""),
      suburb: form.suburb ?? String(currentAddress.suburb ?? ""),
      state: form.state ?? String(currentAddress.state ?? ""),
      postcode: form.postcode ?? String(currentAddress.postcode ?? ""),
    };
    const division = divisions.find((item) => text(item, "divisionId") === form.divisionId);
    const nextDivisionId = form.divisionId ?? text(record, "divisionId");
    const changesDivision = nextDivisionId !== text(record, "divisionId");
    const changesState = nextAddress.state !== String(currentAddress.state ?? "");
    if ((changesDivision || changesState) && !window.confirm("The change affects the voter’s electoral division or state. Continue?")) return;
    await run(() => sendJson(`/api/employee/voters/${encodeURIComponent(voterId)}/address`, "PATCH", {
      newAddress: nextAddress,
      newDivisionId: nextDivisionId,
      reason: form.reason ?? "correction",
    }), `Address updated${division ? `; division is ${text(division, "name")}` : ""}.`);
  };

  const submitStaffCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (editingStaff) {
      await run(() => sendJson(`/api/admin/staff/${encodeURIComponent(text(editingStaff, "staffId"))}`, "PATCH", {
        name: form.name, role: form.role, stateId: form.stateId, active: form.active === "true",
      }), "Staff account updated.");
      setEditingStaff(null);
    } else {
      if (form.password !== form.confirmPassword) {
        setError("Passwords do not match.");
        return;
      }
      if (!form.password || form.password.length < 12 || !/[a-z]/.test(form.password)
          || !/[A-Z]/.test(form.password) || !/\d/.test(form.password)) {
        setError("Password must be at least 12 characters and include upper-case, lower-case and numeric characters.");
        return;
      }
      await run(() => sendJson("/api/admin/staff", "POST", {
        name: form.name, email: form.email, role: form.role, stateId: form.stateId,
        password: form.password,
      }), "Staff account created. Share the password with the staff member securely.");
    }
    setForm({});
  };

  const submitIpCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (editingIp) {
      await run(() => sendJson(`/api/admin/ip-ranges/${encodeURIComponent(text(editingIp, "locationId"))}`, "PATCH", {
        cidr: form.cidr, label: form.label, active: editingIp.active === true, confirmLockout: false,
      }), "IP range updated.");
      setEditingIp(null);
    } else {
      await run(() => sendJson("/api/admin/ip-ranges", "POST", {
        cidr: form.cidr, label: form.label, active: true,
      }), "IP range added.");
    }
    setForm({});
  };

  const submitStaffDeactivate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!pendingStaff || form.confirmName !== text(pendingStaff, "name")) return;
    void run(() => apiRequest(`/api/admin/staff/${encodeURIComponent(text(pendingStaff, "staffId"))}`, { method: "DELETE" }), "Staff account deactivated.");
    setPendingStaff(null);
    setForm({});
  };

  const submitAuditFilters = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = new URLSearchParams();
    Object.entries(auditFilters).forEach(([key, value]) => {
      if (value) query.set(key, value);
    });
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest<CollectionResponse>(`/api/admin/audit-logs?${query.toString()}`);
      setRows(result.items);
      setNextCursor(result.nextCursor ?? null);
    } catch (cause) {
      displayError(cause);
    } finally {
      setBusy(false);
    }
  };

  const loadMore = async () => {
    if (!nextCursor || !path) return;
    setBusy(true);
    setError("");
    try {
      let result: CollectionResponse;
      if (path.endsWith("/enrolments")) {
        result = await apiRequest<CollectionResponse>(
          `/api/employee/enrolments?status=pending&cursor=${encodeURIComponent(nextCursor)}`,
        );
      } else {
        const query = new URLSearchParams();
        Object.entries(auditFilters).forEach(([key, value]) => {
          if (value) query.set(key, value);
        });
        query.set("cursor", nextCursor);
        result = await apiRequest<CollectionResponse>(`/api/admin/audit-logs?${query.toString()}`);
      }
      setRows((current) => [...current, ...result.items]);
      setNextCursor(result.nextCursor ?? null);
    } catch (cause) {
      displayError(cause);
    } finally {
      setBusy(false);
    }
  };

  const submitElectionCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await run(() => sendJson("/api/admin/elections", "POST", {
      name: form.name, type: "federal", openAt: form.openAt, closeAt: form.closeAt, timezone: form.timezone,
    }), "Election created.");
    setForm({});
  };

  const submitPhase = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!phaseElection || phaseName !== text(phaseElection, "name")) return;
    const id = text(phaseElection, "electionId");
    await run(() => sendJson(`/api/admin/elections/${encodeURIComponent(id)}/phase`, "POST", {
      to: phaseTarget, reason: "Confirmed in staff dashboard",
    }), `Election phase changed to ${phaseTarget}.`);
    setPhaseElection(null);
    setPhaseName("");
  };

  const home = path?.endsWith("/dashboard");
  const formField = (name: string, label: string, type = "text", required = true) => (
    <label key={name} className="block space-y-1 text-sm font-semibold">
      <span>{label}</span>
      <input className={inputStyle} type={type} name={name} required={required} autoComplete={type === "password" ? "new-password" : undefined} value={form[name] ?? ""}
        onChange={(event) => setForm((current) => ({ ...current, [name]: event.target.value }))} />
    </label>
  );
  const selectField = (name: string, label: string, values: { value: string; label: string }[]) => (
    <label key={name} className="block space-y-1 text-sm font-semibold">
      <span>{label}</span>
      <select className={inputStyle} name={name} required value={form[name] ?? ""}
        onChange={(event) => setForm((current) => ({ ...current, [name]: event.target.value }))}>
        <option value="">Select {label.toLowerCase()}</option>
        {values.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>
    </label>
  );
  const rowsTable = (columns: DataColumn<Row>[], emptyMessage?: string, sourceRows = rows) =>
    loading ? <p role="status" className="py-6 text-slate-600">Loading records...</p>
      : <DataTable columns={columns} rows={sourceRows} emptyMessage={emptyMessage} />;

  const homeCards = profile?.role === "admin"
    ? [
      ["/staff/admin/staff", "Staff accounts", "Create and manage staff access."],
      ["/staff/admin/ip-whitelist", "IP allowlist", "Manage staff network access."],
      ["/staff/admin/audit-log", "Audit log", "Review and verify staff activity."],
      ["/staff/admin/elections", "Elections", "Create elections and advance their phases."],
    ]
    : profile?.role === "commissionerDelegate"
      ? [["/staff/employee/candidates", "Candidates", "Create, edit and withdraw candidates."]]
      : [
        ["/staff/employee/enrolments", "Enrolments", "Review pending voter applications."],
        ["/staff/employee/voters/new", "Register voter", "Create an enrolled voter account."],
        ["/staff/employee/voters/lookup", "Voter lookup", "Find a voter by name or government ID."],
        ["/staff/employee/voters/lookup", "Address updates", "Open a voter record to update its address and division."],
      ];

  let content: React.ReactNode = null;

  if (home) {
    content = (
      <>
        <PageHeading title={profile?.role === "admin" ? "Admin dashboard" : "Employee dashboard"} help="Choose an authorized staff function." />
        {profile?.role === "aecEmployee" && form.pendingCount !== undefined && <Banner>Pending enrolments: {form.pendingCount}</Banner>}
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          {homeCards.map(([href, title, description]) => (
            <Link key={href} href={href} className="rounded-lg border border-slate-300 bg-white p-5 shadow-sm transition hover:border-[#1f538d]">
              <h2 className="text-lg font-semibold text-[#1f538d]">{title}</h2><p className="mt-2 text-sm text-slate-600">{description}</p>
            </Link>
          ))}
        </div>
      </>
    );
  } else if (path?.endsWith("/enrolments")) {
    content = (
      <>
        <PageHeading title="Pending voter enrolments" help="Government IDs are masked in this list." />
        {rowsTable([
          { key: "givenNames", label: "Given names" }, { key: "surname", label: "Surname" },
          { key: "dateOfBirth", label: "Date of birth" }, { key: "govId", label: "Government ID" },
          { key: "address", label: "Address", render: (row) => text(row, "address") },
          { key: "actions", label: "Review", render: (row) => (
            <div className="min-w-56 space-y-2">
              <select aria-label={`Division for ${text(row, "givenNames")}`} className={inputStyle}
                value={form[`division-${text(row, "voterId")}`] ?? ""}
                onChange={(event) => setForm((current) => ({ ...current, [`division-${text(row, "voterId")}`]: event.target.value }))}>
                <option value="">Select division</option>{divisions.map((division) => <option key={text(division, "divisionId")} value={text(division, "divisionId")}>{text(division, "name")}</option>)}
              </select>
              <div className="flex gap-2">
                <button type="button" disabled={busy} onClick={() => setPendingApprove(row)} className={buttonSecondary}>Approve</button>
                <button type="button" disabled={busy} onClick={() => setPendingReject(row)} className="rounded border border-red-300 px-3 py-2 text-sm text-red-800">Reject</button>
              </div>
            </div>
          ) },
        ], "There are no pending enrolments.")}
        {nextCursor && <button type="button" disabled={busy} onClick={() => void loadMore()} className={`${buttonSecondary} mt-4`}>
          {busy ? "Loading..." : "Load more"}
        </button>}
        {pendingApprove && <ConfirmModal title="Approve voter enrolment" confirmLabel="Approve" busy={busy} onCancel={() => setPendingApprove(null)} onConfirm={submitApprove}>
          <p>Approve {text(pendingApprove, "givenNames")} {text(pendingApprove, "surname")} for the selected electoral division?</p>
        </ConfirmModal>}
        {pendingReject && <ConfirmModal title="Reject enrolment" confirmLabel="Reject enrolment" busy={busy} onCancel={() => setPendingReject(null)} onConfirm={(event) => void submitReject(event)}>
          <p className="mb-3">Enter a reason for rejecting {text(pendingReject, "givenNames")} {text(pendingReject, "surname")}.</p>
          <textarea ref={(element) => element?.focus()} className={inputStyle} required maxLength={500} rows={4} value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} aria-label="Reason for rejection" />
        </ConfirmModal>}
      </>
    );
  } else if (path?.endsWith("/voters/new")) {
    content = <><PageHeading title="Register a voter" help="The account is created without showing a password; setup instructions are sent by Firebase." />
      <form onSubmit={(event) => void submitRegistration(event)} className="grid gap-4 rounded-lg border bg-white p-6 sm:grid-cols-2">
        {formField("givenNames", "Given names")}{formField("surname", "Surname")}
        {formField("dateOfBirth", "Date of birth", "date")}
        <label className="block space-y-1 text-sm font-semibold"><span>Government ID</span><input className={inputStyle} autoComplete="off" required minLength={6} maxLength={20} value={form.govId ?? ""} onChange={(event) => setForm((old) => ({ ...old, govId: event.target.value }))} /></label>
        {formField("email", "Email", "email")}{formField("street", "Street address")}{formField("suburb", "Suburb")}
        {selectField("state", "State", ["ACT","NSW","NT","QLD","SA","TAS","VIC","WA"].map((v) => ({ value: v, label: v })))}
        {formField("postcode", "Postcode")}
        {selectField("divisionId", "Division", divisions.map((v) => ({ value: text(v, "divisionId"), label: text(v, "name") })))}
        <button className={`${buttonStyle} sm:col-span-2 disabled:opacity-50`} disabled={busy}>{busy ? "Registering..." : "Register voter"}</button>
      </form>
    </>;
  } else if (path?.endsWith("/voters/lookup")) {
    content = <><PageHeading title="Voter lookup" help="Search terms are sent in a POST body, not a URL. Results mask government IDs." />
      <form onSubmit={(event) => void submitLookup(event)} className="space-y-4 rounded-lg border bg-white p-6">
        <div className="flex gap-4">
          <label className="flex items-center gap-2"><input type="radio" checked={searchMode === "govId"} onChange={() => setSearchMode("govId")} />Government ID</label>
          <label className="flex items-center gap-2"><input type="radio" checked={searchMode === "name"} onChange={() => setSearchMode("name")} />Name</label>
        </div>
        {searchMode === "govId"
          ? <label className="block space-y-1 text-sm font-semibold"><span>Government ID</span><input className={inputStyle} autoComplete="off" minLength={6} maxLength={20} required value={search.govId} onChange={(event) => setSearch({ ...search, govId: event.target.value })} /></label>
          : <div className="grid gap-4 sm:grid-cols-2"><label className="space-y-1 text-sm font-semibold"><span>Given names</span><input className={inputStyle} required value={search.givenNames} onChange={(event) => setSearch({ ...search, givenNames: event.target.value })} /></label><label className="space-y-1 text-sm font-semibold"><span>Surname</span><input className={inputStyle} required value={search.surname} onChange={(event) => setSearch({ ...search, surname: event.target.value })} /></label></div>}
        <button disabled={busy} className={buttonSecondary}>{busy ? "Searching..." : "Search"}</button>
      </form>
      <div className="mt-6">{rowsTable([
        { key: "givenNames", label: "Given names" }, { key: "surname", label: "Surname" },
        { key: "govId", label: "Government ID" }, { key: "enrolmentStatus", label: "Status" },
        { key: "detail", label: "Details", render: (row) => <Link className="text-[#1f538d] underline" href={`/staff/employee/voters/${encodeURIComponent(text(row, "voterId"))}`}>Open voter record</Link> },
      ], "Search for a voter to view results.")}</div>
    </>;
  } else if (path?.includes("/voters/") && voterId) {
    const address = record?.address && typeof record.address === "object" ? record.address as Record<string, unknown> : {};
    const history = Array.isArray(record?.addressHistory) ? record.addressHistory as Row[] : [];
    content = <><PageHeading title="Voter details" help="This explicitly authorized detail view includes the full government ID." />
      {record && <section className="space-y-3 rounded-lg border bg-white p-6">
        <p><strong>Name:</strong> {text(record, "givenNames")} {text(record, "surname")}</p>
        <p><strong>Date of birth:</strong> {text(record, "dateOfBirth")}</p>
        <p><strong>Government ID:</strong> {text(record, "govId")}</p>
        <p><strong>Email:</strong> {text(record, "email")}</p>
        <p><strong>Enrolment:</strong> <StatusBadge value={text(record, "enrolmentStatus")} /></p>
        <p><strong>Address:</strong> {text(address as Row, "street")} {text(address as Row, "unit")} {text(address as Row, "suburb")} {text(address as Row, "state")} {text(address as Row, "postcode")}</p>
      </section>}
      {record?.enrolmentStatus === "enrolled" && <form onSubmit={(event) => void submitAddress(event)} className="mt-6 grid gap-4 rounded-lg border bg-white p-6 sm:grid-cols-2">
        <h2 className="text-lg font-semibold sm:col-span-2">Update address and division</h2>
        {((form.divisionId ?? text(record, "divisionId")) !== text(record, "divisionId") ||
          (form.state ?? String(address.state ?? "")) !== String(address.state ?? "")) &&
          <Banner kind="info">This change alters the voter’s electoral division or state. Verify the voter’s new residential details before saving.</Banner>}
        {formField("street", "Street", "text", false)}{formField("unit", "Unit (optional)", "text", false)}
        {formField("suburb", "Suburb", "text", false)}
        {selectField("state", "State", ["ACT","NSW","NT","QLD","SA","TAS","VIC","WA"].map((v) => ({ value: v, label: v })))}
        {formField("postcode", "Postcode", "text", false)}
        {selectField("divisionId", "New division", divisions.map((v) => ({ value: text(v, "divisionId"), label: text(v, "name") })))}
        {selectField("reason", "Reason", ["moved_house","correction","other"].map((v) => ({ value: v, label: v.replace("_"," ") })))}
        <button disabled={busy} className={`${buttonSecondary} sm:col-span-2`}>Save address update</button>
      </form>}
      <h2 className="mb-3 mt-8 text-xl font-semibold">Address history</h2>
      {history.length ? <ol className="space-y-3">{history.map((item) => <li key={text(item, "changeId")} className="rounded border bg-white p-4"><p>{text(item, "changedAt")} · {text(item, "changeChannel")} · {text(item, "reason")}</p><p className="mt-2 text-sm text-slate-600">{text(item, "previousAddress")} → {text(item, "newAddress")}</p></li>)}</ol> : <p className="text-slate-600">No address changes recorded.</p>}
    </>;
  } else if (path?.endsWith("/candidates")) {
    const parties = Array.isArray(candidateOptions.parties) ? candidateOptions.parties as Row[] : [];
    const candidateDivisions = Array.isArray(candidateOptions.divisions) ? candidateOptions.divisions as Row[] : [];
    const groups = Array.isArray(candidateOptions.senateGroups) ? candidateOptions.senateGroups as Row[] : [];
    const submitCandidate = (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (editingCandidate) {
        const update = {
          name: form.candidateName,
          partyId: form.partyId,
          groupId: form.chamber === "senate" ? (form.groupId || null) : null,
          ballotPosition: Number(form.ballotPosition),
        };
        void run(() => sendJson(
          `/api/delegate/elections/${encodeURIComponent(electionId)}/candidates/${encodeURIComponent(text(editingCandidate, "candidateId"))}`,
          "PATCH",
          update,
        ), "Candidate updated.");
        setEditingCandidate(null);
        setForm({});
        return;
      }
      const payload = {
        name: form.candidateName, partyId: form.partyId, chamber: form.chamber,
        divisionId: form.chamber === "house" ? form.divisionId : null,
        stateId: form.chamber === "senate" ? profile?.stateId : null,
        groupId: form.chamber === "senate" ? (form.groupId || null) : null,
        ballotPosition: Number(form.ballotPosition),
      };
      void run(() => sendJson(`/api/delegate/elections/${encodeURIComponent(electionId)}/candidates`, "POST", payload), "Candidate created.");
      setForm({});
    };
    const setupPhase = text((candidateOptions.election ?? {}) as Row, "status") === "setup";
    const filteredCandidates = rows.filter((row) =>
      (!candidateFilters.chamber || text(row, "chamber") === candidateFilters.chamber) &&
      (!candidateFilters.divisionId || text(row, "divisionId") === candidateFilters.divisionId) &&
      (!candidateFilters.stateId || text(row, "stateId") === candidateFilters.stateId),
    );
    content = <><PageHeading title="Candidate management" help={`${electionName || "Election"} · only candidates within your state are accessible.`} />
      <div className="mb-4 grid gap-3 rounded border bg-white p-4 sm:grid-cols-3">
        <label className="space-y-1 text-sm font-semibold"><span>Chamber</span><select className={inputStyle} value={candidateFilters.chamber} onChange={(event) => setCandidateFilters((old) => ({ ...old, chamber: event.target.value }))}><option value="">All</option><option value="house">House</option><option value="senate">Senate</option></select></label>
        <label className="space-y-1 text-sm font-semibold"><span>Division</span><select className={inputStyle} value={candidateFilters.divisionId} onChange={(event) => setCandidateFilters((old) => ({ ...old, divisionId: event.target.value }))}><option value="">All divisions</option>{candidateDivisions.map((item) => <option key={text(item,"divisionId")} value={text(item,"divisionId")}>{text(item,"name")}</option>)}</select></label>
        <label className="space-y-1 text-sm font-semibold"><span>State</span><select className={inputStyle} value={candidateFilters.stateId} onChange={(event) => setCandidateFilters((old) => ({ ...old, stateId: event.target.value }))}><option value="">All in your scope</option>{profile?.stateId && <option value={profile.stateId}>{profile.stateId}</option>}</select></label>
      </div>
      {setupPhase && <form onSubmit={submitCandidate} className="mb-6 grid gap-4 rounded-lg border bg-white p-6 sm:grid-cols-2">
        <h2 className="text-lg font-semibold sm:col-span-2">Create candidate</h2>
        {formField("candidateName", "Candidate name")}
        {!editingCandidate && selectField("chamber", "Chamber", [{ value: "house", label: "House" }, { value: "senate", label: "Senate" }])}
        {selectField("partyId", "Party", parties.map((v) => ({ value: text(v, "partyId"), label: text(v, "name") })))}
        {!editingCandidate && form.chamber === "house"
          ? selectField("divisionId", "Division", candidateDivisions.map((v) => ({ value: text(v, "divisionId"), label: text(v, "name") })))
          : form.chamber === "senate" && selectField("groupId", "Senate group", groups.map((v) => ({ value: text(v, "groupId"), label: text(v, "displayName") })))}
        {formField("ballotPosition", "Ballot position", "number")}
        <div className="flex gap-3 sm:col-span-2">
          <button disabled={busy} className={buttonSecondary}>{editingCandidate ? "Save candidate changes" : "Create candidate"}</button>
          {editingCandidate && <button type="button" className={buttonSecondary} onClick={() => { setEditingCandidate(null); setForm({}); }}>Cancel edit</button>}
        </div>
      </form>}
      {rowsTable([
        { key: "name", label: "Candidate" }, { key: "chamber", label: "Chamber" },
        { key: "divisionId", label: "Division" }, { key: "stateId", label: "State" },
        { key: "partyId", label: "Party" }, { key: "ballotPosition", label: "Position" },
        { key: "withdrawn", label: "Withdrawn", render: (row) => row.withdrawn === true ? "Yes" : "No" },
        { key: "actions", label: "Action", render: (row) => row.withdrawn === true ? "—" : <div className="flex gap-3">
          {setupPhase && <button disabled={busy} className="text-[#1f538d] underline" onClick={() => {
            setEditingCandidate(row);
            setForm({
              candidateName: text(row, "name"),
              partyId: text(row, "partyId"),
              chamber: text(row, "chamber"),
              divisionId: text(row, "divisionId"),
              groupId: text(row, "groupId"),
              ballotPosition: text(row, "ballotPosition"),
            });
          }}>Edit</button>}
          {["setup", "open"].includes(text((candidateOptions.election ?? {}) as Row, "status")) &&
            <button disabled={busy} className="text-red-800 underline" onClick={() => setPendingCandidate(row)}>Withdraw</button>}
        </div> },
      ], "No candidates match these filters.", filteredCandidates)}
      {pendingCandidate && <ConfirmModal title="Withdraw candidate" confirmLabel="Withdraw candidate" busy={busy} onCancel={() => setPendingCandidate(null)} onConfirm={(event) => {
        event.preventDefault();
        void run(() => sendJson(`/api/delegate/elections/${encodeURIComponent(electionId)}/candidates/${encodeURIComponent(text(pendingCandidate, "candidateId"))}/withdraw`, "POST", { reason: withdrawReason }), "Candidate withdrawn.");
        setPendingCandidate(null); setWithdrawReason("");
      }}>
        <p className="mb-3">Withdrawal does not delete the candidate. Provide a reason.</p>
        <textarea className={inputStyle} required maxLength={500} rows={4} value={withdrawReason} onChange={(event) => setWithdrawReason(event.target.value)} aria-label="Withdrawal reason" />
      </ConfirmModal>}
    </>;
  } else if (path?.endsWith("/admin/staff")) {
    content = <><PageHeading title="Staff accounts" />
      <form onSubmit={(event) => void submitStaffCreate(event)} className="mb-6 grid gap-4 rounded-lg border bg-white p-6 sm:grid-cols-2">
        <h2 className="text-lg font-semibold sm:col-span-2">{editingStaff ? "Edit staff account" : "Create staff account"}</h2>
        {formField("name", "Name")}{!editingStaff && formField("email", "Email", "email")}
        {!editingStaff && formField("password", "Password (min 12 characters)", "password")}
        {!editingStaff && formField("confirmPassword", "Confirm password", "password")}
        {selectField("role", "Role", [{ value:"aecEmployee",label:"AEC employee" },{ value:"commissionerDelegate",label:"Commissioner delegate" },{ value:"admin",label:"Admin" }])}
        {selectField("stateId", "State", ["ACT","NSW","NT","QLD","SA","TAS","VIC","WA"].map((v)=>({value:v,label:v})))}
        {editingStaff && <label className="flex items-center gap-2 text-sm font-semibold"><input type="checkbox" checked={form.active === "true"} onChange={(event) => setForm((old) => ({ ...old, active: String(event.target.checked) }))} />Active</label>}
        <div className="flex gap-3 sm:col-span-2"><button disabled={busy} className={buttonSecondary}>{editingStaff ? "Save changes" : "Create staff"}</button>{editingStaff && <button type="button" className={buttonSecondary} onClick={() => { setEditingStaff(null); setForm({}); }}>Cancel</button>}</div>
      </form>
      {rowsTable([
        { key: "name", label: "Name" }, { key: "role", label: "Role" }, { key: "stateId", label: "State" },
        { key: "active", label: "Status", render: (row) => <StatusBadge value={row.active ? "active" : "inactive"} /> },
        { key: "lastLoginAt", label: "Last login" },
        { key: "actions", label: "Action", render: (row) => <div className="flex gap-3">
          <button className="text-[#1f538d] underline" onClick={() => {
            setEditingStaff(row);
            setForm({ name: text(row, "name"), role: text(row, "role"), stateId: text(row, "stateId"), active: String(row.active === true) });
          }}>Edit</button>
          {row.active === true && <button disabled={busy} className="text-red-800 underline" onClick={() => setPendingStaff(row)}>Deactivate</button>}
        </div> },
      ])}
      {pendingStaff && <ConfirmModal title="Deactivate staff account" confirmLabel="Deactivate" busy={busy} onCancel={() => setPendingStaff(null)} onConfirm={submitStaffDeactivate}>
        <p className="mb-3">Type <strong>{text(pendingStaff, "name")}</strong> to confirm. Deactivation ends this account’s access.</p>
        <input className={inputStyle} required value={form.confirmName ?? ""} onChange={(event) => setForm((old) => ({ ...old, confirmName: event.target.value }))} aria-label="Type the staff member name" />
      </ConfirmModal>}
    </>;
  } else if (path?.endsWith("/admin/ip-whitelist")) {
    content = <><PageHeading title="IP allowlist" help="Use narrow CIDR ranges. Keep at least one active range that includes your current IP." />
      <Banner>Your current IP: {currentIp || "Loading..."}</Banner>
      <form onSubmit={(event) => void submitIpCreate(event)} className="mb-6 grid gap-4 rounded-lg border bg-white p-6 sm:grid-cols-2">
        {formField("label", editingIp ? "Location label" : "Location label")}{formField("cidr", "CIDR range")}
        <div className="flex gap-3 sm:col-span-2"><button disabled={busy} className={buttonSecondary}>{editingIp ? "Save IP range" : "Add IP range"}</button>{editingIp && <button type="button" className={buttonSecondary} onClick={() => { setEditingIp(null); setForm({}); }}>Cancel</button>}</div>
      </form>
      {rowsTable([
        { key: "label", label: "Label" }, { key: "cidr", label: "CIDR" },
        { key: "active", label: "Active", render: (row) => row.active ? "Active" : "Inactive" },
        { key: "actions", label: "Action", render: (row) => <div className="flex gap-3">
          <button className="text-[#1f538d] underline" onClick={() => { setEditingIp(row); setForm({ label:text(row,"label"), cidr:text(row,"cidr") }); }}>Edit</button>
          <button disabled={busy} className="text-[#1f538d] underline" onClick={() => {
            const active = row.active !== true;
            if (!active && !window.confirm("This may block your current IP. Continue?")) return;
            void run(() => sendJson(`/api/admin/ip-ranges/${encodeURIComponent(text(row,"locationId"))}`, "PATCH", {
              cidr:text(row,"cidr"), label:text(row,"label"), active, confirmLockout:!active,
            }), active ? "IP range activated." : "IP range deactivated.");
          }}>{row.active ? "Deactivate" : "Activate"}</button>
          <button disabled={busy} className="text-red-800 underline" onClick={() => {
            if (window.confirm("Delete this IP range? This may block your current IP.")) void run(() => apiRequest(`/api/admin/ip-ranges/${encodeURIComponent(text(row,"locationId"))}?confirmLockout=true`, { method:"DELETE" }), "IP range deleted.");
          }}>Delete</button>
        </div> },
      ])}
    </>;
  } else if (path?.endsWith("/admin/audit-log")) {
    content = <><PageHeading title="Audit log" help="Read-only audit records, newest first." />
      <form onSubmit={(event) => void submitAuditFilters(event)} className="mb-4 grid gap-3 rounded border bg-white p-4 sm:grid-cols-2 lg:grid-cols-4">
        {(["actorId","actorType","category","action","outcome","electionId","from","to"] as const).map((key) => (
          <label key={key} className="space-y-1 text-sm font-semibold"><span>{key === "from" || key === "to" ? `${key} time` : key}</span>
            <input className={inputStyle} type={key === "from" || key === "to" ? "datetime-local" : "text"} value={auditFilters[key]} onChange={(event) => setAuditFilters((old) => ({ ...old, [key]: event.target.value }))} />
          </label>
        ))}
        <button disabled={busy} className={buttonSecondary}>Apply filters</button>
      </form>
      <button type="button" disabled={busy} className={buttonSecondary} onClick={() => void run(async () => {
        const result = await apiRequest<Row>("/api/admin/audit-logs/verify");
        setVerification(result);
      }, "Audit chain verification complete.", false)}>Verify integrity</button>
      {verification && <Banner kind={verification.valid === true ? "success" : "error"}>
        {verification.valid === true ? `Valid chain (${text(verification, "checkedCount")} entries checked).` : `Integrity failure at ${text(verification, "firstBrokenLogId")}.`}
      </Banner>}
      {rowsTable([
        { key: "timestamp", label: "Time" }, { key: "actorId", label: "Actor" }, { key: "actorType", label: "Role" },
        { key: "action", label: "Action" }, { key: "targetId", label: "Target" },
        { key: "outcome", label: "Outcome", render: (row) => <StatusBadge value={text(row, "outcome")} /> },
        { key: "ipAddress", label: "IP address" },
        { key: "details", label: "Before / after", render: (row) => <details><summary className="cursor-pointer text-[#1f538d]">View details</summary><pre className="mt-2 max-w-md overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify({ before: row.before, after: row.after }, null, 2)}</pre></details> },
      ])}
      {nextCursor && <button type="button" disabled={busy} onClick={() => void loadMore()} className={`${buttonSecondary} mt-4`}>
        {busy ? "Loading..." : "Load more"}
      </button>}
    </>;
  } else if (path?.endsWith("/admin/elections")) {
    const transition: Record<string, string> = { setup:"open", open:"closed", closed:"counting", counting:"finalised" };
    content = <><PageHeading title="Elections" help="Phase changes are sequential and finalisation is irreversible." />
      <form onSubmit={(event) => void submitElectionCreate(event)} className="mb-6 grid gap-4 rounded-lg border bg-white p-6 sm:grid-cols-2">
        <h2 className="text-lg font-semibold sm:col-span-2">Create election</h2>
        {formField("name", "Election name")}{formField("timezone", "IANA timezone")}
        {formField("openAt", "Open at", "datetime-local")}{formField("closeAt", "Close at", "datetime-local")}
        <button disabled={busy} className={`${buttonSecondary} sm:col-span-2`}>Create election</button>
      </form>
      {rowsTable([
        { key: "name", label: "Election" }, { key: "status", label: "Phase", render: (row) => <StatusBadge value={text(row,"status")} /> },
        { key: "openAt", label: "Opens" }, { key: "closeAt", label: "Closes" },
        { key: "phase", label: "Next phase", render: (row) => {
          const next = transition[text(row, "status")];
          return next ? <button className="text-[#1f538d] underline" disabled={busy} onClick={() => {
            setPhaseElection(row); setPhaseTarget(next); setPhaseName("");
          }}>Advance to {next}</button> : "Finalised";
        } },
      ])}
      {phaseElection && <ConfirmModal title={`Advance election to ${phaseTarget}`} confirmLabel="Advance phase" busy={busy} onCancel={() => setPhaseElection(null)} onConfirm={(event) => void submitPhase(event)}>
        <p className="mb-3 text-sm text-red-800">This transition cannot be reversed. Type the election name to confirm.</p>
        <input className={inputStyle} ref={(element) => element?.focus()} required value={phaseName} onChange={(event) => setPhaseName(event.target.value)} aria-label="Election name confirmation" />
        <p className="mt-2 text-sm text-slate-600">Election: {text(phaseElection, "name")}</p>
      </ConfirmModal>}
    </>;
  } else {
    content = <PageHeading title="Staff dashboard" help="This staff function is unavailable." />;
  }

  return <main>{error && <div className="mb-4"><Banner kind="error">{error}</Banner></div>}{notice && <div className="mb-4"><Banner kind="success">{notice}</Banner></div>}{content}</main>;
}