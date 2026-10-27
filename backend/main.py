import asyncio
import logging
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone


from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded


from backend import sessions
from backend.config import ALLOWED_ORIGINS
from backend.auth import staff_access
from backend.firestore_client import db
from backend.rate_limit import limiter
from backend.routers import (
    admin_audit,
    admin_elections,
    admin_ip,
    admin_results,
    admin_staff,
    auth_lockout,
    employee_candidates,
    employee_voters,
    public_results,
    session,
    voter_ballot_session,
    voter_registration,
)


logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Ends sessions left idle past the inactivity limit (see backend/sessions.py)
    sweep = asyncio.create_task(sessions.sweep_forever())
    yield
    sweep.cancel()


app = FastAPI(title="E-voting Staff API", lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Session-Id", sessions.HEADER],
)


app.include_router(admin_staff.router)
app.include_router(admin_ip.router)
app.include_router(admin_elections.router)
app.include_router(admin_audit.router)
app.include_router(employee_voters.router)
app.include_router(employee_candidates.router)
app.include_router(admin_results.router)
app.include_router(voter_registration.router)
app.include_router(voter_ballot_session.router)
app.include_router(public_results.router)
app.include_router(auth_lockout.router)
app.include_router(session.router)



def _record_request_failure(request: Request, *, outcome: str, reason: str) -> None:
    staff = getattr(request.state, "staff", None)
    if not staff or getattr(request.state, "audit_written", False):
        return
    try:
        from backend.audit import audit_standalone


        phase_change = request.url.path.startswith("/api/admin/elections/") and request.url.path.endswith("/phase")
        denied = outcome == "denied" and not phase_change
        audit_standalone(
            actor=staff,
            action="election.phaseChange" if phase_change else ("auth.denied" if denied else "request.failed"),
            category="admin" if phase_change else "security",
            target_type="election" if phase_change else "request",
            target_id=request.path_params.get("election_id") if phase_change else None,
            target_path=request.url.path,
            before=None,
            after=None,
            outcome=outcome,
            reason=reason,
            request=request,
        )
    except Exception:
        logging.exception("Unable to record staff request failure")



@app.exception_handler(HTTPException)
async def audit_staff_failure(request: Request, exc: HTTPException):
    _record_request_failure(
        request,
        outcome="denied" if exc.status_code == 403 else "failed",
        reason=f"http_{exc.status_code}",
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)



@app.exception_handler(RequestValidationError)
async def validation_failure(request: Request, exc: RequestValidationError):
    logging.info("Staff API request validation failed for %s", request.url.path)
    _record_request_failure(request, outcome="failed", reason="request_validation_failed")
    return JSONResponse(status_code=422, content={"detail": "Request validation failed"})



@app.exception_handler(RateLimitExceeded)
async def rate_limit_failure(request: Request, exc: RateLimitExceeded):
    _record_request_failure(request, outcome="failed", reason="rate_limit_exceeded")
    return _rate_limit_exceeded_handler(request, exc)



@app.exception_handler(Exception)
async def unexpected_failure(request: Request, exc: Exception):
    logging.exception("Unhandled API error")
    _record_request_failure(request, outcome="failed", reason="internal_error")
    return JSONResponse(status_code=500, content={"detail": "The request could not be completed"})



@app.get("/api/me")
def me(staff=Depends(staff_access("admin", "aecEmployee", "commissionerDelegate"))):
    return {
        "staffId": staff["staffId"],
        "name": staff.get("name"),
        "role": staff.get("role"),
        "stateId": staff.get("stateId"),
    }



@app.get("/api/elections/active/divisions")
def active_divisions(staff=Depends(staff_access("aecEmployee"))):
    active = list(db.collection("elections").where("status", "in", ["setup", "open"]).stream())
    active.sort(key=lambda item: 0 if item.get("status") == "open" else 1)
    if not active:
        raise HTTPException(status_code=404, detail="No active election")
    return [
        {"divisionId": item.id, **(item.to_dict() or {})}
        for item in active[0].reference.collection("divisions").stream()
    ]



@app.get("/health")
def health():
    # The load balancer polls this; the instance name shows which one answered
    return {"status": "ok", "instance": socket.gethostname()}