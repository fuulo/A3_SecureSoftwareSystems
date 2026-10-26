import os

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-staff-dashboard")

import hashlib
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore
from starlette.requests import Request

from backend import audit as audit_module
from backend import config
from backend.main import app
from backend.rate_limit import limiter
from backend.routers import admin_audit, public_results
from backend.security import hashing
from backend.tests.fake_firestore import FakeDb, fake_transactional

CODE = "7KQ2M9XD4RTAH8WC"


def use_algorithm(monkeypatch, purpose, algorithm):
    monkeypatch.setitem(config.HASH_ALGORITHMS, purpose, algorithm)


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    for module in (audit_module, admin_audit, public_results):
        monkeypatch.setattr(module, "db", fake)
    monkeypatch.setattr(firestore, "transactional", fake_transactional)
    limiter.reset()
    yield fake
    limiter.reset()


def test_sha256_is_the_default_for_every_purpose():
    assert set(config.HASH_ALGORITHMS.values()) == {"sha256"}
    assert hashing.digest("receipt", "abc") == ("sha256", hashlib.sha256(b"abc").hexdigest())


def test_document_ids_stay_plain_for_sha256_and_name_any_other_algorithm(monkeypatch):
    assert hashing.document_id("receipt", "abc") == hashlib.sha256(b"abc").hexdigest()

    use_algorithm(monkeypatch, "receipt", "sha3_256")

    assert hashing.document_id("receipt", "abc") == "sha3_256-" + hashlib.sha3_256(b"abc").hexdigest()
    # Lookups try the current algorithm first, then the plain SHA-256 IDs from before
    ids = hashing.document_ids("receipt", "abc")
    assert ids[0].startswith("sha3_256-")
    assert hashlib.sha256(b"abc").hexdigest() in ids


def test_unknown_or_browser_incompatible_settings_are_refused():
    with pytest.raises(ValueError):
        hashing.hexdigest("abc", "md5")
    with pytest.raises(ValueError):
        hashing._validate({**config.HASH_ALGORITHMS, "receipt": "md5"})
    # Browsers verify result packages with Web Crypto, which has no SHA-3
    with pytest.raises(ValueError):
        hashing._validate({**config.HASH_ALGORITHMS, "results": "sha3_256"})


def store_receipt(db, receipt_id):
    db.store[f"receipts/{receipt_id}"] = {
        "electionId": "e1", "recordedAt": datetime(2028, 3, 1, 9, 0, tzinfo=timezone.utc),
    }


@pytest.mark.parametrize("issued_with", ["sha256", "sha512"])
def test_receipts_verify_after_the_algorithm_changes(db, monkeypatch, issued_with):
    use_algorithm(monkeypatch, "receipt", issued_with)
    store_receipt(db, hashing.document_id("receipt", CODE))

    use_algorithm(monkeypatch, "receipt", "sha3_256")
    response = TestClient(app).post("/api/public/receipts/verify", json={"receipt": CODE})

    assert response.status_code == 200


def write_entries(count):
    request = Request({"type": "http", "method": "POST", "path": "/test", "headers": [], "client": None})
    for number in range(count):
        audit_module.audit_standalone(
            actor={"staffId": "a1", "role": "admin"}, action="test.entry", category="admin",
            target_type="test", target_id=str(number), target_path="test", before=None, after=None,
            outcome="success", reason=None, request=request,
        )


def test_an_audit_chain_spanning_an_algorithm_change_still_verifies(db, monkeypatch):
    write_entries(2)
    use_algorithm(monkeypatch, "audit", "sha512")
    write_entries(2)

    entries = sorted((data for path, data in db.store.items() if path.startswith("auditLogs/")),
                     key=lambda entry: entry["seq"])
    assert [entry["hashAlgorithm"] for entry in entries] == ["sha256", "sha256", "sha512", "sha512"]
    assert admin_audit.verify_audit_chain(staff={"staffId": "a1"}) == {
        "valid": True, "checkedCount": 4, "firstBrokenLogId": None,
    }


def test_changing_an_entrys_algorithm_breaks_the_chain(db, monkeypatch):
    write_entries(2)
    first = min((path for path in db.store if path.startswith("auditLogs/")))
    db.store[first]["hashAlgorithm"] = "sha512"

    result = admin_audit.verify_audit_chain(staff={"staffId": "a1"})

    assert result["valid"] is False
    assert result["firstBrokenLogId"] == first.split("/", 1)[1]


def test_audit_entries_from_before_algorithm_names_still_verify(db):
    write_entries(2)
    # Entries written before hashAlgorithm existed: no field, SHA-256 over the rest
    previous = ""
    for path in sorted(p for p in db.store if p.startswith("auditLogs/")):
        entry = db.store[path]
        entry.pop("hashAlgorithm")
        entry["previousHash"] = previous
        body = {key: value for key, value in entry.items() if key != "hash"}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        entry["hash"] = previous = hashlib.sha256((previous + canonical).encode()).hexdigest()
    db.store["auditMeta/head"]["lastHash"] = previous

    assert admin_audit.verify_audit_chain(staff={"staffId": "a1"})["valid"] is True


def publish(db, **fields):
    db.store["publishedResults/e1"] = {
        "electionId": "e1", "packageJson": "{}", "publishedAt": datetime(2028, 3, 1, tzinfo=timezone.utc), **fields,
    }


def test_published_results_name_their_fingerprint_algorithm(db):
    publish(db, fingerprint="f" * 128, hashAlgorithm="sha512")

    body = TestClient(app).get("/api/public/results").json()

    assert body["fingerprint"] == "f" * 128
    assert body["algorithm"] == "sha512"
    assert "sha256" not in body


def test_results_published_before_algorithm_names_read_as_sha256(db):
    publish(db, sha256="a" * 64)

    body = TestClient(app).get("/api/public/results").json()

    assert (body["fingerprint"], body["algorithm"], body["sha256"]) == ("a" * 64, "sha256", "a" * 64)
