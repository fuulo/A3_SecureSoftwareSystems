"""Public, unauthenticated endpoints behind the results and verification pages."""
import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from google.cloud import firestore

from backend.firestore_client import db
from backend.models import ReceiptCheck
from backend.rate_limit import limiter
from backend.receipts import normalize_receipt, receipt_hashes
from backend.security import hashing

router = APIRouter(prefix="/api/public", tags=["public"])
# One message for every miss, so lookups reveal nothing beyond "not found".
RECEIPT_NOT_FOUND = "No ballot was found for this receipt code. Check the code and try again."
CACHE = "public, max-age=60"


def _latest_published() -> dict[str, Any]:
    items = list(
        db.collection("publishedResults")
        .order_by("publishedAt", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )
    if not items:
        raise HTTPException(status_code=404, detail="No results have been published yet")
    return items[0].to_dict() or {}


@router.get("/results")
def published_results(response: Response) -> dict[str, Any]:
    published = _latest_published()
    response.headers["Cache-Control"] = CACHE
    # The stored fingerprint is returned, not a fresh hash of the stored package,
    # so a package altered after publication fails verification. Packages
    # published before fingerprints named their algorithm used SHA-256.
    algorithm = published.get("hashAlgorithm", hashing.LEGACY_ALGORITHM)
    fingerprint = published.get("fingerprint") or published["sha256"]
    return {
        "fingerprint": fingerprint,
        "algorithm": algorithm,
        # Kept for clients that predate "fingerprint"
        **({"sha256": fingerprint} if algorithm == "sha256" else {}),
        "package": json.loads(published["packageJson"]),
    }


@router.get("/results/package.json")
def result_package() -> Response:
    published = _latest_published()
    name = re.sub(r"[^A-Za-z0-9_-]", "", str(published.get("electionId", ""))) or "election"
    return Response(
        content=published["packageJson"].encode("utf-8"),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="result-package-{name}.json"',
            "Cache-Control": CACHE,
        },
    )


# POST keeps receipt codes out of URLs, browser history and access logs.
@router.post("/receipts/verify")
@limiter.limit("10/minute")
def verify_receipt(body: ReceiptCheck, request: Request) -> dict[str, Any]:
    code = normalize_receipt(body.receipt)
    if code is None:
        raise HTTPException(status_code=404, detail=RECEIPT_NOT_FOUND)
    snapshot = None
    for receipt_id in receipt_hashes(code):
        snapshot = db.collection("receipts").document(receipt_id).get()
        if snapshot.exists:
            break
    if snapshot is None or not snapshot.exists:
        raise HTTPException(status_code=404, detail=RECEIPT_NOT_FOUND)
    receipt = snapshot.to_dict() or {}
    published = db.collection("publishedResults").document(receipt.get("electionId", "")).get().exists
    return {"recordedAt": receipt["recordedAt"].isoformat(), "includedInTally": published}
