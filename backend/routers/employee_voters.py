import hashlib
import logging
import secrets
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from firebase_admin import auth
from google.cloud import firestore

from backend.audit import write_audit
from backend.auth import staff_access
from backend.email import send_password_setup_email
from backend.firestore_client import db
from backend.models import (
    AddressChange,
    EnrolmentApproval,
    EnrolmentRejection,
    VoterLookup,
    VoterRegistration,
)
from backend.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/employee", tags=["employee-voters"])
aec_access = staff_access("aecEmployee")
STATES = {"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"}


def _active_election(transaction: Any | None = None, include_closed: bool = False):
    result = list(db.collection("elections").stream(transaction=transaction))
    priority = {"open": 0, "setup": 1}
    if include_closed:
        priority.update({"closed": 2, "counting": 3, "finalised": 4})
    result = [item for item in result if (item.to_dict() or {}).get("status") in priority]
    result.sort(key=lambda item: (
        priority[(item.to_dict() or {})["status"]],
        -(((item.to_dict() or {}).get("createdAt").timestamp())
          if hasattr((item.to_dict() or {}).get("createdAt"), "timestamp") else 0),
    ))
    if not result:
        raise HTTPException(status_code=409, detail="No active election is available")
    return result[0]


def _age(dob: str) -> int:
    try:
        birth = date.fromisoformat(dob)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Voter date of birth is invalid") from exc
    today = date.today()
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    if birth.year < 1900 or age < 0 or age > 120:
        raise HTTPException(status_code=409, detail="Voter date of birth is invalid")
    return age


def _mask_gov_id(value: str) -> str:
    return f"***{value[-3:]}"


def _public_voter(snapshot: Any) -> dict[str, Any]:
    item = snapshot.to_dict() or {}
    item.pop("authUid", None)
    item.pop("email", None)
    item["voterId"] = snapshot.id
    item["govId"] = _mask_gov_id(item.get("govId", ""))
    return item


@router.get("/voters/enrolments/pending/count")
def pending_count(staff: dict[str, Any] = Depends(aec_access)) -> dict[str, int]:
    result = db.collection("voters").where("enrolmentStatus", "==", "pending").count().get()
    return {"count": int(result[0][0].value)}


@router.get("/enrolments")
def list_enrolments(status: str = "pending", cursor: str | None = None, limit: int = 50,
                    staff: dict[str, Any] = Depends(aec_access)) -> dict[str, Any]:
    if status != "pending":
        raise HTTPException(status_code=422, detail="Only pending enrolments can be reviewed")
    limit = min(max(limit, 1), 100)
    query = db.collection("voters").where("enrolmentStatus", "==", status).order_by("createdAt").limit(limit + 1)
    if cursor:
        last = db.collection("voters").document(cursor).get()
        if last.exists:
            query = query.start_after(last)
    records = list(query.stream())
    more = len(records) > limit
    records = records[:limit]
    return {"items": [_public_voter(item) for item in records],
            "nextCursor": records[-1].id if more and records else None}


@router.post("/enrolments/{voter_id}/approve")
def approve_enrolment(voter_id: str, body: EnrolmentApproval, request: Request,
                      staff: dict[str, Any] = Depends(aec_access)) -> dict[str, bool]:
    voter_ref = db.collection("voters").document(voter_id)
    transaction = db.transaction()

    @firestore.transactional
    def approve(tx: Any) -> None:
        voter_snapshot = voter_ref.get(transaction=tx)
        if not voter_snapshot.exists:
            raise HTTPException(status_code=404, detail="Voter not found")
        voter = voter_snapshot.to_dict() or {}
        if voter.get("enrolmentStatus") != "pending":
            raise HTTPException(status_code=409, detail="Enrolment is no longer pending")
        if voter.get("authUid") == staff.get("authUid"):
            raise HTTPException(status_code=409, detail="You cannot review your own enrolment")
        if _age(voter.get("dateOfBirth")) < 18:
            raise HTTPException(status_code=409, detail="Voter does not meet the minimum age")
        election = _active_election(tx)
        division_ref = election.reference.collection("divisions").document(body.divisionId)
        division_snapshot = division_ref.get(transaction=tx)
        division = division_snapshot.to_dict() if division_snapshot.exists else None
        address = voter.get("address") or {}
        if not division or division.get("stateId") != address.get("state"):
            raise HTTPException(status_code=409, detail="Division does not match the voter address")
        after = {"enrolmentStatus": "enrolled", "divisionId": body.divisionId,
                 "stateId": division["stateId"], "updatedAt": firestore.SERVER_TIMESTAMP}
        write_audit(tx, actor=staff, action="voter.enrolment.approve", category="enrolment",
                    target_type="voter", target_id=voter_id, target_path=voter_ref.path,
                    before={"enrolmentStatus": "pending"},
                    after={"enrolmentStatus": "enrolled", "divisionId": body.divisionId},
                    outcome="success", reason=None, request=request, election_id=election.id)
        tx.update(voter_ref, after)

    try:
        approve(transaction)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Enrolment approval failed")
        raise HTTPException(status_code=400, detail="Unable to approve enrolment") from exc


@router.post("/enrolments/{voter_id}/reject")
def reject_enrolment(voter_id: str, body: EnrolmentRejection, request: Request,
                     staff: dict[str, Any] = Depends(aec_access)) -> dict[str, bool]:
    voter_ref = db.collection("voters").document(voter_id)
    transaction = db.transaction()

    @firestore.transactional
    def reject(tx: Any) -> None:
        snapshot = voter_ref.get(transaction=tx)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Voter not found")
        voter = snapshot.to_dict() or {}
        if voter.get("enrolmentStatus") != "pending":
            raise HTTPException(status_code=409, detail="Enrolment is no longer pending")
        if voter.get("authUid") == staff.get("authUid"):
            raise HTTPException(status_code=409, detail="You cannot review your own enrolment")
        after = {"enrolmentStatus": "removed", "rejectionReason": body.reason.strip(),
                 "reviewedBy": staff["staffId"], "reviewedAt": firestore.SERVER_TIMESTAMP,
                 "updatedAt": firestore.SERVER_TIMESTAMP}
        write_audit(tx, actor=staff, action="voter.enrolment.reject", category="enrolment",
                    target_type="voter", target_id=voter_id, target_path=voter_ref.path,
                    before={"enrolmentStatus": "pending"}, after={"enrolmentStatus": "removed"},
                    outcome="success", reason=body.reason.strip(), request=request)
        tx.update(voter_ref, after)

    try:
        reject(transaction)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Enrolment rejection failed")
        raise HTTPException(status_code=400, detail="Unable to reject enrolment") from exc


@router.post("/voters", status_code=201)
def register_voter(body: VoterRegistration, request: Request,
                   staff: dict[str, Any] = Depends(aec_access)) -> dict[str, str]:
    if _age(body.dateOfBirth) < 18:
        raise HTTPException(status_code=422, detail="Voter does not meet the minimum age")
    election = _active_election()
    division = election.reference.collection("divisions").document(body.divisionId).get()
    if not division.exists or division.get("stateId") != body.state:
        raise HTTPException(status_code=422, detail="Division does not match the voter address")
    email = body.email.strip().lower()
    gov_hash = hashlib.sha256(body.govId.encode("utf-8")).hexdigest()
    index_ref = db.collection("govIdIndex").document(gov_hash)
    voter_ref = db.collection("voters").document()
    account = None
    try:
        account = auth.create_user(email=email, password=secrets.token_urlsafe(32))
        setup_link = auth.generate_password_reset_link(email)
        send_password_setup_email(email, f"{body.givenNames} {body.surname}", setup_link)
    except Exception as exc:
        logger.exception("Voter account setup failed")
        if account is not None:
            try:
                auth.delete_user(account.uid)
            except Exception:
                logger.exception("Unable to clean up incomplete voter account")
        raise HTTPException(status_code=503, detail="Unable to create the voter account") from exc

    transaction = db.transaction()

    @firestore.transactional
    def create(tx: Any) -> None:
        if index_ref.get(transaction=tx).exists:
            raise HTTPException(status_code=409, detail="Government ID is already registered")
        duplicates = list(db.collection("voters").where("govId", "==", body.govId).limit(1).stream(transaction=tx))
        if duplicates:
            raise HTTPException(status_code=409, detail="Government ID is already registered")
        data = {
            "authUid": account.uid,
            "givenNames": body.givenNames.strip(),
            "givenNamesLower": body.givenNames.strip().lower(),
            "surname": body.surname.strip(),
            "surnameLower": body.surname.strip().lower(),
            "govId": body.govId,
            "dateOfBirth": body.dateOfBirth,
            "address": {"street": body.street.strip(), "suburb": body.suburb.strip(),
                        "state": body.state, "postcode": body.postcode},
            "email": email,
            "divisionId": body.divisionId,
            "stateId": body.state,
            "enrolmentStatus": "enrolled",
            "enrolledBy": staff["staffId"],
            "voted": False,
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
        write_audit(tx, actor=staff, action="voter.register", category="enrolment",
                    target_type="voter", target_id=voter_ref.id, target_path=voter_ref.path,
                    before=None, after={"enrolmentStatus": "enrolled", "divisionId": body.divisionId},
                    outcome="success", reason=None, request=request, election_id=election.id)
        tx.create(index_ref, {"voterId": voter_ref.id})
        tx.create(voter_ref, data)

    try:
        create(transaction)
    except HTTPException:
        auth.delete_user(account.uid)
        raise
    except Exception as exc:
        logger.exception("Voter registration failed")
        auth.delete_user(account.uid)
        raise HTTPException(status_code=400, detail="Unable to register voter") from exc
    return {"voterId": voter_ref.id, "message": "Password setup instructions were sent."}


@router.post("/voters/lookup")
@limiter.limit("5/minute")
def lookup_voter(body: VoterLookup, request: Request,
                 staff: dict[str, Any] = Depends(aec_access)) -> dict[str, Any]:
    by_id = body.govId is not None
    by_name = body.givenNames is not None and body.surname is not None
    if by_id == by_name:
        raise HTTPException(status_code=422, detail="Provide a government ID or both name fields")
    if by_id:
        snapshots = list(db.collection("voters").where("govId", "==", body.govId).limit(25).stream())
    else:
        surname = body.surname.strip().lower()
        given = body.givenNames.strip().lower()
        query = (db.collection("voters").where("surnameLower", ">=", surname)
                 .where("surnameLower", "<=", surname + "\uf8ff").order_by("surnameLower").limit(100))
        snapshots = [item for item in query.stream() if (item.get("givenNamesLower") or "").startswith(given)][:25]
    transaction = db.transaction()

    @firestore.transactional
    def audit_lookup(tx: Any) -> None:
        write_audit(tx, actor=staff, action="voter.lookup", category="enrolment",
                    target_type="voterSearch", target_id=None, target_path="voters",
                    before=None, after={"method": "govId" if by_id else "name", "resultCount": len(snapshots)},
                    outcome="success", reason=None, request=request)
    audit_lookup(transaction)
    return {"items": [_public_voter(item) for item in snapshots]}


@router.get("/voters/{voter_id}")
def voter_detail(voter_id: str, request: Request,
                 staff: dict[str, Any] = Depends(aec_access)) -> dict[str, Any]:
    ref = db.collection("voters").document(voter_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Voter not found")
    voter = snapshot.to_dict() or {}
    history = list(ref.collection("addressHistory").order_by("createdAt", direction=firestore.Query.DESCENDING).limit(50).stream())
    transaction = db.transaction()

    @firestore.transactional
    def audit_detail(tx: Any) -> None:
        write_audit(tx, actor=staff, action="voter.lookup", category="enrolment",
                    target_type="voter", target_id=voter_id, target_path=ref.path,
                    before=None, after={"viewed": True}, outcome="success", reason="detail_view",
                    request=request)
    audit_detail(transaction)
    voter.pop("authUid", None)
    return {"voterId": voter_id, **voter,
            "addressHistory": [{"changeId": item.id, **(item.to_dict() or {})} for item in history]}


@router.patch("/voters/{voter_id}/address")
def update_address(voter_id: str, body: AddressChange, request: Request,
                   staff: dict[str, Any] = Depends(aec_access)) -> dict[str, bool]:
    voter_ref = db.collection("voters").document(voter_id)
    transaction = db.transaction()
    history_ref = voter_ref.collection("addressHistory").document()

    @firestore.transactional
    def update(tx: Any) -> None:
        voter_snapshot = voter_ref.get(transaction=tx)
        if not voter_snapshot.exists:
            raise HTTPException(status_code=404, detail="Voter not found")
        voter = voter_snapshot.to_dict() or {}
        if voter.get("enrolmentStatus") != "enrolled":
            raise HTTPException(status_code=409, detail="Only enrolled voters can be updated")
        try:
            election = _active_election(tx, include_closed=True)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            election = None
        if election and election.get("status") in {"open", "closed", "counting", "finalised"} and voter.get("voted") is True:
            raise HTTPException(status_code=409, detail="Address cannot be changed after voting in this election")
        if election:
            division_ref = election.reference.collection("divisions").document(body.newDivisionId)
            division_snapshot = division_ref.get(transaction=tx)
            division = division_snapshot.to_dict() if division_snapshot.exists else None
            if not division or division.get("stateId") != body.newAddress.state:
                raise HTTPException(status_code=422, detail="Division does not match the new address")
        else:
            if (body.newDivisionId != voter.get("divisionId") or
                    body.newAddress.state != voter.get("stateId")):
                raise HTTPException(status_code=409, detail="A division cannot be changed without election data")
        previous_address = voter.get("address") or {}
        previous_state = voter.get("stateId")
        division_changed = voter.get("divisionId") != body.newDivisionId
        state_changed = previous_state != body.newAddress.state
        now = firestore.SERVER_TIMESTAMP
        history_data = {
            "previousAddress": previous_address, "newAddress": body.newAddress.model_dump(),
            "previousDivisionId": voter.get("divisionId"), "newDivisionId": body.newDivisionId,
            "divisionChanged": division_changed, "stateChanged": state_changed,
            "changedAt": now, "changedBy": staff["staffId"], "changeChannel": "aec_staff",
            "reviewedBy": staff["staffId"], "verificationStatus": "verified",
            "reason": body.reason, "createdAt": now,
        }
        write_audit(tx, actor=staff, action="voter.addressUpdate", category="enrolment",
                    target_type="voter", target_id=voter_id, target_path=voter_ref.path,
                    before={"address": previous_address, "divisionId": voter.get("divisionId")},
                    after={"address": body.newAddress.model_dump(), "divisionId": body.newDivisionId},
                    outcome="success", reason=body.reason, request=request,
                    election_id=election.id if election else None)
        tx.set(history_ref, history_data)
        tx.update(voter_ref, {"address": body.newAddress.model_dump(),
                              "divisionId": body.newDivisionId, "stateId": body.newAddress.state,
                              "updatedAt": now})

    try:
        update(transaction)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Voter address update failed")
        raise HTTPException(status_code=400, detail="Unable to update voter address") from exc
