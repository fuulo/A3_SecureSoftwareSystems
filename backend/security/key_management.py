"""Firestore-backed encryption-key management with 90-day rotation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from firebase_admin import firestore

from backend.security.encryption import (
    KEY_ROTATION_DAYS,
    EncryptionKeyError,
    EncryptionService,
    generate_key,
    is_key_due_for_rotation,
)

KEY_COLLECTION = "encryptionKeys"


def _get_db():
    return firestore.client()


def ensure_encryption_key() -> tuple[str, str]:
    """Return the active key ID and material, creating a key if required."""
    db = _get_db()
    now = datetime.now(timezone.utc)

    active_documents = (
        db.collection(KEY_COLLECTION)
        .where("status", "==", "active")
        .order_by(
            "createdAt",
            direction=firestore.Query.DESCENDING,
        )
        .limit(1)
        .stream()
    )

    for document in active_documents:
        data = document.to_dict()
        key_material = data.get("keyMaterial")
        created_at = data.get("createdAt")

        if not key_material:
            raise EncryptionKeyError(
                "Active encryption key has no key material"
            )

        if created_at and is_key_due_for_rotation(
            created_at,
            now,
        ):
            rotate_encryption_keys()
            return get_active_encryption_key()

        return document.id, key_material

    key_id = f"key-{now.strftime('%Y%m%d%H%M%S')}"
    key_material = generate_key()

    db.collection(KEY_COLLECTION).document(key_id).set(
        {
            "keyMaterial": key_material,
            "status": "active",
            "algorithm": "AES-256-GCM",
            "createdAt": firestore.SERVER_TIMESTAMP,
            "rotationDueAt": now + timedelta(
                days=KEY_ROTATION_DAYS
            ),
        }
    )

    return key_id, key_material


def get_active_encryption_key() -> tuple[str, str]:
    """Return the current active key ID and material."""
    db = _get_db()

    documents = (
        db.collection(KEY_COLLECTION)
        .where("status", "==", "active")
        .order_by(
            "createdAt",
            direction=firestore.Query.DESCENDING,
        )
        .limit(1)
        .stream()
    )

    for document in documents:
        data = document.to_dict()
        key_material = data.get("keyMaterial")

        if not key_material:
            raise EncryptionKeyError(
                "Active encryption key has no key material"
            )

        return document.id, key_material

    return ensure_encryption_key()


def rotate_encryption_keys() -> str:
    """Create a new active key and retire previous active keys."""
    db = _get_db()
    now = datetime.now(timezone.utc)

    previous_documents = (
        db.collection(KEY_COLLECTION)
        .where("status", "==", "active")
        .stream()
    )

    for document in previous_documents:
        document.reference.update(
            {
                "status": "retired",
                "retiredAt": firestore.SERVER_TIMESTAMP,
            }
        )

    new_key_id = (
        f"key-{now.strftime('%Y%m%d%H%M%S')}"
    )
    new_key_material = generate_key()

    db.collection(KEY_COLLECTION).document(
        new_key_id
    ).set(
        {
            "keyMaterial": new_key_material,
            "status": "active",
            "algorithm": "AES-256-GCM",
            "createdAt": firestore.SERVER_TIMESTAMP,
            "rotationDueAt": now + timedelta(
                days=KEY_ROTATION_DAYS
            ),
        }
    )

    return new_key_id


def get_encryption_service() -> EncryptionService:
    """Build an EncryptionService containing all retained key versions."""
    db = _get_db()

    documents = db.collection(KEY_COLLECTION).stream()

    keys: dict[str, str] = {}
    active_key_id: str | None = None

    for document in documents:
        data = document.to_dict()
        key_id = document.id
        key_material = data.get("keyMaterial")
        status = data.get("status")

        if not key_material:
            continue

        keys[key_id] = key_material

        if status == "active":
            active_key_id = key_id

    if active_key_id is None:
        active_key_id, active_key_material = (
            ensure_encryption_key()
        )
        keys[active_key_id] = active_key_material

    return EncryptionService(
        keys=keys,
        active_key_id=active_key_id,
    )