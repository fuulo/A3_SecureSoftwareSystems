"""Session tokens for the inactivity timeout (see backend/sessions.py)."""
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from backend import sessions
from backend.auth import verify_firebase_token, verify_token
from backend.rate_limit import limiter

router = APIRouter(prefix="/api/session", tags=["session"])


# Only allowed shortly after signing in
@router.post("/start")
@limiter.limit("30/minute")
def start_session(request: Request, claims: dict[str, Any] = Depends(verify_firebase_token)) -> dict[str, Any]:
    return sessions.start_session(claims)


# Called while the user is active; refused once the session has expired.
# Generous per IP, since a polling place or office shares one address.
@router.post("/renew")
@limiter.limit("120/minute")
def renew_session(request: Request, _claims: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    return sessions.renew_session(request.state.session)


# Sign-out. The session token alone identifies the session, since the Firebase
# sign-in may already be gone.
@router.post("/end", status_code=204)
@limiter.limit("30/minute")
def end_session(request: Request) -> Response:
    sessions.sign_out(request)
    return Response(status_code=204)
