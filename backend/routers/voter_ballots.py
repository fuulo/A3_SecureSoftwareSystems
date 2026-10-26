"""Casting a ballot: the voting session and the single transaction that records a vote.

The HTTP routes are in ``voter_ballot_session``. A voter first starts a voting
session for an election (R-04), then submits one ballot. Submitting validates
the ballot, stores it encrypted in the election's ``houseBallots`` and
``senateBallots`` (``backend.ballots``), marks the voter as having voted in
that election (R-05) and issues a hashed receipt (R-06), all in one
transaction.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request
from google.cloud import firestore

from backend import ballots
from backend.audit import audit_standalone
from backend.auth import verify_token
from backend.firestore_client import db
from backend.models import BallotSubmission
from backend.receipts import issue_receipt
from backend.reconciliation import has_voted, voted_field
from backend.security.encryption import EncryptionService

logger = logging.getLogger(__name__)
SESSION_DURATION_MINUTES = 15


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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _usable(snapshot: Any) -> bool:
    data = snapshot.to_dict() or {}
    return data.get("withdrawn") is not True and data.get("excluded") is not True


def _unique_known(choices: list[str], known: set[str], label: str) -> None:
    if len(set(choices)) != len(choices):
        raise BallotRejected(422, f"Each {label} can only be numbered once", "duplicate_preference")
    if any(choice not in known for choice in choices):
        raise BallotRejected(422, f"Ballot contains an unknown {label}", "unknown_choice")


def _check_voter(voter: dict[str, Any], election_id: str) -> None:
    if voter.get("enrolmentStatus") != "enrolled":
        raise BallotRejected(403, "Only enrolled voters can vote", "not_enrolled")
    if has_voted(voter, election_id):
        raise BallotRejected(409, "A ballot has already been recorded for you", "double_vote_attempt")


def _open_election(tx: Any, election_id: str) -> Any:
    snapshot = db.collection("elections").document(election_id).get(transaction=tx)
    election = (snapshot.to_dict() or {}) if snapshot.exists else {}
    if election.get("status") != "open":
        raise BallotRejected(409, "Voting is not open", "election_not_open")
    now = _now()
    open_at, close_at = election.get("openAt"), election.get("closeAt")
    if isinstance(open_at, datetime) and now < open_at:
        raise BallotRejected(409, "Voting has not started", "election_not_started")
    if isinstance(close_at, datetime) and now >= close_at:
        raise BallotRejected(409, "Voting has closed", "election_closed")
    return snapshot.reference


def _session_active(voter: dict[str, Any], election_id: str) -> bool:
    expires_at = voter.get("sessionExpiresAt")
    return (voter.get("voting") is True and voter.get("activeElectionId") == election_id
            and isinstance(expires_at, datetime) and _now() < expires_at)


def _house_choices(tx: Any, election_ref: Any, voter: dict[str, Any], preferences: list[str]) -> str:
    division_id = voter.get("divisionId")
    if not division_id:
        raise BallotRejected(409, "Your enrolment has no division", "no_division")
    candidates = {
        item.id for item in election_ref.collection("candidates").where("divisionId", "==", division_id).stream(transaction=tx)
        if (item.to_dict() or {}).get("chamber") == "house" and _usable(item)
    }
    _unique_known(preferences, candidates, "House candidate")
    return division_id


def _senate_choices(tx: Any, election_ref: Any, voter: dict[str, Any], above: list[str], below: list[str]) -> str:
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
    return state_id


def _audit_rejection(action: str, voter_id: str, voter_ref: Any, exc: BallotRejected,
                     request: Request, election_id: str) -> None:
    try:
        audit_standalone(
            actor={"staffId": voter_id, "role": "voter"}, action=action,
            category="voting", target_type="voter", target_id=voter_id,
            target_path=voter_ref.path, before=None, after=None,
            outcome="denied", reason=exc.reason, request=request, election_id=election_id,
        )
    except Exception:
        logger.exception("Unable to record rejected %s", action)


def start_session(voter_id: str, election_id: str, request: Request) -> datetime:
    """Mark the voter as voting in this election for SESSION_DURATION_MINUTES (R-04)."""
    voter_ref = db.collection("voters").document(voter_id)
    transaction = db.transaction()

    @firestore.transactional
    def start(tx: Any) -> datetime:
        voter = voter_ref.get(transaction=tx).to_dict() or {}
        _check_voter(voter, election_id)
        if voter.get("voting") is True and _session_active(voter, voter.get("activeElectionId") or ""):
            raise BallotRejected(409, "You already have an active voting session", "session_already_active")
        _open_election(tx, election_id)
        expires_at = _now() + timedelta(minutes=SESSION_DURATION_MINUTES)
        tx.update(voter_ref, {"voting": True, "activeElectionId": election_id, "sessionExpiresAt": expires_at})
        return expires_at

    try:
        return start(transaction)
    except BallotRejected as exc:
        _audit_rejection("ballot.session.rejected", voter_id, voter_ref, exc, request, election_id)
        raise
    except Exception as exc:
        logger.exception("Voting session start failed")
        raise HTTPException(status_code=400, detail="Unable to start your voting session") from exc


def record_ballot(voter_id: str, election_id: str, body: BallotSubmission, request: Request, *,
                  encryption: EncryptionService, require_session: bool = True) -> dict[str, str]:
    """Record one voter's House and Senate ballots and return their receipt.

    Ballots are stored encrypted, without any voter reference or timestamp, and
    the voter record only gains ``voted: true`` and the election it voted in, so
    a ballot cannot be traced to a voter. ``require_session`` is turned off only
    by trusted internal callers such as the demo seed.
    """
    voter_ref = db.collection("voters").document(voter_id)
    transaction = db.transaction()

    @firestore.transactional
    def cast(tx: Any) -> tuple[str, datetime]:
        voter = voter_ref.get(transaction=tx).to_dict() or {}
        _check_voter(voter, election_id)
        if require_session and not _session_active(voter, election_id):
            raise BallotRejected(409, "Your voting session has expired or was not started", "no_active_session")
        election_ref = _open_election(tx, election_id)
        division_id = _house_choices(tx, election_ref, voter, body.house.preferences)
        state_id = _senate_choices(tx, election_ref, voter, body.senate.aboveTheLine, body.senate.belowTheLine)
        tx.create(election_ref.collection("houseBallots").document(),
                  ballots.house_document(division_id, body.house.preferences, encryption))
        tx.create(election_ref.collection("senateBallots").document(),
                  ballots.senate_document(state_id, body.senate.aboveTheLine, body.senate.belowTheLine, encryption))
        tx.update(voter_ref, {"voted": True, voted_field(election_id): True,
                              "voting": False, "activeElectionId": None, "sessionExpiresAt": None})
        return issue_receipt(tx, election_id)

    try:
        receipt, recorded_at = cast(transaction)
    except BallotRejected as exc:
        _audit_rejection("ballot.rejected", voter_id, voter_ref, exc, request, election_id)
        raise
    except Exception as exc:
        logger.exception("Ballot submission failed")
        raise HTTPException(status_code=400, detail="Unable to record your ballot") from exc
    return {"receipt": receipt, "recordedAt": recorded_at.isoformat(), "electionId": election_id}
