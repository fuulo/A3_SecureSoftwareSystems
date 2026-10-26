import os

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-staff-dashboard")

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from backend import audit as audit_module
from backend import auth as auth_dependencies
from backend import sessions
from backend.main import app
from backend.rate_limit import limiter
from backend.routers import auth_lockout
from backend.tests.fake_firestore import FakeAuth, FakeDb, fake_transactional


class Env:
    def __init__(self, db, fake_auth, clock):
        self.db, self.auth, self.clock, self.client = db, fake_auth, clock, TestClient(app)

    def advance(self, **delta):
        self.clock["now"] += timedelta(**delta)

    def headers(self, session_token=None, firebase="uid_voter"):
        headers = {"Authorization": f"Bearer {firebase}"}
        if session_token:
            headers[sessions.HEADER] = session_token
        return headers

    def start(self, firebase="uid_voter"):
        response = self.client.post("/api/session/start", headers=self.headers(firebase=firebase))
        assert response.status_code == 200, response.text
        return response.json()["sessionToken"]

    def renew(self, session_token, firebase="uid_voter"):
        return self.client.post("/api/session/renew", headers=self.headers(session_token, firebase))

    def records(self):
        return {path: data for path, data in self.db.store.items() if path.startswith("sessions/")}

    def audit_actions(self):
        return [data["action"] for path, data in self.db.store.items() if path.startswith("auditLogs/")]


@pytest.fixture
def env(monkeypatch):
    db = FakeDb()
    fake_auth = FakeAuth()
    fake_auth.users["uid_voter"] = {"email": "voter@example.org", "disabled": False}
    signed_in_at = datetime.now(timezone.utc).replace(microsecond=0)
    clock = {"now": signed_in_at}

    # The bearer token stands for a Firebase ID token for that user id
    def verify_id_token(token, **_kwargs):
        return {"uid": token, "email": f"{token}@example.org", "auth_time": int(signed_in_at.timestamp())}

    monkeypatch.setattr(auth_dependencies.auth, "verify_id_token", verify_id_token)
    for module in (sessions, audit_module, auth_lockout):
        monkeypatch.setattr(module, "db", db)
    monkeypatch.setattr(sessions, "auth", fake_auth)
    monkeypatch.setattr(sessions, "_now", lambda: clock["now"])
    # No signing key cached, so each test loads or creates one in its own store
    monkeypatch.setattr(sessions, "_secret", None)
    monkeypatch.setattr(firestore, "transactional", fake_transactional)
    limiter.reset()
    yield Env(db, fake_auth, clock)
    limiter.reset()


def test_a_session_starts_after_signing_in_and_lasts_the_idle_limit(env):
    token = env.start()

    [record] = env.records().values()
    assert record["uid"] == "uid_voter"
    assert record["expiresAt"] == env.clock["now"] + timedelta(seconds=150)
    assert jwt.decode(token, options={"verify_signature": False})["sub"] == "uid_voter"


def test_the_signing_key_is_created_once_and_stored(env):
    assert sessions.SIGNING_KEY_DOCUMENT not in env.db.store

    env.start()
    stored = env.db.store[sessions.SIGNING_KEY_DOCUMENT]["key"]
    env.start()

    assert len(stored) >= 43
    assert env.db.store[sessions.SIGNING_KEY_DOCUMENT]["key"] == stored


def test_sessions_survive_an_api_restart(env, monkeypatch):
    token = env.start()
    # A restarted API has no key in memory and loads the stored one
    monkeypatch.setattr(sessions, "_secret", None)

    assert env.renew(token).status_code == 200


def test_a_session_cannot_be_started_long_after_signing_in(env):
    env.advance(minutes=5, seconds=1)

    response = env.client.post("/api/session/start", headers=env.headers())

    assert response.status_code == 401
    assert response.json()["detail"] == sessions.SESSION_EXPIRED
    assert env.records() == {}


def test_protected_endpoints_need_a_session(env):
    response = env.client.post("/api/auth/lockout/success", headers=env.headers())

    assert response.status_code == 401
    assert response.json()["detail"] == sessions.SESSION_INVALID


def test_protected_endpoints_accept_an_active_session(env):
    token = env.start()

    response = env.client.post("/api/auth/lockout/success", headers=env.headers(token))

    assert response.status_code == 200


def test_activity_keeps_the_session_alive(env):
    token = env.start()
    env.advance(seconds=100)
    renewed = env.renew(token)
    assert renewed.status_code == 200
    env.advance(seconds=100)

    # 200 seconds after starting, but only 100 since the last activity
    assert env.renew(renewed.json()["sessionToken"]).status_code == 200
    assert env.auth.revoked == []


def test_an_idle_session_is_refused_and_ended(env):
    token = env.start()
    env.advance(seconds=151)

    response = env.renew(token)

    assert response.status_code == 401
    assert response.json()["detail"] == sessions.SESSION_EXPIRED
    assert env.auth.revoked == ["uid_voter"]
    assert env.records() == {}
    assert env.audit_actions() == ["auth.sessionTimeout"]


def test_an_ended_session_cannot_be_replaced_without_signing_in_again(env):
    token = env.start()
    env.advance(minutes=5, seconds=1)
    assert env.renew(token).status_code == 401

    assert env.client.post("/api/session/start", headers=env.headers()).status_code == 401


def test_the_sweep_ends_sessions_nobody_renewed(env):
    idle = env.start()
    env.advance(seconds=100)
    active = env.start()
    env.advance(seconds=60)

    assert sessions.sweep_expired_sessions() == 1

    assert env.auth.revoked == ["uid_voter"]
    assert env.renew(active).status_code == 200
    assert env.renew(idle).status_code == 401
    assert env.audit_actions() == ["auth.sessionTimeout"]


def test_a_session_from_another_user_or_a_forged_token_is_refused(env):
    token = env.start()
    forged = jwt.encode({"sub": "uid_voter", "sid": "x", "auth_time": 0, "exp": 9999999999}, "wrong-secret")

    assert env.renew(token, firebase="uid_other").status_code == 401
    assert env.renew(forged).json()["detail"] == sessions.SESSION_INVALID
    assert env.auth.revoked == []


def test_signing_out_closes_the_session_without_revoking(env):
    token = env.start()

    response = env.client.post("/api/session/end", headers={sessions.HEADER: token})

    assert response.status_code == 204
    assert env.records() == {}
    assert env.auth.revoked == []


def test_signing_out_does_not_avoid_the_timeout(env):
    token = env.start()
    env.advance(seconds=151)

    env.client.post("/api/session/end", headers={sessions.HEADER: token})

    assert env.auth.revoked == ["uid_voter"]
    assert env.audit_actions() == ["auth.sessionTimeout"]
