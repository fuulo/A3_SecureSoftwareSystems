import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore
from starlette.requests import Request

from backend.firestore_client import db
from backend.security import hashing


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted = {}
        for key, item in value.items():
            if str(key).lower() in {"password", "newpassword", "currentpassword"}:
                continue
            if str(key).lower() == "govid" and isinstance(item, str):
                redacted[key] = f"***{item[-3:]}"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _client_ip(request: Request) -> str | None:
    return getattr(request.state, "client_ip", None) or (request.client.host if request.client else None)


def write_audit(
    tx_or_batch: Any,
    *,
    actor: dict[str, Any] | None,
    action: str,
    category: str,
    target_type: str,
    target_id: str | None,
    target_path: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    outcome: str,
    reason: str | None,
    request: Request,
    election_id: str | None = None,
) -> str:
    head_ref = db.document("auditMeta/head")
    head_snapshot = next(tx_or_batch.get(head_ref))
    head = head_snapshot.to_dict() or {}
    previous_hash = head.get("lastHash", "")
    seq = int(head.get("seq", 0)) + 1
    log_id = f"{seq:020d}_{uuid.uuid4().hex}"
    log_ref = db.collection("auditLogs").document(log_id)
    entry = {
        "seq": seq,
        "timestamp": datetime.now(timezone.utc),
        "electionId": election_id,
        "actorId": (actor or {}).get("staffId"),
        "actorType": (actor or {}).get("role", "system"),
        "actorStateId": (actor or {}).get("stateId"),
        "action": action,
        "category": category,
        "targetType": target_type,
        "targetId": target_id,
        "targetPath": target_path,
        "before": _redact(before),
        "after": _redact(after),
        "outcome": outcome,
        "reason": reason,
        "ipAddress": _client_ip(request),
        "deviceId": None,
        "terminalId": None,
        "sessionId": request.headers.get("x-session-id"),
        "previousHash": previous_hash,
        # Part of the hashed content, so the algorithm cannot be changed afterwards
        "hashAlgorithm": hashing.algorithm_for("audit"),
    }
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
    entry["hash"] = hashing.hexdigest(previous_hash + canonical, entry["hashAlgorithm"])
    tx_or_batch.set(log_ref, entry)
    tx_or_batch.set(
        head_ref,
        {"lastHash": entry["hash"], "lastLogId": log_id, "seq": seq},
    )
    return log_id


def audit_standalone(**kwargs: Any) -> None:
    transaction = db.transaction()

    @firestore.transactional
    def commit(tx: Any) -> None:
        write_audit(tx, **kwargs)

    commit(transaction)
    request = kwargs.get("request")
    if request is not None:
        request.state.audit_written = True
