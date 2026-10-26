"""Seed a demo election with real ballots, receipts and published results.

Runs the same code paths as the API (``record_ballot`` and ``publish_results``)
so the Published Results, Verify receipt and Verify result package pages can be
exercised end to end without logging in as voters. Ballots are encrypted with
the project's encryption keys, as the API does; only the voting session (which
needs a signed-in voter) is skipped.

    python -m backend.seed_demo_results                  # cast ballots and publish
    python -m backend.seed_demo_results --skip-publish   # stop before publishing
    python -m backend.seed_demo_results --publish ELECTION_ID

It writes to the emulator only, unless --allow-live is passed.
"""
import argparse
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from google.cloud import firestore
from starlette.requests import Request

from backend.election_defaults import DIVISIONS, PARTIES, SENATE_GROUPS, write_default_structure
from backend.firestore_client import db
from backend.models import BallotSubmission
from backend.reconciliation import describe, reconcile_votes
from backend.results import publish_results
from backend.routers.voter_ballots import record_ballot
from backend.security.key_management import get_encryption_service

ACTOR = {"staffId": "system_seed", "role": "system"}
GIVEN = ["Alex", "Sam", "Jordan", "Priya", "Mei", "Daniel", "Aisha", "Tom", "Lena", "Ravi", "Chloe", "Noah"]
FAMILY = ["Nguyen", "Sharma", "O'Brien", "Lin", "Patel", "Smith", "Kaur", "Rossi", "Walker", "Chen", "Hughes"]


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/seed", "headers": [],
                    "client": ("127.0.0.1", 0), "query_string": b""})


def _name(rng: random.Random) -> str:
    return f"{rng.choice(GIVEN)} {rng.choice(FAMILY)}"


def create_election(rng: random.Random) -> str:
    now = datetime.now(timezone.utc)
    election_ref = db.collection("elections").document()
    batch = db.batch()
    batch.create(election_ref, {
        "name": f"Demo Results Election {now:%Y-%m-%d %H:%M}", "type": "federal", "status": "setup",
        "openAt": now - timedelta(hours=1), "closeAt": now + timedelta(hours=2),
        "timezone": "Australia/Melbourne", "createdBy": ACTOR["staffId"], "createdAt": now,
        "updatedBy": ACTOR["staffId"], "updatedAt": now, "demo": True,
    })
    write_default_structure(batch, election_ref, ACTOR["staffId"])
    batch.commit()

    batch = db.batch()
    candidates = election_ref.collection("candidates")
    party_ids = [party[0] for party in PARTIES]
    for division_id, _, state_id in DIVISIONS:
        for position, party_id in enumerate(party_ids, start=1):
            batch.create(candidates.document(), {
                "name": _name(rng), "partyId": party_id, "chamber": "house", "divisionId": division_id,
                "stateId": state_id, "groupId": None, "ballotPosition": position,
                "enteredBy": ACTOR["staffId"], "excluded": False, "withdrawn": False,
            })
    # Two senate candidates in each seeded Victorian group, two ungrouped in every other state.
    for group_id, _, _, _, party_id, _ in SENATE_GROUPS:
        order = []
        for position in (1, 2):
            ref = candidates.document()
            order.append(ref.id)
            batch.create(ref, {
                "name": _name(rng), "partyId": party_id, "chamber": "senate", "divisionId": None,
                "stateId": "VIC", "groupId": group_id, "ballotPosition": position,
                "enteredBy": ACTOR["staffId"], "excluded": False, "withdrawn": False,
            })
        batch.update(election_ref.collection("senateGroups").document(group_id),
                     {"candidateOrder": order, "candidateCount": len(order)})
    for state_id in sorted({state for _, _, state in DIVISIONS} - {"VIC"}):
        for position in (1, 2):
            batch.create(candidates.document(), {
                "name": _name(rng), "partyId": rng.choice(party_ids + [None]), "chamber": "senate",
                "divisionId": None, "stateId": state_id, "groupId": None, "ballotPosition": position,
                "enteredBy": ACTOR["staffId"], "excluded": False, "withdrawn": False,
            })
    batch.commit()
    return election_ref.id


def create_voters(rng: random.Random, count: int) -> list[str]:
    now = datetime.now(timezone.utc)
    batch = db.batch()
    ids = []
    for index in range(count):
        division_id, _, state_id = DIVISIONS[index % len(DIVISIONS)]
        ref = db.collection("voters").document()
        ids.append(ref.id)
        given, surname = rng.choice(GIVEN), rng.choice(FAMILY)
        batch.create(ref, {
            "authUid": f"demo-{uuid.uuid4().hex}", "givenNames": given, "givenNamesLower": given.lower(),
            "surname": surname, "surnameLower": surname.lower(), "govId": f"DEMO{index:06d}",
            "dateOfBirth": "1990-01-01", "email": f"demo{index}@example.org",
            "address": {"street": "1 Demo Street", "suburb": "Demo", "state": state_id, "postcode": "3000"},
            "divisionId": division_id, "stateId": state_id, "enrolmentStatus": "enrolled",
            "enrolledBy": ACTOR["staffId"], "voted": False, "createdAt": now, "updatedAt": now, "demo": True,
        })
    batch.commit()
    return ids


def random_ballot(rng: random.Random, election_id: str, voter_id: str) -> BallotSubmission:
    election_ref = db.collection("elections").document(election_id)
    voter = db.collection("voters").document(voter_id).get().to_dict() or {}
    candidates = [(item.id, item.to_dict() or {}) for item in election_ref.collection("candidates").stream()]
    house = [cid for cid, c in candidates if c.get("chamber") == "house" and c.get("divisionId") == voter["divisionId"]]
    senate = [cid for cid, c in candidates if c.get("chamber") == "senate" and c.get("stateId") == voter["stateId"]]
    groups = [item.id for item in election_ref.collection("senateGroups").where("stateId", "==", voter["stateId"]).stream()
              if (item.to_dict() or {}).get("candidateOrder")]
    rng.shuffle(house)
    rng.shuffle(senate)
    rng.shuffle(groups)
    roll = rng.random()
    preferences = house if roll > 0.08 else house[:1]  # about 8% informal (partly numbered)
    if groups and roll > 0.35:
        above, below = groups, []
    elif roll > 0.05:
        above, below = [], senate
    else:
        above, below = [], []  # blank senate ballot
    return BallotSubmission.model_validate(
        {"house": {"preferences": preferences}, "senate": {"aboveTheLine": above, "belowTheLine": below}}
    )


def set_status(election_id: str, status: str) -> None:
    db.collection("elections").document(election_id).update(
        {"status": status, "updatedBy": ACTOR["staffId"], "updatedAt": firestore.SERVER_TIMESTAMP}
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--voters", type=int, default=40, help="number of demo voters (max 400)")
    parser.add_argument("--skip-publish", action="store_true", help="finalise but do not publish results")
    parser.add_argument("--publish", metavar="ELECTION_ID", help="only publish an already finalised election")
    parser.add_argument("--allow-live", action="store_true", help="allow writing to a real Firebase project")
    parser.add_argument("--seed", type=int, default=None, help="random seed for repeatable data")
    args = parser.parse_args()

    if not os.getenv("FIRESTORE_EMULATOR_HOST") and not args.allow_live:
        print("FIRESTORE_EMULATOR_HOST is not set. Refusing to write demo data to a live project.\n"
              "Start the emulator, or pass --allow-live if you really mean it.", file=sys.stderr)
        return 2
    if args.publish:
        result = publish_results(args.publish, ACTOR, _request())
        print(f"Published {result['electionId']}\nFingerprint ({result['hashAlgorithm']}): {result['fingerprint']}")
        return 0
    if not 1 <= args.voters <= 400:
        parser.error("--voters must be between 1 and 400")
    if list(db.collection("elections").where("status", "==", "open").limit(1).stream()):
        print("Another election is open. Close it before seeding a demo election.", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    election_id = create_election(rng)
    voter_ids = create_voters(rng, args.voters)
    set_status(election_id, "open")
    encryption = get_encryption_service()
    receipts = []
    for voter_id in voter_ids:
        cast = record_ballot(voter_id, election_id, random_ballot(rng, election_id, voter_id), _request(),
                             encryption=encryption, require_session=False)
        receipts.append(cast["receipt"])
    db.collection("elections").document(election_id).update({"closedAt": firestore.SERVER_TIMESTAMP})
    # The same check the API runs before finalisation (R-05).
    reconciliation = reconcile_votes(election_id)
    if not reconciliation["reconciled"]:
        print(f"Votes do not reconcile: {'; '.join(describe(reconciliation))}. "
              f"Election {election_id} was not finalised.", file=sys.stderr)
        return 1
    set_status(election_id, "finalised")

    print(f"Election: {election_id}")
    print(f"Ballots cast: {len(receipts)}")
    print(f"Reconciled: {'; '.join(describe(reconciliation))}")
    print("Sample receipts (each voter normally only sees their own):")
    for code in receipts[:5]:
        print(f"  {code}")
    if args.skip_publish:
        print(f"\nResults NOT published. Publish later with:\n"
              f"  python -m backend.seed_demo_results --publish {election_id}")
        return 0
    result = publish_results(election_id, ACTOR, _request())
    print(f"\nPublished. Fingerprint ({result['hashAlgorithm']}): {result['fingerprint']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
