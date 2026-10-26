"""Self-service voter registration endpoints.

A voter authenticates with Firebase, then submits their registration details.
The backend derives the voter's Firebase UID and verified email from the ID
token, rather than trusting client-supplied identity fields.

Sensitive personal information is encrypted at rest using AES-256-GCM before
being written to Firestore.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import auth as firebase_auth
from firebase_admin import firestore

from backend.dependencies.auth import get_current_firebase_user
from backend.models import VoterSelfRegistration, VoterSelfRegistrationResult
from backend.security.key_management import get_encryption_service

router = APIRouter(
    prefix="/api/voter",
    tags=["voter-registration"],
)

VOTERS_COLLECTION = "voters"
AUDIT_COLLECTION = "auditLogs"


@router.post(
    "/register",
    response_model=VoterSelfRegistrationResult,
    status_code=status.HTTP_201_CREATED,
    summary="Register Self Service Voter",
)
def register_self_service_voter(
    body: VoterSelfRegistration,
    decoded_token: dict = Depends(get_current_firebase_user),
) -> VoterSelfRegistrationResult:
    """Create a pending voter registration for the authenticated Firebase user.

    The voter cannot choose their own authUid, enrolment status, division,
    state, or voting status. These are controlled by the backend.
    """
    uid = decoded_token["uid"]
    token_email = decoded_token.get("email")

    if not token_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Firebase account has no verified email address",
        )

    if token_email.lower() != body.email.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address does not match the authenticated account",
        )

    db = firestore.client()
    voters = db.collection(VOTERS_COLLECTION)

    existing_by_auth_uid = (
        voters
        .where("authUid", "==", uid)
        .limit(1)
        .stream()
    )

    if any(existing_by_auth_uid):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A voter registration already exists for this account",
        )

    existing_by_gov_id = (
        voters
        .where("govId", "==", body.govId)
        .limit(1)
        .stream()
    )

    if any(existing_by_gov_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A voter registration already exists for this GovID",
        )

    encryption = get_encryption_service()

    encrypted_given_names = encryption.encrypt(body.givenNames)
    encrypted_surname = encryption.encrypt(body.surname)
    encrypted_gov_id = encryption.encrypt(body.govId)
    encrypted_date_of_birth = encryption.encrypt(body.dateOfBirth)
    encrypted_address = encryption.encrypt(body.address)
    encrypted_phone_number = encryption.encrypt(body.phoneNumber)

    voter_data = {
        "authUid": uid,
        "givenNames": (
            encrypted_given_names.ciphertext
            if encrypted_given_names
            else None
        ),
        "givenNamesLower": body.givenNames.lower(),
        "surname": (
            encrypted_surname.ciphertext
            if encrypted_surname
            else None
        ),
        "surnameLower": body.surname.lower(),
        "govId": (
            encrypted_gov_id.ciphertext
            if encrypted_gov_id
            else None
        ),
        "dateOfBirth": (
            encrypted_date_of_birth.ciphertext
            if encrypted_date_of_birth
            else None
        ),
        "enrolmentStatus": "pending",
        "enrolledBy": "self",
        "address": (
            encrypted_address.ciphertext
            if encrypted_address
            else None
        ),
        "email": token_email,
        "divisionId": None,
        "stateId": None,
        "voted": False,
        "votedElections": {},
        "phoneNumber": (
            encrypted_phone_number.ciphertext
            if encrypted_phone_number
            else None
        ),
        "encryption": {
            "givenNamesKeyId": (
                encrypted_given_names.keyId
                if encrypted_given_names
                else None
            ),
            "surnameKeyId": (
                encrypted_surname.keyId
                if encrypted_surname
                else None
            ),
            "govIdKeyId": (
                encrypted_gov_id.keyId
                if encrypted_gov_id
                else None
            ),
            "dateOfBirthKeyId": (
                encrypted_date_of_birth.keyId
                if encrypted_date_of_birth
                else None
            ),
            "addressKeyId": (
                encrypted_address.keyId
                if encrypted_address
                else None
            ),
            "phoneNumberKeyId": (
                encrypted_phone_number.keyId
                if encrypted_phone_number
                else None
            ),
        },
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    voter_ref = voters.document()
    voter_id = voter_ref.id

    now = datetime.now(timezone.utc)

    audit_data = {
        "action": "voter_self_registration",
        "actor": {
            "staffId": uid,
            "role": "voter",
        },
        "target": {
            "collection": VOTERS_COLLECTION,
            "documentId": voter_id,
        },
        "before": None,
        "after": {
            "enrolmentStatus": "pending",
            "enrolledBy": "self",
        },
        "ipAddress": None,
        "userAgent": None,
        "timestamp": firestore.SERVER_TIMESTAMP,
    }

    transaction = db.transaction()

    @firestore.transactional
    def create_voter_and_audit(transaction):
        transaction.set(voter_ref, voter_data)
        transaction.set(
            db.collection(AUDIT_COLLECTION).document(),
            audit_data,
        )

    try:
        create_voter_and_audit(transaction)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to complete voter registration",
        ) from exc

    return VoterSelfRegistrationResult(
        voterId=voter_id,
        enrolmentStatus="pending",
        message="Voter registration submitted and awaiting AEC approval",
    )