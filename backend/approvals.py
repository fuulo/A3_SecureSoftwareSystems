"""Shared helpers for change requests that a second person must approve.

Delegates (candidate changes) and admins (staff account changes) never apply
their own changes. They submit a change request, and a different staff member
approves or rejects it. Requests live in
``elections/{electionId}/candidateChangeRequests`` and ``staffChangeRequests``.
"""
from typing import Any

from fastapi import HTTPException
from google.cloud import firestore

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
RECENT_LIMIT = 20
PENDING_LIMIT = 100


def new_request(*, action: str, target_type: str, target_id: str | None, target_path: str | None,
                summary: str, payload: dict[str, Any], before: dict[str, Any] | None,
                staff: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "action": action, "status": PENDING, "targetType": target_type,
        "targetId": target_id, "targetPath": target_path, "summary": summary,
        "payload": payload, "before": before,
        "requestedBy": staff["staffId"], "requestedByName": staff.get("name"),
        "requestedAt": firestore.SERVER_TIMESTAMP,
        "reviewedBy": None, "reviewedByName": None, "reviewedAt": None, "reviewReason": None,
        **extra,
    }


def assert_no_pending(requests_ref: Any, target_id: str | None, tx: Any) -> None:
    """One undecided request per target, so approvals can never be applied out of order."""
    if target_id is None:
        return
    query = requests_ref.where("status", "==", PENDING).where("targetId", "==", target_id).limit(1)
    if list(query.stream(transaction=tx)):
        raise HTTPException(status_code=409, detail="A change to this record is already awaiting approval")


def load_reviewable(request_ref: Any, reviewer: dict[str, Any], tx: Any,
                    *, scope_state: bool = False) -> dict[str, Any]:
    """Read a request and enforce the four-eyes rules for the reviewer."""
    snapshot = request_ref.get(transaction=tx)
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Change request not found")
    change = snapshot.to_dict() or {}
    if scope_state and change.get("stateId") != reviewer.get("stateId"):
        raise HTTPException(status_code=403, detail="Change request is outside your state")
    if change.get("requestedBy") == reviewer["staffId"]:
        raise HTTPException(status_code=403, detail="You cannot review your own change request")
    if change.get("status") != PENDING:
        raise HTTPException(status_code=409, detail="Change request has already been decided")
    return change


def approval_reason(request_id: str, requester_id: str, note: str | None = None) -> str:
    text = f"Approved change request {request_id} (requested by {requester_id})"
    return f"{note}; {text}" if note else text


def decision(status: str, reviewer: dict[str, Any], reason: str | None) -> dict[str, Any]:
    return {
        "status": status, "reviewedBy": reviewer["staffId"], "reviewedByName": reviewer.get("name"),
        "reviewedAt": firestore.SERVER_TIMESTAMP, "reviewReason": reason,
    }


def list_requests(requests_ref: Any, **equals: str) -> dict[str, list[dict[str, Any]]]:
    """Pending requests plus the most recent decided ones, newest first."""
    def fetch(query: Any, limit: int) -> list[dict[str, Any]]:
        for field, value in equals.items():
            query = query.where(field, "==", value)
        return [{"requestId": item.id, **(item.to_dict() or {})}
                for item in query.order_by("requestedAt", direction=firestore.Query.DESCENDING)
                .limit(limit).stream()]

    return {
        "pending": fetch(requests_ref.where("status", "==", PENDING), PENDING_LIMIT),
        "recent": fetch(requests_ref.where("status", "in", [APPROVED, REJECTED]), RECENT_LIMIT),
    }
