"""Rule-based anomaly monitoring for security-sensitive events.

Counts recent events of the same type and creates an investigation alert when
the configured threshold is exceeded within the monitoring window.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from firebase_admin import firestore

logger = logging.getLogger(__name__)

ALERTS_COLLECTION = "securityAlerts"
EVENTS_COLLECTION = "securityEvents"

DEFAULT_THRESHOLD = 5
DEFAULT_WINDOW_MINUTES = 5
ALERT_RESOLUTION_MINUTES = 15


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def record_security_event(
    event_type: str,
    *,
    source_ip: str | None = None,
    actor_id: str | None = None,
    target_path: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    threshold: int = DEFAULT_THRESHOLD,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> bool:
    """Record a security event and create an alert when a spike is detected.

    Returns True when an alert is created; otherwise returns False.
    """
    db = firestore.client()
    now = _utc_now()
    window_start = now - timedelta(minutes=window_minutes)

    event_data = {
        "eventType": event_type,
        "sourceIp": source_ip,
        "actorId": actor_id,
        "targetPath": target_path,
        "reason": reason,
        "metadata": metadata or {},
        "detectedAt": now,
    }

    try:
        db.collection(EVENTS_COLLECTION).add(event_data)

        recent_events = (
            db.collection(EVENTS_COLLECTION)
            .where("eventType", "==", event_type)
            .where("detectedAt", ">=", window_start)
            .stream()
        )

        event_count = sum(1 for _ in recent_events)

        if event_count < threshold:
            return False

        existing_alerts = (
            db.collection(ALERTS_COLLECTION)
            .where("alertType", "==", event_type)
            .where("status", "==", "open")
            .where("detectedAt", ">=", window_start)
            .limit(1)
            .stream()
        )

        if any(existing_alerts):
            return False

        db.collection(ALERTS_COLLECTION).add(
            {
                "alertType": event_type,
                "severity": "high",
                "status": "open",
                "eventCount": event_count,
                "threshold": threshold,
                "windowMinutes": window_minutes,
                "sourceIp": source_ip,
                "actorId": actor_id,
                "targetPath": target_path,
                "reason": reason,
                "metadata": metadata or {},
                "detectedAt": now,
                "investigateBy": now + timedelta(
                    minutes=ALERT_RESOLUTION_MINUTES
                ),
            }
        )

        logger.warning(
            "Security anomaly detected: %s had %d events within %d minutes",
            event_type,
            event_count,
            window_minutes,
        )

        return True

    except Exception:
        logger.exception("Unable to record security anomaly event")
        return False