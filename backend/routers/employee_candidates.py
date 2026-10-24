import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from google.cloud import firestore

from backend.approvals import (
    APPROVED, REJECTED, approval_reason, assert_no_pending, decision, list_requests,
    load_reviewable, new_request,
)
from backend.audit import write_audit
from backend.auth import staff_access
from backend.firestore_client import db
from backend.models import CandidateCreate, CandidateEdit, ChangeRequestRejection, Withdrawal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/delegate/elections", tags=["delegate-candidates"])
delegate_access = staff_access("commissionerDelegate")


@router.get("/active")
def active_election(staff: dict[str, Any] = Depends(delegate_access)) -> dict[str, Any]:
    elections = list(db.collection("elections").where("status", "in", ["setup", "open"]).stream())
    elections.sort(key=lambda item: 0 if item.get("status") == "open" else 1)
    if not elections:
        raise HTTPException(status_code=404, detail="No election is available")
    return {"electionId": elections[0].id, **(elections[0].to_dict() or {})}


def _requests(election_ref: Any) -> Any:
    return election_ref.collection("candidateChangeRequests")


def _election(election_id: str, transaction: Any | None = None):
    ref = db.collection("elections").document(election_id)
    snapshot = ref.get(transaction=transaction)
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Election not found")
    return ref, snapshot, snapshot.to_dict() or {}


def _assert_scope(candidate: dict[str, Any], staff: dict[str, Any],
                  election_ref: Any | None = None, tx: Any | None = None) -> None:
    if candidate.get("chamber") == "senate":
        if candidate.get("stateId") != staff.get("stateId"):
            raise HTTPException(status_code=403, detail="Candidate is outside your state")
    else:
        state_id = candidate.get("stateId")
        if state_id is None and election_ref is not None and candidate.get("divisionId"):
            division = election_ref.collection("divisions").document(candidate["divisionId"]).get(transaction=tx)
            state_id = division.get("stateId") if division.exists else None
        if state_id != staff.get("stateId"):
            raise HTTPException(status_code=403, detail="Candidate is outside your state")


def _validate_candidate(data: dict[str, Any], election_ref: Any, staff: dict[str, Any],
                        tx: Any | None = None) -> dict[str, Any]:
    if data.get("chamber") == "house":
        if not data.get("divisionId") or data.get("groupId") is not None:
            raise HTTPException(status_code=422, detail="House candidate requires only a division")
        division_ref = election_ref.collection("divisions").document(data["divisionId"])
        division_snapshot = division_ref.get(transaction=tx)
        if not division_snapshot.exists:
            raise HTTPException(status_code=422, detail="Division does not exist")
        division_state = (division_snapshot.to_dict() or {}).get("stateId")
        if division_state != staff.get("stateId"):
            raise HTTPException(status_code=403, detail="Division is outside your state")
        # stateId is derived from the division. Accept an absent value, or one matching the
        # division, so already-normalised data (re-validation, edits) passes again.
        if data.get("stateId") not in (None, division_state):
            raise HTTPException(status_code=422, detail="House candidate requires only a division")
        data["stateId"] = division_state
    else:
        if not data.get("stateId") or data.get("divisionId") is not None:
            raise HTTPException(status_code=422, detail="Senate candidate requires only a state")
        if data["stateId"] != staff.get("stateId"):
            raise HTTPException(status_code=403, detail="State is outside your scope")
        regions = list(election_ref.collection("senateRegions").stream(transaction=tx))
        if not any(region.id == data["stateId"] or (region.to_dict() or {}).get("stateId") == data["stateId"]
                   for region in regions):
            raise HTTPException(status_code=422, detail="Senate region does not exist")
        group_id = data.get("groupId")
        if group_id:
            group = election_ref.collection("senateGroups").document(group_id).get(transaction=tx)
            if not group.exists or group.get("stateId") != data["stateId"]:
                raise HTTPException(status_code=422, detail="Senate group does not belong to this state")
    party = election_ref.collection("parties").document(data["partyId"]).get(transaction=tx)
    if not party.exists:
        raise HTTPException(status_code=422, detail="Party does not exist")
    return data


def _check_position(election_ref: Any, candidate: dict[str, Any], candidate_id: str | None,
                    tx: Any) -> None:
    field = "divisionId" if candidate["chamber"] == "house" else "groupId"
    key = candidate.get(field)
    query = election_ref.collection("candidates").where("chamber", "==", candidate["chamber"]).where(field, "==", key)
    for existing in query.stream(transaction=tx):
        if existing.id != candidate_id and existing.get("ballotPosition") == candidate["ballotPosition"]:
            raise HTTPException(status_code=409, detail="Ballot position is already in use")


def _senate_group_updates(tx: Any, election_ref: Any, group_ids: set[str | None],
                          candidate_id: str, replacement: dict[str, Any] | None) -> list[tuple[Any, dict[str, Any]]]:
    updates = []
    for group_id in group_ids - {None}:
        group_ref = election_ref.collection("senateGroups").document(group_id)
        group_snapshot = group_ref.get(transaction=tx)
        if not group_snapshot.exists:
            continue
        snapshots = list(election_ref.collection("candidates").where("groupId", "==", group_id).stream(transaction=tx))
        candidates = {item.id: item.to_dict() or {} for item in snapshots if item.id != candidate_id}
        if replacement is not None and replacement.get("groupId") == group_id:
            candidates[candidate_id] = replacement
        ordered = sorted(
            ((identifier, item) for identifier, item in candidates.items() if item.get("withdrawn") is not True),
            key=lambda pair: (pair[1].get("ballotPosition", 0), pair[0]),
        )
        updates.append((group_ref, {
            "candidateOrder": [identifier for identifier, _ in ordered],
            "candidateCount": len(ordered),
        }))
    return updates


@router.get("/{election_id}/options")
def candidate_options(election_id: str, staff: dict[str, Any] = Depends(delegate_access)) -> dict[str, Any]:
    ref, snapshot, election = _election(election_id)
    if election.get("status") not in {"setup", "open"}:
        raise HTTPException(status_code=409, detail="Election candidate data is unavailable")
    return {
        "election": {"electionId": election_id, **election},
        "parties": [{"partyId": item.id, **(item.to_dict() or {})} for item in ref.collection("parties").stream()],
        "divisions": [{"divisionId": item.id, **(item.to_dict() or {})}
                      for item in ref.collection("divisions").where("stateId", "==", staff["stateId"]).stream()],
        "senateRegions": [{"regionId": item.id, **(item.to_dict() or {})}
                          for item in ref.collection("senateRegions").stream()
                          if item.id == staff["stateId"] or (item.to_dict() or {}).get("stateId") == staff["stateId"]],
        "senateGroups": [{"groupId": item.id, **(item.to_dict() or {})}
                         for item in ref.collection("senateGroups").where("stateId", "==", staff["stateId"]).stream()],
    }


@router.get("/{election_id}/candidates")
def list_candidates(election_id: str, chamber: str | None = None, divisionId: str | None = None,
                    stateId: str | None = None,
                    staff: dict[str, Any] = Depends(delegate_access)) -> list[dict[str, Any]]:
    ref, _, election = _election(election_id)
    query: Any = ref.collection("candidates")
    if chamber:
        query = query.where("chamber", "==", chamber)
    if divisionId:
        query = query.where("divisionId", "==", divisionId)
    if stateId:
        query = query.where("stateId", "==", stateId)
    results = []
    for item in query.stream():
        candidate = item.to_dict() or {}
        try:
            _assert_scope(candidate, staff, ref)
        except HTTPException:
            continue
        results.append({"candidateId": item.id, **candidate})
    return results


@router.post("/{election_id}/candidates", status_code=202)
def create_candidate(election_id: str, body: CandidateCreate, request: Request,
                     staff: dict[str, Any] = Depends(delegate_access)) -> dict[str, str]:
    """Submit a new candidate for approval by another delegate; nothing is created yet."""
    ref, _, election = _election(election_id)
    if election.get("status") != "setup":
        raise HTTPException(status_code=409, detail="Candidates can only be created during setup")
    candidate = _validate_candidate(body.model_dump(), ref, staff)
    candidate_ref = ref.collection("candidates").document()
    request_ref = _requests(ref).document()
    transaction = db.transaction()

    @firestore.transactional
    def submit(tx: Any) -> None:
        current = ref.get(transaction=tx)
        if current.get("status") != "setup":
            raise HTTPException(status_code=409, detail="Candidates are locked")
        normalized = _validate_candidate(candidate.copy(), ref, staff, tx)
        _check_position(ref, normalized, None, tx)
        write_audit(tx, actor=staff, action="candidate.create.request", category="candidateManagement",
                    target_type="candidate", target_id=candidate_ref.id, target_path=candidate_ref.path,
                    before=None, after=normalized, outcome="success", reason=None, request=request,
                    election_id=election_id)
        tx.create(request_ref, new_request(
            action="candidate.create", target_type="candidate", target_id=candidate_ref.id,
            target_path=candidate_ref.path,
            summary=f"Create {normalized['chamber']} candidate {normalized['name']}",
            payload={"candidate": normalized}, before=None, staff=staff,
            electionId=election_id, stateId=staff["stateId"],
        ))

    try:
        submit(transaction)
        return {"requestId": request_ref.id, "candidateId": candidate_ref.id, "status": "pending"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Candidate creation request failed")
        raise HTTPException(status_code=400, detail="Unable to submit candidate for approval") from exc


@router.patch("/{election_id}/candidates/{candidate_id}", status_code=202)
def edit_candidate(election_id: str, candidate_id: str, body: CandidateEdit,
                   request: Request, staff: dict[str, Any] = Depends(delegate_access)) -> dict[str, str]:
    """Submit candidate edits for approval by another delegate; the candidate is unchanged for now."""
    ref, _, election = _election(election_id)
    if election.get("status") != "setup":
        raise HTTPException(status_code=409, detail="Candidates can only be edited during setup")
    candidate_ref = ref.collection("candidates").document(candidate_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="No changes supplied")
    request_ref = _requests(ref).document()
    transaction = db.transaction()

    @firestore.transactional
    def submit(tx: Any) -> None:
        election_snapshot = ref.get(transaction=tx)
        if election_snapshot.get("status") != "setup":
            raise HTTPException(status_code=409, detail="Candidates are locked")
        snapshot = candidate_ref.get(transaction=tx)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Candidate not found")
        before = snapshot.to_dict() or {}
        _assert_scope(before, staff, ref, tx)
        updated = _validate_candidate({**before, **changes}, ref, staff, tx)
        _check_position(ref, updated, candidate_id, tx)
        assert_no_pending(_requests(ref), candidate_id, tx)
        before_fields = {key: before.get(key) for key in changes}
        write_audit(tx, actor=staff, action="candidate.edit.request", category="candidateManagement",
                    target_type="candidate", target_id=candidate_id, target_path=candidate_ref.path,
                    before=before_fields, after={key: updated.get(key) for key in changes},
                    outcome="success", reason=None, request=request, election_id=election_id)
        tx.create(request_ref, new_request(
            action="candidate.edit", target_type="candidate", target_id=candidate_id,
            target_path=candidate_ref.path, summary=f"Edit candidate {before.get('name')}",
            payload={"changes": changes}, before=before_fields, staff=staff,
            electionId=election_id, stateId=staff["stateId"],
        ))

    try:
        submit(transaction)
        return {"requestId": request_ref.id, "status": "pending"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Candidate update request failed")
        raise HTTPException(status_code=400, detail="Unable to submit candidate changes for approval") from exc


@router.post("/{election_id}/candidates/{candidate_id}/withdraw", status_code=202)
def withdraw_candidate(election_id: str, candidate_id: str, body: Withdrawal,
                       request: Request, staff: dict[str, Any] = Depends(delegate_access)) -> dict[str, str]:
    """Submit a withdrawal for approval by another delegate; the candidate stays on the ballot for now."""
    ref, _, election = _election(election_id)
    if election.get("status") not in {"setup", "open"}:
        raise HTTPException(status_code=409, detail="Candidate withdrawal is not available")
    candidate_ref = ref.collection("candidates").document(candidate_id)
    request_ref = _requests(ref).document()
    transaction = db.transaction()

    @firestore.transactional
    def submit(tx: Any) -> None:
        current_election = ref.get(transaction=tx)
        if current_election.get("status") not in {"setup", "open"}:
            raise HTTPException(status_code=409, detail="Candidate withdrawal is not available")
        snapshot = candidate_ref.get(transaction=tx)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Candidate not found")
        candidate = snapshot.to_dict() or {}
        _assert_scope(candidate, staff, ref, tx)
        if candidate.get("withdrawn") is True:
            raise HTTPException(status_code=409, detail="Candidate is already withdrawn")
        assert_no_pending(_requests(ref), candidate_id, tx)
        write_audit(tx, actor=staff, action="candidate.withdraw.request", category="candidateManagement",
                    target_type="candidate", target_id=candidate_id, target_path=candidate_ref.path,
                    before={"withdrawn": False}, after={"withdrawn": True},
                    outcome="success", reason=body.reason.strip(), request=request, election_id=election_id)
        tx.create(request_ref, new_request(
            action="candidate.withdraw", target_type="candidate", target_id=candidate_id,
            target_path=candidate_ref.path, summary=f"Withdraw candidate {candidate.get('name')}",
            payload={"reason": body.reason.strip()}, before={"withdrawn": False}, staff=staff,
            electionId=election_id, stateId=staff["stateId"],
        ))

    try:
        submit(transaction)
        return {"requestId": request_ref.id, "status": "pending"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Candidate withdrawal request failed")
        raise HTTPException(status_code=400, detail="Unable to submit withdrawal for approval") from exc


@router.get("/{election_id}/change-requests")
def list_change_requests(election_id: str,
                         staff: dict[str, Any] = Depends(delegate_access)) -> dict[str, list[dict[str, Any]]]:
    ref, _, _ = _election(election_id)
    return list_requests(_requests(ref), stateId=staff["stateId"])


@router.post("/{election_id}/change-requests/{request_id}/approve")
def approve_change_request(election_id: str, request_id: str, request: Request,
                           staff: dict[str, Any] = Depends(delegate_access)) -> dict[str, bool]:
    """Apply a candidate change that another delegate in the same state requested."""
    ref, _, _ = _election(election_id)
    request_ref = _requests(ref).document(request_id)
    transaction = db.transaction()

    @firestore.transactional
    def approve(tx: Any) -> None:
        change = load_reviewable(request_ref, staff, tx, scope_state=True)
        status = ref.get(transaction=tx).get("status")
        action, requester = change.get("action"), change["requestedBy"]
        candidate_id = change["targetId"]
        candidate_ref = ref.collection("candidates").document(candidate_id)
        payload = change.get("payload") or {}
        reason = approval_reason(request_id, requester)
        group_updates: list[tuple[Any, dict[str, Any]]] = []

        if action == "candidate.create":
            if status != "setup":
                raise HTTPException(status_code=409, detail="Candidates are locked")
            normalized = _validate_candidate(dict(payload["candidate"]), ref, staff, tx)
            _check_position(ref, normalized, candidate_id, tx)
            data = {**normalized, "enteredBy": requester, "excluded": False, "withdrawn": False}
            group_updates = _senate_group_updates(tx, ref, {data.get("groupId")}, candidate_id, data)
            audit_before, audit_after, write = None, data, ("create", data)
        elif action in {"candidate.edit", "candidate.withdraw"}:
            snapshot = candidate_ref.get(transaction=tx)
            if not snapshot.exists:
                raise HTTPException(status_code=404, detail="Candidate not found")
            before = snapshot.to_dict() or {}
            _assert_scope(before, staff, ref, tx)
            if action == "candidate.edit":
                if status != "setup":
                    raise HTTPException(status_code=409, detail="Candidates are locked")
                changes = payload["changes"]
                updated = _validate_candidate({**before, **changes}, ref, staff, tx)
                _check_position(ref, updated, candidate_id, tx)
                group_updates = _senate_group_updates(
                    tx, ref, {before.get("groupId"), updated.get("groupId")}, candidate_id, updated,
                )
                audit_before = {key: before.get(key) for key in changes}
                audit_after = {key: updated.get(key) for key in changes}
                write = ("update", changes)
            else:
                if status not in {"setup", "open"}:
                    raise HTTPException(status_code=409, detail="Candidate withdrawal is not available")
                if before.get("withdrawn") is True:
                    raise HTTPException(status_code=409, detail="Candidate is already withdrawn")
                group_updates = _senate_group_updates(
                    tx, ref, {before.get("groupId")}, candidate_id, {**before, "withdrawn": True},
                )
                audit_before, audit_after = {"withdrawn": False}, {"withdrawn": True}
                reason = approval_reason(request_id, requester, payload.get("reason"))
                write = ("update", {"withdrawn": True, "withdrawnAt": firestore.SERVER_TIMESTAMP,
                                    "withdrawnBy": requester, "withdrawalReason": payload.get("reason")})
        else:
            raise HTTPException(status_code=409, detail="Unsupported change request")

        write_audit(tx, actor=staff, action=action, category="candidateManagement",
                    target_type="candidate", target_id=candidate_id, target_path=candidate_ref.path,
                    before=audit_before, after=audit_after, outcome="success", reason=reason,
                    request=request, election_id=ref.id)
        if write[0] == "create":
            tx.create(candidate_ref, write[1])
        else:
            tx.update(candidate_ref, write[1])
        for group_ref, group_data in group_updates:
            tx.update(group_ref, group_data)
        tx.update(request_ref, decision(APPROVED, staff, None))

    try:
        approve(transaction)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Candidate change approval failed")
        raise HTTPException(status_code=400, detail="Unable to approve change request") from exc


@router.post("/{election_id}/change-requests/{request_id}/reject")
def reject_change_request(election_id: str, request_id: str, body: ChangeRequestRejection,
                          request: Request,
                          staff: dict[str, Any] = Depends(delegate_access)) -> dict[str, bool]:
    ref, _, _ = _election(election_id)
    request_ref = _requests(ref).document(request_id)
    transaction = db.transaction()

    @firestore.transactional
    def reject(tx: Any) -> None:
        change = load_reviewable(request_ref, staff, tx, scope_state=True)
        write_audit(tx, actor=staff, action=f"{change.get('action')}.reject", category="candidateManagement",
                    target_type="candidate", target_id=change.get("targetId"),
                    target_path=change.get("targetPath"), before={"status": "pending"},
                    after={"status": "rejected"}, outcome="success", reason=body.reason.strip(),
                    request=request, election_id=ref.id)
        tx.update(request_ref, decision(REJECTED, staff, body.reason.strip()))

    try:
        reject(transaction)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Candidate change rejection failed")
        raise HTTPException(status_code=400, detail="Unable to reject change request") from exc
