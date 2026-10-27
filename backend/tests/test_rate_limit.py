import os

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-staff-dashboard")

from starlette.requests import Request

from backend import rate_limit


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "client": (peer, 443)})


def test_without_a_trusted_proxy_the_connecting_address_is_the_client(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", False)

    assert rate_limit.client_address(_request("203.0.113.5", "198.51.100.7")) == "203.0.113.5"


def test_behind_the_edge_proxy_each_client_is_counted_by_its_forwarded_address(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", True)

    assert rate_limit.client_address(_request("172.19.0.6", "198.51.100.7")) == "198.51.100.7"
    assert rate_limit.client_address(_request("172.19.0.6", " 198.51.100.8 , 10.0.0.1")) == "198.51.100.8"
    # A request without the header (such as a health check) falls back to the peer
    assert rate_limit.client_address(_request("172.19.0.6")) == "172.19.0.6"


def test_health_reports_which_instance_answered():
    from fastapi.testclient import TestClient

    from backend.main import app

    body = TestClient(app).get("/health").json()

    assert body["status"] == "ok"
    assert body["instance"]
