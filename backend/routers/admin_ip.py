import ipaddress
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from google.cloud import firestore

from backend.audit import write_audit
from backend.auth import invalidate_ip_cache, staff_access
from backend.firestore_client import db
from backend.models import IpRangeCreate, IpRangeEdit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin-ip"])
ip_admin = staff_access("admin", bootstrap_ip=True)


def _range_collection():
    return db.collection("config").document("allowedIpRanges").collection("ranges")


def _validated_network(cidr: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    network = ipaddress.ip_network(cidr, strict=True)
    if network.prefixlen < (16 if network.version == 4 else 48):
        raise HTTPException(status_code=422, detail="IP range is too broad")
    if str(network) in {"0.0.0.0/0", "::/0"}:
        raise HTTPException(status_code=422, detail="Default routes are not allowed")
    return network


def _ensure_not_locked_out(request: Request, staff: dict[str, Any], docs: dict[str, dict[str, Any]], confirm: bool) -> None:
    ip = ipaddress.ip_address(request.state.client_ip)
    allowed = False
    for item in docs.values():
        if item.get("active") is True:
            network = ipaddress.ip_network(item["cidr"], strict=True)
            allowed = allowed or (network.version == ip.version and ip in network)
    if not allowed and not confirm:
        raise HTTPException(status_code=409, detail="This change would block your current IP")
    if not docs:
        raise HTTPException(status_code=409, detail="At least one IP range must remain configured")


@router.get("/ip-ranges")
def list_ranges(staff: dict[str, Any] = Depends(ip_admin)) -> list[dict[str, Any]]:
    return [{"locationId": item.id, **(item.to_dict() or {})} for item in _range_collection().stream()]


@router.get("/my-ip")
def my_ip(request: Request, staff: dict[str, Any] = Depends(ip_admin)) -> dict[str, str]:
    return {"ipAddress": getattr(request.state, "client_ip", "Unavailable")}


@router.post("/ip-ranges", status_code=201)
def create_range(body: IpRangeCreate, request: Request, staff: dict[str, Any] = Depends(ip_admin)) -> dict[str, str]:
    try:
        _validated_network(body.cidr)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid IP range") from exc
    range_ref = _range_collection().document()
    transaction = db.transaction()
    bootstrap = bool(getattr(request.state, "bootstrap_ip_access", False))

    @firestore.transactional
    def create(tx: Any) -> None:
        active = [item.to_dict() or {} for item in _range_collection().stream(transaction=tx) if item.get("active")]
        if not active and not bootstrap:
            raise HTTPException(status_code=409, detail="IP allowlist is unavailable")
        if not active and not body.active:
            raise HTTPException(status_code=409, detail="The first IP range must be active")
        if bootstrap and body.active and ipaddress.ip_address(request.state.client_ip) not in ipaddress.ip_network(body.cidr, strict=True):
            raise HTTPException(status_code=409, detail="Bootstrap range must include your current IP")
        data = {"cidr": body.cidr, "label": body.label.strip(), "active": body.active,
                "updatedBy": staff["staffId"], "updatedAt": firestore.SERVER_TIMESTAMP}
        write_audit(tx, actor=staff, action="config.ipRange.create", category="security",
                    target_type="ipRange", target_id=range_ref.id, target_path=range_ref.path,
                    before=None, after={"cidr": body.cidr, "label": body.label, "active": body.active},
                    outcome="success", reason="bootstrap" if bootstrap else None, request=request)
        tx.create(range_ref, data)

    try:
        create(transaction)
        invalidate_ip_cache()
        return {"locationId": range_ref.id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("IP range creation failed")
        raise HTTPException(status_code=400, detail="Unable to add IP range") from exc


@router.patch("/ip-ranges/{location_id}")
def edit_range(location_id: str, body: IpRangeEdit, request: Request, staff: dict[str, Any] = Depends(ip_admin)) -> dict[str, bool]:
    try:
        _validated_network(body.cidr)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid IP range") from exc
    target = _range_collection().document(location_id)
    transaction = db.transaction()

    @firestore.transactional
    def update(tx: Any) -> None:
        snapshots = list(_range_collection().stream(transaction=tx))
        docs = {item.id: item.to_dict() or {} for item in snapshots}
        old = docs.get(location_id)
        if old is None:
            raise HTTPException(status_code=404, detail="IP range not found")
        docs[location_id] = {"cidr": body.cidr, "label": body.label.strip(), "active": body.active}
        if not any(value.get("active") for value in docs.values()):
            raise HTTPException(status_code=409, detail="At least one active IP range is required")
        _ensure_not_locked_out(request, staff, docs, body.confirmLockout)
        after = {"cidr": body.cidr, "label": body.label.strip(), "active": body.active,
                 "updatedBy": staff["staffId"], "updatedAt": firestore.SERVER_TIMESTAMP}
        write_audit(tx, actor=staff, action="config.ipRange.edit", category="security",
                    target_type="ipRange", target_id=location_id, target_path=target.path,
                    before=old, after={"cidr": body.cidr, "label": body.label, "active": body.active},
                    outcome="success", reason=None, request=request)
        tx.update(target, after)

    try:
        update(transaction)
        invalidate_ip_cache()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("IP range update failed")
        raise HTTPException(status_code=400, detail="Unable to update IP range") from exc


@router.delete("/ip-ranges/{location_id}")
def delete_range(location_id: str, request: Request, confirmLockout: bool = False,
                 staff: dict[str, Any] = Depends(ip_admin)) -> dict[str, bool]:
    target = _range_collection().document(location_id)
    transaction = db.transaction()

    @firestore.transactional
    def delete(tx: Any) -> None:
        snapshots = list(_range_collection().stream(transaction=tx))
        docs = {item.id: item.to_dict() or {} for item in snapshots}
        before = docs.get(location_id)
        if before is None:
            raise HTTPException(status_code=404, detail="IP range not found")
        docs.pop(location_id)
        if not docs or not any(value.get("active") for value in docs.values()):
            raise HTTPException(status_code=409, detail="At least one active IP range must remain")
        _ensure_not_locked_out(request, staff, docs, confirmLockout)
        write_audit(tx, actor=staff, action="config.ipRange.delete", category="security",
                    target_type="ipRange", target_id=location_id, target_path=target.path,
                    before=before, after=None, outcome="success", reason=None, request=request)
        tx.delete(target)

    try:
        delete(transaction)
        invalidate_ip_cache()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("IP range deletion failed")
        raise HTTPException(status_code=400, detail="Unable to delete IP range") from exc
