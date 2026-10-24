import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from firebase_admin import auth
from google.cloud import firestore

from backend.approvals import (
    APPROVED, REJECTED, approval_reason, assert_no_pending, decision, list_requests,
    load_reviewable, new_request,
)
from backend.audit import write_audit
from backend.auth import staff_access
from backend.firestore_client import db
from backend.models import ChangeRequestRejection, StaffCreate, StaffEdit
from backend.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/staff", tags=["admin-staff"])
admin_access = staff_access("admin")


def _requests() -> Any:
    return db.collection("staffChangeRequests")


def _assert_edit_allowed(tx: Any, staff_id: str, before: dict[str, Any], changes: dict[str, Any],
                         requester_id: str) -> None:
    becoming_inactive = changes.get("active") is False
    demoted = changes.get("role") is not None and changes["role"] != "admin"
    if staff_id == requester_id and (becoming_inactive or demoted):
        raise HTTPException(status_code=409, detail="You cannot deactivate or demote yourself")
    if before.get("role") == "admin" and before.get("active") and (becoming_inactive or demoted):
        active_admins = list(
            db.collection("staff").where("role", "==", "admin").where("active", "==", True).stream(transaction=tx)
        )
        if len(active_admins) <= 1:
            raise HTTPException(status_code=409, detail="The last active admin cannot be removed")


def _assert_deactivation_allowed(tx: Any, before: dict[str, Any]) -> None:
    if before.get("active") is not True:
        raise HTTPException(status_code=409, detail="Staff account is already inactive")
    if before.get("role") == "admin":
        admins = list(db.collection("staff").where("role", "==", "admin").where("active", "==", True)
                      .stream(transaction=tx))
        if len(admins) <= 1:
            raise HTTPException(status_code=409, detail="The last active admin cannot be removed")


@router.get("")
def list_staff(staff: dict[str, Any] = Depends(admin_access)) -> list[dict[str, Any]]:
    rows = []
    for item in db.collection("staff").stream():
        # DocumentSnapshot.get() raises KeyError for missing fields (e.g. lastLoginAt
        # before a new account's first login), so read from the dict instead.
        data = item.to_dict() or {}
        rows.append({
            "staffId": item.id,
            "name": data.get("name"),
            "role": data.get("role"),
            "stateId": data.get("stateId"),
            "active": data.get("active"),
            "lastLoginAt": data.get("lastLoginAt"),
        })
    return rows


@router.post("", status_code=202)
@limiter.limit("3/hour")
def create_staff(
    body: StaffCreate,
    request: Request,
    staff: dict[str, Any] = Depends(admin_access),
) -> dict[str, str]:
    """Submit a new staff account for approval by another admin.

    The sign-in account is created disabled so the password is never stored in
    Firestore; approval enables it and rejection deletes it.
    """
    email = body.email.strip().lower()
    try:
        user = auth.create_user(email=email, password=body.password, disabled=True)
        staff_ref = db.collection("staff").document()
        request_ref = _requests().document()
        transaction = db.transaction()

        @firestore.transactional
        def submit(tx: Any) -> None:
            proposed = {"name": body.name.strip(), "role": body.role, "stateId": body.stateId}
            write_audit(
                tx, actor=staff, action="staff.create.request", category="admin",
                target_type="staff", target_id=staff_ref.id, target_path=staff_ref.path,
                before=None, after=proposed, outcome="success", reason=None, request=request,
            )
            tx.create(request_ref, new_request(
                action="staff.create", target_type="staff", target_id=staff_ref.id,
                target_path=staff_ref.path,
                summary=f"Create {body.role} account for {proposed['name']}",
                payload={**proposed, "email": email, "authUid": user.uid}, before=None, staff=staff,
            ))

        submit(transaction)
        return {"requestId": request_ref.id, "staffId": staff_ref.id, "status": "pending",
                "message": "Staff account submitted for approval by another admin."}
    except auth.EmailAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
    except Exception as exc:
        logger.exception("Staff account creation request failed")
        if "user" in locals():
            try:
                auth.delete_user(user.uid)
            except Exception:
                logger.exception("Unable to clean up incomplete staff auth account")
        raise HTTPException(status_code=400, detail="Unable to submit staff account for approval") from exc


@router.patch("/{staff_id}", status_code=202)
def edit_staff(
    staff_id: str,
    body: StaffEdit,
    request: Request,
    staff: dict[str, Any] = Depends(admin_access),
) -> dict[str, str]:
    """Submit staff account changes for approval by another admin."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="No changes supplied")
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    target_ref = db.collection("staff").document(staff_id)
    request_ref = _requests().document()
    transaction = db.transaction()

    @firestore.transactional
    def submit(tx: Any) -> None:
        snapshot = target_ref.get(transaction=tx)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Staff account not found")
        before = snapshot.to_dict() or {}
        _assert_edit_allowed(tx, staff_id, before, changes, staff["staffId"])
        assert_no_pending(_requests(), staff_id, tx)
        before_fields = {key: before.get(key) for key in changes if key in before}
        write_audit(
            tx, actor=staff, action="staff.edit.request", category="admin",
            target_type="staff", target_id=staff_id, target_path=target_ref.path,
            before=before_fields, after=changes, outcome="success", reason=None, request=request,
        )
        tx.create(request_ref, new_request(
            action="staff.edit", target_type="staff", target_id=staff_id, target_path=target_ref.path,
            summary=f"Edit staff account {before.get('name')}", payload={"changes": changes},
            before=before_fields, staff=staff,
        ))

    try:
        submit(transaction)
        return {"requestId": request_ref.id, "status": "pending"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Staff account update request failed")
        raise HTTPException(status_code=400, detail="Unable to submit staff changes for approval") from exc


@router.delete("/{staff_id}", status_code=202)
def deactivate_staff(
    staff_id: str,
    request: Request,
    staff: dict[str, Any] = Depends(admin_access),
) -> dict[str, str]:
    """Submit a staff deactivation for approval by another admin."""
    if staff_id == staff["staffId"]:
        raise HTTPException(status_code=409, detail="You cannot deactivate yourself")
    target_ref = db.collection("staff").document(staff_id)
    request_ref = _requests().document()
    transaction = db.transaction()

    @firestore.transactional
    def submit(tx: Any) -> None:
        snapshot = target_ref.get(transaction=tx)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Staff account not found")
        before = snapshot.to_dict() or {}
        _assert_deactivation_allowed(tx, before)
        assert_no_pending(_requests(), staff_id, tx)
        write_audit(
            tx, actor=staff, action="staff.delete.request", category="admin",
            target_type="staff", target_id=staff_id, target_path=target_ref.path,
            before={"active": True, "role": before.get("role")}, after={"active": False},
            outcome="success", reason=None, request=request,
        )
        tx.create(request_ref, new_request(
            action="staff.delete", target_type="staff", target_id=staff_id, target_path=target_ref.path,
            summary=f"Deactivate staff account {before.get('name')}", payload={},
            before={"active": True, "role": before.get("role")}, staff=staff,
        ))

    try:
        submit(transaction)
        return {"requestId": request_ref.id, "status": "pending"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Staff deactivation request failed")
        raise HTTPException(status_code=400, detail="Unable to submit deactivation for approval") from exc


@router.get("/change-requests")
def list_change_requests(staff: dict[str, Any] = Depends(admin_access)) -> dict[str, list[dict[str, Any]]]:
    return list_requests(_requests())


@router.post("/change-requests/{request_id}/approve")
def approve_change_request(
    request_id: str,
    request: Request,
    staff: dict[str, Any] = Depends(admin_access),
) -> dict[str, bool]:
    """Apply a staff account change that another admin requested."""
    request_ref = _requests().document(request_id)
    transaction = db.transaction()
    uid_to_enable: str | None = None
    uid_to_disable: str | None = None
    uid_to_revoke: str | None = None
    reactivation: bool | None = None

    @firestore.transactional
    def approve(tx: Any) -> None:
        nonlocal uid_to_enable, uid_to_disable, uid_to_revoke, reactivation
        # The transaction function can be retried, so start each attempt clean.
        uid_to_enable = uid_to_disable = uid_to_revoke = reactivation = None
        change = load_reviewable(request_ref, staff, tx)
        action, requester, staff_id = change.get("action"), change["requestedBy"], change["targetId"]
        payload = change.get("payload") or {}
        target_ref = db.collection("staff").document(staff_id)
        now = firestore.SERVER_TIMESTAMP

        if action == "staff.create":
            data = {
                "authUid": payload["authUid"], "name": payload["name"], "role": payload["role"],
                "stateId": payload["stateId"], "active": True, "createdBy": requester,
                "createdAt": now, "updatedBy": requester, "updatedAt": now,
                "deactivatedAt": None, "deactivatedBy": None,
            }
            audit_before = None
            audit_after = {"name": data["name"], "role": data["role"], "stateId": data["stateId"]}
            write = ("create", data)
            uid_to_enable = payload["authUid"]
        elif action in {"staff.edit", "staff.delete"}:
            snapshot = target_ref.get(transaction=tx)
            if not snapshot.exists:
                raise HTTPException(status_code=404, detail="Staff account not found")
            before = snapshot.to_dict() or {}
            if action == "staff.edit":
                changes = dict(payload["changes"])
                _assert_edit_allowed(tx, staff_id, before, changes, requester)
                demoted = changes.get("role") is not None and changes["role"] != "admin"
                changes.update({"updatedBy": requester, "updatedAt": now})
                if changes.get("active") is False:
                    changes.update({"deactivatedAt": now, "deactivatedBy": requester})
                if demoted or "active" in changes:
                    uid_to_revoke = before.get("authUid")
                if "active" in changes:
                    reactivation = changes["active"] is True
                audit_before = {key: before.get(key) for key in changes if key in before}
                audit_after = {key: value for key, value in changes.items() if key != "updatedAt"}
                write = ("update", changes)
            else:
                if staff_id == requester:
                    raise HTTPException(status_code=409, detail="You cannot deactivate yourself")
                _assert_deactivation_allowed(tx, before)
                uid_to_disable = before.get("authUid")
                audit_before = {"active": True, "role": before.get("role")}
                audit_after = {"active": False}
                write = ("update", {
                    "active": False, "deactivatedAt": now, "deactivatedBy": requester,
                    "updatedBy": requester, "updatedAt": now,
                })
        else:
            raise HTTPException(status_code=409, detail="Unsupported change request")

        write_audit(
            tx, actor=staff, action=action, category="admin",
            target_type="staff", target_id=staff_id, target_path=target_ref.path,
            before=audit_before, after=audit_after, outcome="success",
            reason=approval_reason(request_id, requester), request=request,
        )
        if write[0] == "create":
            tx.create(target_ref, write[1])
        else:
            tx.update(target_ref, write[1])
        tx.update(request_ref, decision(APPROVED, staff, None))

    try:
        approve(transaction)
        # Firebase Auth cannot join the Firestore transaction. If one of these calls fails after the
        # commit, the staff record is already correct; an edit to the account's `active` flag re-syncs it.
        if uid_to_enable:
            auth.update_user(uid_to_enable, disabled=False)
        if uid_to_revoke:
            auth.revoke_refresh_tokens(uid_to_revoke)
            if reactivation is not None:
                auth.update_user(uid_to_revoke, disabled=not reactivation)
        if uid_to_disable:
            auth.update_user(uid_to_disable, disabled=True)
            auth.revoke_refresh_tokens(uid_to_disable)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Staff change approval failed")
        raise HTTPException(status_code=400, detail="Unable to approve change request") from exc


@router.post("/change-requests/{request_id}/reject")
def reject_change_request(
    request_id: str,
    body: ChangeRequestRejection,
    request: Request,
    staff: dict[str, Any] = Depends(admin_access),
) -> dict[str, bool]:
    request_ref = _requests().document(request_id)
    transaction = db.transaction()
    orphan_uid: str | None = None

    @firestore.transactional
    def reject(tx: Any) -> None:
        nonlocal orphan_uid
        change = load_reviewable(request_ref, staff, tx)
        if change.get("action") == "staff.create":
            orphan_uid = (change.get("payload") or {}).get("authUid")
        write_audit(
            tx, actor=staff, action=f"{change.get('action')}.reject", category="admin",
            target_type="staff", target_id=change.get("targetId"), target_path=change.get("targetPath"),
            before={"status": "pending"}, after={"status": "rejected"}, outcome="success",
            reason=body.reason.strip(), request=request,
        )
        tx.update(request_ref, decision(REJECTED, staff, body.reason.strip()))

    try:
        reject(transaction)
        if orphan_uid:
            try:
                auth.delete_user(orphan_uid)
            except Exception:
                # The decision is recorded and the leftover sign-in account stays disabled.
                logger.exception("Unable to delete the sign-in account of a rejected staff request")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Staff change rejection failed")
        raise HTTPException(status_code=400, detail="Unable to reject change request") from exc
