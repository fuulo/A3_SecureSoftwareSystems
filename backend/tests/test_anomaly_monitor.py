from types import SimpleNamespace

import pytest

from backend.security import anomaly_monitor

class FakeSnapshot:
    def __init__(self, data):
        self.data = data


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = documents or {}

    def add(self, data):
        document_id = f"generated_{len(self.documents) + 1}"
        self.documents[document_id] = data
        return SimpleNamespace(id=document_id)

    def where(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def stream(self):
        return [
            FakeSnapshot(data)
            for data in self.documents.values()
        ]


class FakeFirestore:
    def __init__(self):
        self.security_events = FakeCollection()
        self.security_alerts = FakeCollection()

    def collection(self, name):
        if name == "securityEvents":
            return self.security_events

        if name == "securityAlerts":
            return self.security_alerts

        raise AssertionError(f"Unexpected collection: {name}")


@pytest.fixture
def fake_firestore(monkeypatch):
    fake_db = FakeFirestore()

    monkeypatch.setattr(
        anomaly_monitor,
        "firestore",
        SimpleNamespace(client=lambda: fake_db),
    )

    return fake_db


def test_no_alert_below_threshold(fake_firestore):
    created = anomaly_monitor.record_security_event(
        "login_failure",
        source_ip="203.0.113.10",
        threshold=5,
    )

    assert created is False
    assert len(fake_firestore.security_events.documents) == 1
    assert len(fake_firestore.security_alerts.documents) == 0


def test_alert_created_when_threshold_reached(fake_firestore):
    created = False

    for _ in range(5):
        created = anomaly_monitor.record_security_event(
            "login_failure",
            source_ip="203.0.113.10",
            threshold=5,
        )

    assert created is True
    assert len(fake_firestore.security_events.documents) == 5
    assert len(fake_firestore.security_alerts.documents) == 1

    alert = next(
        iter(fake_firestore.security_alerts.documents.values())
    )

    assert alert["alertType"] == "login_failure"
    assert alert["eventCount"] == 5
    assert alert["status"] == "open"


def test_duplicate_alert_not_created_within_window(fake_firestore):
    for _ in range(5):
        anomaly_monitor.record_security_event(
            "invalid_vote_submission",
            threshold=5,
        )

    created = anomaly_monitor.record_security_event(
        "invalid_vote_submission",
        threshold=5,
    )

    assert created is False
    assert len(fake_firestore.security_alerts.documents) == 1