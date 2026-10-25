"""Voter ballot-session endpoints.

Implements atomic voting-state controls:

- A voter may start only one voting session.
- A voter who has already voted cannot start or submit another ballot.
- A ballot can be submitted only during an active voting session.
- Ballot content is encrypted at rest using AES-256-GCM.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import firestore

from backend.dependencies.auth import get_current_firebase_user
from backend.models import BallotSubmission
from backend.security.key_management import get_encryption_service

router = APIRouter(
    prefix="/api/voter/ballots",
    tags=["voter-ballots"],
)

VOTERS_COLLECTION = "voters"
BALLOTS_COLLECTION = "ballots"
AUDIT_COLLECTION = "auditLogs"


def _get_voter_by_auth_uid(
    db,
    uid: str,
):
    """Return the Firestore document for the authenticated voter."""
    documents = (
        db.collection(VOTERS_COLLECTION)
        .where("authUid", "==", uid)
        .limit(1)
        .stream()
    )

    for document in documents:
        return document

    return None


@router.post(
    "/{election_id}/start",
    status_code=status.HTTP_200_OK,
    summary="Start Voting Session",
)
def start_voting_session(
    election_id: str,
    decoded_token: dict = Depends(get_current_firebase_user),
) -> dict:
    """Atomically mark an eligible voter as currently voting.

    Prevents concurrent voting sessions and rejects voters who have already
    voted, are not enrolled, or are not eligible.
    """
    uid = decoded_token["uid"]
    db = firestore.client()

    voter_document = _get_voter_by_auth_uid(db, uid)

    if voter_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voter registration not found",
        )

    voter_ref = voter_document.reference
    election_ref = db.collection("elections").document(election_id)

    @firestore.transactional
    def start_session(transaction):
        voter_snapshot = voter_ref.get(transaction=transaction)
        election_snapshot = election_ref.get(transaction=transaction)

        if not election_snapshot.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Election not found",
            )

        election_data = election_snapshot.to_dict() or {}

        if election_data.get("phase") != "open":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Voting is not currently open for this election",
            )

        if not voter_snapshot.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voter registration not found",
            )

        voter_data = voter_snapshot.to_dict() or {}

        if voter_data.get("enrolmentStatus") != "approved":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Voter enrolment has not been approved",
            )

        if voter_data.get("eligibilityStatus") != "approved":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Voter is not eligible to vote",
            )

        if voter_data.get("voted") is True:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Voter has already voted in this election",
            )

        voted_elections = voter_data.get("votedElections") or {}

        if election_id in voted_elections:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Voter has already voted in this election",
            )

        if voter_data.get("voting") is True:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A voting session is already active",
            )

        transaction.update(
            voter_ref,
            {
                "voting": True,
                "activeElectionId": election_id,
                "votingSessionStartedAt": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            },
        )

    try:
        start_session(db.transaction())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to start voting session",
        ) from exc

    return {
        "electionId": election_id,
        "voting": True,
        "message": "Voting session started",
    }


@router.post(
    "/{election_id}/submit",
    status_code=status.HTTP_201_CREATED,
    summary="Submit Ballot",
)
def submit_ballot(
    election_id: str,
    body: BallotSubmission,
    decoded_token: dict = Depends(get_current_firebase_user),
) -> dict:
    """Atomically submit an encrypted ballot and mark the voter as voted."""
    uid = decoded_token["uid"]
    db = firestore.client()

    voter_document = _get_voter_by_auth_uid(db, uid)

    if voter_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voter registration not found",
        )

    voter_ref = voter_document.reference
    election_ref = db.collection("elections").document(election_id)
    ballot_ref = db.collection(BALLOTS_COLLECTION).document()

    encryption = get_encryption_service()

    encrypted_house_preferences = encryption.encrypt(
        repr(body.house.preferences)
    )
    encrypted_senate_above = encryption.encrypt(
        repr(body.senate.aboveTheLine)
    )
    encrypted_senate_below = encryption.encrypt(
        repr(body.senate.belowTheLine)
    )

    ballot_data = {
        "electionId": election_id,
        "housePreferences": (
            encrypted_house_preferences.ciphertext
            if encrypted_house_preferences
            else None
        ),
        "senateAboveTheLine": (
            encrypted_senate_above.ciphertext
            if encrypted_senate_above
            else None
        ),
        "senateBelowTheLine": (
            encrypted_senate_below.ciphertext
            if encrypted_senate_below
            else None
        ),
        "encryption": {
            "housePreferencesKeyId": (
                encrypted_house_preferences.keyId
                if encrypted_house_preferences
                else None
            ),
            "senateAboveTheLineKeyId": (
                encrypted_senate_above.keyId
                if encrypted_senate_above
                else None
            ),
            "senateBelowTheLineKeyId": (
                encrypted_senate_below.keyId
                if encrypted_senate_below
                else None
            ),
        },
        "submittedAt": firestore.SERVER_TIMESTAMP,
    }

    audit_data = {
        "action": "ballot_submitted",
        "actor": {
            "staffId": uid,
            "role": "voter",
        },
        "target": {
            "collection": BALLOTS_COLLECTION,
            "documentId": ballot_ref.id,
        },
        "electionId": election_id,
        "before": None,
        "after": {
            "voted": True,
            "voting": False,
        },
        "timestamp": firestore.SERVER_TIMESTAMP,
    }

    @firestore.transactional
    def submit_vote(transaction):
        voter_snapshot = voter_ref.get(transaction=transaction)
        election_snapshot = election_ref.get(transaction=transaction)

        if not election_snapshot.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Election not found",
            )

        election_data = election_snapshot.to_dict() or {}

        if election_data.get("phase") != "open":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Voting is not currently open for this election",
            )

        if not voter_snapshot.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voter registration not found",
            )

        voter_data = voter_snapshot.to_dict() or {}

        if voter_data.get("voted") is True:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Voter has already voted in this election",
            )

        voted_elections = voter_data.get("votedElections") or {}

        if election_id in voted_elections:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Voter has already voted in this election",
            )

        if voter_data.get("voting") is not True:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No active voting session",
            )

        if voter_data.get("activeElectionId") != election_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Active voting session is for a different election",
            )

        updated_voted_elections = dict(voted_elections)
        updated_voted_elections[election_id] = True

        transaction.set(ballot_ref, ballot_data)

        transaction.update(
            voter_ref,
            {
                "voting": False,
                "voted": True,
                "votedAt": firestore.SERVER_TIMESTAMP,
                "activeElectionId": None,
                "votedElections": updated_voted_elections,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            },
        )

        transaction.set(
            db.collection(AUDIT_COLLECTION).document(),
            audit_data,
        )

    try:
        submit_vote(db.transaction())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to submit ballot",
        ) from exc

    return {
        "ballotId": ballot_ref.id,
        "electionId": election_id,
        "voted": True,
        "message": "Ballot submitted successfully",
    }