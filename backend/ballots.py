"""How a ballot is stored, and how it is opened and checked again for counting.

Ballot choices are encrypted with AES-256-GCM (backend/security/encryption.py)
before they are stored. Only the division (House) or state (Senate) stays
readable, so each contest's ballots can be counted; it is already known from
the voter's enrolment. Formality, and which part of a Senate ballot counts,
are worked out only when ballots are decrypted for counting, so nothing about
how someone voted is stored in the clear. Ballots never hold a voter reference
or a timestamp.

The ballot's election, chamber, contest, ID and source are the cipher's
associated data (R-15). They are authenticated but not encrypted, so a ballot
whose choices were altered, or that was copied or moved to another ballot,
contest or election, no longer decrypts. Once decrypted, its choices must
still be valid for its contest. ``backend.ballot_integrity`` runs these checks
on every ballot before counting.
"""
import json
from dataclasses import dataclass
from typing import Any

from backend.security.encryption import EncryptedValue, EncryptionService

SENATE_BTL_MINIMUM = 6  # savings provision: 6 boxes below the line is formal
# Stored on each ballot sealed with its context; ballots without it cannot be verified
INTEGRITY_VERSION = 1


class BallotInvalid(Exception):
    """A stored ballot failed its integrity checks; ``reason`` names the check."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class HouseContest:
    # Every candidate in the division, withdrawn ones too: ballots cast before a withdrawal name them
    candidates: frozenset[str]
    # Candidates still standing, which a formal ballot must number
    standing: int


@dataclass(frozen=True)
class SenateContest:
    groups: frozenset[str]
    candidates: frozenset[str]
    standing: int


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


def _context(election_id: str, ballot_id: str, chamber: str, contest_id: Any, source: Any) -> bytes:
    return json.dumps({"electionId": election_id, "ballotId": ballot_id, "chamber": chamber,
                       "contestId": contest_id, "source": source, "integrity": INTEGRITY_VERSION},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def _seal(encryption: EncryptionService, value: Any, context: bytes) -> dict[str, str]:
    sealed = encryption.encrypt(json.dumps(value, separators=(",", ":")), context)
    return {"ciphertext": sealed.ciphertext, "keyId": sealed.keyId}


def _unseal(encryption: EncryptionService, sealed: Any, context: bytes) -> Any:
    try:
        return json.loads(encryption.decrypt(EncryptedValue(sealed["ciphertext"], sealed["keyId"]), context))
    except Exception as exc:
        raise BallotInvalid("decrypt_failed", "Ballot was altered or is not where it was stored") from exc


def _choices(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BallotInvalid("malformed", "Ballot does not hold a list of choices")
    return value


def _check(choices: list[str], known: frozenset[str]) -> None:
    if len(set(choices)) != len(choices):
        raise BallotInvalid("duplicate_choice", "Ballot numbers a choice more than once")
    if not known.issuperset(choices):
        raise BallotInvalid("unknown_choice", "Ballot names a choice outside its contest")


def _require_protected(document: dict[str, Any], field: str) -> None:
    if document.get("integrity") != INTEGRITY_VERSION or not isinstance(document.get(field), dict):
        raise BallotInvalid("legacy_unverified", "Ballot was stored without integrity protection")


def house_document(election_id: str, ballot_id: str, division_id: str, preferences: list[str],
                   encryption: EncryptionService, source: str = "electronic") -> dict[str, Any]:
    context = _context(election_id, ballot_id, "house", division_id, source)
    return {"divisionId": division_id, "source": source, "integrity": INTEGRITY_VERSION,
            "encryptedPreferences": _seal(encryption, preferences, context)}


def senate_document(election_id: str, ballot_id: str, state_id: str, above: list[str], below: list[str],
                    encryption: EncryptionService, source: str = "electronic") -> dict[str, Any]:
    context = _context(election_id, ballot_id, "senate", state_id, source)
    return {"stateId": state_id, "source": source, "integrity": INTEGRITY_VERSION,
            "encryptedChoices": _seal(encryption, {"aboveTheLine": above, "belowTheLine": below}, context)}


def is_protected(document: dict[str, Any]) -> bool:
    return document.get("integrity") == INTEGRITY_VERSION


def open_house(election_id: str, ballot_id: str, document: dict[str, Any], encryption: EncryptionService,
               contest: HouseContest) -> dict[str, Any]:
    """The checked ballot as counting needs it: divisionId, preferences and isFormal.

    Raises BallotInvalid if any integrity check fails.
    """
    _require_protected(document, "encryptedPreferences")
    division_id = document.get("divisionId")
    context = _context(election_id, ballot_id, "house", division_id, document.get("source"))
    preferences = _choices(_unseal(encryption, document["encryptedPreferences"], context))
    _check(preferences, contest.candidates)
    return {"divisionId": division_id, "preferences": preferences,
            "isFormal": house_is_formal(preferences, contest.standing)}


def open_senate(election_id: str, ballot_id: str, document: dict[str, Any], encryption: EncryptionService,
                contest: SenateContest) -> dict[str, Any]:
    """The checked ballot as counting needs it: stateId, both parts, isFormal and countedAs.

    Raises BallotInvalid if any integrity check fails.
    """
    _require_protected(document, "encryptedChoices")
    state_id = document.get("stateId")
    context = _context(election_id, ballot_id, "senate", state_id, document.get("source"))
    choices = _unseal(encryption, document["encryptedChoices"], context)
    if not isinstance(choices, dict):
        raise BallotInvalid("malformed", "Senate ballot does not hold its two parts")
    above, below = _choices(choices.get("aboveTheLine")), _choices(choices.get("belowTheLine"))
    _check(above, contest.groups)
    _check(below, contest.candidates)
    counted_as = senate_counted_as(above, below, contest.standing)
    return {"stateId": state_id, "aboveTheLine": above, "belowTheLine": below,
            "isFormal": counted_as is not None, "countedAs": counted_as}
