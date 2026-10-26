"""Voter ballot routes: read the ballot paper, start a voting session, then submit one encrypted ballot.

Both routes need a voter's Firebase token and an allowed voter IP address. The
work is done in ``voter_ballots``: starting marks the voter as voting for 15
minutes (R-04); submitting stores the encrypted ballot, marks the voter as
having voted (R-05) and returns a one-time receipt code (R-06).
"""
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import StringConstraints
from typing_extensions import Annotated

from backend.auth import enforce_voter_ip_allowlist
from backend.models import BallotSubmission
from backend.rate_limit import limiter
from backend.routers.voter_ballots import current_ballot, current_voter, record_ballot, start_session
from backend.security.key_management import get_encryption_service

router = APIRouter(prefix="/api/voter/ballots", tags=["Voter Ballots"])

ElectionId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


@router.get("/current")
@limiter.limit("30/minute")
def ballot_paper(
    request: Request,
    voter: dict[str, Any] = Depends(current_voter),
    _: None = Depends(enforce_voter_ip_allowlist),
) -> dict[str, Any]:
    """The open election and this voter's House and Senate ballot papers."""
    return current_ballot(voter)


@router.post("/{election_id}/start", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
def start_voting_session(
    election_id: ElectionId,
    request: Request,
    voter: dict[str, Any] = Depends(current_voter),
    _: None = Depends(enforce_voter_ip_allowlist),
) -> dict[str, Any]:
    expires_at = start_session(voter["voterId"], election_id, request)
    return {"electionId": election_id, "voting": True, "expiresAt": expires_at.isoformat()}


@router.post("/{election_id}/submit", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def submit_ballot(
    election_id: ElectionId,
    ballot: BallotSubmission,
    request: Request,
    voter: dict[str, Any] = Depends(current_voter),
    _: None = Depends(enforce_voter_ip_allowlist),
) -> dict[str, str]:
    return record_ballot(voter["voterId"], election_id, ballot, request,
                         encryption=get_encryption_service())
