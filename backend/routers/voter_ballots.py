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


def _party(parties: dict[str, dict[str, Any]], party_id: str | None) -> str:
    return (parties.get(party_id or "") or {}).get("name") or "Independent"


def _entry(candidate_id: str, candidate: dict[str, Any], parties: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {"id": candidate_id, "name": candidate.get("name", candidate_id),
            "party": _party(parties, candidate.get("partyId"))}


def current_ballot(voter: dict[str, Any]) -> dict[str, Any]:
    """The open election and this voter's House and Senate ballot papers, in ballot order.

    Only contests and choices the submit route accepts are listed: the voter's
    division, their state's groups with candidates, and usable candidates.
    """
    if voter.get("enrolmentStatus") != "enrolled":
        raise HTTPException(status_code=403, detail="Only enrolled voters can vote")
    opened = list(db.collection("elections").where("status", "==", "open").limit(2).stream())
    if len(opened) != 1:
        raise HTTPException(status_code=404, detail="Voting is not open")
    election_ref, election = opened[0].reference, opened[0].to_dict() or {}
    summary = {"id": election_ref.id, "name": election.get("name", election_ref.id),
               "openAt": election.get("openAt"), "closeAt": election.get("closeAt")}
    expires_at = voter.get("sessionExpiresAt")
    status = {"hasVoted": has_voted(voter, election_ref.id),
              "sessionExpiresAt": expires_at if _session_active(voter, election_ref.id) else None}
    if status["hasVoted"]:
        return {"election": summary, "voter": status, "house": None, "senate": None}

    division_id, state_id = voter.get("divisionId"), voter.get("stateId")
    if not division_id or not state_id:
        raise HTTPException(status_code=409, detail="Your enrolment has no division")
    parties = {item.id: item.to_dict() or {} for item in election_ref.collection("parties").stream()}
    usable = {item.id: item.to_dict() or {} for item in election_ref.collection("candidates").stream() if _usable(item)}

    house = sorted(((cid, c) for cid, c in usable.items()
                    if c.get("chamber") == "house" and c.get("divisionId") == division_id),
                   key=lambda item: (item[1].get("ballotPosition", 0), item[0]))
    senate = {cid: c for cid, c in usable.items() if c.get("chamber") == "senate" and c.get("stateId") == state_id}
    groups = sorted(((item.id, item.to_dict() or {}) for item in
                     election_ref.collection("senateGroups").where("stateId", "==", state_id).stream()),
                    key=lambda item: (item[1].get("columnPosition", 0), item[0]))
    ungrouped = sorted(((cid, c) for cid, c in senate.items() if not c.get("groupId")),
                       key=lambda item: (item[1].get("ballotPosition", 0), item[0]))
    division = election_ref.collection("divisions").document(division_id).get().to_dict() or {}
    region = election_ref.collection("senateRegions").document(state_id).get().to_dict() or {}

    return {
        "election": summary,
        "voter": status,
        "house": {
            "divisionId": division_id,
            "divisionName": division.get("name", division_id),
            "candidates": [_entry(cid, c, parties) for cid, c in house],
        },
        "senate": {
            "stateId": state_id,
            "regionName": region.get("name", state_id),
            "senatorsToElect": int(region.get("senatorsToElect", 0)),
            "minimumAbove": ballots.SENATE_BTL_MINIMUM,
            "minimumBelow": ballots.SENATE_BTL_MINIMUM,
            "groups": [
                {"id": group_id, "letter": group.get("groupLetter", ""),
                 "name": group.get("displayName", group_id), "party": _party(parties, group.get("partyId")),
                 "candidates": [_entry(cid, senate[cid], parties)
                                for cid in group.get("candidateOrder") or [] if cid in senate]}
                for group_id, group in groups if group.get("candidateOrder")
            ],
            "ungrouped": [_entry(cid, c, parties) for cid, c in ungrouped],
        },
    }


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

    Ballots are stored encrypted and sealed to their own ID, contest and
    election (R-15), without any voter reference or timestamp, and
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
        # Each ballot is sealed to its own ID and contest (R-15), so its ID is chosen first.
        house_ref = election_ref.collection("houseBallots").document()
        senate_ref = election_ref.collection("senateBallots").document()
        tx.create(house_ref, ballots.house_document(election_id, house_ref.id, division_id,
                                                    body.house.preferences, encryption))
        tx.create(senate_ref, ballots.senate_document(election_id, senate_ref.id, state_id, body.senate.aboveTheLine,
                                                      body.senate.belowTheLine, encryption))
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
