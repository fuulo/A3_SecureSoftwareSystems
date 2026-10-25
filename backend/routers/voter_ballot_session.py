import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from firebase_admin import firestore
from pydantic import StringConstraints
from typing_extensions import Annotated

from backend.auth import enforce_voter_ip_allowlist, verify_token
from backend.models import BallotSubmission
from backend.security.encryption import EncryptedValue

router = APIRouter(prefix="/api/voter/ballots", tags=["Voter Ballots"])

VOTERS_COLLECTION = "voters"
ELECTIONS_COLLECTION = "elections"
BALLOTS_COLLECTION = "ballots"
AUDIT_LOGS_COLLECTION = "auditLogs"

SESSION_DURATION_MINUTES = 15

ElectionId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


def get_encryption_service():
    raise NotImplementedError("Encryption service is not configured")


async def get_current_firebase_user(
    current_user: Any = Depends(verify_token),
) -> dict[str, Any]:
    if isinstance(current_user, dict):
        return current_user

    uid = getattr(current_user, "uid", None)

    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        )

    return {"uid": uid}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_voter(
    db: firestore.Client,
    transaction: firestore.Transaction,
    auth_uid: str,
):
    voters = (
        db.collection(VOTERS_COLLECTION)
        .where("authUid", "==", auth_uid)
        .limit(1)
        .stream()
    )

    for voter_snapshot in voters:
        return voter_snapshot

    return None


def _validate_voter(
    voter_snapshot,
    election_id: str,
) -> dict[str, Any]:
    if voter_snapshot is None or not voter_snapshot.exists:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voter profile not found",
        )

    voter = voter_snapshot.to_dict() or {}

    if voter.get("enrolmentStatus") != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voter enrolment is not approved",
        )

    if voter.get("eligibilityStatus") != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voter is not eligible to vote",
        )

    if voter.get("voted", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voter has already submitted a ballot",
        )

    if voter.get("voting", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voter already has an active voting session",
        )

    voted_elections = voter.get("votedElections") or {}

    if voted_elections.get(election_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voter has already voted in this election",
        )

    return voter


def _get_open_election(
    db: firestore.Client,
    transaction: firestore.Transaction,
    election_id: str,
):
    election_ref = db.collection(ELECTIONS_COLLECTION).document(election_id)
    election_snapshot = election_ref.get(transaction=transaction)

    if not election_snapshot.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Election not found",
        )

    election = election_snapshot.to_dict() or {}

    if election.get("status") != "open" or election.get("phase") != "open":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Election is not open for voting",
        )

    return election_ref, election


@router.post("/{election_id}/start", status_code=status.HTTP_200_OK)
async def start_voting_session(
    election_id: ElectionId,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_firebase_user),
    _: None = Depends(enforce_voter_ip_allowlist),
):
    auth_uid = current_user["uid"]
    db = firestore.client()

    try:
        transaction = db.transaction()

        voter_snapshot = _get_voter(db, transaction, auth_uid)
        voter = _validate_voter(voter_snapshot, election_id)

        _get_open_election(db, transaction, election_id)

        voter_ref = voter_snapshot.reference
        expires_at = _utc_now() + timedelta(minutes=SESSION_DURATION_MINUTES)

        transaction.update(
            voter_ref,
            {
                "voting": True,
                "activeElectionId": election_id,
                "sessionExpiresAt": expires_at,
            },
        )

        return {
            "electionId": election_id,
            "voting": True,
            "expiresAt": expires_at.isoformat(),
        }

    except HTTPException:
        raise
    except Exception:
        logging.exception("Unable to start voting session")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to start voting session",
        )


@router.post("/{election_id}/submit", status_code=status.HTTP_201_CREATED)
async def submit_ballot(
    election_id: ElectionId,
    ballot: BallotSubmission,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_firebase_user),
    _: None = Depends(enforce_voter_ip_allowlist),
):
    auth_uid = current_user["uid"]
    db = firestore.client()

    try:
        transaction = db.transaction()

        voter_snapshot = _get_voter(db, transaction, auth_uid)

        if voter_snapshot is None or not voter_snapshot.exists:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Voter profile not found",
            )

        voter = voter_snapshot.to_dict() or {}

        if voter.get("activeElectionId") != election_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No active voting session for this election",
            )

        if not voter.get("voting", False):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Voting session is not active",
            )

        if voter.get("voted", False):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Voter has already submitted a ballot",
            )

        _get_open_election(db, transaction, election_id)

        encryption_service = get_encryption_service()

        encrypted_house_preferences = encryption_service.encrypt(
            json.dumps(ballot.house.preferences, separators=(",", ":"))
        )
        encrypted_senate_above_the_line = encryption_service.encrypt(
            json.dumps(ballot.senate.aboveTheLine, separators=(",", ":"))
        )
        encrypted_senate_below_the_line = encryption_service.encrypt(
            json.dumps(ballot.senate.belowTheLine, separators=(",", ":"))
        )

        ballot_ref = db.collection(BALLOTS_COLLECTION).document()
        ballot_id = ballot_ref.id

        transaction.set(
            ballot_ref,
            {
                "ballotId": ballot_id,
                "electionId": election_id,
                "housePreferences": encrypted_house_preferences.ciphertext,
                "senateAboveTheLine": encrypted_senate_above_the_line.ciphertext,
                "senateBelowTheLine": encrypted_senate_below_the_line.ciphertext,
                "keyId": encrypted_house_preferences.keyId,
                "submittedAt": _utc_now(),
            },
        )

        voter_ref = voter_snapshot.reference
        voted_elections = voter.get("votedElections") or {}
        voted_elections[election_id] = True

        transaction.update(
            voter_ref,
            {
                "voted": True,
                "voting": False,
                "activeElectionId": None,
                "votedElections": voted_elections,
            },
        )

        return {
            "receipt": ballot_id,
            "electionId": election_id,
            "voted": True,
        }

    except HTTPException:
        raise
    except Exception:
        logging.exception("Unable to submit ballot")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to submit ballot",
        )