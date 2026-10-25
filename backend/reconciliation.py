"""One vote per voter, checked after voting closes (R-05).

Ballots carry no voter reference, so the only reconciliation that keeps the
ballot secret is by totals: the voters marked as having voted in an election
must equal its House ballots, its Senate ballots and its issued receipts.
Each voter records the elections they voted in as ``votedElections.{id}``.
"""
import logging
from typing import Any

from fastapi import HTTPException, Request

from backend.audit import audit_standalone
from backend.firestore_client import db

logger = logging.getLogger(__name__)

COUNT_LABELS = {
    "votersMarkedVoted": "voters marked voted",
    "houseBallots": "House ballots",
    "senateBallots": "Senate ballots",
    "receiptsIssued": "receipts issued",
}


def voted_field(election_id: str) -> str:
    return f"votedElections.{election_id}"


def has_voted(voter: dict[str, Any], election_id: str) -> bool:
    voted_in = voter.get("votedElections")
    if voted_in is None:
        # Records from before votes were tied to an election: fail safe.
        return voter.get("voted") is True
    return voted_in.get(election_id) is True


def _count(query: Any) -> int:
    return int(query.count().get()[0][0].value)


def reconcile_votes(election_id: str) -> dict[str, Any]:
    """Count voters marked voted, ballots and receipts, and whether they all match."""
    election_ref = db.collection("elections").document(election_id)
    counts = {
        "votersMarkedVoted": _count(db.collection("voters").where(voted_field(election_id), "==", True)),
        "houseBallots": _count(election_ref.collection("houseBallots")),
        "senateBallots": _count(election_ref.collection("senateBallots")),
        "receiptsIssued": _count(db.collection("receipts").where("electionId", "==", election_id)),
    }
    return {**counts, "reconciled": len(set(counts.values())) == 1}


def describe(result: dict[str, Any]) -> list[str]:
    return [f"{result[key]} {label}" for key, label in COUNT_LABELS.items()]


def require_reconciled(election_id: str, actor: dict[str, Any] | None, request: Request) -> dict[str, Any]:
    """Return the reconciliation, or log the mismatch for investigation and refuse with 409."""
    result = reconcile_votes(election_id)
    if not result["reconciled"]:
        try:
            audit_standalone(
                actor=actor, action="election.reconcile", category="counting",
                target_type="election", target_id=election_id, target_path=f"elections/{election_id}",
                before=None, after=result, outcome="failed", reason="vote_count_mismatch",
                request=request, election_id=election_id,
            )
        except Exception:
            logger.exception("Unable to record failed vote reconciliation")
        raise HTTPException(status_code=409, detail={"message": "Votes do not reconcile", "missing": describe(result)})
    return result
