"""Ballot receipt codes.

A receipt proves a ballot was recorded without saying who cast it or what it
contains. Only a hash of each code is stored (the "receipt" algorithm in
backend/security/hashing.py), so the receipts collection cannot be turned back
into working codes, and a receipt holds no voter or ballot reference.
"""
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from backend.firestore_client import db
from backend.security import hashing

# Letters and numbers without look-alikes (0/O, 1/I/L); must match lib/receipts.ts.
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
GROUPS = 4
GROUP_LENGTH = 4
LENGTH = GROUPS * GROUP_LENGTH
_CODE = re.compile(rf"^[{ALPHABET}]{{{LENGTH}}}$")


def normalize_receipt(raw: str) -> str | None:
    """Return the bare 16-character code, or None if it can never be a receipt."""
    code = re.sub(r"[\s-]", "", raw).upper()
    return code if _CODE.match(code) else None


def format_receipt(code: str) -> str:
    return "-".join(code[i:i + GROUP_LENGTH] for i in range(0, LENGTH, GROUP_LENGTH))


def receipt_hash(code: str) -> str:
    """The document ID a new receipt is stored under."""
    return hashing.document_id("receipt", code)


def receipt_hashes(code: str) -> list[str]:
    """Every ID the receipt may be stored under, so receipts issued before an
    algorithm upgrade still verify."""
    return hashing.document_ids("receipt", code)


def new_receipt_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def issue_receipt(tx: Any, election_id: str) -> tuple[str, datetime]:
    """Create a receipt inside ``tx`` and return (formatted code, recorded time).

    The code itself is returned once and never stored. The time is rounded down
    to the minute so it is harder to match against other timestamped records.
    """
    code = new_receipt_code()
    recorded_at = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    tx.create(db.collection("receipts").document(receipt_hash(code)),
              {"electionId": election_id, "recordedAt": recorded_at})
    return format_receipt(code), recorded_at


def receipt_list(election_id: str) -> bytes:
    """The public receipt list: every receipt ID for an election, sorted, one per line.

    Each ID is the hash of a receipt code: plain hex for SHA-256, or
    "<algorithm>-<hex>" after an algorithm upgrade (see hashing.document_id).
    It holds no times or voter references. Its fingerprint goes into the result
    package, so anyone can check a receipt against a copy without this API, and
    there are far too many possible codes to work one out from its hash.
    """
    hashes = sorted(item.id for item in db.collection("receipts").where("electionId", "==", election_id).stream())
    return "".join(f"{value}\n" for value in hashes).encode("ascii")
