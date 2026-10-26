import os

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-staff-dashboard")

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import app
from backend.security import signing
# Fixtures shared with the archive tests
from backend.tests.test_archive import PUBLISHED, _publish, bucket, db  # noqa: F401

# Captured before the autouse fixture replaces it, to test loading from a file
LOAD_KEY_FILE = signing._private_key.__wrapped__


def _pem(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


def test_a_signature_verifies_only_the_exact_bytes_with_the_matching_key(results_signing_key):
    data = b'{"packageVersion":4}'
    signature = signing.sign(data)

    assert signature["algorithm"] == "Ed25519"
    assert signature["keyId"] == signing.public_key()["keyId"]
    assert signing.verify(data, signature["value"], _pem(results_signing_key))
    assert not signing.verify(data + b" ", signature["value"], _pem(results_signing_key))
    assert not signing.verify(data, signature["value"], _pem(Ed25519PrivateKey.generate()))
    assert not signing.verify(data, "not hex", _pem(results_signing_key))


def test_key_file_is_created_once_and_loaded_from_disk(tmp_path, monkeypatch):
    path = tmp_path / "keys" / "results-signing-key.pem"
    created = signing.generate_key_file(path)
    monkeypatch.setattr(signing, "RESULTS_SIGNING_KEY_FILE", str(path))

    assert signing.key_id(LOAD_KEY_FILE().public_key()) == created
    with pytest.raises(FileExistsError):
        signing.generate_key_file(path)


def test_a_missing_or_wrong_key_file_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(signing, "RESULTS_SIGNING_KEY_FILE", str(tmp_path / "missing.pem"))
    with pytest.raises(signing.SigningKeyMissing):
        LOAD_KEY_FILE()

    rsa_like = tmp_path / "other.pem"
    rsa_like.write_bytes(b"-----BEGIN PRIVATE KEY-----\n-----END PRIVATE KEY-----\n")
    monkeypatch.setattr(signing, "RESULTS_SIGNING_KEY_FILE", str(rsa_like))
    with pytest.raises((signing.SigningKeyMissing, ValueError)):
        LOAD_KEY_FILE()


def test_published_results_are_signed_and_verify_with_the_public_key(db, bucket):
    out, published = _publish(db)
    client = TestClient(app)

    summary = client.get("/api/public/results").json()
    key = client.get("/api/public/results/signing-key").json()
    package = client.get("/api/public/results/package.json").content
    raw_signature = client.get("/api/public/results/package.sig").content

    assert summary["signature"] == {"algorithm": "Ed25519", "keyId": out["signingKeyId"],
                                    "value": published["signature"]}
    assert key["keyId"] == out["signingKeyId"]
    assert raw_signature == bytes.fromhex(published["signature"])
    assert signing.verify(package, summary["signature"]["value"], key["publicKeyPem"])
    tampered = package.replace(b'"votes":2', b'"votes":3')
    assert tampered != package
    assert not signing.verify(tampered, summary["signature"]["value"], key["publicKeyPem"])
    [entry] = [d for p, d in db.store.items() if p.startswith("auditLogs/")]
    assert entry["after"]["signature"]["value"] == published["signature"]


def test_nothing_is_published_or_archived_without_a_signing_key(db, bucket, monkeypatch):
    def missing():
        raise signing.SigningKeyMissing("no key")

    monkeypatch.setattr(signing, "_private_key", missing)

    with pytest.raises(HTTPException) as refused:
        _publish(db)

    assert refused.value.status_code == 503
    assert bucket.uploads == []
    assert "publishedResults/e1" not in db.store
    assert TestClient(app).get("/api/public/results/signing-key").status_code == 404


def test_results_published_before_signing_have_no_signature(db):
    db.store["publishedResults/e1"] = {"electionId": "e1", "packageJson": "{}", "sha256": "0" * 64,
                                     "publishedAt": PUBLISHED}
    client = TestClient(app)

    assert client.get("/api/public/results").json()["signature"] is None
    assert client.get("/api/public/results/package.sig").status_code == 404
