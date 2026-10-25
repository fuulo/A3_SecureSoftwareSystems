"""Write-once archive of each published election (R-06).

When results are published, the result package and the receipt list are
uploaded to a Backblaze B2 bucket with Object Lock, each locked for 7 years.
In compliance mode nobody, including the account owner, can delete or replace
them before that date. Governance mode can be lifted by a key with the
bypassGovernance capability, so it is only for test buckets.

Publishing fails closed: if the archive is required and cannot be written and
locked, nothing is published. The B2 key needs listBuckets,
readBucketRetentions, writeFiles, writeFileRetentions and readFileRetentions.
"""
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any

from b2sdk.v2 import B2Api, FileRetentionSetting, InMemoryAccountInfo, RetentionMode
from fastapi import HTTPException

from backend.config import (
    ARCHIVE_REQUIRED,
    B2_APPLICATION_KEY,
    B2_BUCKET,
    B2_KEY_ID,
    B2_RETENTION_MODE,
)

logger = logging.getLogger(__name__)
RETENTION_DAYS = 2557  # 7 years, including leap days
MODES = {"governance": RetentionMode.GOVERNANCE, "compliance": RetentionMode.COMPLIANCE}


class ArchiveRefused(Exception):
    pass


def _bucket() -> Any:
    api = B2Api(InMemoryAccountInfo())
    api.authorize_account("production", B2_KEY_ID, B2_APPLICATION_KEY)
    return api.get_bucket_by_name(B2_BUCKET)


def archive_election(election_id: str, files: dict[str, tuple[bytes, str]],
                     published_at: datetime) -> dict[str, Any] | None:
    """Upload ``files`` ({name: (content, content type)}) locked until 7 years after publication.

    Returns the archive record to store with the published results, or None when
    no archive is configured and ARCHIVE_REQUIRED is off (development only).
    """
    if not (B2_KEY_ID and B2_APPLICATION_KEY and B2_BUCKET):
        if ARCHIVE_REQUIRED:
            raise HTTPException(status_code=503, detail="The result archive is not configured")
        logger.warning("Publishing %s without an archive: ARCHIVE_REQUIRED is off", election_id)
        return None
    mode = MODES.get((B2_RETENTION_MODE or "").strip().lower())
    if mode is None:
        raise HTTPException(status_code=503, detail="The result archive retention mode is not configured")

    retain_until = published_at + timedelta(days=RETENTION_DAYS)
    retain_until_ms = int(retain_until.timestamp() * 1000)
    stored = []
    try:
        bucket = _bucket()
        if bucket.is_file_lock_enabled is not True:
            raise ArchiveRefused("Object Lock is not enabled on the bucket, or the key cannot read it")
        for name, (content, content_type) in files.items():
            version = bucket.upload_bytes(
                content, f"elections/{election_id}/{name}", content_type=content_type,
                file_retention=FileRetentionSetting(mode, retain_until_ms),
            )
            retention = version.file_retention
            if retention is None or retention.mode != mode or (retention.retain_until or 0) < retain_until_ms:
                raise ArchiveRefused(f"{version.file_name} was stored without the required retention")
            stored.append({
                "name": version.file_name,
                "fileId": version.id_,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            })
    except Exception as exc:
        logger.exception("Archiving election %s failed", election_id)
        raise HTTPException(status_code=503, detail="Results could not be archived, so they were not published") from exc

    return {
        "provider": "backblaze-b2",
        "bucket": B2_BUCKET,
        "retentionMode": mode.value,
        "retainUntil": retain_until,
        "files": stored,
    }
