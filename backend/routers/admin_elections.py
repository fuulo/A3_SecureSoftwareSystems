import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from google.cloud import firestore

from backend.audit import write_audit
from backend.auth import staff_access
from backend.firestore_client import db
from backend.models import ElectionCreate, PhaseChange

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/elections", tags=["admin-elections"])
admin_access = staff_access("admin")
TRANSITIONS = {"setup": "open", "open": "closed", "closed": "counting", "counting": "finalised"}


@router.get("")
def list_elections(staff: dict[str, Any] = Depends(admin_access)) -> list[dict[str, Any]]:
    return [{"electionId": item.id, **(item.to_dict() or {})} for item in db.collection("elections").stream()]


@router.post("", status_code=201)
def create_election(body: ElectionCreate, request: Request,
                    staff: dict[str, Any] = Depends(admin_access)) -> dict[str, str]:
    try:
        timezone = ZoneInfo(body.timezone)
        open_at = datetime.fromisoformat(body.openAt.replace("Z", "+00:00"))
        close_at = datetime.fromisoformat(body.closeAt.replace("Z", "+00:00"))
        if open_at.tzinfo is None:
            open_at = open_at.replace(tzinfo=timezone)
        if close_at.tzinfo is None:
            close_at = close_at.replace(tzinfo=timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(status_code=422, detail="Election date or timezone is invalid") from exc
    if close_at <= open_at:
        raise HTTPException(status_code=422, detail="Election close time must follow open time")
    election_ref = db.collection("elections").document()
    transaction = db.transaction()

    @firestore.transactional
    def create(tx: Any) -> None:
        existing = list(db.collection("elections").where("name", "==", body.name.strip()).limit(1).stream(transaction=tx))
        if existing:
            raise HTTPException(status_code=409, detail="Election name already exists")
        data = {"name": body.name.strip(), "type": body.type, "status": "setup",
                "openAt": open_at, "closeAt": close_at, "timezone": body.timezone,
                "createdBy": staff["staffId"], "createdAt": firestore.SERVER_TIMESTAMP,
                "updatedBy": staff["staffId"], "updatedAt": firestore.SERVER_TIMESTAMP}
        write_audit(tx, actor=staff, action="election.create", category="admin",
                    target_type="election", target_id=election_ref.id, target_path=election_ref.path,
                    before=None, after={"name": data["name"], "status": "setup"},
                    outcome="success", reason=None, request=request)
        tx.create(election_ref, data)

    try:
        create(transaction)
        return {"electionId": election_ref.id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Election creation failed")
        raise HTTPException(status_code=400, detail="Unable to create election") from exc


def _phase_requirements(tx: Any, election_id: str, election: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    election_ref = db.collection("elections").document(election_id)
    if not list(election_ref.collection("divisions").limit(1).stream(transaction=tx)):
        missing.append("At least one division is required")
    if not list(election_ref.collection("senateRegions").limit(1).stream(transaction=tx)):
        missing.append("At least one senate region is required")
    divisions = list(election_ref.collection("divisions").stream(transaction=tx))
    candidates = list(election_ref.collection("candidates").where("chamber", "==", "house").stream(transaction=tx))
    covered = {candidate.get("divisionId") for candidate in candidates if not candidate.get("withdrawn") and not candidate.get("excluded")}
    if any(division.id not in covered for division in divisions):
        missing.append("Every division needs a non-withdrawn candidate")
    open_at = election.get("openAt")
    if isinstance(open_at, datetime) and open_at.timestamp() < datetime.now(timezone.utc).timestamp() - 86400:
        missing.append("Election opening time is too far in the past")
    opened = list(db.collection("elections").where("status", "==", "open").limit(2).stream(transaction=tx))
    if any(item.id != election_id for item in opened):
        missing.append("Another election is already open")
    return missing


@router.post("/{election_id}/phase")
def change_phase(election_id: str, body: PhaseChange, request: Request,
                 staff: dict[str, Any] = Depends(admin_access)) -> dict[str, str]:
    ref = db.collection("elections").document(election_id)
    transaction = db.transaction()

    @firestore.transactional
    def change(tx: Any) -> str:
        snapshot = ref.get(transaction=tx)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Election not found")
        election = snapshot.to_dict() or {}
        current = election.get("status")
        expected = TRANSITIONS.get(current)
        if expected != body.to:
            raise HTTPException(status_code=409, detail="Invalid election phase transition")
        if current == "setup":
            missing = _phase_requirements(tx, election_id, election)
            if missing:
                raise HTTPException(status_code=409, detail={"message": "Election setup is incomplete", "missing": missing})
        if current == "closed":
            active_upload = False
            for place in ref.collection("pollingPlaces").stream(transaction=tx):
                terminals = list(place.reference.collection("terminals").stream(transaction=tx))
                if any(item.get("status") == "active" and (
                    item.get("uploading") is True or item.get("uploadStatus") == "uploading"
                ) for item in terminals):
                    active_upload = True
                    break
            if active_upload:
                raise HTTPException(status_code=409, detail="An active terminal is still uploading")
        if current == "counting":
            counts = list(ref.collection("counts").stream(transaction=tx))
            if any(item.get("status") != "complete" for item in counts):
                raise HTTPException(status_code=409, detail="All counts must be complete before finalisation")
        after = {"status": body.to, "updatedBy": staff["staffId"], "updatedAt": firestore.SERVER_TIMESTAMP}
        if body.to == "closed":
            after["closedAt"] = firestore.SERVER_TIMESTAMP
        write_audit(tx, actor=staff, action="election.phaseChange", category="admin",
                    target_type="election", target_id=election_id, target_path=ref.path,
                    before={"status": current}, after={"status": body.to},
                    outcome="success", reason=body.reason, request=request, election_id=election_id)
        tx.update(ref, after)
        return body.to

    try:
        status = change(transaction)
        return {"status": status}
    except HTTPException as exc:
        if not getattr(request.state, "audit_written", False):
            try:
                from backend.audit import audit_standalone
                audit_standalone(
                    actor=staff, action="election.phaseChange", category="admin",
                    target_type="election", target_id=election_id, target_path=ref.path,
                    before=None, after={"status": body.to},
                    outcome="denied" if exc.status_code == 403 else "failed",
                    reason=exc.detail if isinstance(exc.detail, str) else "phase_change_failed",
                    request=request, election_id=election_id,
                )
            except Exception:
                logger.exception("Unable to record failed election phase change")
        raise
    except Exception as exc:
        logger.exception("Election phase change failed")
        raise HTTPException(status_code=400, detail="Unable to change election phase") from exc
