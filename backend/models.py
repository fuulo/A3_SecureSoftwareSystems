import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from typing_extensions import Annotated

Name = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-zÀ-ÖØ-öø-ÿ' -]+$",
    ),
]

GovId = Annotated[
    str,
    StringConstraints(
        min_length=6,
        max_length=20,
        pattern=r"^[A-Za-z0-9]{6,20}$",
    ),
]

Email = Annotated[
    str,
    Field(
        min_length=3,
        max_length=254,
        pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
    ),
]

SafeId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]

BallotChoice = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]

Receipt = Annotated[
    str,
    Field(
        min_length=1,
        max_length=40,
    ),
]

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitise_free_text(value: str) -> str:
    if _CONTROL_CHARACTERS.search(value):
        raise ValueError("Control characters are not allowed")

    cleaned = value.strip()

    if not cleaned:
        raise ValueError("Value must not be empty")

    return cleaned


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StaffCreate(StrictModel):
    name: Name
    email: Email
    role: Literal["aecEmployee", "commissionerDelegate", "admin"]
    stateId: Literal[
        "ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"
    ]
    password: Annotated[str, Field(min_length=12, max_length=128)]

    @field_validator("password")
    @classmethod
    def password_is_strong_enough(cls, value: str) -> str:
        if not (
            any(character.islower() for character in value)
            and any(character.isupper() for character in value)
            and any(character.isdigit() for character in value)
        ):
            raise ValueError(
                "Password must include upper-case, lower-case and numeric characters"
            )

        if value != value.strip():
            raise ValueError(
                "Password must not start or end with whitespace"
            )

        return value


class StaffEdit(StrictModel):
    name: Name | None = None
    role: Literal[
        "aecEmployee",
        "commissionerDelegate",
        "admin",
    ] | None = None
    stateId: Literal[
        "ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"
    ] | None = None
    active: bool | None = None


class IpRangeCreate(StrictModel):
    cidr: Annotated[str, Field(min_length=3, max_length=43)]
    label: Annotated[str, Field(min_length=1, max_length=100)]
    active: bool

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return sanitise_free_text(value)


class IpRangeEdit(IpRangeCreate):
    confirmLockout: bool = False


class ElectionCreate(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    type: Literal["federal"]
    openAt: str
    closeAt: str
    timezone: Annotated[str, Field(min_length=1, max_length=100)]

    @field_validator("name", "timezone")
    @classmethod
    def validate_text_fields(cls, value: str) -> str:
        return sanitise_free_text(value)


class PhaseChange(StrictModel):
    to: Literal["open", "closed", "counting", "finalised"]
    reason: Annotated[str, Field(max_length=500)] | None = None

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return sanitise_free_text(value)


class EnrolmentApproval(StrictModel):
    divisionId: SafeId


class EnrolmentRejection(StrictModel):
    reason: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return sanitise_free_text(value)


class VoterRegistration(StrictModel):
    givenNames: Name
    surname: Name
    dateOfBirth: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    govId: GovId
    street: Annotated[str, Field(min_length=1, max_length=200)]
    suburb: Annotated[str, Field(min_length=1, max_length=100)]
    state: Literal[
        "ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"
    ]
    postcode: Annotated[str, Field(pattern=r"^\d{4}$")]
    email: Email
    divisionId: SafeId

    @field_validator("street", "suburb")
    @classmethod
    def validate_address_fields(cls, value: str) -> str:
        return sanitise_free_text(value)


class Address(StrictModel):
    street: Annotated[str, Field(min_length=1, max_length=200)]
    unit: Annotated[str, Field(max_length=50)] | None = None
    suburb: Annotated[str, Field(min_length=1, max_length=100)]
    state: Literal[
        "ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"
    ]
    postcode: Annotated[str, Field(pattern=r"^\d{4}$")]

    @field_validator("street", "suburb", "unit")
    @classmethod
    def validate_address_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return sanitise_free_text(value)


class AddressChange(StrictModel):
    newAddress: Address
    newDivisionId: SafeId
    reason: Literal["moved_house", "correction", "other"]


class VoterLookup(StrictModel):
    govId: GovId | None = None
    givenNames: Name | None = None
    surname: Name | None = None


class CandidateCreate(StrictModel):
    name: Name
    partyId: SafeId
    chamber: Literal["house", "senate"]
    divisionId: SafeId | None = None
    stateId: Literal[
        "ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"
    ] | None = None
    groupId: SafeId | None = None
    ballotPosition: Annotated[int, Field(ge=1, le=1000)]


class CandidateEdit(StrictModel):
    name: Name | None = None
    partyId: SafeId | None = None
    groupId: SafeId | None = None
    ballotPosition: Annotated[int, Field(ge=1, le=1000)] | None = None


class Withdrawal(StrictModel):
    reason: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return sanitise_free_text(value)


class ChangeRequestRejection(StrictModel):
    reason: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return sanitise_free_text(value)


class HouseBallotInput(StrictModel):
    # Candidate IDs in preference order; index 0 = preference 1.
    # Empty means a blank ballot.
    preferences: Annotated[list[BallotChoice], Field(max_length=100)]


class SenateBallotInput(StrictModel):
    aboveTheLine: Annotated[list[BallotChoice], Field(max_length=100)] = []
    belowTheLine: Annotated[list[BallotChoice], Field(max_length=500)] = []


class BallotSubmission(StrictModel):
    house: HouseBallotInput
    senate: SenateBallotInput


class ReceiptCheck(StrictModel):
    receipt: Receipt

    @field_validator("receipt")
    @classmethod
    def validate_receipt(cls, value: str) -> str:
        if _CONTROL_CHARACTERS.search(value):
            raise ValueError("Control characters are not allowed")

        return value


class LockoutReport(StrictModel):
    email: Email


class VoterSelfRegistration(StrictModel):
    """Details submitted by a voter creating their own account.

    Identity and security-sensitive fields such as authUid, enrolmentStatus,
    divisionId and voted are intentionally excluded because the backend must
    derive or control them.
    """

    givenNames: Name
    surname: Name
    dateOfBirth: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    govId: GovId
    email: Email
    address: Annotated[str, Field(min_length=10, max_length=200)]
    phoneNumber: Annotated[
        str,
        Field(min_length=8, max_length=20, pattern=r"^\+?[0-9 ]{8,20}$"),
    ] | None = None

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        return sanitise_free_text(value)


class VoterSelfRegistrationResult(StrictModel):
    voterId: SafeId
    enrolmentStatus: Literal["pending"]
    message: Annotated[str, Field(min_length=1, max_length=200)]

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return sanitise_free_text(value)