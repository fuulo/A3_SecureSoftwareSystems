from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from backend.auth import enforce_voter_ip_allowlist
from backend.main import app
from backend.routers import voter_ballot_session
from backend.routers.voter_ballot_session import get_current_firebase_user
from backend.security.encryption import EncryptedValue


ELECTION_ID = "election_1"
START_URL = f"/api/voter/ballots/{ELECTION_ID}/start"
SUBMIT_URL = f"/api/voter/ballots/{ELECTION_ID}/submit"

VALID_BALLOT = {
    "house": {
        "preferences": ["candidate_1", "candidate_2"],
    },
    "senate": {
        "aboveTheLine": ["group_1"],
        "belowTheLine": [],
    },
}


class FakeDocumentSnapshot:
    def __init__(self, reference):
        self.reference = reference

    @property
    def exists(self) -> bool:
        return self.reference.exists

    def to_dict(self) -> dict:
        return self.reference.data


class FakeDocumentReference:
    def __init__(
        self,
        document_id: str,
        data: dict | None = None,
        exists: bool = True,
    ):
        self.id = document_id
        self.data = data or {}
        self.exists = exists
        self.updates = []
        self.created_documents = []

    def get(self, transaction=None):
        return FakeDocumentSnapshot(self)

    def update(self, values):
        self.updates.append(values)
        self.data.update(values)

    def set(self, values):
        self.created_documents.append(values)
        self.data.update(values)

    def collection(self, name):
        return FakeCollection()


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = documents or {}

    def document(self, document_id=None):
        if document_id:
            return self.documents.get(
                document_id,
                FakeDocumentReference(document_id, exists=False),
            )

        new_id = f"generated_{len(self.documents) + 1}"
        reference = FakeDocumentReference(new_id, exists=False)
        self.documents[new_id] = reference
        return reference

    def where(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def stream(self):
        return [
            FakeDocumentSnapshot(reference)
            for reference in self.documents.values()
            if reference.exists
        ]


class FakeTransaction:
    def get(self, reference, transaction=None):
        return reference.get(transaction=self)

    def update(self, reference, values):
        reference.update(values)

    def set(self, reference, values):
        reference.set(values)


class FakeFirestore:
    def __init__(self, voter=None, election=None):
        self.voter = voter
        self.election = election
        self.voters = FakeCollection(
            {"voter_1": voter} if voter else {}
        )
        self.elections = FakeCollection(
            {ELECTION_ID: election} if election else {}
        )
        self.ballots = FakeCollection()
        self.audit_logs = FakeCollection()
        self.security_alerts = FakeCollection()

    def collection(self, name):
        if name == "voters":
            return self.voters

        if name == "elections":
            return self.elections

        if name == "ballots":
            return self.ballots

        if name == "auditLogs":
            return self.audit_logs

        if name == "securityAlerts":
            return self.security_alerts

        return FakeCollection()

    def transaction(self):
        return FakeTransaction()


class FakeEncryptionService:
    def encrypt(self, value):
        return EncryptedValue(
            ciphertext=f"encrypted::{value}",
            keyId="key_1",
        )


def approved_voter(**overrides):
    data = {
        "authUid": "uid_1",
        "enrolmentStatus": "approved",
        "eligibilityStatus": "approved",
        "voted": False,
        "voting": False,
        "votedElections": {},
        "activeElectionId": None,
    }
    data.update(overrides)
    return FakeDocumentReference("voter_1", data)


def open_election():
    return FakeDocumentReference(
        ELECTION_ID,
        {
            "status": "open",
            "phase": "open",
        },
    )


def configure_voter(voter, election=None):
    fake_db = FakeFirestore(
        voter=voter,
        election=election or open_election(),
    )

    voter_ballot_session.firestore.client = lambda: fake_db
    voter_ballot_session.get_encryption_service = lambda: FakeEncryptionService()

    app.dependency_overrides[get_current_firebase_user] = lambda: {
        "uid": "uid_1",
        "email": "voter@example.com",
    }
    app.dependency_overrides[enforce_voter_ip_allowlist] = lambda: None

    return fake_db


def use_unauthenticated_client():
    def raise_unauthorised():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        )

    app.dependency_overrides[get_current_firebase_user] = raise_unauthorised
    app.dependency_overrides[enforce_voter_ip_allowlist] = lambda: None


def use_unapproved_voter_ip():
    app.dependency_overrides[enforce_voter_ip_allowlist] = (
        enforce_voter_ip_allowlist
    )


def test_start_voting_session_succeeds_for_eligible_voter():
    voter = approved_voter()
    configure_voter(voter)

    response = TestClient(app).post(START_URL)

    assert response.status_code == 200
    assert response.json()["voting"] is True
    assert voter.data["voting"] is True
    assert voter.data["activeElectionId"] == ELECTION_ID


def test_start_voting_session_requires_authentication():
    use_unauthenticated_client()

    response = TestClient(app).post(START_URL)

    assert response.status_code == 401


def test_start_voting_session_rejects_unapproved_enrolment():
    voter = approved_voter(enrolmentStatus="pending")
    configure_voter(voter)

    response = TestClient(app).post(START_URL)

    assert response.status_code == 403
    assert voter.data["voting"] is False


def test_start_voting_session_rejects_ineligible_voter():
    voter = approved_voter(eligibilityStatus="pending")
    configure_voter(voter)

    response = TestClient(app).post(START_URL)

    assert response.status_code == 403
    assert voter.data["voting"] is False


def test_start_voting_session_rejects_voter_already_voted():
    voter = approved_voter(
        voted=True,
        votedElections={ELECTION_ID: True},
    )
    configure_voter(voter)

    response = TestClient(app).post(START_URL)

    assert response.status_code == 409
    assert voter.data["voting"] is False


def test_start_voting_session_rejects_active_session():
    voter = approved_voter(
        voting=True,
        activeElectionId=ELECTION_ID,
    )
    configure_voter(voter)

    response = TestClient(app).post(START_URL)

    assert response.status_code == 409


def test_start_voting_session_blocks_unapproved_voter_ip():
    voter = approved_voter()
    configure_voter(voter)
    use_unapproved_voter_ip()

    response = TestClient(app).post(START_URL)

    assert response.status_code == 403
    assert voter.data["voting"] is False
    assert voter.data["activeElectionId"] is None


def test_submit_ballot_succeeds_and_marks_voter_voted():
    voter = approved_voter(
        voting=True,
        activeElectionId=ELECTION_ID,
    )
    fake_db = configure_voter(voter)

    response = TestClient(app).post(
        SUBMIT_URL,
        json=VALID_BALLOT,
    )

    assert response.status_code == 201
    assert response.json()["voted"] is True

    assert voter.data["voted"] is True
    assert voter.data["voting"] is False
    assert voter.data["votedElections"][ELECTION_ID] is True
    assert voter.data["activeElectionId"] is None

    stored_ballots = list(fake_db.ballots.documents.values())
    assert len(stored_ballots) == 1
    assert stored_ballots[0].data["housePreferences"].startswith("encrypted::")
    assert stored_ballots[0].data["senateAboveTheLine"].startswith("encrypted::")
    assert stored_ballots[0].data["senateBelowTheLine"].startswith("encrypted::")


def test_submit_ballot_requires_authentication():
    use_unauthenticated_client()

    response = TestClient(app).post(
        SUBMIT_URL,
        json=VALID_BALLOT,
    )

    assert response.status_code == 401


def test_submit_ballot_rejects_voter_already_voted():
    voter = approved_voter(
        voted=True,
        votedElections={ELECTION_ID: True},
    )
    configure_voter(voter)

    response = TestClient(app).post(
        SUBMIT_URL,
        json=VALID_BALLOT,
    )

    assert response.status_code == 409


def test_submit_ballot_rejects_request_without_active_session():
    voter = approved_voter()
    configure_voter(voter)

    response = TestClient(app).post(
        SUBMIT_URL,
        json=VALID_BALLOT,
    )

    assert response.status_code == 409
    assert voter.data["voted"] is False


def test_submit_ballot_rejects_closed_election():
    voter = approved_voter(
        voting=True,
        activeElectionId=ELECTION_ID,
    )
    closed_election = FakeDocumentReference(
        ELECTION_ID,
        {
            "status": "closed",
            "phase": "closed",
        },
    )
    configure_voter(voter, closed_election)

    response = TestClient(app).post(
        SUBMIT_URL,
        json=VALID_BALLOT,
    )

    assert response.status_code == 409
    assert voter.data["voted"] is False


def test_submit_ballot_blocks_unapproved_voter_ip():
    voter = approved_voter(
        voting=True,
        activeElectionId=ELECTION_ID,
    )
    configure_voter(voter)
    use_unapproved_voter_ip()

    response = TestClient(app).post(
        SUBMIT_URL,
        json=VALID_BALLOT,
    )

    assert response.status_code == 403
    assert voter.data["voted"] is False