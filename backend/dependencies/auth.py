"""Firebase Authentication dependencies for FastAPI routes."""

from __future__ import annotations

from fastapi import Header, HTTPException, status
from firebase_admin import auth as firebase_auth


def get_current_firebase_user(
    authorization: str = Header(...),
) -> dict:
    """Verify a Firebase ID token from the Authorization header.

    Expects:
        Authorization: Bearer <firebase-id-token>

    Returns the decoded Firebase token, including `uid` and `email`.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    id_token = authorization.removeprefix("Bearer ").strip()

    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        decoded_token = firebase_auth.verify_id_token(id_token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        ) from exc

    uid = decoded_token.get("uid")

    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token does not contain a user ID",
        )

    return decoded_token