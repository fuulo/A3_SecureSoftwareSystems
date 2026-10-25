import pytest
from pydantic import ValidationError

from backend.models import (
    BallotSubmission,
    CandidateCreate,
    EnrolmentRejection,
    IpRangeCreate,
    VoterRegistration,
)


def test_rejects_control_characters_in_rejection_reason():
    with pytest.raises(ValidationError):
        EnrolmentRejection(reason="bad\x00reason")


def test_rejects_unsafe_division_id():
    with pytest.raises(ValidationError):
        VoterRegistration(
            givenNames="Jane",
            surname="Citizen",
            dateOfBirth="1990-01-01",
            govId="ABC12345",
            street="10 Example Street",
            suburb="Canberra",
            state="ACT",
            postcode="2600",
            email="voter@example.com",
            divisionId="../voters/voter_1",
        )


def test_rejects_unsafe_ballot_choice():
    with pytest.raises(ValidationError):
        BallotSubmission(
            house={
                "preferences": ["candidate_1\x00"],
            },
            senate={
                "aboveTheLine": [],
                "belowTheLine": [],
            },
        )


def test_rejects_unsafe_candidate_party_id():
    with pytest.raises(ValidationError):
        CandidateCreate(
            name="Jane Citizen",
            partyId="party/$collection",
            chamber="house",
            divisionId="division_1",
            ballotPosition=1,
        )


def test_rejects_unsafe_ip_range_label():
    with pytest.raises(ValidationError):
        IpRangeCreate(
            cidr="203.0.113.0/24",
            label="Diplomatic\x1fRange",
            active=True,
        )


def test_accepts_safe_inputs():
    model = VoterRegistration(
        givenNames="Jane",
        surname="Citizen",
        dateOfBirth="1990-01-01",
        govId="ABC12345",
        street="10 Example Street",
        suburb="Canberra",
        state="ACT",
        postcode="2600",
        email="voter@example.com",
        divisionId="division_1",
    )

    assert model.divisionId == "division_1"