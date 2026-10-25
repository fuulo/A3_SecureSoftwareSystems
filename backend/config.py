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
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
TRUST_PROXY_HEADERS = _as_bool(os.getenv("TRUST_PROXY_HEADERS"))
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
