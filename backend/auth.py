import ipaddress
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth
from google.cloud import firestore

from backend.audit import audit_standalone
from backend.config import TRUST_PROXY_HEADERS
from backend.firestore_client import db

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)
_login_seen: dict[str, int] = {}
_login_lock = threading.Lock()
_ip_cache: tuple[float, list[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, dict[str, Any]]]] = (0, [])
_ip_lock = threading.Lock()
_IP_CACHE_TTL = 30
# A freshly issued ID token carries Google's time; if this server's clock is
# slightly behind, a zero tolerance rejects it as "used too early"
_TOKEN_CLOCK_SKEW_SECONDS = 10


async def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict[str, Any]:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        claims = auth.verify_id_token(
            credentials.credentials,
            check_revoked=True,
            clock_skew_seconds=_TOKEN_CLOCK_SKEW_SECONDS,
        )
        auth_time = int(claims.get("auth_time", 0))
    except Exception as exc:
        logger.info(
            "Rejected Firebase token: %s: %s",
            exc.__class__.__name__,
            exc,
        )
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        ) from exc

    request.state.token_claims = claims

    if not auth_time or (
        datetime.now(timezone.utc).timestamp() - auth_time
    ) > 8 * 60 * 60:
        uid = claims.get("uid")

        try:
            staff_matches = (
                list(
                    db.collection("staff")
                    .where("authUid", "==", uid)
                    .limit(1)
                    .stream()
                )
                if uid
                else []
            )
            actor = (
                {
                    **(staff_matches[0].to_dict() or {}),
                    "staffId": staff_matches[0].id,
                }
                if staff_matches
                else {
                    "staffId": uid or "unknown",
                    "role": "unknown",
                }
            )
            request.state.staff = actor

            audit_standalone(
                actor=actor,
                action="auth.denied",
                category="security",
                target_type="staff",
                target_id=actor.get("staffId"),
                target_path="staff",
                before=None,
                after=None,
                outcome="denied",
                reason="auth_time_expired",
                request=request,
            )
        except Exception:
            logger.exception(
                "Unable to record stale-authentication denial"
            )

        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    return claims


async def current_staff(
    request: Request,
    claims: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    uid = claims.get("uid")

    if not uid:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    matches = list(
        db.collection("staff")
        .where("authUid", "==", uid)
        .limit(1)
        .stream()
    )

    if not matches:
        try:
            audit_standalone(
                actor={"staffId": uid, "role": "unknown"},
                action="auth.denied",
                category="security",
                target_type="staff",
                target_id=uid,
                target_path="staff",
                before=None,
                after=None,
                outcome="denied",
                reason="staff_record_missing",
                request=request,
            )
        except Exception:
            logger.exception(
                "Unable to write missing staff denial audit record"
            )

        raise HTTPException(
            status_code=403,
            detail="Staff access denied",
        )

    if matches[0].to_dict().get("active") is not True:
        record = matches[0].to_dict() or {}
        request.state.staff = {
            **record,
            "staffId": matches[0].id,
        }

        try:
            audit_standalone(
                actor=request.state.staff,
                action="auth.denied",
                category="security",
                target_type="staff",
                target_id=matches[0].id,
                target_path=matches[0].reference.path,
                before={"active": record.get("active")},
                after=None,
                outcome="denied",
                reason="staff_inactive",
                request=request,
            )
        except Exception:
            logger.exception(
                "Unable to write inactive staff denial audit record"
            )

        raise HTTPException(
            status_code=403,
            detail="Staff access denied",
        )

    snapshot = matches[0]
    staff = {**(snapshot.to_dict() or {}), "staffId": snapshot.id}
    request.state.staff = staff

    with _login_lock:
        if _login_seen.get(uid) != int(claims.get("auth_time", 0)):
            db.collection("staff").document(snapshot.id).update(
                {"lastLoginAt": firestore.SERVER_TIMESTAMP}
            )
            _login_seen[uid] = int(claims.get("auth_time", 0))

        expired = [
            key
            for key, value in _login_seen.items()
            if datetime.now(timezone.utc).timestamp() - value
            > 8 * 60 * 60
        ]

        for key in expired:
            _login_seen.pop(key, None)

    return staff


def _request_ip(
    request: Request,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    raw = request.client.host if request.client else ""

    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")

        if forwarded:
            # The trusted edge proxy must replace, not append to, this header.
            raw = forwarded.split(",")[0].strip()

    try:
        return ipaddress.ip_address(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail="Network access denied",
        ) from exc


def _active_ranges() -> list[
    tuple[
        ipaddress.IPv4Network | ipaddress.IPv6Network,
        dict[str, Any],
    ]
]:
    global _ip_cache
    now = time.monotonic()

    with _ip_lock:
        if now - _ip_cache[0] < _IP_CACHE_TTL:
            return _ip_cache[1]

        try:
            ranges = []

            for snapshot in (
                db.collection("config")
                .document("allowedIpRanges")
                .collection("ranges")
                .stream()
            ):
                item = snapshot.to_dict() or {}

                if item.get("active") is True:
                    ranges.append(
                        (
                            ipaddress.ip_network(
                                item["cidr"],
                                strict=True,
                            ),
                            {**item, "id": snapshot.id},
                        )
                    )

            _ip_cache = (now, ranges)
            return ranges
        except Exception as exc:
            logger.exception("Unable to read IP allowlist")
            raise HTTPException(
                status_code=403,
                detail="Network access denied",
            ) from exc


async def enforce_ip_allowlist(
    request: Request,
    staff: dict[str, Any] = Depends(current_staff),
) -> dict[str, Any]:
    return check_ip_allowlist(request, staff)


def check_ip_allowlist(
    request: Request,
    staff: dict[str, Any],
    *,
    allow_bootstrap: bool = False,
) -> dict[str, Any]:
    ranges = _active_ranges()
    client_ip = _request_ip(request)

    if (
        not ranges
        and allow_bootstrap
        and staff.get("role") == "admin"
    ):
        request.state.bootstrap_ip_access = True
        request.state.client_ip = str(client_ip)
        return staff

    if not any(
        client_ip.version == network.version
        and client_ip in network
        for network, _ in ranges
    ):
        try:
            audit_standalone(
                actor=staff,
                action="auth.denied",
                category="security",
                target_type="request",
                target_id=None,
                target_path=request.url.path,
                before=None,
                after=None,
                outcome="denied",
                reason="ip_not_allowed",
                request=request,
            )
        except Exception:
            logger.exception(
                "Unable to write IP denial audit record"
            )

        raise HTTPException(
            status_code=403,
            detail="Network access denied",
        )

    request.state.client_ip = str(client_ip)
    return staff


async def enforce_voter_ip_allowlist(
    request: Request,
) -> None:
    """Restrict voter voting access to approved diplomatic IP ranges."""
    ranges = _active_ranges()
    client_ip = _request_ip(request)

    allowed = any(
        client_ip.version == network.version
        and client_ip in network
        for network, _ in ranges
    )

    if allowed:
        request.state.client_ip = str(client_ip)
        return

    detected_at = datetime.now(timezone.utc)
    report_due_at = detected_at + timedelta(minutes=3)

    try:
        audit_standalone(
            actor={"role": "voter"},
            action="voter.access.denied",
            category="security",
            target_type="request",
            target_id=None,
            target_path=request.url.path,
            before=None,
            after=None,
            outcome="denied",
            reason="voter_ip_not_allowed",
            request=request,
        )
    except Exception:
        logger.exception(
            "Unable to write voter IP denial audit record"
        )

    try:
        db.collection("securityAlerts").add(
            {
                "alertType": "voter_ip_not_allowed",
                "severity": "high",
                "sourceIp": str(client_ip),
                "targetPath": request.url.path,
                "detectedAt": detected_at,
                "reportDueAt": report_due_at,
                "status": "open",
            }
        )
    except Exception:
        logger.exception(
            "Unable to create voter IP denial alert"
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Voting access is not permitted from this network",
    )


def require_roles(*roles: str) -> Callable[..., Any]:
    async def dependency(
        request: Request,
        staff: dict[str, Any] = Depends(current_staff),
    ) -> dict[str, Any]:
        if staff.get("role") not in roles:
            try:
                audit_standalone(
                    actor=staff,
                    action="auth.denied",
                    category="security",
                    target_type="request",
                    target_id=None,
                    target_path=request.url.path,
                    before=None,
                    after=None,
                    outcome="denied",
                    reason="role_not_allowed",
                    request=request,
                )
            except Exception:
                logger.exception(
                    "Unable to write role denial audit record"
                )

            raise HTTPException(
                status_code=403,
                detail="Access denied",
            )

        return staff

    return dependency


def staff_access(
    *roles: str,
    bootstrap_ip: bool = False,
) -> Callable[..., Any]:
    async def dependency(
        request: Request,
        staff: dict[str, Any] = Depends(current_staff),
    ) -> dict[str, Any]:
        if staff.get("role") not in roles:
            try:
                audit_standalone(
                    actor=staff,
                    action="auth.denied",
                    category="security",
                    target_type="request",
                    target_id=None,
                    target_path=request.url.path,
                    before=None,
                    after=None,
                    outcome="denied",
                    reason="role_not_allowed",
                    request=request,
                )
            except Exception:
                logger.exception(
                    "Unable to write role denial audit record"
                )

            raise HTTPException(
                status_code=403,
                detail="Access denied",
            )

        return check_ip_allowlist(
            request,
            staff,
            allow_bootstrap=bootstrap_ip,
        )

    return dependency


def invalidate_ip_cache() -> None:
    global _ip_cache

    with _ip_lock:
        _ip_cache = (0, [])