# E-Voting Firestore Schema
#### Feel free to modify this file as needed for your implementation / security requirements

## Contents

1. [Collections Overview](#collections-overview)
2. [Collections Details](#collections-details)
   - [Staff](#staff)
   - [Voters](#voters)
   - [Elections](#elections)
   - [Audit Logs](#audit-logs)

---

## Collections Overview

```text
/config/allowedIpRanges/{locationId}
/staff/{staffId}
/voters/{voterId}
    /addressHistory/{changeId}
/elections/{electionId}
    /divisions/{divisionId}            ← House electorates
    /senateRegions/{senateRegionsId}   ← Senate regions
    /parties/{partyId}
    /senateGroups/{groupId}            ← column groupings on Senate ballot
    /candidates/{candidateId}
    /pollingPlaces/{placeId}
        /terminals/{terminalId}
    /houseBallots/{ballotId}
    /senateBallots/{ballotId}
    /counts/{countId}                  ← results & recounts
        /rounds/{roundNumber}
/auditLogs/{logId}
```

---

## Collections Details

## Config

The allowlist uses the `ranges` subcollection under the `allowedIpRanges`
configuration document (`config/allowedIpRanges/ranges/{locationId}`).

### `config/allowedIpRanges/ranges/{locationId}`

```jsonc
{
  "cidr": "203.0.113.0/28",
  "label": "London Diplomatic Mission",
  "updatedBy": "staffId",
  "updatedAt": "timestamp",
  "active": true | false
}
```

## Staff

### `staff/{staffId}`

```jsonc
{
  "authUid": "abc123",
  "name": "Jane Citizen",
  "role": "aecEmployee | commissionerDelegate | admin",
  "stateId": "VIC",
  "active": true | false,
  "createdBy": "staff_admin_0001",
  "createdAt": "timestamp",
  "updatedBy": "staff_admin_0001",
  "updatedAt": "timestamp",
  "deactivatedAt": null,
  "deactivatedBy": null,
  "lastLoginAt": "timestamp"
}
```

---

## Voters

### `voters/{voterId}`

```jsonc
{
  "authUid": "xyz789",
  "givenNames": "...",
  "givenNamesLower": "lowercase given names for staff lookup",
  "surname": "...",
  "surnameLower": "lowercase surname for staff lookup",
  "govId": "...",
  "dateOfBirth": "1990-05-01",
  "enrolmentStatus": "enrolled | pending | removed",
  "enrolledBy": "self | staffId",
  "address": {
    "street": "...",
    "unit": "...",
    "suburb": "...",
    "state": "VIC",
    "postcode": "3000"
  },
  "email": "voter@example.org",
  "divisionId": "div_melbourne | null while pending",
  "stateId": "VIC",
  "rejectionReason": "optional staff rejection reason",
  "reviewedBy": "optional staffId",
  "reviewedAt": "optional timestamp",
  "createdAt": "timestamp",
  "updatedAt": "timestamp",
  "voted": true | false
}
```

Self-service registration creates a pending voter document with `enrolledBy: "self"`, `divisionId: null`, `stateId` copied from the structured address, and `voted: false`. Staff rejection is recorded as `enrolmentStatus: "removed"` with `rejectionReason`, `reviewedBy`, and `reviewedAt`; this avoids conflating a rejection with an ordinary later removal in the audit history.

### `voters/{voterId}/addressHistory/{changeId}`

```jsonc
{
  "previousAddress": {
    "street": "42 Collins Street",
    "unit": "Apt 5",
    "suburb": "Melbourne",
    "state": "VIC",
    "postcode": "3000"
  },
  "newAddress": {
    "street": "17 Smith Street",
    "unit": null,
    "suburb": "Fitzroy",
    "state": "VIC",
    "postcode": "3065"
  },
  "previousDivisionId": "div_melbourne",
  "newDivisionId": "div_wills",
  "divisionChanged": true,
  "stateChanged": false,
  "changedAt": "2028-03-12T09:41:22Z",
  "changedBy": "voterId | staffId",
  "changeChannel": "self_service | aec_staff",
  "reviewedBy": "staffId",
  "verificationStatus": "pending | verified | rejected",
  "reason": "moved_house | correction | other",
  "createdAt": "2028-03-12T09:41:22Z"
}
```

---

## Elections

### `elections/{electionId}`

```jsonc
{
  "name": "2028 Federal Election",
  "type": "federal",
  "status": "setup | open | closed | counting | finalised",
  "openAt": "timestamp",
  "closeAt": "timestamp",
  "timezone": "Australia/Melbourne",
  "createdBy": "staff_admin_0001",
  "createdAt": "timestamp",
  "updatedBy": "staff_admin_0001",
  "updatedAt": "timestamp"
}
```

### `elections/{electionId}/divisions/{divisionId}`

```jsonc
{
  "name": "Melbourne",
  "stateId": "VIC",
  "seatCount": 1   // number of winners for House of Representatives (always 1 in Australia)
}
```

### `elections/{electionId}/senateRegions/{senateRegionId}`

```jsonc
{
  "name": "Victoria",
  "senatorsToElect": 6,        // number of winners in the Senate election
  "type": "state | territory"
}
```

### `elections/{electionId}/parties/{partyId}`

```jsonc
{
  "name": "Greenleaf Alliance",
  "abbreviation": "GLA",
  "registeredName": "Greenleaf Alliance Incorporated",
  "registrationStatus": "registered",
  "logoUrl": "gs://evoting-assets/parties/greenleaf.png",
  "colourHex": "#2E8B57",
  "registeredStates": ["VIC", "NSW", "QLD", "WA", "SA", "TAS", "ACT", "NT"],
  "enteredBy": "staffId",
  "createdAt": "2028-03-01T02:15:00Z",
  "updatedAt": "2028-03-01T02:15:00Z"
}
```

### `elections/{electionId}/senateGroups/{groupId}`

**Example: party group**

```jsonc
{
  "stateId": "VIC",
  "groupLetter": "C",
  "columnPosition": 3,
  "groupType": "party",
  "partyId": "party_greenleaf",   // links to /elections/fed2028/parties/party_greenleaf
  "displayName": "Greenleaf Alliance",
  "candidateCount": 6,
  "candidateOrder": [
    "cand_vic_301",
    "cand_vic_302",
    "cand_vic_303",
    "cand_vic_304",
    "cand_vic_305",
    "cand_vic_306"
  ],
  "drawnAt": "2028-04-10T00:00:00Z",
  "enteredBy": "staffId",
  "createdAt": "2028-04-10T03:30:00Z"
}
```

**Example: independent group**

```jsonc
{
  "stateId": "VIC",
  "groupLetter": "H",
  "columnPosition": 8,
  "groupType": "independentGroup",
  "partyId": null,
  "displayName": "Independent Group H",
  "candidateCount": 2,
  "candidateOrder": ["cand_vic_380", "cand_vic_381"],
  "drawnAt": "2028-04-10T00:00:00Z",
  "enteredBy": "staffId",
  "createdAt": "2028-04-10T03:30:00Z"
}
```

### `elections/{electionId}/candidates/{candidateId}`

```jsonc
{
  "name": "...",
  "partyId": "party_x",
  "chamber": "house | senate",
  "divisionId": "div_melbourne",   // house only
  "stateId": "VIC",                // senate only
  "groupId": "group_A",            // senate only (null if ungrouped)
  "ballotPosition": 14,            // order printed on ballot
  "enteredBy": "staffId",
  "excluded": false,               // manual exclusion for Court of Disputed Returns
  "withdrawn": false,
  "withdrawnAt": null,
  "withdrawnBy": null,
  "withdrawalReason": null
}
```

Candidate withdrawals are soft state changes. A withdrawn candidate is never deleted; ballot rendering and counting must exclude both `withdrawn: true` and `excluded: true`.

**Example entry (senate)**

```jsonc
{
  "name": "Alex Nguyen",
  "partyId": "party_greenleaf",
  "chamber": "senate",
  "stateId": "VIC",
  "groupId": "vic_group_C",
  "ballotPosition": 2,
  "enteredBy": "staffId"
}
```

### `elections/{electionId}/pollingPlaces/{placeId}`

```jsonc
{
  "name": "...",
  "location": "GeoPoint",
  "type": "domestic | diplomaticMission",
  "country": "AU"
}
```

#### `elections/{electionId}/pollingPlaces/{placeId}/terminals/{terminalId}`

```jsonc
{
  "status": "active | disabled",
  "registeredDeviceId": "..."
}
```

**Example entry**

```jsonc
{
  "status": "active",
  "registeredDeviceId": "dev_7f3a91"
}
```

### `elections/{electionId}/houseBallots/{ballotId}`

```jsonc
{
  "divisionId": "div_melbourne",
  "preferences": ["cand_5", "cand_2", "cand_9", "cand_1"],   // index 0 = preference 1
  "source": "electronic | paper_scan",
  "isFormal": true | false           // valid vote or not (formal vs informal)
}
```

### `elections/{electionId}/senateBallots/{ballotId}`

```jsonc
{
  "stateId": "VIC",
  "aboveTheLine": ["group_C", "group_A", "group_F"],   // empty if not used
  "belowTheLine": ["cand_44", "cand_41", "cand_12"],   // empty if not used
  "source": "electronic | paper_scan",
  "isFormal": true | false
}
```

### `elections/{electionId}/counts/{countId}`

```jsonc
{
  "chamber": "senate | house",
  "scopeId": "VIC",                       // state or division
  "type": "initial | recount",
  "excludedCandidateIds": ["cand_7"],     // manual exclusions set by delegate
  "orderedByCourt": true,                 // whether recount is ordered by court
  "status": "running | complete",         // is the system done counting?
  "elected": ["cand_3", "cand_9"],        // in order of election
  "quota": 123456,                        // number of votes a candidate needs to be elected
  "totalFormalBallots": 864000,
  "computedAt": "timestamp",
  "sharedExternally": true | false,       // prevents sharing the same results twice
  "ballotHash": "hash value",             // integrity of ballots for recounts
  "triggeredBy": "staffId"                // who triggered the count/recount
}
```

#### `elections/{electionId}/counts/{countId}/rounds/{roundNumber}`

```jsonc
{
  "roundNumber": 1,
  "action": "elected | excluded | transfer",
  "candidateId": "cand_3",
  "tallies": { "cand_1": 50210.5, "cand_2": 31000 }
}
```

| Field         | Description                                                                                  |
| ------------- | -------------------------------------------------------------------------------------------- |
| `action`      | See values below                                                                             |
| `candidateId` | The candidate the action applies to (who was elected, excluded, or whose votes were transferred) |
| `tallies`     | Map of every remaining candidate's vote total after this round                               |

**`action` values**

| Value      | Meaning                                                                         |
| ---------- | ------------------------------------------------------------------------------- |
| `elected`  | A candidate reached the quota                                                   |
| `excluded` | The lowest candidate was eliminated                                             |
| `transfer` | Votes moved from an elected or excluded candidate to the next preferences       |

---

## Audit Logs

### `auditLogs/{logId}` (append only)

#### Events to log

| Category              | Events                                                                                      |
| --------------------- | ------------------------------------------------------------------------------------------- |
| Staff actions (voters)     | Registration, address changes                                                          |
| Staff actions (candidates) | Entry, edits, withdrawals, manual exclusions                                           |
| Voting events         | Rejected votes (outside geofence, unregistered terminal, double vote attempt)               |
| Counting              | Counts/recounts started and completed, finalisation                                         |
| Exports               | Results shared externally                                                                   |
| Admin actions         | Logins, staff account create/edit/delete, geofencing changes, election creation / phase change |

#### Example: candidate entry log

```jsonc
{
  "timestamp": "2028-04-10T03:30:12Z",
  "electionId": "fed2028",                // null for actions outside election
  "actorId": "staff_vic_0042",            // staff/voter/admin ID or "system"
  "actorType": "commissionerDelegate",    // aecEmployee, commissionerDelegate, admin, auditor, voter or system
  "actorStateId": "VIC",
  "action": "candidate.create",           // add more as you go (see below)
  "category": "candidateManagement",      // broad grouping for dashboards (see below)
  "targetType": "candidate",
  "targetId": "cand_vic_302",
  "targetPath": "/elections/fed2028/candidates/cand_vic_302",   // where the changes take place
  "before": null,
  "after": { "name": "Alex Nguyen", "groupId": "vic_group_C", "orderInGroup": 2 },
  "outcome": "success",                   // success | denied | failed
  "reason": null,                         // reason for outcome (see below)
  "ipAddress": "203.0.113.45",
  "deviceId": "dev_7f3a91",
  "terminalId": null,
  "sessionId": "sess_8c21e4",
  "previousHash": "9f2b...e1",            // tamper-evident log: hash chain
  "hash": "c47a...3d"
}
```

#### Field notes

- **`action`**: examples so far are `voter.register`, `voter.addressUpdate`, `candidate.create`, `candidate.exclude`, `count.start`, `results.export`. Add more as needed.
- **`category`**: `enrolment`, `candidateManagement`, `voting`, `counting`, `export`, `security`, `admin`.
- **`reason`**: explains the outcome, e.g. a rejected vote → `"outside_geofence"`, a recount → `"court_order_2028/17"`.
- **`previousHash` / `hash`**: form a hash chain, a tamper-evident log security requirement.
