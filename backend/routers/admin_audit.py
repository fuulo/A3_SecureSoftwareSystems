from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from google.cloud import firestore

from backend.audit import write_audit
from backend.auth import staff_access
from backend.firestore_client import db

router = APIRouter(prefix="/api/admin/audit-logs", tags=["admin-audit"])
admin_access = staff_access("admin")


@router.get("")
def list_audit_logs(request: Request, actorId: str | None = None,
                    actorType: str | None = None, category: str | None = None,
                    action: str | None = None, outcome: str | None = None,
                    electionId: str | None = None, from_: str | None = Query(default=None, alias="from"),
                    to: str | None = None, limit: int = 50,
                    cursor: str | None = None,
                    staff: dict[str, Any] = Depends(admin_access)) -> dict[str, Any]:
    limit = min(max(limit, 1), 100)
    query: Any = db.collection("auditLogs")
    filters = [("actorId", actorId), ("actorType", actorType), ("category", category),
               ("action", action), ("outcome", outcome), ("electionId", electionId)]
    for field, value in filters:
        if value is not None:
            query = query.where(field, "==", value)
    try:
        if from_:
            query = query.where("timestamp", ">=", datetime.fromisoformat(from_.replace("Z", "+00:00")))
        if to:
            query = query.where("timestamp", "<=", datetime.fromisoformat(to.replace("Z", "+00:00")))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid audit date filter") from exc
    query = query.order_by("timestamp", direction=firestore.Query.DESCENDING)
    if cursor:
        snapshot = db.collection("auditLogs").document(cursor).get()
        if snapshot.exists:
            query = query.start_after(snapshot)
    records = list(query.limit(limit + 1).stream())
    has_more = len(records) > limit
    records = records[:limit]
    session = request.headers.get("x-session-id") or staff["staffId"]
    import hashlib
    throttle_id = hashlib.sha256(f'{staff["staffId"]}:{session}'.encode()).hexdigest()
    throttle_ref = db.collection("auditMeta").document("viewSessions").collection("sessions").document(throttle_id)
    transaction = db.transaction()

    @firestore.transactional
    def record_view(tx: Any) -> None:
        previous = throttle_ref.get(transaction=tx)
        now = datetime.now().astimezone()
        last_view = previous.get("lastViewedAt") if previous.exists else None
        if not last_view or (now - last_view).total_seconds() >= 60:
            write_audit(tx, actor=staff, action="auditLog.view", category="security",
                        target_type="auditLog", target_id=None, target_path="auditLogs",
                        before=None, after={"count": len(records)}, outcome="success",
                        reason=None, request=request)
            tx.set(throttle_ref, {"lastViewedAt": now})
    record_view(transaction)
    return {
        "items": [{"id": item.id, **(item.to_dict() or {})} for item in records],
        "nextCursor": records[-1].id if has_more and records else None,
    }


@router.get("/verify")
def verify_audit_chain(staff: dict[str, Any] = Depends(admin_access)) -> dict[str, Any]:
    import hashlib
    import json

    previous_hash = ""
    checked = 0
    first_broken = None
    last_log_id = None
    query = db.collection("auditLogs").order_by("seq")
    cursor = None
    while True:
        page = query.start_after(cursor).limit(500).stream() if cursor else query.limit(500).stream()
        page_items = list(page)
        if not page_items:
            break
        for snapshot in page_items:
            entry = snapshot.to_dict() or {}
            stored_hash = entry.pop("hash", None)
            if entry.get("previousHash", "") != previous_hash:
                first_broken = snapshot.id
                break
            canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
            expected = hashlib.sha256((previous_hash + canonical).encode("utf-8")).hexdigest()
            if stored_hash != expected:
                first_broken = snapshot.id
                break
            previous_hash = stored_hash
            checked += 1
            last_log_id = snapshot.id
        if first_broken or len(page_items) < 500:
            break
        cursor = page_items[-1]
    head = db.collection("auditMeta").document("head").get()
    if first_broken is None and checked and not head.exists:
        first_broken = "auditMeta/head"
    if first_broken is None and head.exists:
        head_data = head.to_dict() or {}
        if (head_data.get("seq", 0) != checked or
                head_data.get("lastHash", "") != previous_hash or
                head_data.get("lastLogId") != last_log_id):
            first_broken = head_data.get("lastLogId") or "auditMeta/head"
    return {"valid": first_broken is None, "checkedCount": checked, "firstBrokenLogId": first_broken}
