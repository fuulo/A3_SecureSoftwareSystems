"""Default election structure, copied into every newly created election.

The values mirror seed.js: divisions, senate regions, parties, senate groups and
polling places (with their terminals). Candidates and ballots are deliberately not
seeded, so senate groups start with no candidates; the candidate routes keep each
group's ``candidateOrder`` / ``candidateCount`` up to date as candidates are added.
"""
from copy import deepcopy
from typing import Any

from google.cloud import firestore

# (collection, document id, collection, document id, ...) -> document data
DocPath = tuple[str, ...]

ALL_STATES = ["VIC", "NSW", "QLD", "WA", "SA", "TAS", "ACT", "NT"]

DIVISIONS = [
    ("div_melbourne", "Melbourne", "VIC"),
    ("div_wills", "Wills", "VIC"),
    ("div_sydney", "Sydney", "NSW"),
    ("div_canberra", "Canberra", "ACT"),
    ("div_solomon", "Solomon", "NT"),
]

SENATE_REGIONS = [
    ("NSW", "New South Wales", 6, "state"),
    ("VIC", "Victoria", 6, "state"),
    ("QLD", "Queensland", 6, "state"),
    ("WA", "Western Australia", 6, "state"),
    ("SA", "South Australia", 6, "state"),
    ("TAS", "Tasmania", 6, "state"),
    ("ACT", "Australian Capital Territory", 2, "territory"),
    ("NT", "Northern Territory", 2, "territory"),
]

# (id, name, abbreviation, registeredName, colourHex, logo file)
PARTIES = [
    ("party_greenleaf", "Greenleaf Alliance", "GLA", "Greenleaf Alliance Incorporated", "#2E8B57", "greenleaf.png"),
    ("party_civic", "Civic Union Party", "CUP", "Civic Union Party Incorporated", "#1F4E9C", "civic.png"),
    ("party_harbour", "Harbour Reform Party", "HRP", "Harbour Reform Party Incorporated", "#C0392B", "harbour.png"),
]

# (id, letter, column, groupType, partyId, displayName); Victorian groups, as in seed.js.
SENATE_GROUPS = [
    ("vic_group_A", "A", 1, "party", "party_greenleaf", "Greenleaf Alliance"),
    ("vic_group_B", "B", 2, "party", "party_civic", "Civic Union Party"),
    ("vic_group_C", "C", 3, "independentGroup", None, "Independent Group C"),
]

# (id, name, latitude, longitude, type, country, [(terminal id, status, device id)])
POLLING_PLACES = [
    ("place_mel_townhall", "Melbourne Town Hall", -37.815, 144.967, "domestic", "AU",
     [("term_mel_001", "active", "dev_a1b2c3"), ("term_mel_002", "disabled", "dev_a1b2c4")]),
    ("place_lon_highcomm", "Australian High Commission, London", 51.5115, -0.117, "diplomaticMission", "GB",
     [("term_lon_001", "active", "dev_7f3a91")]),
]


def default_documents(staff_id: str) -> list[tuple[DocPath, dict[str, Any]]]:
    """Return (path relative to the election document, data) for every default document."""
    now = firestore.SERVER_TIMESTAMP
    docs: list[tuple[DocPath, dict[str, Any]]] = []

    for doc_id, name, state_id in DIVISIONS:
        docs.append((("divisions", doc_id), {"name": name, "stateId": state_id, "seatCount": 1}))

    for doc_id, name, senators, region_type in SENATE_REGIONS:
        docs.append((("senateRegions", doc_id),
                     {"name": name, "senatorsToElect": senators, "type": region_type}))

    for doc_id, name, abbreviation, registered_name, colour, logo in PARTIES:
        docs.append((("parties", doc_id), {
            "name": name, "abbreviation": abbreviation, "registeredName": registered_name,
            "registrationStatus": "registered",
            "logoUrl": f"gs://evoting-assets/parties/{logo}",
            "colourHex": colour, "registeredStates": list(ALL_STATES),
            "enteredBy": staff_id, "createdAt": now, "updatedAt": now,
        }))

    for doc_id, letter, column, group_type, party_id, display_name in SENATE_GROUPS:
        docs.append((("senateGroups", doc_id), {
            "stateId": "VIC", "groupLetter": letter, "columnPosition": column,
            "groupType": group_type, "partyId": party_id, "displayName": display_name,
            # No candidates are seeded; the candidate routes maintain these two fields.
            "candidateCount": 0, "candidateOrder": [],
            "drawnAt": now, "enteredBy": staff_id, "createdAt": now,
        }))

    for place_id, name, latitude, longitude, place_type, country, terminals in POLLING_PLACES:
        docs.append((("pollingPlaces", place_id), {
            "name": name, "location": firestore.GeoPoint(latitude, longitude),
            "type": place_type, "country": country,
        }))
        for terminal_id, status, device_id in terminals:
            docs.append((("pollingPlaces", place_id, "terminals", terminal_id),
                         {"status": status, "registeredDeviceId": device_id}))

    return deepcopy(docs)


def write_default_structure(tx: Any, election_ref: Any, staff_id: str) -> int:
    """Create every default document under ``election_ref`` inside transaction ``tx``."""
    docs = default_documents(staff_id)
    for path, data in docs:
        ref = election_ref
        for index in range(0, len(path), 2):
            ref = ref.collection(path[index]).document(path[index + 1])
        tx.create(ref, data)
    return len(docs)