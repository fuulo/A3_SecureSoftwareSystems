from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing_extensions import Annotated

Name = Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"^[A-Za-zÀ-ÖØ-öø-ÿ' -]+$")]
GovId = Annotated[str, StringConstraints(min_length=6, max_length=20, pattern=r"^[A-Za-z0-9]{6,20}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StaffCreate(StrictModel):
    name: Name
    email: Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]
    role: Literal["aecEmployee", "commissionerDelegate", "admin"]
    stateId: Literal["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"]


class StaffEdit(StrictModel):
    name: Name | None = None
    role: Literal["aecEmployee", "commissionerDelegate", "admin"] | None = None
    stateId: Literal["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"] | None = None
    active: bool | None = None


class IpRangeCreate(StrictModel):
    cidr: Annotated[str, Field(min_length=3, max_length=43)]
    label: Annotated[str, Field(min_length=1, max_length=100)]
    active: bool


class IpRangeEdit(IpRangeCreate):
    confirmLockout: bool = False


class ElectionCreate(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    type: Literal["federal"]
    openAt: str
    closeAt: str
    timezone: Annotated[str, Field(min_length=1, max_length=100)]


class PhaseChange(StrictModel):
    to: Literal["open", "closed", "counting", "finalised"]
    reason: Annotated[str, Field(max_length=500)] | None = None


class EnrolmentApproval(StrictModel):
    divisionId: Annotated[str, Field(min_length=1, max_length=120)]


class EnrolmentRejection(StrictModel):
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class VoterRegistration(StrictModel):
    givenNames: Name
    surname: Name
    dateOfBirth: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    govId: GovId
    street: Annotated[str, Field(min_length=1, max_length=200)]
    suburb: Annotated[str, Field(min_length=1, max_length=100)]
    state: Literal["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"]
    postcode: Annotated[str, Field(pattern=r"^\d{4}$")]
    email: Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]
    divisionId: Annotated[str, Field(min_length=1, max_length=120)]


class Address(StrictModel):
    street: Annotated[str, Field(min_length=1, max_length=200)]
    unit: Annotated[str, Field(max_length=50)] | None = None
    suburb: Annotated[str, Field(min_length=1, max_length=100)]
    state: Literal["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"]
    postcode: Annotated[str, Field(pattern=r"^\d{4}$")]


class AddressChange(StrictModel):
    newAddress: Address
    newDivisionId: Annotated[str, Field(min_length=1, max_length=120)]
    reason: Literal["moved_house", "correction", "other"]


class VoterLookup(StrictModel):
    govId: GovId | None = None
    givenNames: Name | None = None
    surname: Name | None = None


class CandidateCreate(StrictModel):
    name: Name
    partyId: Annotated[str, Field(min_length=1, max_length=120)]
    chamber: Literal["house", "senate"]
    divisionId: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    stateId: Literal["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"] | None = None
    groupId: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    ballotPosition: Annotated[int, Field(ge=1, le=1000)]


class CandidateEdit(StrictModel):
    name: Name | None = None
    partyId: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    groupId: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    ballotPosition: Annotated[int, Field(ge=1, le=1000)] | None = None


class Withdrawal(StrictModel):
    reason: Annotated[str, Field(min_length=1, max_length=500)]
