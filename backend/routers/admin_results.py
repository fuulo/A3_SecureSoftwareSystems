from typing import Any

from fastapi import APIRouter, Depends, Request

from backend.auth import staff_access
from backend.results import publish_results

router = APIRouter(prefix="/api/admin/elections", tags=["admin-results"])
admin_access = staff_access("admin")


@router.post("/{election_id}/results/publish", status_code=201)
def publish(election_id: str, request: Request,
            staff: dict[str, Any] = Depends(admin_access)) -> dict[str, str]:
    return publish_results(election_id, staff, request)
