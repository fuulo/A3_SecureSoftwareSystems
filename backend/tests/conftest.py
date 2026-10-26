import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.security import signing

TEST_SIGNING_KEY = Ed25519PrivateKey.generate()


@pytest.fixture(autouse=True)
def results_signing_key(monkeypatch):
    """Every test signs with an in-memory key instead of RESULTS_SIGNING_KEY_FILE."""
    monkeypatch.setattr(signing, "_private_key", lambda: TEST_SIGNING_KEY)
    return TEST_SIGNING_KEY
