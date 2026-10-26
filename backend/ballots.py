"""How a ballot is stored, and how it is opened again for counting.

Ballot choices are encrypted with AES-256-GCM (backend/security/encryption.py)
before they are stored. Only the division (House) or state (Senate) stays
readable, so each contest's ballots can be counted; it is already known from
the voter's enrolment. Formality, and which part of a Senate ballot counts,
are worked out only when ballots are decrypted for counting, so nothing about
how someone voted is stored in the clear. Ballots never hold a voter reference
or a timestamp.

Ballots stored before encryption (plaintext ``preferences`` and ``isFormal``)
are still counted as they are.
"""
import json
from typing import Any

from backend.security.encryption import EncryptedValue, EncryptionService

SENATE_BTL_MINIMUM = 6  # savings provision: 6 boxes below the line is formal


class BallotUnreadable(Exception):
    """A stored ballot could not be decrypted, or decrypted to something that is not a ballot."""


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


def _seal(encryption: EncryptionService, value: Any) -> dict[str, str]:
    sealed = encryption.encrypt(json.dumps(value, separators=(",", ":")))
    return {"ciphertext": sealed.ciphertext, "keyId": sealed.keyId}


def _unseal(encryption: EncryptionService, sealed: Any) -> Any:
    try:
        return json.loads(encryption.decrypt(EncryptedValue(sealed["ciphertext"], sealed["keyId"])))
    except Exception as exc:
        raise BallotUnreadable("Ballot could not be decrypted") from exc


def _choices(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BallotUnreadable("Ballot does not hold a list of choices")
    return value


def house_document(division_id: str, preferences: list[str], encryption: EncryptionService) -> dict[str, Any]:
    return {"divisionId": division_id, "source": "electronic",
            "encryptedPreferences": _seal(encryption, preferences)}


def senate_document(state_id: str, above: list[str], below: list[str],
                    encryption: EncryptionService) -> dict[str, Any]:
    return {"stateId": state_id, "source": "electronic",
            "encryptedChoices": _seal(encryption, {"aboveTheLine": above, "belowTheLine": below})}


def is_encrypted(document: dict[str, Any]) -> bool:
    return "encryptedPreferences" in document or "encryptedChoices" in document


def open_house(document: dict[str, Any], encryption: EncryptionService | None,
               candidate_count: int) -> dict[str, Any]:
    """The ballot as counting needs it: divisionId, preferences and isFormal."""
    if "encryptedPreferences" not in document:
        return document
    if encryption is None:
        raise BallotUnreadable("No encryption keys are available")
    preferences = _choices(_unseal(encryption, document["encryptedPreferences"]))
    return {"divisionId": document.get("divisionId"), "preferences": preferences,
            "isFormal": house_is_formal(preferences, candidate_count)}


def open_senate(document: dict[str, Any], encryption: EncryptionService | None,
                candidate_count: int) -> dict[str, Any]:
    """The ballot as counting needs it: stateId, both parts, isFormal and countedAs."""
    if "encryptedChoices" not in document:
        return document
    if encryption is None:
        raise BallotUnreadable("No encryption keys are available")
    choices = _unseal(encryption, document["encryptedChoices"])
    if not isinstance(choices, dict):
        raise BallotUnreadable("Senate ballot does not hold its two parts")
    above, below = _choices(choices.get("aboveTheLine")), _choices(choices.get("belowTheLine"))
    counted_as = senate_counted_as(above, below, candidate_count)
    return {"stateId": document.get("stateId"), "aboveTheLine": above, "belowTheLine": below,
            "isFormal": counted_as is not None, "countedAs": counted_as}
