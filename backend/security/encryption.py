"""Application-level encryption for sensitive data stored in Firestore.

Uses AES-256-GCM. Each ciphertext records the key version used, allowing
keys to be rotated without losing access to previously encrypted data.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_ROTATION_DAYS = 90
KEY_LENGTH_BYTES = 32
NONCE_LENGTH_BYTES = 12


class EncryptionKeyError(RuntimeError):
    """Raised when encryption keys are missing, invalid, or unusable."""


@dataclass(frozen=True)
class EncryptedValue:
    ciphertext: str
    keyId: str


def generate_key() -> str:
    """Generate a base64-encoded 256-bit encryption key."""
    return base64.urlsafe_b64encode(
        secrets.token_bytes(KEY_LENGTH_BYTES)
    ).decode("utf-8")


def _decode_key(key_material: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(key_material.encode("utf-8"))
    except Exception as exc:
        raise EncryptionKeyError("Encryption key is not valid base64") from exc

    if len(key) != KEY_LENGTH_BYTES:
        raise EncryptionKeyError("Encryption key must be 256 bits")

    return key


def keyed_hash(value: str, key_material: str) -> str:
    """Create a deterministic keyed index for exact-match searches."""
    key = _decode_key(key_material)

    return hmac.new(
        key,
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class EncryptionService:
    """Encrypts and decrypts strings using versioned AES-256-GCM keys."""

    def __init__(
        self,
        keys: dict[str, str],
        active_key_id: str,
    ) -> None:
        if not keys:
            raise EncryptionKeyError("At least one encryption key is required")

        if active_key_id not in keys:
            raise EncryptionKeyError(
                "Active encryption key ID does not exist"
            )

        self._keys = {
            key_id: _decode_key(key_material)
            for key_id, key_material in keys.items()
        }
        self._active_key_id = active_key_id

    @property
    def active_key_id(self) -> str:
        return self._active_key_id

    def encrypt(self, plaintext: str | None) -> EncryptedValue | None:
        """Encrypt a UTF-8 string and return a portable ciphertext bundle."""
        if plaintext is None:
            return None

        if not isinstance(plaintext, str):
            raise TypeError("Only strings can be encrypted")

        nonce = os.urandom(NONCE_LENGTH_BYTES)
        aesgcm = AESGCM(self._keys[self._active_key_id])
        ciphertext = aesgcm.encrypt(
            nonce,
            plaintext.encode("utf-8"),
            None,
        )

        packed = nonce + ciphertext

        return EncryptedValue(
            ciphertext=base64.urlsafe_b64encode(packed).decode("utf-8"),
            keyId=self._active_key_id,
        )

    def decrypt(self, encrypted: EncryptedValue | None) -> str | None:
        """Decrypt a ciphertext bundle produced by encrypt()."""
        if encrypted is None:
            return None

        if encrypted.keyId not in self._keys:
            raise EncryptionKeyError(
                f"Unknown encryption key ID: {encrypted.keyId}"
            )

        try:
            packed = base64.urlsafe_b64decode(
                encrypted.ciphertext.encode("utf-8")
            )
            nonce = packed[:NONCE_LENGTH_BYTES]
            ciphertext = packed[NONCE_LENGTH_BYTES:]

            aesgcm = AESGCM(self._keys[encrypted.keyId])
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        except Exception as exc:
            raise EncryptionKeyError("Unable to decrypt value") from exc

        return plaintext.decode("utf-8")


def is_key_due_for_rotation(
    created_at: datetime,
    now: datetime | None = None,
) -> bool:
    """Return True when a key is older than 90 days."""
    checked_at = now or datetime.now(timezone.utc)

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return checked_at >= created_at + timedelta(days=KEY_ROTATION_DAYS)