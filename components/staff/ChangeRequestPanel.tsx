"use client";

import { FormEvent, useState } from "react";
import { ChangeRequest, ChangeRequestList } from "@/lib/api";
import { ConfirmModal } from "@/components/staff/ConfirmModal";
import { DataTable } from "@/components/staff/DataTable";
import { StatusBadge } from "@/components/staff/StatusBadge";

const inputStyle = "w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]";
const buttonSecondary = "rounded border border-slate-300 px-3 py-2 text-sm font-semibold text-[#1f538d] hover:bg-slate-50 disabled:opacity-50";

function when(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function who(name?: string | null, id?: string | null) {
  return name || id || "—";
}

function Details({ request }: { request: ChangeRequest }) {
  return (
    <details>
      <summary className="cursor-pointer text-[#1f538d]">View details</summary>
      <pre className="mt-2 max-w-md overflow-auto whitespace-pre-wrap text-xs">
        {JSON.stringify({ current: request.before, proposed: request.payload },
          (key, value) => (key === "authUid" ? undefined : value), 2)}
      </pre>
    </details>
  );
}

// Lists change requests that need a second person's approval. The API enforces who may decide;
// hiding the buttons on a person's own requests is only a convenience.
export function ChangeRequestPanel({
  title,
  reviewerLabel,
  requests,
  currentStaffId,
  busy,
  loading,
  onApprove,
  onReject,
}: {
  title: string;
  reviewerLabel: string;
  requests: ChangeRequestList;
  currentStaffId: string;
  busy: boolean;
  loading: boolean;
  onApprove: (request: ChangeRequest) => Promise<void>;
  onReject: (request: ChangeRequest, reason: string) => Promise<void>;
}) {
  const [approving, setApproving] = useState<ChangeRequest | null>(null);
  const [rejecting, setRejecting] = useState<ChangeRequest | null>(null);
  const [reason, setReason] = useState("");

  const submitApprove = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!approving) return;
    await onApprove(approving);
    setApproving(null);
  };

  const submitReject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!rejecting) return;
    await onReject(rejecting, reason.trim());
    setRejecting(null);
    setReason("");
  };

  if (loading) return <p role="status" className="py-6 text-slate-600">Loading change requests...</p>;

  return (
    <section aria-label={title} className="mt-8">
      <h2 className="mb-1 text-xl font-semibold">{title}</h2>
      <p className="mb-3 text-sm text-slate-600">
        Changes take effect only after {reviewerLabel} approves them. You cannot approve your own requests.
      </p>
      <DataTable<ChangeRequest>
        emptyMessage="No changes are awaiting approval."
        rows={requests.pending}
        columns={[
          { key: "requestedAt", label: "Submitted", render: (row) => when(row.requestedAt) },
          { key: "summary", label: "Change" },
          { key: "requestedBy", label: "Requested by", render: (row) => who(row.requestedByName, row.requestedBy) },
          { key: "details", label: "Details", render: (row) => <Details request={row} /> },
          { key: "actions", label: "Review", render: (row) => row.requestedBy === currentStaffId
            ? <span className="text-slate-600">Awaiting {reviewerLabel}</span>
            : <div className="flex gap-2">
              <button type="button" disabled={busy} onClick={() => setApproving(row)} className={buttonSecondary}>Approve</button>
              <button type="button" disabled={busy} onClick={() => setRejecting(row)} className="rounded border border-red-300 px-3 py-2 text-sm text-red-800 disabled:opacity-50">Reject</button>
            </div> },
        ]}
      />
      {requests.recent.length > 0 && <>
        <h3 className="mb-3 mt-6 text-lg font-semibold">Recently decided</h3>
        <DataTable<ChangeRequest>
          rows={requests.recent}
          columns={[
            { key: "summary", label: "Change" },
            { key: "requestedBy", label: "Requested by", render: (row) => who(row.requestedByName, row.requestedBy) },
            { key: "status", label: "Decision", render: (row) => <StatusBadge value={row.status} /> },
            { key: "reviewedBy", label: "Decided by", render: (row) => who(row.reviewedByName, row.reviewedBy) },
            { key: "reviewedAt", label: "Decided", render: (row) => when(row.reviewedAt) },
            { key: "reviewReason", label: "Reason" },
          ]}
        />
      </>}
      {approving && <ConfirmModal title="Approve change" confirmLabel="Approve and apply" busy={busy}
        onCancel={() => setApproving(null)} onConfirm={(event) => void submitApprove(event)}>
        <p>Approve “{approving.summary}”, requested by {who(approving.requestedByName, approving.requestedBy)}? It takes effect immediately.</p>
      </ConfirmModal>}
      {rejecting && <ConfirmModal title="Reject change" confirmLabel="Reject change" busy={busy}
        onCancel={() => { setRejecting(null); setReason(""); }} onConfirm={(event) => void submitReject(event)}>
        <p className="mb-3">Enter a reason for rejecting “{rejecting.summary}”. Nothing will be changed.</p>
        <textarea className={inputStyle} required maxLength={500} rows={4} value={reason}
          onChange={(event) => setReason(event.target.value)} aria-label="Reason for rejection" />
      </ConfirmModal>}
    </section>
  );
}
