"""Builds and publishes the official result package for a finalised election.

The package is frozen as exact JSON bytes when published. Its fingerprint (the
"results" algorithm in backend/security/hashing.py, SHA-256 by default) is
stored next to it with the algorithm's name and written into the audit hash
chain, so a downloaded copy can be checked against the fingerprint on the
results page. The bytes are also signed with Ed25519 (R-09,
``backend.security.signing``), so a copy can be proven genuine with the public
key alone. The package, its signature, the public key and the receipt list are
archived, locked for 7 years (``backend.archive``), before anything is published.

Only ballots that pass their integrity checks are counted (R-15,
``backend.ballot_integrity``); the package reports how many were left out.
"""
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from google.cloud import firestore

from backend.archive import archive_election
from backend.audit import write_audit
from backend.ballot_integrity import ballots_to_count
from backend.firestore_client import db
from backend.receipts import receipt_list
from backend.reconciliation import require_reconciled
from backend.security import hashing, signing

logger = logging.getLogger(__name__)
PACKAGE_VERSION = 5
INDEPENDENT = "Independent"

Docs = dict[str, dict[str, Any]]


def _party_name(parties: Docs, party_id: str | None) -> str:
    return (parties.get(party_id or "") or {}).get("name") or INDEPENDENT


def _shown(candidate: dict[str, Any], votes: int) -> bool:
    # Withdrawn candidates stay listed only if ballots cast before withdrawal still name them.
    return votes > 0 or candidate.get("withdrawn") is not True


def tally_house(divisions: Docs, candidates: Docs, parties: Docs,
                ballots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First-preference House results, one contest per division."""
    cast: Counter[str] = Counter()
    informal: Counter[str] = Counter()
    votes: Counter[str] = Counter()
    for ballot in ballots:
        division_id = ballot.get("divisionId") or ""
        cast[division_id] += 1
        if ballot.get("isFormal") and ballot.get("preferences"):
            votes[ballot["preferences"][0]] += 1
        else:
            informal[division_id] += 1

    by_division: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for candidate_id, candidate in candidates.items():
        if candidate.get("chamber") == "house":
            by_division[candidate.get("divisionId") or ""].append((candidate_id, candidate))

    contests = []
    for division_id in sorted(set(cast) | set(by_division)):
        division = divisions.get(division_id) or {}
        rows = sorted(by_division[division_id], key=lambda item: (item[1].get("ballotPosition", 0), item[0]))
        contests.append({
            "id": f"house-{division_id}",
            "chamber": "house",
            "title": f"House of Representatives - Division of {division.get('name', division_id)}",
            "seats": int(division.get("seatCount", 1)),
            "ballotsCast": cast[division_id],
            "informal": informal[division_id],
            "candidates": [
                {"id": candidate_id, "name": candidate.get("name", candidate_id),
                 "party": _party_name(parties, candidate.get("partyId")), "votes": votes[candidate_id]}
                for candidate_id, candidate in rows if _shown(candidate, votes[candidate_id])
            ],
        })
    return contests


def tally_senate(regions: Docs, groups: Docs, candidates: Docs, parties: Docs,
                 ballots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First-preference Senate results by group, one contest per state or territory."""
    ungrouped = "ungrouped"
    cast: Counter[str] = Counter()
    informal: Counter[str] = Counter()
    votes: Counter[tuple[str, str]] = Counter()
    for ballot in ballots:
        state_id = ballot.get("stateId") or ""
        cast[state_id] += 1
        counted_as = ballot.get("countedAs") if ballot.get("isFormal") else None
        if counted_as == "belowTheLine" and ballot.get("belowTheLine"):
            first = candidates.get(ballot["belowTheLine"][0]) or {}
            votes[(state_id, first.get("groupId") or ungrouped)] += 1
        elif counted_as == "aboveTheLine" and ballot.get("aboveTheLine"):
            votes[(state_id, ballot["aboveTheLine"][0])] += 1
        else:
            informal[state_id] += 1

    has_ungrouped = {
        candidate.get("stateId") for candidate in candidates.values()
        if candidate.get("chamber") == "senate" and not candidate.get("groupId")
    }
    states = set(cast) | {g.get("stateId") for g in groups.values() if g.get("candidateOrder")} | has_ungrouped
    contests = []
    for state_id in sorted(s for s in states if s):
        region = regions.get(state_id) or {}
        rows = sorted(
            ((group_id, group) for group_id, group in groups.items()
             if group.get("stateId") == state_id
             and (group.get("candidateOrder") or votes[(state_id, group_id)])),
            key=lambda item: (item[1].get("columnPosition", 0), item[0]),
        )
        table = [
            {"id": group_id, "name": group.get("displayName", group_id),
             "party": _party_name(parties, group.get("partyId")), "votes": votes[(state_id, group_id)]}
            for group_id, group in rows
        ]
        if state_id in has_ungrouped or votes[(state_id, ungrouped)]:
            table.append({"id": f"{state_id}-{ungrouped}", "name": "Ungrouped candidates",
                          "party": INDEPENDENT, "votes": votes[(state_id, ungrouped)]})
        contests.append({
            "id": f"senate-{state_id}",
            "chamber": "senate",
            "title": f"Senate - {region.get('name', state_id)}",
            "seats": int(region.get("senatorsToElect", 0)),
            "ballotsCast": cast[state_id],
            "informal": informal[state_id],
            "candidates": table,
        })
    return contests


def build_package(election_id: str, election: dict[str, Any], contests: list[dict[str, Any]], *,
                  enrolled: int, ballots_cast: int, senate_ballots_cast: int, voters_marked_voted: int,
                  receipts_issued: int, receipts_fingerprint: str, receipts_hash_algorithm: str,
                  excluded_house_ballots: int, excluded_senate_ballots: int,
                  published_at: datetime) -> dict[str, Any]:
    try:
        local = ZoneInfo(election.get("timezone") or "Australia/Melbourne")
    except Exception:
        local = ZoneInfo("Australia/Melbourne")
    return {
        "packageVersion": PACKAGE_VERSION,
        "election": {
            "id": election_id,
            "name": election.get("name", election_id),
            "status": "Final",
            "publishedAt": published_at.astimezone(local).isoformat(timespec="seconds"),
            "enrolledVoters": enrolled,
            # ballotsCast is the House ballot count, as in version 2 packages. Both
            # counts include ballots excluded for failing integrity checks.
            "ballotsCast": ballots_cast,
            "senateBallotsCast": senate_ballots_cast,
            # Added in version 5: ballots left out of every contest (R-15)
            "excludedHouseBallots": excluded_house_ballots,
            "excludedSenateBallots": excluded_senate_ballots,
            "votersMarkedVoted": voters_marked_voted,
            "receiptsIssued": receipts_issued,
            # Fingerprint of the published receipt list (see backend.receipts.receipt_list),
            # made with the "results" algorithm so browsers can check it.
            "receiptsFingerprint": receipts_fingerprint,
            "receiptsHashAlgorithm": receipts_hash_algorithm,
        },
        "contests": contests,
    }


def package_bytes(package: dict[str, Any]) -> bytes:
    # One line and a fixed key order, so the bytes (and fingerprint) never vary.
    return json.dumps(package, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _docs(collection: Any) -> Docs:
    return {item.id: item.to_dict() or {} for item in collection.stream()}


def _count(query: Any) -> int:
    return int(query.count().get()[0][0].value)


def publish_results(election_id: str, actor: dict[str, Any], request: Request) -> dict[str, str]:
    election_ref = db.collection("elections").document(election_id)
    published_ref = db.collection("publishedResults").document(election_id)
    snapshot = election_ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Election not found")
    election = snapshot.to_dict() or {}
    if election.get("status") != "finalised":
        raise HTTPException(status_code=409, detail="Results can only be published once the election is finalised")
    if published_ref.get().exists:
        raise HTTPException(status_code=409, detail="Results for this election have already been published")
    # Checked again here: finalisation required it, so a mismatch now means records changed since.
    reconciliation = require_reconciled(election_id, actor, request)

    # Ballots cannot change once an election is finalised, so they are read outside the transaction.
    # Checked again here: finalisation required it, so a failure now means a ballot changed since.
    checked = ballots_to_count(election_id, actor, request)
    candidates = _docs(election_ref.collection("candidates"))
    parties = _docs(election_ref.collection("parties"))
    contests = (
        tally_house(_docs(election_ref.collection("divisions")), candidates, parties, checked.house)
        + tally_senate(_docs(election_ref.collection("senateRegions")), _docs(election_ref.collection("senateGroups")),
                       candidates, parties, checked.senate)
    )
    receipts = receipt_list(election_id)
    if receipts.count(b"\n") != reconciliation["receiptsIssued"]:
        raise HTTPException(status_code=409, detail="Receipts changed while publishing; please try again")
    receipts_algorithm, receipts_fingerprint = hashing.digest("results", receipts)
    published_at = datetime.now(timezone.utc)
    package = build_package(
        election_id, election, contests,
        enrolled=_count(db.collection("voters").where("enrolmentStatus", "==", "enrolled")),
        ballots_cast=len(checked.house) + checked.excluded_house,
        senate_ballots_cast=len(checked.senate) + checked.excluded_senate,
        voters_marked_voted=reconciliation["votersMarkedVoted"],
        receipts_issued=reconciliation["receiptsIssued"],
        receipts_fingerprint=receipts_fingerprint,
        receipts_hash_algorithm=receipts_algorithm,
        excluded_house_ballots=checked.excluded_house,
        excluded_senate_ballots=checked.excluded_senate,
        published_at=published_at,
    )
    content = package_bytes(package)
    algorithm, fingerprint = hashing.digest("results", content)
    # Results are never published unsigned
    try:
        signature = signing.sign(content)
        public_key = signing.public_key()
    except signing.SigningKeyMissing as exc:
        logger.exception("Results could not be signed")
        raise HTTPException(status_code=503, detail="Results could not be signed, so they were not published") from exc
    # Kept beside the named fingerprint for readers that expect it
    legacy_field = {"sha256": fingerprint} if algorithm == "sha256" else {}
    # Archived before anything is published, so results never go out without their 7-year copy.
    # The public key goes with the signature, so the copy can be checked after the key is replaced.
    archive = archive_election(election_id, {
        f"result-package-{fingerprint}.json": (content, "application/json"),
        f"result-package-{fingerprint}.sig": (bytes.fromhex(signature["value"]), "application/octet-stream"),
        f"results-signing-key-{signature['keyId']}.pem": (public_key["publicKeyPem"].encode("ascii"),
                                                          "application/x-pem-file"),
        f"receipts-{receipts_fingerprint}.txt": (receipts, "text/plain"),
    }, published_at)
    transaction = db.transaction()

    @firestore.transactional
    def publish(tx: Any) -> None:
        if (election_ref.get(transaction=tx).to_dict() or {}).get("status") != "finalised":
            raise HTTPException(status_code=409, detail="Election is no longer finalised")
        if published_ref.get(transaction=tx).exists:
            raise HTTPException(status_code=409, detail="Results for this election have already been published")
        write_audit(tx, actor=actor, action="results.publish", category="export",
                    target_type="election", target_id=election_id, target_path=published_ref.path,
                    before=None,
                    after={"fingerprint": fingerprint, "hashAlgorithm": algorithm,
                           "signature": signature,
                           "ballotsCast": len(checked.house) + checked.excluded_house,
                           "excludedHouseBallots": checked.excluded_house,
                           "excludedSenateBallots": checked.excluded_senate,
                           "receiptsFingerprint": receipts_fingerprint, "archive": archive},
                    outcome="success", reason=None if archive else "archive_not_configured",
                    request=request, election_id=election_id)
        tx.create(published_ref, {
            "electionId": election_id,
            "packageJson": content.decode("utf-8"),
            "fingerprint": fingerprint,
            "hashAlgorithm": algorithm,
            **legacy_field,
            "signature": signature["value"],
            "signatureAlgorithm": signature["algorithm"],
            "signingKeyId": signature["keyId"],
            "receiptsFingerprint": receipts_fingerprint,
            "archive": archive,
            "publishedAt": published_at,
            "publishedBy": actor.get("staffId"),
        })

    try:
        publish(transaction)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Result publication failed")
        raise HTTPException(status_code=400, detail="Unable to publish results") from exc
    return {"electionId": election_id, "fingerprint": fingerprint, "hashAlgorithm": algorithm,
            "signingKeyId": signature["keyId"], **legacy_field}
