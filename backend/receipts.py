"""Ballot receipt codes.

A receipt proves a ballot was recorded without saying who cast it or what it
contains. Only the SHA-256 of each code is stored, so the receipts collection
cannot be turned back into working codes, and a receipt holds no voter or
ballot reference.
"""
import hashlib
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from backend.firestore_client import db

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
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


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
