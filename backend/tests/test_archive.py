import os

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-staff-dashboard")

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from b2sdk.v2 import RetentionMode
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.cloud import firestore
from starlette.requests import Request

from backend import archive, audit, receipts, reconciliation, results
from backend.main import app
from backend.rate_limit import limiter
from backend.routers import public_results
from backend.tests.fake_firestore import FakeDb, fake_transactional

PUBLISHED = datetime(2028, 5, 1, 9, 0, tzinfo=timezone.utc)
ADMIN = {"staffId": "a1", "role": "admin", "stateId": "VIC"}
CODES = ["7KQ2M9XD4RTAH8WC", "23456789ABCDEFGH"]


class FakeBucket:
    """Stands in for a B2 bucket; echoes the requested retention like B2 does."""

    def __init__(self) -> None:
        self.is_file_lock_enabled = True
        self.keeps_retention = True
        self.uploads: list[dict] = []

    def upload_bytes(self, data, file_name, content_type=None, file_retention=None):
        self.uploads.append({"name": file_name, "data": data, "type": content_type, "retention": file_retention})
        return SimpleNamespace(file_name=file_name, id_=f"file{len(self.uploads)}",
                               file_retention=file_retention if self.keeps_retention else None)


@pytest.fixture
def bucket(monkeypatch):
    fake = FakeBucket()
    monkeypatch.setattr(archive, "_bucket", lambda: fake)
    settings = {"B2_KEY_ID": "key-id", "B2_APPLICATION_KEY": "key", "B2_BUCKET": "voting-test",
                "B2_RETENTION_MODE": "compliance", "ARCHIVE_REQUIRED": True}
    for name, value in settings.items():
        monkeypatch.setattr(archive, name, value)
    return fake


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    store = fake.store
    store["elections/e1"] = {"name": "Federal", "status": "finalised", "timezone": "Australia/Melbourne"}
    store["elections/e1/divisions/div_vic"] = {"name": "Melbourne", "stateId": "VIC", "seatCount": 1}
    store["elections/e1/senateRegions/VIC"] = {"name": "Victoria", "senatorsToElect": 6}
    store["elections/e1/candidates/h1"] = {"chamber": "house", "divisionId": "div_vic", "name": "Ann"}
    store["elections/e1/candidates/s1"] = {"chamber": "senate", "stateId": "VIC", "groupId": None, "name": "Sam"}
    for number, code in enumerate(CODES, start=1):
        store[f"voters/v{number}"] = {"enrolmentStatus": "enrolled", "voted": True, "votedElections.e1": True}
        store[f"elections/e1/houseBallots/h{number}"] = {"divisionId": "div_vic", "preferences": ["h1"], "isFormal": True}
        store[f"elections/e1/senateBallots/s{number}"] = {"stateId": "VIC", "belowTheLine": ["s1"], "aboveTheLine": [],
                                                          "isFormal": True, "countedAs": "belowTheLine"}
        store[f"receipts/{receipts.receipt_hash(code)}"] = {"electionId": "e1", "recordedAt": PUBLISHED}
    store[f"receipts/{receipts.receipt_hash('ABCDEFGHJKMNPQRS')}"] = {"electionId": "e2", "recordedAt": PUBLISHED}
    for module in (results, receipts, reconciliation, audit, public_results):
        monkeypatch.setattr(module, "db", fake)
    monkeypatch.setattr(firestore, "transactional", fake_transactional)
    limiter.reset()
    yield fake
    limiter.reset()


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [],
                    "client": ("127.0.0.1", 0), "query_string": b""})


def _publish(db) -> tuple[dict, dict]:
    out = results.publish_results("e1", ADMIN, _request())
    return out, db.store["publishedResults/e1"]


# ------------------------------------------------------------------ archive


def test_files_are_locked_for_at_least_seven_years(bucket):
    record = archive.archive_election("e1", {"a.json": (b"{}", "application/json")}, PUBLISHED)

    [upload] = bucket.uploads
    retain_until = datetime.fromtimestamp(upload["retention"].retain_until / 1000, tz=timezone.utc)
    assert upload["name"] == "elections/e1/a.json"
    assert upload["retention"].mode is RetentionMode.COMPLIANCE
    assert retain_until >= PUBLISHED.replace(year=PUBLISHED.year + 7)
    assert record["retainUntil"] == PUBLISHED + timedelta(days=archive.RETENTION_DAYS)
    assert record["files"] == [{"name": "elections/e1/a.json", "fileId": "file1",
                                "sha256": hashlib.sha256(b"{}").hexdigest(), "size": 2}]


def test_missing_archive_settings_refuse_publication(bucket, monkeypatch):
    monkeypatch.setattr(archive, "B2_KEY_ID", None)

    with pytest.raises(HTTPException) as refused:
        archive.archive_election("e1", {"a.json": (b"{}", "application/json")}, PUBLISHED)

    assert refused.value.status_code == 503
    assert bucket.uploads == []


def test_archive_is_skipped_only_when_not_configured_and_not_required(bucket, monkeypatch):
    monkeypatch.setattr(archive, "B2_KEY_ID", None)
    monkeypatch.setattr(archive, "ARCHIVE_REQUIRED", False)

    assert archive.archive_election("e1", {"a.json": (b"{}", "application/json")}, PUBLISHED) is None


@pytest.mark.parametrize("problem", ["no_object_lock", "stored_without_retention", "unknown_mode"])
def test_unlockable_archives_are_refused(bucket, monkeypatch, problem):
    if problem == "no_object_lock":
        bucket.is_file_lock_enabled = False
    elif problem == "stored_without_retention":
        bucket.keeps_retention = False
    else:
        monkeypatch.setattr(archive, "B2_RETENTION_MODE", "none")

    with pytest.raises(HTTPException) as refused:
        archive.archive_election("e1", {"a.json": (b"{}", "application/json")}, PUBLISHED)

    assert refused.value.status_code == 503


# --------------------------------------------------------------- publishing


def test_receipt_list_holds_only_sorted_hashes_for_the_election(db):
    lines = receipts.receipt_list("e1").decode("ascii").splitlines()

    assert lines == sorted(receipts.receipt_hash(code) for code in CODES)
    assert all(re.fullmatch(r"[0-9a-f]{64}", line) for line in lines)


def test_publishing_archives_the_package_and_receipt_list(db, bucket):
    out, published = _publish(db)

    package = json.loads(published["packageJson"])
    receipt_list = receipts.receipt_list("e1")
    receipts_sha256 = hashlib.sha256(receipt_list).hexdigest()
    assert package["packageVersion"] == 4
    assert package["election"]["receiptsSha256"] == receipts_sha256 == published["receiptsSha256"]
    assert {(u["name"], u["data"]) for u in bucket.uploads} == {
        (f"elections/e1/result-package-{out['sha256']}.json", published["packageJson"].encode("utf-8")),
        (f"elections/e1/receipts-{receipts_sha256}.txt", receipt_list),
    }
    assert published["archive"]["bucket"] == "voting-test"
    assert [f["name"] for f in published["archive"]["files"]] == [u["name"] for u in bucket.uploads]
    [entry] = [d for p, d in db.store.items() if p.startswith("auditLogs/")]
    assert entry["action"] == "results.publish" and entry["after"]["archive"]["retentionMode"] == "compliance"


def test_nothing_is_published_when_archiving_fails(db, bucket):
    bucket.is_file_lock_enabled = False

    with pytest.raises(HTTPException) as refused:
        _publish(db)

    assert refused.value.status_code == 503
    assert "publishedResults/e1" not in db.store


def test_public_receipt_list_matches_the_published_package(db, bucket):
    _publish(db)
    client = TestClient(app)

    summary = client.get("/api/public/results").json()
    download = client.get("/api/public/results/receipts.txt")

    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == summary["package"]["election"]["receiptsSha256"]
    assert 'filename="receipts-e1.txt"' in download.headers["content-disposition"]
    assert summary["archive"]["files"][0]["name"].startswith("elections/e1/")
