import os

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-staff-dashboard")

import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.main import app
from backend import auth as auth_dependencies


def test_staff_api_requires_a_bearer_token():
    client = TestClient(app)

    response = client.get("/api/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_voter_endpoint_requires_a_bearer_token():
    client = TestClient(app)

    response = client.get("/api/employee/enrolments")

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/admin/staff", None),
        ("POST", "/api/admin/staff", {"name": "Alex Employee", "email": "alex@example.org", "role": "aecEmployee", "stateId": "VIC"}),
        ("PATCH", "/api/admin/staff/staff_1", {"name": "Alex Employee"}),
        ("DELETE", "/api/admin/staff/staff_1", None),
        ("GET", "/api/admin/ip-ranges", None),
        ("GET", "/api/admin/my-ip", None),
        ("POST", "/api/admin/ip-ranges", {"cidr": "203.0.113.0/24", "label": "Office", "active": True}),
        ("PATCH", "/api/admin/ip-ranges/range_1", {"cidr": "203.0.113.0/24", "label": "Office", "active": True}),
        ("DELETE", "/api/admin/ip-ranges/range_1", None),
        ("GET", "/api/admin/audit-logs", None),
        ("GET", "/api/admin/audit-logs/verify", None),
        ("GET", "/api/admin/elections", None),
        ("POST", "/api/admin/elections", {"name": "Election", "type": "federal", "openAt": "2028-01-01T08:00:00", "closeAt": "2028-01-01T18:00:00", "timezone": "Australia/Melbourne"}),
        ("POST", "/api/admin/elections/election_1/phase", {"to": "open"}),
        ("GET", "/api/employee/voters/enrolments/pending/count", None),
        ("GET", "/api/employee/enrolments", None),
        ("POST", "/api/employee/enrolments/voter_1/approve", {"divisionId": "div_1"}),
        ("POST", "/api/employee/enrolments/voter_1/reject", {"reason": "Invalid enrolment"}),
        ("POST", "/api/employee/voters", {"givenNames": "Alex", "surname": "Citizen", "dateOfBirth": "1990-01-01", "govId": "ABC12345", "street": "1 Collins Street", "suburb": "Melbourne", "state": "VIC", "postcode": "3000", "email": "alex@example.org", "divisionId": "div_1"}),
        ("POST", "/api/employee/voters/lookup", {"govId": "ABC12345"}),
        ("GET", "/api/employee/voters/voter_1", None),
        ("PATCH", "/api/employee/voters/voter_1/address", {"newAddress": {"street": "2 Collins Street", "suburb": "Melbourne", "state": "VIC", "postcode": "3000"}, "newDivisionId": "div_1", "reason": "correction"}),
        ("GET", "/api/elections/active/divisions", None),
        ("GET", "/api/delegate/elections/active", None),
        ("GET", "/api/delegate/elections/election_1/options", None),
        ("GET", "/api/delegate/elections/election_1/candidates", None),
        ("POST", "/api/delegate/elections/election_1/candidates", {"name": "Alex Candidate", "partyId": "party_1", "chamber": "house", "divisionId": "div_1", "ballotPosition": 1}),
        ("PATCH", "/api/delegate/elections/election_1/candidates/candidate_1", {"name": "Alex Candidate"}),
        ("POST", "/api/delegate/elections/election_1/candidates/candidate_1/withdraw", {"reason": "Withdrew"}),
    ],
)
def test_every_staff_endpoint_requires_a_bearer_token(method, path, body):
    client = TestClient(app)

    response = client.request(method, path, json=body)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("role", "path"),
    [
        ("commissionerDelegate", "/api/employee/enrolments"),
        ("aecEmployee", "/api/delegate/elections/election_1/candidates"),
        ("admin", "/api/employee/enrolments"),
        ("admin", "/api/delegate/elections/election_1/candidates"),
    ],
)
def test_wrong_staff_role_is_denied_and_audited(monkeypatch, role, path):
    audit_entries = []
    monkeypatch.setattr(auth_dependencies, "audit_standalone", lambda **kwargs: audit_entries.append(kwargs))
    app.dependency_overrides[auth_dependencies.current_staff] = lambda: {"staffId": "staff_1", "role": role}
    monkeypatch.setattr(auth_dependencies, "check_ip_allowlist", lambda request, staff, **kwargs: staff)

    try:
        response = TestClient(app).get(path)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert audit_entries
    assert audit_entries[-1]["action"] == "auth.denied"
    assert audit_entries[-1]["outcome"] == "denied"


def test_old_auth_time_is_rejected_and_audited(monkeypatch):
    audit_entries = []

    class EmptyQuery:
        def where(self, *_args, **_kwargs):
            return self

        def limit(self, _count):
            return self

        def stream(self):
            return []

    class EmptyDb:
        def collection(self, _name):
            return EmptyQuery()

    monkeypatch.setattr(auth_dependencies.auth, "verify_id_token", lambda *_args, **_kwargs: {
        "uid": "uid_1", "auth_time": int(time.time()) - 9 * 60 * 60,
    })
    monkeypatch.setattr(auth_dependencies, "db", EmptyDb())
    monkeypatch.setattr(auth_dependencies, "audit_standalone", lambda **kwargs: audit_entries.append(kwargs))

    response = TestClient(app).get("/api/me", headers={"Authorization": "Bearer expired-auth-time"})

    assert response.status_code == 401
    assert audit_entries[-1]["reason"] == "auth_time_expired"


def test_ip_allowlist_denies_non_matching_address_and_audits(monkeypatch):
    audit_entries = []
    monkeypatch.setattr(auth_dependencies, "_active_ranges", lambda: [
        (__import__("ipaddress").ip_network("192.0.2.0/24"), {"active": True}),
    ])
    monkeypatch.setattr(auth_dependencies, "audit_standalone", lambda **kwargs: audit_entries.append(kwargs))
    request = Request({"type": "http", "method": "GET", "path": "/api/me", "headers": [], "client": ("198.51.100.10", 1234)})

    with pytest.raises(HTTPException) as error:
        auth_dependencies.check_ip_allowlist(request, {"staffId": "staff_1", "role": "admin"})

    assert error.value.status_code == 403
    assert audit_entries[-1]["reason"] == "ip_not_allowed"
