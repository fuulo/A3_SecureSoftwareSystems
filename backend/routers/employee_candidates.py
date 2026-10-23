import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from google.cloud import firestore

from backend.audit import write_audit
from backend.auth import staff_access
from backend.firestore_client import db
from backend.models import CandidateCreate, CandidateEdit, Withdrawal

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
        if not data.get("divisionId") or data.get("stateId") is not None or data.get("groupId") is not None:
            raise HTTPException(status_code=422, detail="House candidate requires only a division")
        division_ref = election_ref.collection("divisions").document(data["divisionId"])
        division_snapshot = division_ref.get(transaction=tx)
        if not division_snapshot.exists:
            raise HTTPException(status_code=422, detail="Division does not exist")
        if division_snapshot.get("stateId") != staff.get("stateId"):
            raise HTTPException(status_code=403, detail="Division is outside your state")
        data["stateId"] = division_snapshot.get("stateId")
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


@router.post("/{election_id}/candidates", status_code=201)
def create_candidate(election_id: str, body: CandidateCreate, request: Request,
                     staff: dict[str, Any] = Depends(delegate_access)) -> dict[str, str]:
    ref, _, election = _election(election_id)
    if election.get("status") != "setup":
        raise HTTPException(status_code=409, detail="Candidates can only be created during setup")
    candidate = _validate_candidate(body.model_dump(), ref, staff)
    candidate_ref = ref.collection("candidates").document()
    transaction = db.transaction()

    @firestore.transactional
    def create(tx: Any) -> None:
        current = ref.get(transaction=tx)
        if current.get("status") != "setup":
            raise HTTPException(status_code=409, detail="Candidates are locked")
        _validate_candidate(candidate.copy(), ref, staff, tx)
        _check_position(ref, candidate, None, tx)
        normalized = _validate_candidate(candidate.copy(), ref, staff, tx)
        data = {**normalized, "enteredBy": staff["staffId"], "excluded": False, "withdrawn": False}
        group_updates = _senate_group_updates(tx, ref, {data.get("groupId")}, candidate_ref.id, data)
        write_audit(tx, actor=staff, action="candidate.create", category="candidateManagement",
                    target_type="candidate", target_id=candidate_ref.id, target_path=candidate_ref.path,
                    before=None, after=data, outcome="success", reason=None, request=request, election_id=election_id)
        tx.create(candidate_ref, data)
        for group_ref, group_data in group_updates:
            tx.update(group_ref, group_data)

    try:
        create(transaction)
        return {"candidateId": candidate_ref.id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Candidate creation failed")
        raise HTTPException(status_code=400, detail="Unable to create candidate") from exc


@router.patch("/{election_id}/candidates/{candidate_id}")
def edit_candidate(election_id: str, candidate_id: str, body: CandidateEdit,
                   request: Request, staff: dict[str, Any] = Depends(delegate_access)) -> dict[str, bool]:
    ref, _, election = _election(election_id)
    if election.get("status") != "setup":
        raise HTTPException(status_code=409, detail="Candidates can only be edited during setup")
    candidate_ref = ref.collection("candidates").document(candidate_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="No changes supplied")
    transaction = db.transaction()

    @firestore.transactional
    def update(tx: Any) -> None:
        election_snapshot = ref.get(transaction=tx)
        if election_snapshot.get("status") != "setup":
            raise HTTPException(status_code=409, detail="Candidates are locked")
        snapshot = candidate_ref.get(transaction=tx)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Candidate not found")
        before = snapshot.to_dict() or {}
        _assert_scope(before, staff, ref, tx)
        updated = {**before, **changes}
        updated = _validate_candidate(updated, ref, staff, tx)
        _check_position(ref, updated, candidate_id, tx)
        group_updates = _senate_group_updates(
            tx, ref, {before.get("groupId"), updated.get("groupId")}, candidate_id, updated,
        )
        write_audit(tx, actor=staff, action="candidate.edit", category="candidateManagement",
                    target_type="candidate", target_id=candidate_id, target_path=candidate_ref.path,
                    before={key: before.get(key) for key in changes},
                    after={key: updated.get(key) for key in changes},
                    outcome="success", reason=None, request=request, election_id=election_id)
        tx.update(candidate_ref, changes)
        for group_ref, group_data in group_updates:
            tx.update(group_ref, group_data)

    try:
        update(transaction)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Candidate update failed")
        raise HTTPException(status_code=400, detail="Unable to update candidate") from exc


@router.post("/{election_id}/candidates/{candidate_id}/withdraw")
def withdraw_candidate(election_id: str, candidate_id: str, body: Withdrawal,
                       request: Request, staff: dict[str, Any] = Depends(delegate_access)) -> dict[str, bool]:
    ref, _, election = _election(election_id)
    if election.get("status") not in {"setup", "open"}:
        raise HTTPException(status_code=409, detail="Candidate withdrawal is not available")
    candidate_ref = ref.collection("candidates").document(candidate_id)
    transaction = db.transaction()

    @firestore.transactional
    def withdraw(tx: Any) -> None:
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
        replacement = {**candidate, "withdrawn": True}
        group_updates = _senate_group_updates(
            tx, ref, {candidate.get("groupId")}, candidate_id, replacement,
        )
        after = {"withdrawn": True, "withdrawnAt": firestore.SERVER_TIMESTAMP,
                 "withdrawnBy": staff["staffId"], "withdrawalReason": body.reason.strip()}
        write_audit(tx, actor=staff, action="candidate.withdraw", category="candidateManagement",
                    target_type="candidate", target_id=candidate_id, target_path=candidate_ref.path,
                    before={"withdrawn": False}, after={"withdrawn": True},
                    outcome="success", reason=body.reason.strip(), request=request, election_id=election_id)
        tx.update(candidate_ref, after)
        for group_ref, group_data in group_updates:
            tx.update(group_ref, group_data)

    try:
        withdraw(transaction)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Candidate withdrawal failed")
        raise HTTPException(status_code=400, detail="Unable to withdraw candidate") from exc