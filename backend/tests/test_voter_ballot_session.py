import os

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-staff-dashboard")

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.cloud import firestore
from starlette.requests import Request

from backend import archive, audit, auth, receipts, reconciliation, results
from backend.auth import enforce_voter_ip_allowlist, verify_token
from backend.main import app
from backend.rate_limit import limiter
from backend.routers import voter_ballot_session, voter_ballots
from backend.security.encryption import EncryptionService, generate_key
from backend.tests.fake_firestore import FakeDb, fake_transactional

ELECTION = "e1"
START_URL = f"/api/voter/ballots/{ELECTION}/start"
SUBMIT_URL = f"/api/voter/ballots/{ELECTION}/submit"
# Every House candidate numbered; below the line covers all Senate candidates
BALLOT = {"house": {"preferences": ["h2", "h1"]}, "senate": {"aboveTheLine": [], "belowTheLine": ["s1", "s2"]}}


class Env:
    def __init__(self, db: FakeDb, encryption: EncryptionService) -> None:
        self.db, self.store, self.encryption = db, db.store, encryption
        self.uid = "uid_1"
        self.client = TestClient(app)

    def post(self, path: str, body: dict | None = None, uid: str = "uid_1"):
        self.uid = uid
        return self.client.post(path, json=body)

    def voter(self, voter_id: str = "v1") -> dict:
        return self.store[f"voters/{voter_id}"]

    def docs(self, collection: str) -> list[dict]:
        return [data for path, data in self.store.items() if path.startswith(collection + "/")]

    def audit_actions(self) -> list[tuple[str, str | None]]:
        entries = sorted(self.docs("auditLogs"), key=lambda entry: entry["seq"])
        return [(entry["action"], entry["reason"]) for entry in entries]


@pytest.fixture
def env(monkeypatch):
    db = FakeDb()
    now = datetime.now(timezone.utc)
    store = db.store
    store[f"elections/{ELECTION}"] = {"name": "Federal", "status": "open", "timezone": "Australia/Melbourne",
                                      "openAt": now - timedelta(hours=1), "closeAt": now + timedelta(hours=1)}
    store[f"elections/{ELECTION}/divisions/div_vic"] = {"name": "Melbourne", "stateId": "VIC", "seatCount": 1}
    store[f"elections/{ELECTION}/senateRegions/VIC"] = {"name": "Victoria", "senatorsToElect": 6}
    store[f"elections/{ELECTION}/senateGroups/g1"] = {"stateId": "VIC", "displayName": "Group A",
                                                      "candidateOrder": ["s1", "s2"]}
    for candidate_id, chamber in (("h1", "house"), ("h2", "house"), ("s1", "senate"), ("s2", "senate")):
        store[f"elections/{ELECTION}/candidates/{candidate_id}"] = {
            "name": candidate_id, "chamber": chamber, "divisionId": "div_vic" if chamber == "house" else None,
            "stateId": "VIC", "groupId": "g1" if chamber == "senate" else None,
        }
    for number in (1, 2):
        store[f"voters/v{number}"] = {"authUid": f"uid_{number}", "enrolmentStatus": "enrolled",
                                      "divisionId": "div_vic", "stateId": "VIC", "voted": False}

    for module in (voter_ballots, receipts, audit, reconciliation, results, auth):
        monkeypatch.setattr(module, "db", db)
    monkeypatch.setattr(firestore, "transactional", fake_transactional)
    encryption = EncryptionService({"k1": generate_key()}, "k1")
    monkeypatch.setattr(voter_ballot_session, "get_encryption_service", lambda: encryption)
    monkeypatch.setattr(results, "get_encryption_service", lambda: encryption)
    for name, value in {"B2_KEY_ID": None, "ARCHIVE_REQUIRED": False}.items():
        monkeypatch.setattr(archive, name, value)

    environment = Env(db, encryption)
    app.dependency_overrides[verify_token] = lambda: {"uid": environment.uid}
    app.dependency_overrides[enforce_voter_ip_allowlist] = lambda: None
    limiter.reset()
    yield environment
    app.dependency_overrides.clear()
    limiter.reset()


def _cast(env: Env, uid: str = "uid_1", body: dict = BALLOT):
    assert env.post(START_URL, uid=uid).status_code == 200
    return env.post(SUBMIT_URL, body, uid=uid)


# ------------------------------------------------------------------- start


def test_start_marks_the_voter_as_voting_for_fifteen_minutes(env):
    response = env.post(START_URL)

    assert response.status_code == 200
    voter = env.voter()
    assert voter["voting"] is True and voter["activeElectionId"] == ELECTION
    remaining = voter["sessionExpiresAt"] - datetime.now(timezone.utc)
    assert timedelta(minutes=14) < remaining <= timedelta(minutes=15)


def test_start_requires_a_bearer_token(env):
    del app.dependency_overrides[verify_token]

    assert env.post(START_URL).status_code == 401


def test_start_is_refused_for_a_voter_who_is_not_enrolled(env):
    env.voter()["enrolmentStatus"] = "pending"

    response = env.post(START_URL)

    assert response.status_code == 403
    assert "voting" not in env.voter()
    assert env.audit_actions() == [("ballot.session.rejected", "not_enrolled")]


def test_start_is_refused_after_voting_in_this_election(env):
    assert _cast(env).status_code == 201

    assert env.post(START_URL).status_code == 409


def test_a_second_session_is_refused_until_the_first_expires(env):
    assert env.post(START_URL).status_code == 200
    assert env.post(START_URL).status_code == 409

    env.voter()["sessionExpiresAt"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert env.post(START_URL).status_code == 200


@pytest.mark.parametrize("change", [{"status": "closed"}, {"closeAt": datetime(2000, 1, 1, tzinfo=timezone.utc)}])
def test_start_is_refused_when_voting_is_not_open(env, change):
    env.store[f"elections/{ELECTION}"].update(change)

    assert env.post(START_URL).status_code == 409
    assert "voting" not in env.voter()


def test_start_is_refused_from_a_network_outside_the_voter_allowlist(env, monkeypatch):
    del app.dependency_overrides[enforce_voter_ip_allowlist]
    monkeypatch.setattr(auth, "_active_ranges", lambda: [])

    assert env.post(START_URL).status_code == 403
    assert "voting" not in env.voter()


# ------------------------------------------------------------------ submit


def test_submitting_stores_an_encrypted_ballot_and_returns_a_receipt(env):
    response = _cast(env)

    assert response.status_code == 201
    body = response.json()
    assert receipts.normalize_receipt(body["receipt"]) is not None and body["electionId"] == ELECTION
    [house] = env.docs(f"elections/{ELECTION}/houseBallots")
    [senate] = env.docs(f"elections/{ELECTION}/senateBallots")
    # Only the contest stays readable: no choices, formality, voter reference or time
    assert set(house) == {"divisionId", "source", "encryptedPreferences"}
    assert set(senate) == {"stateId", "source", "encryptedChoices"}
    assert "h1" not in json.dumps(house) and "s1" not in json.dumps(senate)
    assert json.loads(env.encryption.decrypt(_sealed(house["encryptedPreferences"]))) == ["h2", "h1"]
    # The receipt is stored hashed, for this election
    assert env.store[f"receipts/{receipts.receipt_hash(receipts.normalize_receipt(body['receipt']))}"][
        "electionId"] == ELECTION
    voter = env.voter()
    assert voter["voted"] is True and voter[reconciliation.voted_field(ELECTION)] is True
    assert voter["voting"] is False and voter["activeElectionId"] is None


def test_submitting_without_an_active_session_is_refused(env):
    response = env.post(SUBMIT_URL, BALLOT)

    assert response.status_code == 409
    assert env.voter()["voted"] is False
    assert env.audit_actions() == [("ballot.rejected", "no_active_session")]


def test_an_expired_session_cannot_submit(env):
    env.post(START_URL)
    env.voter()["sessionExpiresAt"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert env.post(SUBMIT_URL, BALLOT).status_code == 409
    assert env.docs(f"elections/{ELECTION}/houseBallots") == []


def test_a_second_ballot_is_refused_and_audited(env):
    assert _cast(env).status_code == 201

    response = env.post(SUBMIT_URL, BALLOT)

    assert response.status_code == 409
    assert len(env.docs(f"elections/{ELECTION}/houseBallots")) == 1
    assert ("ballot.rejected", "double_vote_attempt") in env.audit_actions()


@pytest.mark.parametrize("ballot", [
    {"house": {"preferences": ["h1", "h9"]}, "senate": {}},
    {"house": {"preferences": ["h1", "h1"]}, "senate": {}},
    {"house": {"preferences": []}, "senate": {"aboveTheLine": ["g9"]}},
])
def test_invalid_choices_are_refused_and_nothing_is_written(env, ballot):
    env.post(START_URL)

    response = env.post(SUBMIT_URL, ballot)

    assert response.status_code == 422
    assert env.docs(f"elections/{ELECTION}/houseBallots") == []
    assert env.docs("receipts") == []
    assert env.voter()["voted"] is False


def test_submitting_after_voting_closes_is_refused(env):
    env.post(START_URL)
    env.store[f"elections/{ELECTION}"]["status"] = "closed"

    assert env.post(SUBMIT_URL, BALLOT).status_code == 409
    assert env.voter()["voted"] is False


# ----------------------------------------------------- reconciling and counting


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [],
                    "client": ("127.0.0.1", 0), "query_string": b""})


def _sealed(value: dict):
    from backend.security.encryption import EncryptedValue
    return EncryptedValue(value["ciphertext"], value["keyId"])


def test_encrypted_ballots_reconcile_and_are_counted_when_published(env):
    assert _cast(env, "uid_1").status_code == 201
    # Second voter: House informal (one of two numbered); Senate above the line
    assert _cast(env, "uid_2", {"house": {"preferences": ["h1"]},
                                "senate": {"aboveTheLine": ["g1"], "belowTheLine": []}}).status_code == 201

    assert reconciliation.reconcile_votes(ELECTION)["reconciled"] is True
    env.store[f"elections/{ELECTION}"]["status"] = "finalised"
    results.publish_results(ELECTION, {"staffId": "a1", "role": "admin"}, _request())

    contests = {c["id"]: c for c in json.loads(env.store[f"publishedResults/{ELECTION}"]["packageJson"])["contests"]}
    house, senate = contests["house-div_vic"], contests["senate-VIC"]
    assert (house["ballotsCast"], house["informal"]) == (2, 1)
    assert {c["id"]: c["votes"] for c in house["candidates"]} == {"h1": 0, "h2": 1}
    assert senate["informal"] == 0
    assert {c["id"]: c["votes"] for c in senate["candidates"]} == {"g1": 2}


def test_a_ballot_that_cannot_be_decrypted_stops_publication(env):
    assert _cast(env).status_code == 201
    [path] = [p for p in env.store if p.startswith(f"elections/{ELECTION}/houseBallots/")]
    sealed = env.store[path]["encryptedPreferences"]
    env.store[path]["encryptedPreferences"] = {**sealed, "ciphertext": sealed["ciphertext"][:-4] + "AAAA"}
    env.store[f"elections/{ELECTION}"]["status"] = "finalised"

    with pytest.raises(HTTPException) as refused:
        results.publish_results(ELECTION, {"staffId": "a1", "role": "admin"}, _request())

    assert refused.value.status_code == 409
    assert f"publishedResults/{ELECTION}" not in env.store


def test_ballots_stored_before_encryption_are_still_counted(env):
    assert _cast(env).status_code == 201
    env.store[f"elections/{ELECTION}/houseBallots/legacy"] = {
        "divisionId": "div_vic", "preferences": ["h1", "h2"], "source": "electronic", "isFormal": True}
    env.store[f"elections/{ELECTION}/senateBallots/legacy"] = {
        "stateId": "VIC", "aboveTheLine": ["g1"], "belowTheLine": [], "source": "electronic",
        "isFormal": True, "countedAs": "aboveTheLine"}

    house, senate = results._open_ballots(
        {k.rsplit("/", 1)[1]: v for k, v in env.store.items() if "/candidates/" in k},
        env.docs(f"elections/{ELECTION}/houseBallots"), env.docs(f"elections/{ELECTION}/senateBallots"))

    assert sorted(b["preferences"][0] for b in house) == ["h1", "h2"]
    assert all(b["isFormal"] for b in house + senate)
