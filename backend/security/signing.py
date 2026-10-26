"""Digital signatures on published results (R-09).

Each result package is signed with Ed25519 over its exact published bytes, so
anyone holding the public key can prove the package came from this system and
has not changed. The fingerprint (backend/security/hashing.py) is checked
alongside it; the package also names the receipt list's fingerprint, so the
signature covers the receipt list too.

The private key is a PEM file (RESULTS_SIGNING_KEY_FILE), never stored in
Firestore: someone able to rewrite a published package in the database must
not also be able to re-sign it. Browsers check signatures with Web Crypto.

    python -m backend.security.signing [--out certs/results-signing-key.pem]
"""
import argparse
import sys
from functools import cache
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from backend.config import RESULTS_SIGNING_KEY_FILE
from backend.security import hashing

ALGORITHM = "Ed25519"


class SigningKeyMissing(Exception):
    pass


@cache
def _private_key() -> Ed25519PrivateKey:
    path = Path(RESULTS_SIGNING_KEY_FILE)
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except FileNotFoundError as exc:
        raise SigningKeyMissing(f"Results signing key not found ({path})") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyMissing(f"Results signing key in {path} is not an Ed25519 key")
    return key


def _raw(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(public_key: Ed25519PublicKey) -> str:
    # Always SHA-256, so a key keeps its ID when hash settings change
    return hashing.hexdigest(_raw(public_key), hashing.LEGACY_ALGORITHM)[:16]


def public_key() -> dict[str, str]:
    """The current public key, for anyone checking a signature."""
    key = _private_key().public_key()
    pem = key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return {"algorithm": ALGORITHM, "keyId": key_id(key), "publicKeyPem": pem.decode("ascii")}


def sign(data: bytes) -> dict[str, str]:
    """{algorithm, keyId, value (hex)} for ``data``; raises SigningKeyMissing if no key is set up."""
    key = _private_key()
    return {"algorithm": ALGORITHM, "keyId": key_id(key.public_key()), "value": key.sign(data).hex()}


def verify(data: bytes, signature_hex: str, public_key_pem: str) -> bool:
    try:
        key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(bytes.fromhex(signature_hex), data)
    except (InvalidSignature, ValueError):
        return False
    return True


def generate_key_file(path: Path) -> str:
    """Writes a new private key to ``path`` (never overwriting one) and returns its key ID."""
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(pem)
    return key_id(key.public_key())


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the Ed25519 key that signs published results.")
    parser.add_argument("--out", default=RESULTS_SIGNING_KEY_FILE)
    args = parser.parse_args()
    try:
        created = generate_key_file(Path(args.out))
    except FileExistsError:
        sys.exit(f"{args.out} already exists; move it away first to create a new key")
    print(f"Created results signing key {created} in {args.out}. Keep it secret and back it up.")


if __name__ == "__main__":
    main()
