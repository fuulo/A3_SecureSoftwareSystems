"""Every ballot is checked before it is counted (R-15).

A ballot passes only if it decrypts with its own election, chamber, contest, ID
and source as associated data, and its choices are valid for its contest
(``backend.ballots``). A ballot that fails is left out of the count and flagged
in ``elections/{id}/flaggedBallots/{chamber}-{ballotId}``, with an audit entry.
A flagged ballot stays excluded even if it would pass later.

An admin must review every flag before the election can be finalised or its
results published. Reviewing records who looked at the flag and why; it never
puts the ballot back into the count. Flags name the ballot and the failed check,
never its choices, so reviewing them does not reveal how anyone voted.
"""
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from google.cloud import firestore

from backend import ballots
from backend.audit import audit_standalone, write_audit
from backend.firestore_client import db
from backend.security.encryption import EncryptionService
from backend.security.key_management import get_encryption_service

logger = logging.getLogger(__name__)
# Ballots are only opened once voting has closed
CHECKABLE_PHASES = {"closed", "counting", "finalised"}
# chamber, ballot collection, contest field
CHAMBERS = (("house", "houseBallots", "divisionId"), ("senate", "senateBallots", "stateId"))
NO_HOUSE_CONTEST = ballots.HouseContest(frozenset(), 0)
NO_SENATE_CONTEST = ballots.SenateContest(frozenset(), frozenset(), 0)


@dataclass
class BallotCheck:
    """The ballots that passed, ready to count, and how many were left out."""
    house: list[dict[str, Any]]
    senate: list[dict[str, Any]]
    excluded_house: int
    excluded_senate: int
    pending_flags: int

    def summary(self) -> dict[str, int]:
        return {"countedHouseBallots": len(self.house), "countedSenateBallots": len(self.senate),
                "excludedHouseBallots": self.excluded_house, "excludedSenateBallots": self.excluded_senate,
                "pendingFlags": self.pending_flags}


def _flag_id(chamber: str, ballot_id: str) -> str:
    return f"{chamber}-{ballot_id}"


def _contests(election_ref: Any) -> dict[str, dict[str, Any]]:
    """Each contest's valid choices, by chamber and then division or state."""
    members: dict[str, dict[str, set[str]]] = {"house": defaultdict(set), "senate": defaultdict(set)}
    standing: Counter[tuple[str, str]] = Counter()
    for item in election_ref.collection("candidates").stream():
        candidate = item.to_dict() or {}
        chamber = candidate.get("chamber")
        contest_id = candidate.get("divisionId" if chamber == "house" else "stateId")
        if chamber not in members or not contest_id:
            continue
        members[chamber][contest_id].add(item.id)
        if candidate.get("withdrawn") is not True and candidate.get("excluded") is not True:
            standing[(chamber, contest_id)] += 1
    groups: dict[str, set[str]] = defaultdict(set)
    for item in election_ref.collection("senateGroups").stream():
        state_id = (item.to_dict() or {}).get("stateId")
        if state_id:
            groups[state_id].add(item.id)
    return {
        "house": {division_id: ballots.HouseContest(frozenset(ids), standing[("house", division_id)])
                  for division_id, ids in members["house"].items()},
        "senate": {state_id: ballots.SenateContest(frozenset(groups[state_id]),
                                                   frozenset(members["senate"][state_id]),
                                                   standing[("senate", state_id)])
                   for state_id in set(members["senate"]) | set(groups)},
    }


def _encryption() -> EncryptionService:
    try:
        return get_encryption_service()
    except Exception as exc:
        # Not the ballots' fault, so nothing is flagged
        logger.exception("Ballot encryption keys could not be loaded")
        raise HTTPException(status_code=503, detail="Ballot keys are unavailable, so ballots could not be checked") from exc


def _open(election_id: str, chamber: str, ballot_id: str, document: dict[str, Any],
          encryption: EncryptionService, contests: dict[str, dict[str, Any]], contest_id: str | None) -> dict[str, Any]:
    if chamber == "house":
        contest = contests["house"].get(contest_id, NO_HOUSE_CONTEST)
        return ballots.open_house(election_id, ballot_id, document, encryption, contest)
    contest = contests["senate"].get(contest_id, NO_SENATE_CONTEST)
    return ballots.open_senate(election_id, ballot_id, document, encryption, contest)


def _record_flag(election_ref: Any, failure: dict[str, Any], actor: dict[str, Any] | None,
                 request: Request) -> None:
    flag_ref = election_ref.collection("flaggedBallots").document(failure["flagId"])
    transaction = db.transaction()

    @firestore.transactional
    def record(tx: Any) -> None:
        if flag_ref.get(transaction=tx).exists:
            return
        write_audit(tx, actor=actor, action="ballot.integrityFailed", category="counting",
                    target_type="ballot", target_id=failure["flagId"], target_path=failure["ballotPath"],
                    before=None,
                    after={"chamber": failure["chamber"], "contestId": failure["contestId"],
                           "reason": failure["reason"]},
                    outcome="failed", reason=failure["reason"], request=request, election_id=election_ref.id)
        tx.create(flag_ref, {**failure, "status": "pending",
                             "detectedAt": firestore.SERVER_TIMESTAMP, "detectedBy": (actor or {}).get("staffId"),
                             "reviewedBy": None, "reviewedAt": None, "reviewNote": None})

    record(transaction)


def check_ballots(election_id: str, actor: dict[str, Any] | None, request: Request) -> BallotCheck:
    """Check every ballot, flag any new failures, and return the ballots that may be counted."""
    election_ref = db.collection("elections").document(election_id)
    stored = {chamber: [(item.id, item.to_dict() or {}) for item in election_ref.collection(collection).stream()]
              for chamber, collection, _ in CHAMBERS}
    encryption = _encryption() if any(stored.values()) else None
    contests = _contests(election_ref)
    flags = {item.id: item.to_dict() or {} for item in election_ref.collection("flaggedBallots").stream()}

    counted: dict[str, list[dict[str, Any]]] = {"house": [], "senate": []}
    for chamber, collection, contest_field in CHAMBERS:
        for ballot_id, document in stored[chamber]:
            contest_id = document.get(contest_field)
            contest_id = contest_id if isinstance(contest_id, str) else None
            try:
                ballot = _open(election_id, chamber, ballot_id, document, encryption, contests, contest_id)
            except ballots.BallotInvalid as exc:
                flag_id = _flag_id(chamber, ballot_id)
                if flag_id not in flags:
                    failure = {"flagId": flag_id, "chamber": chamber, "ballotId": ballot_id,
                               "ballotPath": f"{election_ref.path}/{collection}/{ballot_id}",
                               "contestId": contest_id, "reason": exc.reason}
                    _record_flag(election_ref, failure, actor, request)
                    flags[flag_id] = {**failure, "status": "pending"}
                continue
            if _flag_id(chamber, ballot_id) not in flags:
                counted[chamber].append(ballot)

    return BallotCheck(
        house=counted["house"], senate=counted["senate"],
        excluded_house=len(stored["house"]) - len(counted["house"]),
        excluded_senate=len(stored["senate"]) - len(counted["senate"]),
        pending_flags=sum(1 for flag in flags.values() if flag.get("status") == "pending"),
    )


def ballots_to_count(election_id: str, actor: dict[str, Any] | None, request: Request) -> BallotCheck:
    """check_ballots, refusing with 409 while any flagged ballot awaits review."""
    check = check_ballots(election_id, actor, request)
    if check.pending_flags:
        raise HTTPException(status_code=409, detail=(
            f"{check.pending_flags} ballot(s) failed integrity checks and must be reviewed "
            "before results are finalised or published"))
    return check


def run_check(election_id: str, actor: dict[str, Any], request: Request) -> dict[str, int]:
    """Admin-requested check: flags failures without finalising anything."""
    snapshot = db.collection("elections").document(election_id).get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Election not found")
    if (snapshot.to_dict() or {}).get("status") not in CHECKABLE_PHASES:
        raise HTTPException(status_code=409, detail="Ballots can only be checked once voting has closed")
    summary = check_ballots(election_id, actor, request).summary()
    try:
        audit_standalone(actor=actor, action="ballot.integrityCheck", category="counting",
                         target_type="election", target_id=election_id, target_path=f"elections/{election_id}",
                         before=None, after=summary, outcome="success", reason=None,
                         request=request, election_id=election_id)
    except Exception:
        logger.exception("Unable to record ballot integrity check")
    return summary


def list_flags(election_id: str) -> list[dict[str, Any]]:
    """Flagged ballots, those awaiting review first."""
    election_ref = db.collection("elections").document(election_id)
    if not election_ref.get().exists:
        raise HTTPException(status_code=404, detail="Election not found")
    flags = [{**(item.to_dict() or {}), "flagId": item.id}
             for item in election_ref.collection("flaggedBallots").stream()]
    return sorted(flags, key=lambda flag: (flag.get("status") != "pending", flag["flagId"]))


def review_flag(election_id: str, flag_id: str, note: str, actor: dict[str, Any],
                request: Request) -> dict[str, str]:
    """Record an admin's review of a flagged ballot. The ballot stays excluded."""
    flag_ref = db.collection("elections").document(election_id).collection("flaggedBallots").document(flag_id)
    transaction = db.transaction()

    @firestore.transactional
    def review(tx: Any) -> None:
        snapshot = flag_ref.get(transaction=tx)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Flagged ballot not found")
        flag = snapshot.to_dict() or {}
        if flag.get("status") != "pending":
            raise HTTPException(status_code=409, detail="This flagged ballot has already been reviewed")
        write_audit(tx, actor=actor, action="ballot.flagReviewed", category="counting",
                    target_type="ballot", target_id=flag_id, target_path=flag.get("ballotPath"),
                    before={"status": "pending"},
                    after={"status": "reviewed", "reason": flag.get("reason"), "note": note},
                    outcome="success", reason=None, request=request, election_id=election_id)
        tx.update(flag_ref, {"status": "reviewed", "reviewedBy": actor.get("staffId"),
                             "reviewedAt": firestore.SERVER_TIMESTAMP, "reviewNote": note})

    try:
        review(transaction)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Flagged ballot review failed")
        raise HTTPException(status_code=400, detail="Unable to record the review") from exc
    return {"flagId": flag_id, "status": "reviewed"}
