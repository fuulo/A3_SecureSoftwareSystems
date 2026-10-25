import os

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-staff-dashboard")

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from backend import audit as audit_module
from backend import auth as auth_dependencies
from backend.main import app
from backend.rate_limit import limiter
from backend.routers import auth_lockout
from backend.tests.fake_firestore import FakeAuth, FakeDb, fake_transactional

VOTER = "voter@example.org"
STAFF = "pending.staff@example.org"


class Env:
    def __init__(self, db, fake_auth, clock):
        self.db, self.auth, self.clock, self.client = db, fake_auth, clock, TestClient(app)

    def advance(self, **delta):
        self.clock["now"] += timedelta(**delta)

    def fail(self, email=VOTER):
        response = self.client.post("/api/auth/lockout/failure", json={"email": email})
        assert response.status_code == 200, response.text
        return response.json()

    def check(self, email=VOTER):
        response = self.client.post("/api/auth/lockout/check", json={"email": email})
        assert response.status_code == 200, response.text
        return response.json()

    def disabled(self, uid):
        return self.auth.users[uid]["disabled"]

    def audit(self):
        return [data for path, data in self.db.store.items() if path.startswith("auditLogs/")]


@pytest.fixture
def env(monkeypatch):
    db = FakeDb()
    fake_auth = FakeAuth()
    fake_auth.users["uid_voter"] = {"email": VOTER, "disabled": False}
    # Staff accounts awaiting approval are created disabled
    fake_auth.users["uid_pending"] = {"email": STAFF, "disabled": True}
    clock = {"now": datetime(2028, 1, 1, 9, 0, tzinfo=timezone.utc)}
    for module in (auth_lockout, audit_module):
        monkeypatch.setattr(module, "db", db)
    monkeypatch.setattr(auth_lockout, "auth", fake_auth)
    monkeypatch.setattr(auth_lockout, "_now", lambda: clock["now"])
    monkeypatch.setattr(firestore, "transactional", fake_transactional)
    limiter.reset()
    yield Env(db, fake_auth, clock)
    app.dependency_overrides.clear()
    limiter.reset()


def test_lock_lengths_double_up_to_an_hour():
    minutes = [auth_lockout.lock_duration(n) / timedelta(minutes=1) for n in range(1, 8)]
    assert minutes == [5, 10, 20, 40, 60, 60, 60]


def test_three_consecutive_failures_lock_the_account_for_five_minutes(env):
    assert env.fail() == {"locked": False, "retryAfterSeconds": 0, "attemptsRemaining": 2}
    assert env.fail()["attemptsRemaining"] == 1
    locked = env.fail()

    assert locked["locked"] is True
    assert 299 <= locked["retryAfterSeconds"] <= 301
    assert env.disabled("uid_voter") is True
    [entry] = env.audit()
    assert entry["action"] == "auth.lockout"
    assert entry["targetId"] == "uid_voter"
    assert entry["after"]["failures"] == 3


def test_failures_during_a_lock_are_refused_not_counted(env):
    for _ in range(3):
        env.fail()
    env.advance(minutes=2)

    status = env.fail()

    assert status["locked"] is True
    assert 179 <= status["retryAfterSeconds"] <= 181
    [record] = [data for path, data in env.db.store.items() if path.startswith("authLockouts/")]
    assert record["failures"] == 3


def test_lock_ends_after_five_minutes_and_the_account_is_re_enabled(env):
    for _ in range(3):
        env.fail()
    env.advance(minutes=4, seconds=59)
    assert env.check()["locked"] is True
    assert env.disabled("uid_voter") is True

    env.advance(seconds=2)

    assert env.check() == {"locked": False, "retryAfterSeconds": 0, "attemptsRemaining": 3}
    assert env.disabled("uid_voter") is False


def test_each_further_three_failures_double_the_lock_up_to_an_hour(env):
    expected_minutes = [5, 10, 20, 40, 60, 60]
    for minutes in expected_minutes:
        for _ in range(3):
            status = env.fail()
        assert status["locked"] is True
        assert minutes * 60 - 1 <= status["retryAfterSeconds"] <= minutes * 60 + 1
        assert env.disabled("uid_voter") is True
        # Waiting out the lock re-enables the account before the next failures
        env.advance(minutes=minutes, seconds=1)
        # The per-IP rate limit runs on real time, not the test clock
        limiter.reset()


def test_a_real_sign_in_resets_the_count(env):
    env.fail()
    env.fail()
    app.dependency_overrides[auth_dependencies.verify_token] = lambda: {"uid": "uid_voter", "email": VOTER}

    response = env.client.post("/api/auth/lockout/success")

    assert response.status_code == 200
    assert env.fail()["attemptsRemaining"] == 2
    assert env.fail()["locked"] is False


def test_resetting_the_count_needs_a_valid_sign_in(env):
    response = env.client.post("/api/auth/lockout/success")

    assert response.status_code == 401


def test_unknown_email_gets_the_same_responses(env):
    responses = [env.fail("nobody@example.org") for _ in range(3)]

    assert [r["attemptsRemaining"] for r in responses[:2]] == [2, 1]
    assert responses[2]["locked"] is True
    assert env.check("nobody@example.org")["locked"] is True
    assert all(not user["disabled"] for uid, user in env.auth.users.items() if uid == "uid_voter")


def test_email_case_and_spaces_do_not_reset_the_count(env):
    env.fail(VOTER)
    env.fail(VOTER.upper())

    assert env.fail(f" {VOTER} ".strip().title())["locked"] is True


def test_an_account_disabled_for_another_reason_stays_disabled_after_the_lock(env):
    for _ in range(3):
        env.fail(STAFF)
    env.advance(minutes=5, seconds=1)

    assert env.check(STAFF)["locked"] is False
    assert env.disabled("uid_pending") is True


def test_staff_deactivated_during_a_lock_are_not_re_enabled(env):
    env.db.store["staff/s1"] = {"authUid": "uid_voter", "active": True}
    for _ in range(3):
        env.fail()
    env.db.store["staff/s1"]["active"] = False
    env.advance(minutes=5, seconds=1)

    env.check()

    assert env.disabled("uid_voter") is True


def test_failure_reports_are_rate_limited_per_ip(env):
    for index in range(10):
        env.fail(f"user{index}@example.org")

    response = env.client.post("/api/auth/lockout/failure", json={"email": "user10@example.org"})

    assert response.status_code == 429
