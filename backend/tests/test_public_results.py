import os

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-staff-dashboard")

import hashlib
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend import receipts
from backend.main import app
from backend.rate_limit import limiter
from backend.results import build_package, package_bytes, tally_house, tally_senate
from backend.routers import public_results
from backend.routers.voter_ballots import house_is_formal, senate_counted_as


class FakeSnapshot:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return self._data


class FakeDocument:
    def __init__(self, store, path):
        self._store, self._path = store, path

    def get(self):
        return FakeSnapshot(self._store.get(self._path))


class FakeCollection:
    def __init__(self, store, name):
        self._store, self._name = store, name

    def document(self, doc_id):
        return FakeDocument(self._store, f"{self._name}/{doc_id}")

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def stream(self):
        prefix = f"{self._name}/"
        return [FakeSnapshot(data) for path, data in self._store.items() if path.startswith(prefix)]


class FakeDb:
    def __init__(self, store):
        self._store = store

    def collection(self, name):
        return FakeCollection(self._store, name)


@pytest.fixture(autouse=True)
def reset_rate_limits():
    limiter.reset()
    yield
    limiter.reset()


def test_receipt_codes_use_the_shared_alphabet_and_format():
    code = receipts.new_receipt_code()

    assert len(code) == receipts.LENGTH
    assert set(code) <= set(receipts.ALPHABET)
    assert receipts.normalize_receipt(receipts.format_receipt(code).lower()) == code


@pytest.mark.parametrize("raw", ["", "7KQ2-M9XD-4RTA", "0KQ2-M9XD-4RTA-H8WC", "7KQ2M9XD4RTAH8WC1", "7KQ2-M9XD-4RTA-H8W!"])
def test_impossible_receipts_are_rejected(raw):
    assert receipts.normalize_receipt(raw) is None


def test_house_ballot_must_number_every_candidate():
    assert house_is_formal(["a", "b", "c"], 3)
    assert not house_is_formal(["a"], 3)
    assert not house_is_formal([], 0)


def test_formal_below_the_line_vote_takes_precedence():
    assert senate_counted_as(["g1"], ["c1", "c2", "c3", "c4", "c5", "c6"], 12) == "belowTheLine"
    assert senate_counted_as(["g1"], ["c1", "c2"], 12) == "aboveTheLine"
    assert senate_counted_as([], ["c1", "c2"], 2) == "belowTheLine"
    assert senate_counted_as([], ["c1"], 12) is None


def test_tallies_count_every_ballot_once_per_contest():
    divisions = {"div_a": {"name": "Alpha", "seatCount": 1}}
    candidates = {
        "h1": {"chamber": "house", "divisionId": "div_a", "name": "Ann", "partyId": "p1", "ballotPosition": 1},
        "h2": {"chamber": "house", "divisionId": "div_a", "name": "Ben", "partyId": None, "ballotPosition": 2},
        "s1": {"chamber": "senate", "stateId": "VIC", "groupId": "g1", "name": "Cal"},
        "s2": {"chamber": "senate", "stateId": "VIC", "groupId": None, "name": "Dee"},
    }
    parties = {"p1": {"name": "Party One"}}
    house = [
        {"divisionId": "div_a", "preferences": ["h1", "h2"], "isFormal": True},
        {"divisionId": "div_a", "preferences": ["h2", "h1"], "isFormal": True},
        {"divisionId": "div_a", "preferences": ["h1", "h2"], "isFormal": True},
        {"divisionId": "div_a", "preferences": ["h1"], "isFormal": False},
    ]
    senate = [
        {"stateId": "VIC", "aboveTheLine": ["g1"], "belowTheLine": [], "isFormal": True, "countedAs": "aboveTheLine"},
        {"stateId": "VIC", "aboveTheLine": [], "belowTheLine": ["s2", "s1"], "isFormal": True, "countedAs": "belowTheLine"},
        {"stateId": "VIC", "aboveTheLine": [], "belowTheLine": [], "isFormal": False, "countedAs": None},
    ]

    [house_contest] = tally_house(divisions, candidates, parties, house)
    [senate_contest] = tally_senate(
        {"VIC": {"name": "Victoria", "senatorsToElect": 6}},
        {"g1": {"stateId": "VIC", "displayName": "Group One", "partyId": "p1", "candidateOrder": ["s1"]}},
        candidates, parties, senate,
    )

    assert {c["name"]: c["votes"] for c in house_contest["candidates"]} == {"Ann": 2, "Ben": 1}
    assert house_contest["candidates"][1]["party"] == "Independent"
    assert (house_contest["ballotsCast"], house_contest["informal"]) == (4, 1)
    assert {c["name"]: c["votes"] for c in senate_contest["candidates"]} == {"Group One": 1, "Ungrouped candidates": 1}
    for contest in (house_contest, senate_contest):
        assert sum(c["votes"] for c in contest["candidates"]) + contest["informal"] == contest["ballotsCast"]


def test_package_bytes_are_deterministic():
    published = datetime(2028, 5, 1, 9, 0, tzinfo=timezone.utc)
    package = build_package("e1", {"name": "Test"}, [], enrolled=10, ballots_cast=4, senate_ballots_cast=4,
                            voters_marked_voted=4, receipts_issued=4, receipts_fingerprint="0" * 64,
                            receipts_hash_algorithm="sha256", published_at=published)

    assert package_bytes(package) == package_bytes(json.loads(package_bytes(package)))
    assert package["election"]["publishedAt"] == "2028-05-01T19:00:00+10:00"


def test_results_return_the_stored_fingerprint_and_exact_package_bytes(monkeypatch):
    content = '{"packageVersion":2,"election":{"id":"e1"},"contests":[]}'
    stored_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    monkeypatch.setattr(public_results, "db", FakeDb({
        "publishedResults/e1": {"electionId": "e1", "packageJson": content, "sha256": stored_hash},
    }))
    client = TestClient(app)

    summary = client.get("/api/public/results")
    download = client.get("/api/public/results/package.json")

    assert summary.status_code == 200
    assert summary.json()["sha256"] == stored_hash
    assert download.content == content.encode("utf-8")
    assert 'filename="result-package-e1.json"' in download.headers["content-disposition"]


def test_results_404_before_anything_is_published(monkeypatch):
    monkeypatch.setattr(public_results, "db", FakeDb({}))

    response = TestClient(app).get("/api/public/results")

    assert response.status_code == 404


def test_receipt_lookup_confirms_recording_without_revealing_the_vote(monkeypatch):
    code = "7KQ2M9XD4RTAH8WC"
    recorded = datetime(2028, 5, 1, 0, 42, tzinfo=timezone.utc)
    monkeypatch.setattr(public_results, "db", FakeDb({
        f"receipts/{receipts.receipt_hash(code)}": {"electionId": "e1", "recordedAt": recorded},
        "publishedResults/e1": {"sha256": "x"},
    }))

    response = TestClient(app).post("/api/public/receipts/verify", json={"receipt": "7kq2-m9xd-4rta-h8wc"})

    assert response.status_code == 200
    assert response.json() == {"recordedAt": recorded.isoformat(), "includedInTally": True}


@pytest.mark.parametrize("receipt", ["7KQ2-M9XD-4RTA-H8WD", "not a receipt"])
def test_unknown_and_malformed_receipts_get_the_same_answer(monkeypatch, receipt):
    monkeypatch.setattr(public_results, "db", FakeDb({}))

    response = TestClient(app).post("/api/public/receipts/verify", json={"receipt": receipt})

    assert response.status_code == 404
    assert response.json()["detail"] == public_results.RECEIPT_NOT_FOUND


def test_receipt_lookups_are_rate_limited(monkeypatch):
    monkeypatch.setattr(public_results, "db", FakeDb({}))
    client = TestClient(app)

    statuses = [client.post("/api/public/receipts/verify", json={"receipt": "7KQ2M9XD4RTAH8WC"}).status_code
                for _ in range(11)]

    assert statuses[:10] == [404] * 10
    assert statuses[10] == 429


@pytest.mark.parametrize(("method", "path", "body"), [
    ("POST", "/api/voter/ballots", {"house": {"preferences": []}, "senate": {}}),
    ("POST", "/api/admin/elections/election_1/results/publish", None),
])
def test_ballot_and_publish_endpoints_require_a_bearer_token(method, path, body):
    response = TestClient(app).request(method, path, json=body)

    assert response.status_code == 401
