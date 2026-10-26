"""Server-side inactivity timeout for signed-in voters and staff.

After signing in, the browser exchanges its Firebase ID token for a session
token: a JWT signed by this API that expires SESSION_IDLE_SECONDS later. The
browser renews it while the user is active. Protected endpoints refuse requests
without an unexpired session token, and a background sweep ends sessions that
were not renewed in time.

Ending a session for inactivity revokes the user's Firebase refresh tokens, so
Firebase stops issuing new ID tokens for that sign-in and this API rejects the
ones already issued. A new session can only be started shortly after signing
in, so an ended session cannot be replaced without signing in again.

The key that signs session tokens is generated automatically the first time it
is needed and kept in Firestore (config/sessionSigning), which only this API can
read. There is nothing to configure, and restarts keep sessions valid.
"""
import asyncio
import logging
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException, Request
from firebase_admin import auth
from google.cloud import firestore

from backend.audit import audit_standalone
from backend.config import SESSION_IDLE_SECONDS, SESSION_SIGNING_ALGORITHM
from backend.firestore_client import db

logger = logging.getLogger(__name__)

COLLECTION = "sessions"
HEADER = "X-Session-Token"
START_WINDOW = timedelta(minutes=5)
SWEEP_INTERVAL_SECONDS = 30
SESSION_INVALID = "Session invalid"
SESSION_EXPIRED = "Session expired"
SIGNING_KEY_DOCUMENT = "config/sessionSigning"
# HMAC-SHA2 JWT algorithms; the key is 512 bits, enough for the strongest
SUPPORTED_ALGORITHMS = {"HS256", "HS384", "HS512"}
_KEY_BYTES = 64

if SESSION_SIGNING_ALGORITHM not in SUPPORTED_ALGORITHMS:
    raise ValueError(f"Unsupported SESSION_SIGNING_ALGORITHM: {SESSION_SIGNING_ALGORITHM!r}")

# (key, algorithm), loaded once
_signing: tuple[str, str] | None = None
_signing_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_or_create_signing_key() -> tuple[str, str]:
    """The stored key and the algorithm it is for. A new key uses
    SESSION_SIGNING_ALGORITHM; an existing one keeps the algorithm stored with it."""
    ref = db.document(SIGNING_KEY_DOCUMENT)
    candidate = secrets.token_urlsafe(_KEY_BYTES)
    transaction = db.transaction()

    # In a transaction, so APIs starting at the same time agree on one key
    @firestore.transactional
    def load(tx: Any) -> tuple[str, str]:
        snapshot = ref.get(transaction=tx)
        if snapshot.exists:
            stored = snapshot.to_dict() or {}
            return stored["key"], stored.get("algorithm", "HS256")
        tx.set(ref, {"key": candidate, "algorithm": SESSION_SIGNING_ALGORITHM, "createdAt": _now()})
        logger.info("Created a %s session signing key in %s", SESSION_SIGNING_ALGORITHM, SIGNING_KEY_DOCUMENT)
        return candidate, SESSION_SIGNING_ALGORITHM

    key, algorithm = load(transaction)
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise ValueError(f"Unsupported session signing algorithm in {SIGNING_KEY_DOCUMENT}: {algorithm!r}")
    if algorithm != SESSION_SIGNING_ALGORITHM:
        logger.warning("The stored session key uses %s, not SESSION_SIGNING_ALGORITHM %s; delete %s "
                       "and restart to switch", algorithm, SESSION_SIGNING_ALGORITHM, SIGNING_KEY_DOCUMENT)
    return key, algorithm


def _signing_key() -> tuple[str, str]:
    """(key, algorithm) for session tokens, loaded from Firestore once."""
    global _signing
    if _signing is None:
        with _signing_lock:
            if _signing is None:
                _signing = _load_or_create_signing_key()
    return _signing


def _ref(sid: str) -> Any:
    return db.collection(COLLECTION).document(sid)


def _issue(uid: str, sid: str, auth_time: int, now: datetime) -> dict[str, Any]:
    expires = now + timedelta(seconds=SESSION_IDLE_SECONDS)
    key, algorithm = _signing_key()
    token = jwt.encode(
        {"sub": uid, "sid": sid, "auth_time": auth_time,
         "iat": int(now.timestamp()), "exp": int(expires.timestamp())},
        key,
        algorithm=algorithm,
    )
    return {"sessionToken": token, "expiresAt": expires.isoformat(), "idleSeconds": SESSION_IDLE_SECONDS}


def decode(token: str | None) -> dict[str, Any] | None:
    """The token's claims if this API signed it, expired or not; otherwise None."""
    if not token:
        return None
    key, algorithm = _signing_key()
    try:
        # Only the stored key's algorithm is accepted. Times are checked
        # against _now() by the callers, not PyJWT's own clock.
        return jwt.decode(token, key, algorithms=[algorithm],
                          options={"verify_exp": False, "verify_iat": False,
                                   "require": ["sub", "sid", "auth_time", "exp"]})
    except jwt.InvalidTokenError:
        return None


def start_session(claims: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    auth_time = int(claims.get("auth_time", 0))
    if now.timestamp() - auth_time > START_WINDOW.total_seconds():
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED)
    sid = uuid.uuid4().hex
    issued = _issue(claims["uid"], sid, auth_time, now)
    _ref(sid).set({
        "uid": claims["uid"],
        "authTime": auth_time,
        "startedAt": now,
        "lastActivityAt": now,
        "expiresAt": now + timedelta(seconds=SESSION_IDLE_SECONDS),
    })
    return issued


def check_session(request: Request, claims: dict[str, Any]) -> dict[str, Any]:
    """Refuses a request without an unexpired session token for this sign-in."""
    payload = decode(request.headers.get(HEADER))
    if (payload is None or payload["sub"] != claims.get("uid")
            or payload["auth_time"] != int(claims.get("auth_time", 0))):
        raise HTTPException(status_code=401, detail=SESSION_INVALID)
    if payload["exp"] <= _now().timestamp():
        end_idle_session(payload["sid"], payload["sub"], request)
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED)
    request.state.session = payload
    return payload


def renew_session(payload: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    ref = _ref(payload["sid"])
    if not ref.get().exists:
        # Already ended by the sweep
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED)
    issued = _issue(payload["sub"], payload["sid"], payload["auth_time"], now)
    ref.update({"lastActivityAt": now, "expiresAt": now + timedelta(seconds=SESSION_IDLE_SECONDS)})
    return issued


def sign_out(request: Request) -> None:
    """Ends the session in the request's token when the user signs out.

    An unexpired session is simply closed. An expired one is ended as idle, with
    revocation, so signing out cannot be used to avoid the inactivity timeout.
    """
    payload = decode(request.headers.get(HEADER))
    if payload is None:
        return
    if payload["exp"] <= _now().timestamp():
        end_idle_session(payload["sid"], payload["sub"], request)
        return
    ref = _ref(payload["sid"])
    if ref.get().exists:
        ref.delete()


def _claim_for_ending(sid: str) -> bool:
    """Deletes the session record; True only for the caller that deleted it."""
    ref = _ref(sid)
    transaction = db.transaction()

    @firestore.transactional
    def claim(tx: Any) -> bool:
        if not ref.get(transaction=tx).exists:
            return False
        tx.delete(ref)
        return True

    return claim(transaction)


def end_idle_session(sid: str, uid: str, request: Request) -> None:
    if not _claim_for_ending(sid):
        return
    try:
        auth.revoke_refresh_tokens(uid)
    except auth.UserNotFoundError:
        pass
    logger.info("Ended session %s after %d seconds of inactivity", sid, SESSION_IDLE_SECONDS)
    try:
        audit_standalone(
            actor={"staffId": uid, "role": "unknown"},
            action="auth.sessionTimeout", category="security",
            target_type="session", target_id=sid, target_path=f"{COLLECTION}/{sid}",
            before=None, after={"idleSeconds": SESSION_IDLE_SECONDS},
            outcome="success", reason="inactivity", request=request,
        )
    except Exception:
        logger.exception("Unable to write session timeout audit record")


def _sweep_request() -> Request:
    # The audit log records the request; the sweep has none of its own
    return Request({"type": "http", "method": "POST", "path": "/internal/session-sweep",
                    "headers": [], "client": None})


def sweep_expired_sessions() -> int:
    """Ends every session that was not renewed in time. Returns how many."""
    expired = list(db.collection(COLLECTION).where("expiresAt", "<=", _now()).stream())
    for snapshot in expired:
        end_idle_session(snapshot.id, (snapshot.to_dict() or {}).get("uid", ""), _sweep_request())
    return len(expired)


async def sweep_forever() -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(sweep_expired_sessions)
        except Exception:
            logger.exception("Session sweep failed")
