import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from google.cloud import firestore

from backend.audit import audit_standalone
from backend.auth import verify_token
from backend.firestore_client import db
from backend.models import BallotSubmission
from backend.rate_limit import limiter
from backend.receipts import issue_receipt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voter", tags=["voter-ballots"])
SENATE_BTL_MINIMUM = 6  # savings provision: 6 boxes below the line is formal


class BallotRejected(HTTPException):
    def __init__(self, status_code: int, detail: str, reason: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.reason = reason


async def current_voter(
    request: Request, claims: dict[str, Any] = Depends(verify_token)
) -> dict[str, Any]:
    uid = claims.get("uid")
    matches = list(db.collection("voters").where("authUid", "==", uid).limit(1).stream()) if uid else []
    if not matches:
        raise HTTPException(status_code=403, detail="Voter access denied")
    voter = {**(matches[0].to_dict() or {}), "voterId": matches[0].id}
    # Lets the API-wide failure handler audit rejected requests against this voter.
    request.state.staff = {"staffId": voter["voterId"], "role": "voter", "stateId": voter.get("stateId")}
    return voter


def _usable(snapshot: Any) -> bool:
    data = snapshot.to_dict() or {}
    return data.get("withdrawn") is not True and data.get("excluded") is not True


def _unique_known(choices: list[str], known: set[str], label: str) -> None:
    if len(set(choices)) != len(choices):
        raise BallotRejected(422, f"Each {label} can only be numbered once", "duplicate_preference")
    if any(choice not in known for choice in choices):
        raise BallotRejected(422, f"Ballot contains an unknown {label}", "unknown_choice")


def house_is_formal(preferences: list[str], candidate_count: int) -> bool:
    # Full preferential voting: every candidate must be numbered.
    return candidate_count > 0 and len(preferences) == candidate_count


def senate_counted_as(above: list[str], below: list[str], candidate_count: int) -> str | None:
    """Which part of a senate ballot is counted, or None if the ballot is informal.

    A formal below-the-line vote takes precedence over above-the-line boxes.
    """
    if below and len(below) >= min(SENATE_BTL_MINIMUM, candidate_count):
        return "belowTheLine"
    if above:
        return "aboveTheLine"
    return None


def _open_election(tx: Any) -> Any:
    opened = list(db.collection("elections").where("status", "==", "open").limit(2).stream(transaction=tx))
    if len(opened) != 1:
        raise BallotRejected(409, "Voting is not open", "election_not_open")
    election = opened[0].to_dict() or {}
    now = datetime.now(timezone.utc)
    open_at, close_at = election.get("openAt"), election.get("closeAt")
    if isinstance(open_at, datetime) and now < open_at:
        raise BallotRejected(409, "Voting has not started", "election_not_started")
    if isinstance(close_at, datetime) and now >= close_at:
        raise BallotRejected(409, "Voting has closed", "election_closed")
    return opened[0].reference


def _house_ballot(tx: Any, election_ref: Any, voter: dict[str, Any], preferences: list[str]) -> dict[str, Any]:
    division_id = voter.get("divisionId")
    if not division_id:
        raise BallotRejected(409, "Your enrolment has no division", "no_division")
    candidates = {
        item.id for item in election_ref.collection("candidates").where("divisionId", "==", division_id).stream(transaction=tx)
        if (item.to_dict() or {}).get("chamber") == "house" and _usable(item)
    }
    _unique_known(preferences, candidates, "House candidate")
    return {"divisionId": division_id, "preferences": preferences, "source": "electronic",
            "isFormal": house_is_formal(preferences, len(candidates))}


def _senate_ballot(tx: Any, election_ref: Any, voter: dict[str, Any],
                   above: list[str], below: list[str]) -> dict[str, Any]:
    state_id = voter.get("stateId")
    groups = {
        item.id for item in election_ref.collection("senateGroups").where("stateId", "==", state_id).stream(transaction=tx)
        if (item.to_dict() or {}).get("candidateOrder")
    }
    candidates = {
        item.id for item in election_ref.collection("candidates").where("stateId", "==", state_id).stream(transaction=tx)
        if (item.to_dict() or {}).get("chamber") == "senate" and _usable(item)
    }
    _unique_known(above, groups, "Senate group")
    _unique_known(below, candidates, "Senate candidate")
    counted_as = senate_counted_as(above, below, len(candidates))
    return {"stateId": state_id, "aboveTheLine": above, "belowTheLine": below, "source": "electronic",
            "isFormal": counted_as is not None, "countedAs": counted_as}


def record_ballot(voter_id: str, body: BallotSubmission, request: Request) -> dict[str, str]:
    """Record one voter's House and Senate ballots and return their receipt.

    Ballots are stored without any voter reference or timestamp, and the voter
    record only gains ``voted: true``, so a ballot cannot be traced to a voter.
    """
    voter_ref = db.collection("voters").document(voter_id)
    transaction = db.transaction()

    @firestore.transactional
    def cast(tx: Any) -> tuple[str, datetime]:
        voter = voter_ref.get(transaction=tx).to_dict() or {}
        if voter.get("enrolmentStatus") != "enrolled":
            raise BallotRejected(403, "Only enrolled voters can vote", "not_enrolled")
        if voter.get("voted") is True:
            raise BallotRejected(409, "A ballot has already been recorded for you", "double_vote_attempt")
        election_ref = _open_election(tx)
        house = _house_ballot(tx, election_ref, voter, body.house.preferences)
        senate = _senate_ballot(tx, election_ref, voter, body.senate.aboveTheLine, body.senate.belowTheLine)
        tx.create(election_ref.collection("houseBallots").document(), house)
        tx.create(election_ref.collection("senateBallots").document(), senate)
        tx.update(voter_ref, {"voted": True})
        return issue_receipt(tx, election_ref.id)

    try:
        receipt, recorded_at = cast(transaction)
    except BallotRejected as exc:
        try:
            audit_standalone(
                actor={"staffId": voter_id, "role": "voter"}, action="ballot.rejected",
                category="voting", target_type="voter", target_id=voter_id,
                target_path=voter_ref.path, before=None, after=None,
                outcome="denied", reason=exc.reason, request=request,
            )
        except Exception:
            logger.exception("Unable to record rejected ballot")
        raise
    except Exception as exc:
        logger.exception("Ballot submission failed")
        raise HTTPException(status_code=400, detail="Unable to record your ballot") from exc
    return {"receipt": receipt, "recordedAt": recorded_at.isoformat()}


@router.post("/ballots", status_code=201)
@limiter.limit("10/minute")
def cast_ballot(body: BallotSubmission, request: Request,
                voter: dict[str, Any] = Depends(current_voter)) -> dict[str, str]:
    return record_ballot(voter["voterId"], body, request)
