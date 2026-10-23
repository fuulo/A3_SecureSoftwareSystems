import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from firebase_admin import auth
from google.cloud import firestore

from backend.audit import write_audit
from backend.auth import staff_access
from backend.firestore_client import db
from backend.models import StaffCreate, StaffEdit
from backend.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/staff", tags=["admin-staff"])
admin_access = staff_access("admin")


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


@router.post("", status_code=201)
@limiter.limit("3/hour")
def create_staff(
    body: StaffCreate,
    request: Request,
    staff: dict[str, Any] = Depends(admin_access),
) -> dict[str, str]:
    email = body.email.strip().lower()
    try:
        user = auth.create_user(email=email, password=body.password)
        staff_ref = db.collection("staff").document()
        transaction = db.transaction()

        @firestore.transactional
        def create(tx: Any) -> None:
            now = firestore.SERVER_TIMESTAMP
            data = {
                "authUid": user.uid, "name": body.name.strip(), "role": body.role,
                "stateId": body.stateId, "active": True, "createdBy": staff["staffId"],
                "createdAt": now, "updatedBy": staff["staffId"], "updatedAt": now,
                "deactivatedAt": None, "deactivatedBy": None,
            }
            write_audit(
                tx, actor=staff, action="staff.create", category="admin",
                target_type="staff", target_id=staff_ref.id, target_path=staff_ref.path,
                before=None, after={"name": data["name"], "role": body.role, "stateId": body.stateId},
                outcome="success", reason=None, request=request,
            )
            tx.create(staff_ref, data)

        create(transaction)
        return {"staffId": staff_ref.id, "message": "Staff account created."}
    except auth.EmailAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
    except Exception as exc:
        logger.exception("Staff account creation failed")
        if "user" in locals():
            try:
                auth.delete_user(user.uid)
            except Exception:
                logger.exception("Unable to clean up incomplete staff auth account")
        raise HTTPException(status_code=400, detail="Unable to create staff account") from exc


@router.patch("/{staff_id}")
def edit_staff(
    staff_id: str,
    body: StaffEdit,
    request: Request,
    staff: dict[str, Any] = Depends(admin_access),
) -> dict[str, bool]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="No changes supplied")
    target_ref = db.collection("staff").document(staff_id)
    transaction = db.transaction()
    uid_to_revoke: str | None = None

    @firestore.transactional
    def update(tx: Any) -> None:
        nonlocal uid_to_revoke
        snapshot = target_ref.get(transaction=tx)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Staff account not found")
        before = snapshot.to_dict() or {}
        becoming_inactive = changes.get("active") is False
        demoted = changes.get("role") is not None and changes["role"] != "admin"
        if staff_id == staff["staffId"] and (becoming_inactive or demoted):
            raise HTTPException(status_code=409, detail="You cannot deactivate or demote yourself")
        if before.get("role") == "admin" and before.get("active") and (becoming_inactive or demoted):
            active_admins = list(
                db.collection("staff").where("role", "==", "admin").where("active", "==", True).stream(transaction=tx)
            )
            if len(active_admins) <= 1:
                raise HTTPException(status_code=409, detail="The last active admin cannot be removed")
        if "name" in changes:
            changes["name"] = changes["name"].strip()
        changes.update({"updatedBy": staff["staffId"], "updatedAt": firestore.SERVER_TIMESTAMP})
        if becoming_inactive:
            changes.update({"deactivatedAt": firestore.SERVER_TIMESTAMP, "deactivatedBy": staff["staffId"]})
        uid_to_revoke = before.get("authUid") if demoted or "active" in changes else None
        audit_after = {key: value for key, value in changes.items() if key not in {"updatedAt"}}
        write_audit(
            tx, actor=staff, action="staff.edit", category="admin",
            target_type="staff", target_id=staff_id, target_path=target_ref.path,
            before={key: before.get(key) for key in changes if key in before},
            after=audit_after, outcome="success", reason=None, request=request,
        )
        tx.update(target_ref, changes)

    try:
        update(transaction)
        if uid_to_revoke:
            auth.revoke_refresh_tokens(uid_to_revoke)
            if "active" in changes:
                auth.update_user(uid_to_revoke, disabled=changes["active"] is False)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Staff account update failed")
        raise HTTPException(status_code=400, detail="Unable to update staff account") from exc


@router.delete("/{staff_id}")
def deactivate_staff(
    staff_id: str,
    request: Request,
    staff: dict[str, Any] = Depends(admin_access),
) -> dict[str, bool]:
    if staff_id == staff["staffId"]:
        raise HTTPException(status_code=409, detail="You cannot deactivate yourself")
    target_ref = db.collection("staff").document(staff_id)
    transaction = db.transaction()
    target_uid: str | None = None

    @firestore.transactional
    def deactivate(tx: Any) -> None:
        nonlocal target_uid
        snapshot = target_ref.get(transaction=tx)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Staff account not found")
        before = snapshot.to_dict() or {}
        if before.get("active") is not True:
            raise HTTPException(status_code=409, detail="Staff account is already inactive")
        if before.get("role") == "admin":
            admins = list(db.collection("staff").where("role", "==", "admin").where("active", "==", True).stream(transaction=tx))
            if len(admins) <= 1:
                raise HTTPException(status_code=409, detail="The last active admin cannot be removed")
        target_uid = before.get("authUid")
        after = {
            "active": False, "deactivatedAt": firestore.SERVER_TIMESTAMP,
            "deactivatedBy": staff["staffId"], "updatedBy": staff["staffId"],
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
        write_audit(
            tx, actor=staff, action="staff.delete", category="admin",
            target_type="staff", target_id=staff_id, target_path=target_ref.path,
            before={"active": True, "role": before.get("role")},
            after={"active": False}, outcome="success", reason=None, request=request,
        )
        tx.update(target_ref, after)

    try:
        deactivate(transaction)
        if target_uid:
            auth.update_user(target_uid, disabled=True)
            auth.revoke_refresh_tokens(target_uid)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Staff deactivation failed")
        raise HTTPException(status_code=400, detail="Unable to deactivate staff account") from exc