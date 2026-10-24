import os

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-staff-dashboard")

import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from backend import audit as audit_module
from backend import auth as auth_dependencies
from backend.main import app
from backend.rate_limit import limiter
from backend.routers import admin_staff, employee_candidates
from backend.tests.fake_firestore import FakeAuth, FakeDb, fake_transactional

ELECTION = "/api/delegate/elections/e1"
PASSWORD = "Str0ngPassw0rd!"
HOUSE = {"name": "Alex Nguyen", "partyId": "p1", "chamber": "house", "divisionId": "div_vic", "ballotPosition": 1}
SENATE = {"name": "Sam Senator", "partyId": "p1", "chamber": "senate", "stateId": "VIC",
          "groupId": "g1", "ballotPosition": 1}
NEW_STAFF = {"name": "Alex Employee", "email": "Alex@Example.org", "role": "aecEmployee",
             "stateId": "VIC", "password": PASSWORD}


def staff_record(role, state="VIC", active=True):
    return {"authUid": "uid_" + role, "name": role, "role": role, "stateId": state, "active": active}


class Env:
    def __init__(self, db, fake_auth, actor):
        self.db, self.auth, self._actor, self.client = db, fake_auth, actor, TestClient(app)

    def call(self, staff_id, method, path, body=None):
        record = self.db.store[f"staff/{staff_id}"]
        self._actor["staff"] = {**record, "staffId": staff_id}
        return self.client.request(method, path, json=body)

    def doc(self, path):
        return self.db.store.get(path)

    def requests(self, collection):
        return {path.rsplit("/", 1)[-1]: data for path, data in self.db.store.items()
                if path.startswith(collection + "/")}

    def only_request(self, collection):
        [(request_id, data)] = self.requests(collection).items()
        return request_id, data

    def candidates(self):
        return self.requests("elections/e1/candidates")

    def audit(self):
        entries = [data for path, data in self.db.store.items() if path.startswith("auditLogs/")]
        return sorted(entries, key=lambda entry: entry["seq"])

    def audit_actions(self):
        return [(entry["action"], entry["actorId"]) for entry in self.audit()]


@pytest.fixture
def env(monkeypatch):
    db = FakeDb()
    store = db.store
    store["elections/e1"] = {"name": "Federal", "status": "setup"}
    store["elections/e1/divisions/div_vic"] = {"name": "Melbourne", "stateId": "VIC"}
    store["elections/e1/divisions/div_nsw"] = {"name": "Sydney", "stateId": "NSW"}
    store["elections/e1/parties/p1"] = {"name": "Party One"}
    store["elections/e1/senateRegions/VIC"] = {"name": "Victoria", "senatorsToElect": 6}
    store["elections/e1/senateGroups/g1"] = {"stateId": "VIC", "candidateOrder": [], "candidateCount": 0}
    store["staff/d1"] = staff_record("commissionerDelegate")
    store["staff/d2"] = staff_record("commissionerDelegate")
    store["staff/d3"] = staff_record("commissionerDelegate", "NSW")
    store["staff/a1"] = staff_record("admin")
    store["staff/a2"] = staff_record("admin")
    store["staff/a3"] = staff_record("admin")
    store["staff/emp"] = staff_record("aecEmployee")
    for staff_id, data in list(store.items()):
        if staff_id.startswith("staff/"):
            data["authUid"] = "uid_" + staff_id.split("/")[1]

    fake_auth = FakeAuth()
    for path, data in store.items():
        if path.startswith("staff/"):
            fake_auth.users[data["authUid"]] = {"email": path + "@x.org", "disabled": False}
    for module in (employee_candidates, admin_staff, audit_module):
        monkeypatch.setattr(module, "db", db)
    monkeypatch.setattr(firestore, "transactional", fake_transactional)
    monkeypatch.setattr(admin_staff, "auth", fake_auth)
    monkeypatch.setattr(auth_dependencies, "check_ip_allowlist", lambda request, staff, **kwargs: staff)
    actor = {"staff": None}
    app.dependency_overrides[auth_dependencies.current_staff] = lambda: actor["staff"]
    limiter.reset()
    yield Env(db, fake_auth, actor)
    app.dependency_overrides.clear()
    limiter.reset()


def submit_house_candidate(env, who="d1", **overrides):
    response = env.call(who, "POST", f"{ELECTION}/candidates", {**HOUSE, **overrides})
    assert response.status_code == 202, response.text
    return response.json()["requestId"]


def approve(env, who, request_id):
    return env.call(who, "POST", f"{ELECTION}/change-requests/{request_id}/approve")


def reject(env, who, request_id, reason="Not correct"):
    return env.call(who, "POST", f"{ELECTION}/change-requests/{request_id}/reject", {"reason": reason})


def add_candidate(env, candidate_id="c1", **overrides):
    env.db.store[f"elections/e1/candidates/{candidate_id}"] = {
        "name": "Old Name", "partyId": "p1", "chamber": "house", "divisionId": "div_vic", "stateId": "VIC",
        "groupId": None, "ballotPosition": 1, "enteredBy": "d1", "excluded": False, "withdrawn": False,
        **overrides,
    }


def assert_audit_chain_is_intact(env):
    previous, seen = "", set()
    for number, entry in enumerate(env.audit(), start=1):
        body = {key: value for key, value in entry.items() if key != "hash"}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        assert entry["seq"] == number and number not in seen
        assert entry["previousHash"] == previous
        assert entry["hash"] == hashlib.sha256((previous + canonical).encode()).hexdigest()
        previous = entry["hash"]
        seen.add(number)


# ---------------------------------------------------------------- candidates


def test_creating_a_candidate_only_submits_a_request(env):
    request_id = submit_house_candidate(env)

    assert env.candidates() == {}
    request = env.doc(f"elections/e1/candidateChangeRequests/{request_id}")
    assert request["status"] == "pending"
    assert request["action"] == "candidate.create"
    assert request["requestedBy"] == "d1" and request["stateId"] == "VIC"
    assert request["payload"]["candidate"]["name"] == "Alex Nguyen"
    assert env.audit_actions() == [("candidate.create.request", "d1")]


def test_requester_cannot_approve_or_reject_their_own_candidate_change(env):
    request_id = submit_house_candidate(env)

    assert approve(env, "d1", request_id).status_code == 403
    assert reject(env, "d1", request_id).status_code == 403

    assert env.candidates() == {}
    assert env.doc(f"elections/e1/candidateChangeRequests/{request_id}")["status"] == "pending"


def test_another_delegate_approval_creates_the_candidate(env):
    request_id = submit_house_candidate(env)

    response = approve(env, "d2", request_id)

    assert response.status_code == 200
    [(candidate_id, candidate)] = env.candidates().items()
    assert candidate["name"] == "Alex Nguyen"
    assert candidate["enteredBy"] == "d1"
    assert candidate["withdrawn"] is False and candidate["stateId"] == "VIC"
    request = env.doc(f"elections/e1/candidateChangeRequests/{request_id}")
    assert (request["status"], request["reviewedBy"]) == ("approved", "d2")
    assert env.audit_actions() == [("candidate.create.request", "d1"), ("candidate.create", "d2")]
    assert env.audit()[-1]["targetId"] == candidate_id
    assert_audit_chain_is_intact(env)


def test_a_decided_request_cannot_be_decided_again(env):
    request_id = submit_house_candidate(env)
    assert approve(env, "d2", request_id).status_code == 200

    assert approve(env, "d2", request_id).status_code == 409
    assert reject(env, "d2", request_id).status_code == 409
    assert len(env.candidates()) == 1


def test_delegate_from_another_state_cannot_review(env):
    request_id = submit_house_candidate(env)

    assert approve(env, "d3", request_id).status_code == 403
    assert reject(env, "d3", request_id).status_code == 403
    assert env.candidates() == {}


@pytest.mark.parametrize("who", ["a1", "emp"])
def test_other_roles_cannot_review_candidate_requests(env, who):
    request_id = submit_house_candidate(env)

    assert approve(env, who, request_id).status_code == 403


def test_rejection_records_the_reason_and_changes_nothing(env):
    request_id = submit_house_candidate(env)

    response = reject(env, "d2", request_id, "Wrong division")

    assert response.status_code == 200
    assert env.candidates() == {}
    request = env.doc(f"elections/e1/candidateChangeRequests/{request_id}")
    assert (request["status"], request["reviewReason"]) == ("rejected", "Wrong division")
    assert env.audit_actions()[-1] == ("candidate.create.reject", "d2")
    assert env.audit()[-1]["reason"] == "Wrong division"


def test_rejection_requires_a_reason(env):
    request_id = submit_house_candidate(env)

    assert env.call("d2", "POST", f"{ELECTION}/change-requests/{request_id}/reject", {"reason": ""}).status_code == 422


def test_senate_candidate_updates_its_group_only_when_approved(env):
    response = env.call("d1", "POST", f"{ELECTION}/candidates", SENATE)
    assert response.status_code == 202
    assert env.doc("elections/e1/senateGroups/g1")["candidateOrder"] == []

    assert approve(env, "d2", response.json()["requestId"]).status_code == 200

    assert env.doc("elections/e1/senateGroups/g1")["candidateOrder"] == [response.json()["candidateId"]]


def test_invalid_candidate_is_refused_at_submission(env):
    response = env.call("d1", "POST", f"{ELECTION}/candidates", {**HOUSE, "partyId": "missing"})

    assert response.status_code == 422
    assert env.requests("elections/e1/candidateChangeRequests") == {}


def test_division_in_another_state_is_refused_at_submission(env):
    response = env.call("d1", "POST", f"{ELECTION}/candidates", {**HOUSE, "divisionId": "div_nsw"})

    assert response.status_code == 403


def test_approval_rechecks_ballot_position_conflicts(env):
    first = submit_house_candidate(env, "d1")
    second = submit_house_candidate(env, "d1", name="Bea Other")

    assert approve(env, "d2", first).status_code == 200
    response = approve(env, "d2", second)

    assert response.status_code == 409
    assert len(env.candidates()) == 1
    assert env.doc(f"elections/e1/candidateChangeRequests/{second}")["status"] == "pending"
    assert reject(env, "d2", second, "Position taken").status_code == 200


def test_approval_is_refused_once_candidates_are_locked(env):
    request_id = submit_house_candidate(env)
    env.db.store["elections/e1"]["status"] = "open"

    response = approve(env, "d2", request_id)

    assert response.status_code == 409
    assert env.candidates() == {}


def test_editing_a_candidate_applies_only_after_approval(env):
    add_candidate(env)

    response = env.call("d1", "PATCH", f"{ELECTION}/candidates/c1", {"name": "New Name", "ballotPosition": 2})

    assert response.status_code == 202
    assert env.doc("elections/e1/candidates/c1")["name"] == "Old Name"
    request_id = response.json()["requestId"]
    assert env.doc(f"elections/e1/candidateChangeRequests/{request_id}")["before"] == {
        "name": "Old Name", "ballotPosition": 1}
    assert approve(env, "d2", request_id).status_code == 200
    assert env.doc("elections/e1/candidates/c1")["name"] == "New Name"
    assert env.doc("elections/e1/candidates/c1")["ballotPosition"] == 2
    assert env.audit_actions() == [("candidate.edit.request", "d1"), ("candidate.edit", "d2")]
    assert_audit_chain_is_intact(env)


def test_only_one_undecided_change_per_candidate(env):
    add_candidate(env)
    assert env.call("d1", "PATCH", f"{ELECTION}/candidates/c1", {"name": "One"}).status_code == 202

    assert env.call("d2", "PATCH", f"{ELECTION}/candidates/c1", {"name": "Two"}).status_code == 409
    assert env.call("d2", "POST", f"{ELECTION}/candidates/c1/withdraw", {"reason": "x"}).status_code == 409


def test_a_new_change_is_allowed_after_the_previous_one_is_decided(env):
    add_candidate(env)
    first = env.call("d1", "PATCH", f"{ELECTION}/candidates/c1", {"name": "One"}).json()["requestId"]
    assert reject(env, "d2", first).status_code == 200

    assert env.call("d1", "PATCH", f"{ELECTION}/candidates/c1", {"name": "Two"}).status_code == 202


def test_withdrawing_a_candidate_applies_only_after_approval(env):
    add_candidate(env)

    response = env.call("d1", "POST", f"{ELECTION}/candidates/c1/withdraw", {"reason": "Ill health"})

    assert response.status_code == 202
    assert env.doc("elections/e1/candidates/c1")["withdrawn"] is False
    assert approve(env, "d2", response.json()["requestId"]).status_code == 200
    candidate = env.doc("elections/e1/candidates/c1")
    assert candidate["withdrawn"] is True
    assert (candidate["withdrawnBy"], candidate["withdrawalReason"]) == ("d1", "Ill health")
    assert "Ill health" in env.audit()[-1]["reason"]
    assert_audit_chain_is_intact(env)


def test_cannot_request_changes_to_a_candidate_in_another_state(env):
    add_candidate(env)

    assert env.call("d3", "PATCH", f"{ELECTION}/candidates/c1", {"name": "Nope"}).status_code == 403
    assert env.call("d3", "POST", f"{ELECTION}/candidates/c1/withdraw", {"reason": "x"}).status_code == 403


def test_change_request_list_is_scoped_to_the_delegates_state(env):
    pending = submit_house_candidate(env)
    decided = submit_house_candidate(env, name="Bea Other", ballotPosition=2)
    assert reject(env, "d2", decided).status_code == 200

    vic = env.call("d2", "GET", f"{ELECTION}/change-requests").json()
    nsw = env.call("d3", "GET", f"{ELECTION}/change-requests").json()

    assert [item["requestId"] for item in vic["pending"]] == [pending]
    assert [item["requestId"] for item in vic["recent"]] == [decided]
    assert nsw == {"pending": [], "recent": []}


# --------------------------------------------------------------------- staff


def submit_staff(env, who="a1", **overrides):
    response = env.call(who, "POST", "/api/admin/staff", {**NEW_STAFF, **overrides})
    assert response.status_code == 202, response.text
    return response.json()["requestId"]


def approve_staff(env, who, request_id):
    return env.call(who, "POST", f"/api/admin/staff/change-requests/{request_id}/approve")


def reject_staff(env, who, request_id, reason="Not needed"):
    return env.call(who, "POST", f"/api/admin/staff/change-requests/{request_id}/reject", {"reason": reason})


def test_creating_staff_submits_a_request_and_keeps_the_login_disabled(env):
    request_id = submit_staff(env)

    assert "staff/auto0001" not in env.db.store and not any(
        path.startswith("staff/auto") for path in env.db.store)
    [new_user] = [user for uid, user in env.auth.users.items() if uid.startswith("uid_new")]
    assert new_user["disabled"] is True and new_user["email"] == "alex@example.org"
    request = env.doc(f"staffChangeRequests/{request_id}")
    assert request["status"] == "pending" and request["payload"]["email"] == "alex@example.org"
    assert PASSWORD not in json.dumps(env.db.store, default=str)
    assert env.audit_actions() == [("staff.create.request", "a1")]


def test_requester_cannot_approve_their_own_staff_request(env):
    request_id = submit_staff(env)

    assert approve_staff(env, "a1", request_id).status_code == 403
    assert reject_staff(env, "a1", request_id).status_code == 403
    assert env.doc(f"staffChangeRequests/{request_id}")["status"] == "pending"
    assert all(user["disabled"] for uid, user in env.auth.users.items() if uid.startswith("uid_new"))


def test_approval_by_another_admin_creates_the_account_and_enables_login(env):
    request_id = submit_staff(env)

    assert approve_staff(env, "a2", request_id).status_code == 200

    request = env.doc(f"staffChangeRequests/{request_id}")
    staff_id = request["targetId"]
    created = env.doc(f"staff/{staff_id}")
    assert created["active"] is True and created["createdBy"] == "a1"
    assert (created["name"], created["role"], created["stateId"]) == ("Alex Employee", "aecEmployee", "VIC")
    assert env.auth.users[created["authUid"]]["disabled"] is False
    assert env.audit_actions() == [("staff.create.request", "a1"), ("staff.create", "a2")]
    assert_audit_chain_is_intact(env)


def test_non_admins_cannot_review_staff_requests(env):
    request_id = submit_staff(env)

    assert approve_staff(env, "d1", request_id).status_code == 403
    assert approve_staff(env, "emp", request_id).status_code == 403


def test_rejecting_a_staff_creation_deletes_the_disabled_login(env):
    request_id = submit_staff(env)
    new_uid = env.doc(f"staffChangeRequests/{request_id}")["payload"]["authUid"]

    assert reject_staff(env, "a2", request_id, "Duplicate").status_code == 200

    assert new_uid not in env.auth.users
    assert env.doc(f"staffChangeRequests/{request_id}")["status"] == "rejected"
    assert not any(path.startswith("staff/auto") for path in env.db.store)
    assert env.audit_actions()[-1] == ("staff.create.reject", "a2")
    # The email is free to use again.
    assert env.call("a1", "POST", "/api/admin/staff", NEW_STAFF).status_code == 202


def test_duplicate_email_is_refused_while_a_request_is_pending(env):
    submit_staff(env)

    assert env.call("a1", "POST", "/api/admin/staff", NEW_STAFF).status_code == 409


def test_editing_staff_applies_only_after_approval(env):
    response = env.call("a1", "PATCH", "/api/admin/staff/emp", {"name": "Renamed", "role": "commissionerDelegate"})

    assert response.status_code == 202
    assert env.doc("staff/emp")["role"] == "aecEmployee"
    assert approve_staff(env, "a2", response.json()["requestId"]).status_code == 200
    assert env.doc("staff/emp")["role"] == "commissionerDelegate"
    assert env.doc("staff/emp")["name"] == "Renamed"
    assert env.doc("staff/emp")["updatedBy"] == "a1"
    assert "uid_emp" in env.auth.revoked
    assert env.audit_actions() == [("staff.edit.request", "a1"), ("staff.edit", "a2")]
    assert_audit_chain_is_intact(env)


def test_reactivating_an_account_enables_the_login_after_approval(env):
    env.db.store["staff/emp"]["active"] = False
    env.auth.users["uid_emp"]["disabled"] = True
    request_id = env.call("a1", "PATCH", "/api/admin/staff/emp", {"active": True}).json()["requestId"]
    assert env.auth.users["uid_emp"]["disabled"] is True

    assert approve_staff(env, "a2", request_id).status_code == 200

    assert env.doc("staff/emp")["active"] is True
    assert env.auth.users["uid_emp"]["disabled"] is False


def test_deactivating_staff_applies_only_after_approval(env):
    response = env.call("a1", "DELETE", "/api/admin/staff/emp")

    assert response.status_code == 202
    assert env.doc("staff/emp")["active"] is True
    assert env.auth.users["uid_emp"]["disabled"] is False
    assert approve_staff(env, "a2", response.json()["requestId"]).status_code == 200
    assert env.doc("staff/emp")["active"] is False
    assert env.doc("staff/emp")["deactivatedBy"] == "a1"
    assert env.auth.users["uid_emp"]["disabled"] is True and "uid_emp" in env.auth.revoked
    assert env.audit_actions() == [("staff.delete.request", "a1"), ("staff.delete", "a2")]
    assert_audit_chain_is_intact(env)


def test_admin_cannot_request_their_own_deactivation_or_demotion(env):
    assert env.call("a1", "DELETE", "/api/admin/staff/a1").status_code == 409
    assert env.call("a1", "PATCH", "/api/admin/staff/a1", {"role": "aecEmployee"}).status_code == 409
    assert env.call("a1", "PATCH", "/api/admin/staff/a1", {"active": False}).status_code == 409
    assert env.requests("staffChangeRequests") == {}


def test_only_one_undecided_change_per_staff_account(env):
    assert env.call("a1", "PATCH", "/api/admin/staff/emp", {"name": "One"}).status_code == 202

    assert env.call("a2", "PATCH", "/api/admin/staff/emp", {"name": "Two"}).status_code == 409
    assert env.call("a2", "DELETE", "/api/admin/staff/emp").status_code == 409


def test_approval_rechecks_the_last_admin_rule(env):
    env.db.store["staff/a3"]["active"] = False
    request_id = env.call("a1", "DELETE", "/api/admin/staff/a2").json()["requestId"]
    env.db.store["staff/a1"]["active"] = False  # the requester is deactivated before the decision

    response = approve_staff(env, "a2", request_id)

    assert response.status_code == 409
    assert env.doc("staff/a2")["active"] is True
    assert env.doc(f"staffChangeRequests/{request_id}")["status"] == "pending"


def test_staff_change_request_list_shows_pending_and_recent(env):
    pending = env.call("a1", "PATCH", "/api/admin/staff/emp", {"name": "One"}).json()["requestId"]
    decided = env.call("a1", "DELETE", "/api/admin/staff/d1").json()["requestId"]
    assert reject_staff(env, "a2", decided).status_code == 200

    listing = env.call("a3", "GET", "/api/admin/staff/change-requests").json()

    assert [item["requestId"] for item in listing["pending"]] == [pending]
    assert [item["requestId"] for item in listing["recent"]] == [decided]
    assert listing["recent"][0]["reviewReason"] == "Not needed"
