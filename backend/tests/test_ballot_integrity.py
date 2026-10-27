import os

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-staff-dashboard")

import base64
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.cloud import firestore
from starlette.requests import Request

from backend import archive, audit, auth, ballot_integrity, ballots, receipts, reconciliation, results
from backend.main import app
from backend.rate_limit import limiter
from backend.routers import admin_elections
from backend.security.encryption import EncryptionService, generate_key
from backend.tests.fake_firestore import FakeDb, fake_transactional

ELECTION = "e1"
BASE = f"elections/{ELECTION}"
ADMIN = {"staffId": "a1", "role": "admin", "stateId": "VIC"}
API = f"/api/admin/elections/{ELECTION}"
ENCRYPTION = EncryptionService({"k1": generate_key()}, "k1")


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [],
                    "client": ("127.0.0.1", 0), "query_string": b""})


class Env:
    def __init__(self, db: FakeDb, actor: dict) -> None:
        self.db, self.store, self._actor = db, db.store, actor
        self.client = TestClient(app)

    def call(self, method: str, path: str, body: dict | None = None, staff: dict = ADMIN):
        self._actor["staff"] = staff
        return self.client.request(method, path, json=body)

    def cast(self, number: int, house: list[str], above: list[str], below: list[str]) -> None:
        """Stores a voter's ballots, receipt and voted mark, as record_ballot does."""
        self.store[f"{BASE}/houseBallots/h{number}"] = ballots.house_document(
            ELECTION, f"h{number}", "div_vic", house, ENCRYPTION)
        self.store[f"{BASE}/senateBallots/s{number}"] = ballots.senate_document(
            ELECTION, f"s{number}", "VIC", above, below, ENCRYPTION)
        self.store[f"voters/v{number}"] = {"enrolmentStatus": "enrolled", "voted": True,
                                           f"votedElections.{ELECTION}": True}
        self.store[f"receipts/{receipts.receipt_hash(f'{number:016d}')}"] = {"electionId": ELECTION}

    def flags(self) -> dict[str, dict]:
        prefix = f"{BASE}/flaggedBallots/"
        return {path[len(prefix):]: data for path, data in self.store.items() if path.startswith(prefix)}

    def audit_actions(self) -> list[tuple[str, str | None]]:
        entries = sorted((d for p, d in self.store.items() if p.startswith("auditLogs/")), key=lambda e: e["seq"])
        return [(entry["action"], entry["reason"]) for entry in entries]

    def check(self) -> ballot_integrity.BallotCheck:
        return ballot_integrity.check_ballots(ELECTION, ADMIN, _request())


@pytest.fixture
def env(monkeypatch):
    db = FakeDb()
    store = db.store
    store[BASE] = {"name": "Federal", "status": "counting", "timezone": "Australia/Melbourne"}
    store["elections/e2"] = {"name": "By-election", "status": "counting"}
    store[f"{BASE}/divisions/div_vic"] = {"name": "Melbourne", "stateId": "VIC", "seatCount": 1}
    store[f"{BASE}/divisions/div_other"] = {"name": "Other", "stateId": "VIC", "seatCount": 1}
    store[f"{BASE}/senateRegions/VIC"] = {"name": "Victoria", "senatorsToElect": 6}
    store[f"{BASE}/senateGroups/g1"] = {"stateId": "VIC", "displayName": "Group A", "candidateOrder": ["s1", "s2"]}
    for candidate_id, chamber, division in (("h1", "house", "div_vic"), ("h2", "house", "div_vic"),
                                            ("h3", "house", "div_vic"), ("o1", "house", "div_other"),
                                            ("s1", "senate", None), ("s2", "senate", None)):
        store[f"{BASE}/candidates/{candidate_id}"] = {
            "name": candidate_id, "chamber": chamber, "divisionId": division, "stateId": "VIC",
            "groupId": "g1" if chamber == "senate" else None, "withdrawn": candidate_id == "h3"}

    for module in (ballot_integrity, audit, auth, results, receipts, reconciliation, admin_elections):
        monkeypatch.setattr(module, "db", db)
    monkeypatch.setattr(firestore, "transactional", fake_transactional)
    monkeypatch.setattr(ballot_integrity, "get_encryption_service", lambda: ENCRYPTION)
    monkeypatch.setattr(auth, "check_ip_allowlist", lambda request, staff, **kwargs: staff)
    for name, value in {"B2_KEY_ID": None, "ARCHIVE_REQUIRED": False}.items():
        monkeypatch.setattr(archive, name, value)
    actor = {"staff": ADMIN}
    app.dependency_overrides[auth.current_staff] = lambda: actor["staff"]
    environment = Env(db, actor)
    environment.cast(1, ["h1", "h2"], [], ["s1", "s2"])
    environment.cast(2, ["h2", "h1"], ["g1"], [])
    limiter.reset()
    yield environment
    app.dependency_overrides.clear()
    limiter.reset()


# ----------------------------------------------------------------- checking


def test_valid_ballots_are_counted_and_nothing_is_flagged(env):
    check = env.check()

    assert check.summary() == {"countedHouseBallots": 2, "countedSenateBallots": 2,
                               "excludedHouseBallots": 0, "excludedSenateBallots": 0, "pendingFlags": 0}
    assert sorted(ballot["preferences"][0] for ballot in check.house) == ["h1", "h2"]
    assert all(ballot["isFormal"] for ballot in check.house + check.senate)
    assert env.flags() == {}


def _alter_ciphertext(env):
    sealed = env.store[f"{BASE}/houseBallots/h1"]["encryptedPreferences"]
    packed = bytearray(base64.urlsafe_b64decode(sealed["ciphertext"]))
    packed[-1] ^= 1  # one bit of the authentication tag
    sealed["ciphertext"] = base64.urlsafe_b64encode(bytes(packed)).decode("ascii")


def _copy_onto_another_ballot(env):
    # A valid ballot written over another: both IDs now hold h2's choices
    env.store[f"{BASE}/houseBallots/h1"] = json.loads(json.dumps(env.store[f"{BASE}/houseBallots/h2"]))


def _move_to_another_division(env):
    env.store[f"{BASE}/houseBallots/h1"]["divisionId"] = "div_other"


def _relabel_as_paper(env):
    env.store[f"{BASE}/houseBallots/h1"]["source"] = "paper_scan"


@pytest.mark.parametrize("tamper", [_alter_ciphertext, _copy_onto_another_ballot,
                                    _move_to_another_division, _relabel_as_paper])
def test_altered_or_moved_ballots_are_excluded_and_flagged(env, tamper):
    tamper(env)

    check = env.check()

    assert (len(check.house), check.excluded_house, check.excluded_senate) == (1, 1, 0)
    flag = env.flags()["house-h1"]
    assert flag["reason"] == "decrypt_failed" and flag["status"] == "pending"
    assert flag["ballotPath"] == f"{BASE}/houseBallots/h1" and flag["detectedBy"] == "a1"
    # Flags never hold the ballot's choices
    assert not {"encryptedPreferences", "preferences"} & set(flag)
    assert env.audit_actions() == [("ballot.integrityFailed", "decrypt_failed")]


def test_a_ballot_copied_into_another_election_does_not_open_there(env):
    env.store["elections/e2/houseBallots/h1"] = env.store[f"{BASE}/houseBallots/h1"]
    env.store["elections/e2/candidates/h1"] = env.store[f"{BASE}/candidates/h1"]

    check = ballot_integrity.check_ballots("e2", ADMIN, _request())

    assert (len(check.house), check.excluded_house) == (0, 1)
    assert env.store["elections/e2/flaggedBallots/house-h1"]["reason"] == "decrypt_failed"


@pytest.mark.parametrize(("house", "above", "below", "flag_id", "reason"), [
    (["h1", "zz"], [], ["s1"], "house-h9", "unknown_choice"),
    (["h1", "o1"], [], ["s1"], "house-h9", "unknown_choice"),  # a candidate from another division
    (["h1", "h1"], [], ["s1"], "house-h9", "duplicate_choice"),
    (["h1"], ["g9"], [], "senate-s9", "unknown_choice"),
    (["h1"], [], ["s1", "s1"], "senate-s9", "duplicate_choice"),
])
def test_ballots_with_invalid_choices_are_excluded_and_flagged(env, house, above, below, flag_id, reason):
    env.cast(9, house, above, below)

    check = env.check()

    assert check.excluded_house + check.excluded_senate == 1
    assert env.flags()[flag_id]["reason"] == reason


def test_a_ballot_that_does_not_hold_choices_is_flagged_as_malformed(env):
    context = ballots._context(ELECTION, "s1", "senate", "VIC", "electronic")
    sealed = ENCRYPTION.encrypt(json.dumps(["s1"]), context)
    env.store[f"{BASE}/senateBallots/s1"]["encryptedChoices"] = {"ciphertext": sealed.ciphertext,
                                                                  "keyId": sealed.keyId}

    assert env.check().excluded_senate == 1
    assert env.flags()["senate-s1"]["reason"] == "malformed"


def test_ballots_stored_without_integrity_protection_are_flagged(env):
    env.store[f"{BASE}/houseBallots/plain"] = {"divisionId": "div_vic", "preferences": ["h1", "h2"], "isFormal": True}
    unbound = ENCRYPTION.encrypt(json.dumps(["h1", "h2"]))
    env.store[f"{BASE}/houseBallots/unbound"] = {"divisionId": "div_vic", "source": "electronic",
                                                 "encryptedPreferences": {"ciphertext": unbound.ciphertext,
                                                                          "keyId": unbound.keyId}}

    check = env.check()

    assert (len(check.house), check.excluded_house) == (2, 2)
    assert {flag_id: flag["reason"] for flag_id, flag in env.flags().items()} == {
        "house-plain": "legacy_unverified", "house-unbound": "legacy_unverified"}


def test_a_ballot_naming_a_since_withdrawn_candidate_still_counts(env):
    env.cast(3, ["h3", "h1", "h2"], [], ["s1"])

    check = env.check()

    assert check.excluded_house == 0
    # Formality is judged against the two candidates still standing
    assert [b["isFormal"] for b in check.house if b["preferences"][0] == "h3"] == [False]


def test_checking_again_neither_duplicates_flags_nor_counts_a_flagged_ballot(env):
    original = json.loads(json.dumps(env.store[f"{BASE}/houseBallots/h1"]))
    _alter_ciphertext(env)
    env.check()

    env.store[f"{BASE}/houseBallots/h1"] = original
    check = env.check()

    assert list(env.flags()) == ["house-h1"]
    assert env.audit_actions() == [("ballot.integrityFailed", "decrypt_failed")]
    assert check.excluded_house == 1 and check.pending_flags == 1


def test_missing_keys_stop_the_check_without_flagging_anything(env, monkeypatch):
    def unavailable():
        raise RuntimeError("no keys")
    monkeypatch.setattr(ballot_integrity, "get_encryption_service", unavailable)

    with pytest.raises(HTTPException) as refused:
        env.check()

    assert refused.value.status_code == 503
    assert env.flags() == {}


# ------------------------------------------------- review, finalise, publish


def test_finalising_waits_for_every_flag_to_be_reviewed_then_excludes_it(env):
    _alter_ciphertext(env)

    refused = env.call("POST", f"{API}/phase", {"to": "finalised"})
    assert refused.status_code == 409
    assert "must be reviewed" in refused.json()["detail"]
    assert env.store[BASE]["status"] == "counting"

    [flag] = env.call("GET", f"{API}/flagged-ballots").json()
    assert (flag["flagId"], flag["status"], flag["reason"]) == ("house-h1", "pending", "decrypt_failed")
    reviewed = env.call("POST", f"{API}/flagged-ballots/house-h1/review", {"note": "Ciphertext edited; excluded"})
    assert reviewed.status_code == 200
    assert env.flags()["house-h1"]["reviewedBy"] == "a1"

    assert env.call("POST", f"{API}/phase", {"to": "finalised"}).status_code == 200
    [entry] = [d for p, d in env.store.items() if p.startswith("auditLogs/") and d["action"] == "election.phaseChange"
               and d["outcome"] == "success"]
    assert entry["after"]["ballotIntegrity"]["excludedHouseBallots"] == 1

    assert env.call("POST", f"{API}/results/publish").status_code == 201
    package = json.loads(env.store[f"publishedResults/{ELECTION}"]["packageJson"])
    election = package["election"]
    assert (election["ballotsCast"], election["excludedHouseBallots"], election["excludedSenateBallots"]) == (2, 1, 0)
    [house] = [c for c in package["contests"] if c["id"] == "house-div_vic"]
    assert house["ballotsCast"] == 1
    assert {c["id"]: c["votes"] for c in house["candidates"]}["h2"] == 1


def test_publishing_flags_a_ballot_altered_after_finalisation(env):
    env.store[BASE]["status"] = "finalised"
    _relabel_as_paper(env)

    with pytest.raises(HTTPException) as refused:
        results.publish_results(ELECTION, ADMIN, _request())

    assert refused.value.status_code == 409
    assert f"publishedResults/{ELECTION}" not in env.store
    assert env.flags()["house-h1"]["status"] == "pending"


def test_a_flag_is_reviewed_once_with_a_note(env):
    _alter_ciphertext(env)
    env.check()

    assert env.call("POST", f"{API}/flagged-ballots/house-h1/review", {"note": "  "}).status_code == 422
    assert env.call("POST", f"{API}/flagged-ballots/house-h1/review", {"note": "Checked"}).status_code == 200
    assert env.call("POST", f"{API}/flagged-ballots/house-h1/review", {"note": "Again"}).status_code == 409
    assert env.call("POST", f"{API}/flagged-ballots/house-h2/review", {"note": "Checked"}).status_code == 404
    assert ("ballot.flagReviewed", None) in env.audit_actions()


def test_only_admins_see_or_review_flags(env):
    employee = {"staffId": "e1", "role": "aecEmployee", "stateId": "VIC"}

    assert env.call("GET", f"{API}/flagged-ballots", staff=employee).status_code == 403
    assert env.call("POST", f"{API}/ballots/check", staff=employee).status_code == 403


def test_an_admin_can_check_ballots_once_voting_has_closed(env):
    _alter_ciphertext(env)

    response = env.call("POST", f"{API}/ballots/check")

    assert response.status_code == 200
    assert response.json() == {"countedHouseBallots": 1, "countedSenateBallots": 2, "excludedHouseBallots": 1,
                               "excludedSenateBallots": 0, "pendingFlags": 1}
    assert env.audit_actions()[-1] == ("ballot.integrityCheck", None)

    env.store[BASE]["status"] = "open"
    assert env.call("POST", f"{API}/ballots/check").status_code == 409
