import os
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env by path: without one, python-dotenv may search from the
# working directory and miss it, depending on how the API was started.
load_dotenv(Path(__file__).with_name(".env"))


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "https://localhost:3000").split(",")
    if origin.strip()
]
TRUST_PROXY_HEADERS = _as_bool(os.getenv("TRUST_PROXY_HEADERS"))
TLS_CERT_FILE = os.getenv("TLS_CERT_FILE", "certs/localhost.pem")
TLS_KEY_FILE = os.getenv("TLS_KEY_FILE", "certs/localhost-key.pem")
TLS_LOG_FILE = os.getenv("TLS_LOG_FILE", "logs/tls-security-api.log")
# Hash algorithm for each purpose (see backend/security/hashing.py). A change
# applies to new values only; values made earlier keep verifying.
HASH_ALGORITHMS = {
    "receipt": os.getenv("HASH_ALGORITHM_RECEIPT", "sha256"),
    "audit": os.getenv("HASH_ALGORITHM_AUDIT", "sha256"),
    "results": os.getenv("HASH_ALGORITHM_RESULTS", "sha256"),
    "index": os.getenv("HASH_ALGORITHM_INDEX", "sha256"),
}
# Used when a new session signing key is created (see backend/sessions.py)
SESSION_SIGNING_ALGORITHM = os.getenv("SESSION_SIGNING_ALGORITHM", "HS256")
# Shared by the frontend and API TLS listeners
TLS_POLICY_FILE = os.getenv("TLS_POLICY_FILE", "tls-policy.json")
# Server-side idle limit: the browser signs out after 2 minutes, and renews at
# most every 30 seconds, so the server allows 2.5 minutes
SESSION_IDLE_SECONDS = int(os.getenv("SESSION_IDLE_SECONDS", "150"))
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")
SMTP_USE_SSL = _as_bool(os.getenv("SMTP_USE_SSL"))
# Write-once result archive (R-06) in a Backblaze B2 bucket with Object Lock enabled.
B2_KEY_ID = os.getenv("B2_KEY_ID")
B2_APPLICATION_KEY = os.getenv("B2_APPLICATION_KEY")
B2_BUCKET = os.getenv("B2_BUCKET")
# "compliance" for real elections; "governance" only for test buckets.
B2_RETENTION_MODE = os.getenv("B2_RETENTION_MODE")
ARCHIVE_REQUIRED = _as_bool(os.getenv("ARCHIVE_REQUIRED"), default=True)
