"""Hash functions for every purpose in the API, chosen by configuration.

Each purpose has its own algorithm setting (HASH_ALGORITHMS in
backend/config.py), so a hash standard can be upgraded without changing the
code that uses it:

- receipt: ballot receipt codes, stored only as hashes
- audit:   the audit log hash chain
- results: the published result package fingerprint, also checked in browsers
- index:   other lookup IDs (lockout records, audit-view throttling)

Values record the algorithm that produced them, so records made before an
upgrade still verify. Digests stored as fields sit beside an algorithm name
(for example hashAlgorithm). Digests used as document IDs are plain hex for
SHA-256, the original algorithm, and "<algorithm>-<hex>" for any other.
"""
import hashlib
from collections.abc import Callable
from typing import Any

from backend.config import HASH_ALGORITHMS

# Every value without an algorithm name was made with this
LEGACY_ALGORITHM = "sha256"

SUPPORTED: dict[str, Callable[..., Any]] = {
    "sha256": hashlib.sha256,
    "sha384": hashlib.sha384,
    "sha512": hashlib.sha512,
    "sha3_256": hashlib.sha3_256,
    "sha3_512": hashlib.sha3_512,
}
# Result packages are checked in the browser, whose Web Crypto API has SHA-2 only
BROWSER_VERIFIABLE = {"sha256": "SHA-256", "sha384": "SHA-384", "sha512": "SHA-512"}


def _validate(algorithms: dict[str, str]) -> None:
    for purpose, name in algorithms.items():
        if name not in SUPPORTED:
            raise ValueError(f"Unsupported hash algorithm for {purpose}: {name!r}")
    if algorithms["results"] not in BROWSER_VERIFIABLE:
        raise ValueError(f"Results must use {', '.join(BROWSER_VERIFIABLE)} so browsers can verify them")


# Fail at startup, not on the first request that needs a hash
_validate(HASH_ALGORITHMS)


def algorithm_for(purpose: str) -> str:
    return HASH_ALGORITHMS[purpose]


def hexdigest(data: bytes | str, algorithm: str) -> str:
    if algorithm not in SUPPORTED:
        raise ValueError(f"Unsupported hash algorithm: {algorithm!r}")
    if isinstance(data, str):
        data = data.encode("utf-8")
    return SUPPORTED[algorithm](data).hexdigest()


def digest(purpose: str, data: bytes | str) -> tuple[str, str]:
    """(algorithm, hex digest) using the current algorithm for this purpose."""
    algorithm = algorithm_for(purpose)
    return algorithm, hexdigest(data, algorithm)


def _document_id(algorithm: str, data: bytes | str) -> str:
    value = hexdigest(data, algorithm)
    return value if algorithm == LEGACY_ALGORITHM else f"{algorithm}-{value}"


def document_id(purpose: str, data: bytes | str) -> str:
    """A document ID for new records, using the current algorithm."""
    return _document_id(algorithm_for(purpose), data)


def document_ids(purpose: str, data: bytes | str) -> list[str]:
    """IDs a record may have been stored under: current algorithm first, then the others."""
    current = algorithm_for(purpose)
    return [_document_id(name, data) for name in [current, *(n for n in SUPPORTED if n != current)]]
