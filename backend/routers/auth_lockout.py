"""Account lockout after repeated failed sign-ins, for voters and staff.

Sign-in happens between the browser and Firebase, so the login and verify pages
report each wrong password or text message code here. Every 3 consecutive
failures lock the account: 5 minutes the first time, doubling each time after,
up to an hour. A lock also disables the Firebase account, so Firebase itself
refuses sign-in until the lock ends. Only a real sign-in (a valid ID token)
resets the count.

Responses are the same whether or not an account exists for the email, so the
endpoints cannot be used to find registered addresses.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from firebase_admin import auth
from google.cloud import firestore

from backend.audit import audit_standalone
from backend.auth import verify_token
from backend.firestore_client import db
from backend.models import LockoutReport
from backend.rate_limit import limiter
from backend.security import hashing

router = APIRouter(prefix="/api/auth/lockout", tags=["auth"])
logger = logging.getLogger(__name__)

COLLECTION = "authLockouts"
FAILURES_PER_LOCK = 3
FIRST_LOCK = timedelta(minutes=5)
MAX_LOCK = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def lock_duration(lock_number: int) -> timedelta:
    """5 minutes for the first lock, doubling for each one after, up to an hour."""
    return min(FIRST_LOCK * 2 ** (lock_number - 1), MAX_LOCK)


def _record_ref(email: str) -> Any:
    # Keyed by a hash, so the collection is not a list of email addresses. Lock
    # records are short-lived, so after an algorithm change they simply start over.
    return db.collection(COLLECTION).document(hashing.document_id("index", email.strip().lower()))


def _find_user(email: str) -> Any | None:
    try:
        return auth.get_user_by_email(email.strip().lower())
    except auth.UserNotFoundError:
        return None


def _seconds_left(record: dict[str, Any], now: datetime) -> int:
    locked_until = record.get("lockedUntil")
    if not locked_until or locked_until <= now:
        return 0
    return int((locked_until - now).total_seconds()) + 1


def _status(record: dict[str, Any], now: datetime) -> dict[str, Any]:
    seconds_left = _seconds_left(record, now)
    failures = int(record.get("failures", 0))
    return {
        "locked": seconds_left > 0,
        "retryAfterSeconds": seconds_left,
        "attemptsRemaining": FAILURES_PER_LOCK - failures % FAILURES_PER_LOCK,
    }


def _staff_is_inactive(uid: str) -> bool:
    matches = list(db.collection("staff").where("authUid", "==", uid).limit(1).stream())
    return bool(matches) and (matches[0].to_dict() or {}).get("active") is False


def _release_if_expired(ref: Any, record: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Re-enables an account this lockout disabled, once its lock has ended."""
    uid = record.get("disabledUid")
    if not uid or _seconds_left(record, now):
        return record
    # A staff account deactivated by an admin during the lock stays disabled
    if not _staff_is_inactive(uid):
        try:
            auth.update_user(uid, disabled=False)
        except auth.UserNotFoundError:
            pass
    record = {**record, "disabledUid": None}
    ref.update({"disabledUid": None})
    return record


def _audit_lock(request: Request, ref: Any, uid: str | None, failures: int, locked_until: datetime) -> None:
    logger.warning("Account locked after %d consecutive failed sign-ins until %s", failures, locked_until)
    try:
        audit_standalone(
            actor={"staffId": uid or "unknown", "role": "unknown"},
            action="auth.lockout", category="security",
            target_type="account", target_id=uid or ref.id, target_path=f"{COLLECTION}/{ref.id}",
            before=None, after={"failures": failures, "lockedUntil": locked_until.isoformat()},
            outcome="denied", reason="consecutive_failed_sign_ins", request=request,
        )
    except Exception:
        logger.exception("Unable to write account lockout audit record")


@router.post("/check")
@limiter.limit("30/minute")
def check_lockout(body: LockoutReport, request: Request) -> dict[str, Any]:
    now = _now()
    ref = _record_ref(body.email)
    snapshot = ref.get()
    record = (snapshot.to_dict() or {}) if snapshot.exists else {}
    if record:
        record = _release_if_expired(ref, record, now)
    return _status(record, now)


@router.post("/failure")
@limiter.limit("10/minute")
def report_failure(body: LockoutReport, request: Request) -> dict[str, Any]:
    now = _now()
    ref = _record_ref(body.email)
    # End an expired lock first, so the account's disabled state below is its own
    existing = ref.get()
    if existing.exists:
        _release_if_expired(ref, existing.to_dict() or {}, now)
    user = _find_user(body.email)

    transaction = db.transaction()

    @firestore.transactional
    def record_failure(tx: Any) -> tuple[dict[str, Any], bool]:
        snapshot = ref.get(transaction=tx)
        record = (snapshot.to_dict() or {}) if snapshot.exists else {}
        # Attempts made while locked are refused, not counted
        if _seconds_left(record, now):
            return record, False
        failures = int(record.get("failures", 0)) + 1
        record = {**record, "failures": failures, "lastFailureAt": now}
        locks_now = failures % FAILURES_PER_LOCK == 0
        if locks_now:
            record["lockedUntil"] = now + lock_duration(failures // FAILURES_PER_LOCK)
            # Remember only accounts this lock disables, so one that was already
            # disabled (for example a staff account awaiting approval) stays so
            if user is not None and not user.disabled:
                record["disabledUid"] = user.uid
        tx.set(ref, record)
        return record, locks_now

    record, locks_now = record_failure(transaction)
    if locks_now:
        if record.get("disabledUid"):
            auth.update_user(record["disabledUid"], disabled=True)
        _audit_lock(request, ref, user.uid if user else None, record["failures"], record["lockedUntil"])
    return _status(record, now)


@router.post("/success")
@limiter.limit("10/minute")
def report_success(request: Request, claims: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    email = claims.get("email")
    if email:
        ref = _record_ref(email)
        if ref.get().exists:
            ref.set({"failures": 0})
    return {"locked": False, "retryAfterSeconds": 0, "attemptsRemaining": FAILURES_PER_LOCK}
