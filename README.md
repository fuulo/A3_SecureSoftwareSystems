# A3 Secure Software Systems

An academic e-voting prototype with a Next.js frontend and a Python FastAPI staff API.

## Architecture and replaceable security

The system is built from distinct subsystems around a centralised database.
Security mechanisms and cryptographic standards sit behind interfaces, so they
can be replaced or upgraded without redesigning the core voting functionality.

| Part | Runs as | Responsible for |
| --- | --- | --- |
| Frontend | Next.js behind its own TLS listener (`npm run dev`) | Pages for voters, staff and the public; calls the API over HTTPS |
| API | FastAPI behind its own TLS listener (`python -m backend.tls_server`) | Voting, counting, staff and election management; each security mechanism in its own module |
| Firebase | Managed service | Sign-in (Authentication) and the centralised database (Firestore), shared by both |

**Core voting functionality** is ballot casting (`record_ballot` in
[backend/routers/voter_ballots.py](./backend/routers/voter_ballots.py)),
reconciliation ([backend/reconciliation.py](./backend/reconciliation.py)), and
counting and publication ([backend/results.py](./backend/results.py)). It
contains no algorithm choices: it calls the interfaces below.

### Security subsystems

| # | Subsystem | Interface used by the rest of the system | Mechanism or standard | How to replace or upgrade | Replaceable without redesigning voting |
| --- | --- | --- | --- | --- | --- |
| 1 | Transport security | [tls-policy.json](./tls-policy.json); listeners that wrap each app ([server/secure-listener.mjs](./server/secure-listener.mjs), [backend/tls_server.py](./backend/tls_server.py)) | TLS 1.3, AEAD cipher suites | Edit `tls-policy.json` and restart both servers, or swap a listener | ✅ |
| 2 | Session management | `verify_token` ([backend/auth.py](./backend/auth.py)), [backend/sessions.py](./backend/sessions.py), [lib/session.ts](./lib/session.ts) | JWT (HS256), 2-minute inactivity timeout | `SESSION_SIGNING_ALGORITHM` (HS256, HS384, HS512), then delete `config/sessionSigning` and restart; time limits in one place each | ✅ |
| 3 | Account lockout | `/api/auth/lockout/*` ([backend/routers/auth_lockout.py](./backend/routers/auth_lockout.py)), [lib/lockout.ts](./lib/lockout.ts) | 3 failures, progressive locks | Rules are constants in one module | ✅ |
| 4 | Access control | `staff_access`, `require_roles`, IP allowlist checks ([backend/auth.py](./backend/auth.py)) | Roles, IP ranges | One module | ✅ |
| 5 | Rate limiting | `limiter.limit(...)` ([backend/rate_limit.py](./backend/rate_limit.py)) | Per-IP limits (slowapi) | Replace the limiter in one module | ✅ |
| 6 | Data encryption and key management | `EncryptionService`, `get_encryption_service()` ([backend/security/](./backend/security/)) | AES-256-GCM, versioned keys, 90-day rotation | New key version, or a new service class | ✅ |
| 7 | Ballot receipts | `issue_receipt`, `receipt_hash` ([backend/receipts.py](./backend/receipts.py)) | Hash provider, `receipt` | `HASH_ALGORITHM_RECEIPT`; earlier receipts still verify | ✅ |
| 8 | Audit log integrity | `write_audit`, chain verification ([backend/audit.py](./backend/audit.py)) | Hash chain, provider `audit` | `HASH_ALGORITHM_AUDIT`; each entry names its algorithm and the chain verifies across a change | ✅ |
| 9 | Result integrity | `publish_results`, `GET /api/public/results`, the verify-package page; signing in [backend/security/signing.py](./backend/security/signing.py) | Fingerprint, provider `results`; Ed25519 signature of the package bytes | `HASH_ALGORITHM_RESULTS` (sha256, sha384, sha512); the browser check follows the published algorithm. A new key file replaces the signing key; each signature names its key ID | ✅ |
| 10 | Authentication and MFA | Firebase Authentication; on the API, `verify_firebase_token` | Password and SMS one-time code | The API side is one function, but the sign-in pages and [lib/mfa.ts](./lib/mfa.ts) use the Firebase SDK directly | ⚠️ Partly: a new provider means rewriting the sign-in pages, not the voting logic |
| 11 | Voter identity index (GovID) | [backend/routers/employee_voters.py](./backend/routers/employee_voters.py), [backend/routers/voter_registration.py](./backend/routers/voter_registration.py) | Staff path: SHA-256 called directly; self-registration: keyed hash from the encryption module | Both call sites must change | ❌ Not yet |

**Result: 9 of 11 security subsystems (82%) can be replaced or upgraded through
their interface alone.**

### Hash algorithms

[backend/security/hashing.py](./backend/security/hashing.py) is the one place
that hashes for receipts, the audit log, result fingerprints and lookup IDs.
Each purpose has its own setting in `backend/.env`, SHA-256 by default:

```dotenv
HASH_ALGORITHM_RECEIPT=sha256   # sha256, sha384, sha512, sha3_256, sha3_512
HASH_ALGORITHM_AUDIT=sha256
HASH_ALGORITHM_RESULTS=sha256   # sha256, sha384 or sha512: checked in browsers
HASH_ALGORITHM_INDEX=sha256     # lockout records and audit-view throttling
```

A change applies to new values only. Stored values name their algorithm, and
values from before had SHA-256, so existing receipts, audit entries and
published results keep verifying. An unsupported setting stops the API at
startup.

Tests: `python -m pytest backend/tests/test_hashing.py backend/tests/test_tls_server.py backend/tests/test_sessions.py`
cover switching each algorithm, verifying data made before the switch, and
the shared TLS policy deciding which connections are accepted.

## Run the frontend

Set the Firebase client configuration in `.env.local`, including:

```dotenv
NEXT_PUBLIC_FIREBASE_API_KEY=...
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=...
NEXT_PUBLIC_FIREBASE_PROJECT_ID=...
NEXT_PUBLIC_FIREBASE_APP_ID=...
NEXT_PUBLIC_API_BASE_URL=https://127.0.0.1:8000
```

Then run:

```powershell
npm install
npm run cert:dev   # once: creates the localhost certificate in certs/
npm run dev
```

The site is served only at `https://localhost:3000`. For the browser to trust
the certificate, install the [mkcert](https://github.com/FiloSottile/mkcert)
development CA once (`mkcert -install`) before running `npm run cert:dev`; the
script signs the certificate with that CA. Without it, the certificate is
self-signed and the browser shows "Not secure". After installing the CA, run
`npm run cert:dev -- --force` to replace an existing certificate.

Do not use `next dev --experimental-https`: Next.js's built-in HTTPS server
accepts TLS 1.2 and does not log rejected connections.

### TLS 1.3 enforcement

`npm run dev` and `npm start` run [server.mjs](./server.mjs) instead of the
built-in Next.js server. Its listener ([server/secure-listener.mjs](./server/secure-listener.mjs))
checks every connection before Next.js reads any request data:

| Connection | Result | Logged reason |
| --- | --- | --- |
| Plain HTTP (first byte is not a TLS handshake record) | Closed | `notTls` |
| No data sent within 10 seconds | Closed | `noClientHello` |
| TLS 1.0 / 1.1, or any other failed handshake | Closed | `handshakeFailed` |
| Negotiated TLS 1.2 | Closed after the handshake | `protocolBelowTls13` |
| TLS 1.3 with a cipher not in the policy | Closed | `cipherNotAllowed` |
| TLS 1.3 with an allowed cipher | Passed to Next.js | — |

The minimum version and allowed ciphers come from
[tls-policy.json](./tls-policy.json), shared with the API listener. Restart both
servers after editing it; a missing or invalid file stops them starting.

Rejections are printed to the console and appended as JSON lines to
`logs/tls-security.log`. Override the defaults with `TLS_CERT_FILE`,
`TLS_KEY_FILE`, `TLS_LOG_FILE`, `TLS_POLICY_FILE`, `HOST` and `PORT`.

To check it by hand (Git Bash or any shell with OpenSSL and curl):

```bash
openssl s_client -connect localhost:3000 -tls1_3   # accepted: "Protocol: TLSv1.3"
openssl s_client -connect localhost:3000 -tls1_2   # rejected: protocolBelowTls13
curl http://localhost:3000                         # rejected: notTls
```

## Run the staff API

Install Python dependencies and configure `backend/.env` (do not commit credentials):

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json
FIREBASE_PROJECT_ID=a3-voting-system-dev
ALLOWED_ORIGINS=https://localhost:3000
```

Start the API from the repository root. It uses the same certificate as the
frontend, so run `npm run cert:dev` first:

```powershell
python -m pip install -r backend/requirements.txt
python -m backend.tls_server --reload
```

If .env file is not detected:

```powershell
python -m backend.tls_server --reload --env-file backend\.env
```

The API is served only at `https://127.0.0.1:8000`.
[backend/tls_server.py](./backend/tls_server.py) applies the same checks as
the frontend listener (see [TLS 1.3 enforcement](#tls-13-enforcement)) before
FastAPI reads any request data, and appends rejections to
`logs/tls-security-api.log`. Do not start the API with plain `uvicorn`, which
serves unencrypted HTTP. `TLS_CERT_FILE`, `TLS_KEY_FILE` and `TLS_LOG_FILE` in
`backend/.env` override the defaults; `--host` and `--port` are also accepted.
For local emulator use, set `FIRESTORE_EMULATOR_HOST` and
`FIREBASE_AUTH_EMULATOR_HOST` in the API process environment and start the
Firestore and Auth emulators with `firebase emulators:start --only firestore,auth`.
The Admin SDK uses the emulator environment variables; configure a test project
ID and credentials in `backend/.env` as well. Only enable
`TRUST_PROXY_HEADERS` behind a trusted proxy that overwrites
`X-Forwarded-For`; the API treats its first address as the client address.

The initial active admin staff record and first IP range must be provisioned
out-of-band using a trusted Firebase Admin SDK setup process. The API fails
closed when the allowlist cannot be read or has no configured range; bootstrap
access is limited to admin IP-range endpoints.
Configure the SMTP settings for staff account setup emails; staff creation
fails if the password setup link cannot be sent.

Run the Python tests with:

```powershell
python -m pytest backend/tests
```

### Result archive (R-06)

Publishing results first uploads the result package and the receipt list to a
Backblaze B2 bucket, each locked for 7 years with Object Lock. If they cannot be
uploaded and locked, nothing is published. Add to `backend/.env`:

```dotenv
B2_KEY_ID=<application key ID>
B2_APPLICATION_KEY=<application key>
B2_BUCKET=voting-test
B2_RETENTION_MODE=governance   # compliance for a real election
ARCHIVE_REQUIRED=true
```

- Create the bucket with **Object Lock enabled** (B2 → Buckets → Create, or
  Bucket Settings → Object Lock).
- Restrict the application key to that bucket, with the capabilities
  `listBuckets`, `readBucketRetentions`, `writeFiles`, `writeFileRetentions`
  and `readFileRetentions`.
- **Compliance** mode: nobody, including the account owner, can delete the
  files (or the bucket) for 7 years. **Governance** mode can be lifted by a key
  with `bypassGovernance`, so use it only for test buckets.
- Without B2 (for example with the emulator), set `ARCHIVE_REQUIRED=false`:
  results are published without an archive and the `results.publish` audit
  entry records `reason: archive_not_configured`.

### Signed results (R-09)

Every result package is signed with Ed25519 over its exact published bytes
([backend/security/signing.py](./backend/security/signing.py)), and checked
together with its fingerprint. The package names the receipt list's
fingerprint, so the signature covers the receipt list too. The signature, its
key ID and the public key are archived with the package (R-06), and the
signature is written to the `results.publish` audit entry.

Create the private key once per deployment, before results are published:

```powershell
python -m backend.security.signing   # writes certs/results-signing-key.pem
```

`RESULTS_SIGNING_KEY_FILE` in `backend/.env` sets another path. The key is
never stored in Firestore, so someone able to change a published package in
the database cannot re-sign it. Keep it secret and backed up. Everyone
publishing to the same Firebase project must use the same key file, or
signatures will not match the key the API serves. Without the key, publishing
fails with 503 and nothing is archived or published.

The verify-package page checks the signature in the browser (Web Crypto
Ed25519). To check a downloaded package without the site, save `publicKeyPem`
from `GET /api/public/results/signing-key` as `results-signing-key.pem`:

```powershell
openssl pkeyutl -verify -pubin -inkey results-signing-key.pem -rawin -in result-package-fed2028.json -sigfile result-package-fed2028.sig
```

Tests: `python -m pytest backend/tests/test_signing.py backend/tests/test_archive.py`

### Ballot integrity (R-15)

Every ballot is checked before it is counted
([backend/ballot_integrity.py](./backend/ballot_integrity.py)). Each ballot's
choices are encrypted with AES-256-GCM, with the ballot's election, chamber,
contest, ballot ID and source as associated data
([backend/ballots.py](./backend/ballots.py)). Those values are authenticated
but not encrypted, so a ballot that was altered, or copied or moved to
another ballot, contest or election, no longer decrypts. Once decrypted, a
ballot must hold a list of choices, number each choice at most once, and name
only candidates (or Senate groups) of its own contest. Candidates withdrawn
after voting began still count as part of the contest.

A ballot that fails is left out of the count and flagged in
`elections/{id}/flaggedBallots`, with a `ballot.integrityFailed` audit entry
naming the failed check (`decrypt_failed`, `malformed`, `duplicate_choice`,
`unknown_choice`, or `legacy_unverified` for ballots stored without this
protection). Flags never hold the ballot's choices. Finalising the election
and publishing its results both run the check, and both are refused with 409
while any flag awaits review. An admin reviews each flag with a note in the
Elections page (**Ballot integrity → Flagged ballots**). The review is audited
(`ballot.flagReviewed`), and the ballot stays excluded. The result package
(version 5) reports `excludedHouseBallots` and `excludedSenateBallots`, and the
verify-package page allows for them when it checks each chamber's totals.

If the encryption keys cannot be loaded, the check stops with 503 and nothing
is flagged.

Scanned paper ballots are not yet supported. An import would store them
through `house_document`/`senate_document` with `source: "paper_scan"`, so they
get the same checks.

Tests: `python -m pytest backend/tests/test_ballot_integrity.py`

## Results, receipts and verification

| Endpoint | Who | Purpose |
| --- | --- | --- |
| `GET /api/voter/ballots/current` | Enrolled voter (Firebase token, voter IP allowlist) | The open election and the voter's House and Senate ballot papers in ballot order, used by `/voter/ballot`; once they have voted, only that fact |
| `POST /api/voter/ballots/{electionId}/start` | Enrolled voter (Firebase token, voter IP allowlist) | Starts a 15-minute voting session; refused if the voter has voted in this election or already has an active session |
| `POST /api/voter/ballots/{electionId}/submit` | Voter with an active session | Validates the ballot, stores it encrypted (AES-256-GCM), marks the voter as voted and returns a one-time receipt code, all in one transaction |
| `POST /api/admin/elections/{id}/results/publish` | Admin | Checks every ballot again (R-15), counts those that pass, archives the package and receipt list for 7 years (R-06), then freezes the result package |
| `POST /api/admin/elections/{id}/phase` with `{"to": "finalised"}` | Admin | Finalises only if voters marked voted, House ballots, Senate ballots and receipts all match (R-05), and every ballot passes its integrity check or has a reviewed flag (R-15); otherwise it is refused and logged |
| `POST /api/admin/elections/{id}/ballots/check` | Admin, once voting has closed | Checks every ballot's integrity now and flags failures (R-15); returns the counted, excluded and pending-review totals |
| `GET /api/admin/elections/{id}/flagged-ballots` | Admin | Ballots that failed their integrity check, awaiting review first |
| `POST /api/admin/elections/{id}/flagged-ballots/{flagId}/review` with `{"note": "..."}` | Admin | Records the review of a flag (audited); the ballot stays excluded |
| `GET /api/public/results` | Anyone | Latest published results, their fingerprint and its hash algorithm (SHA-256 by default), and their Ed25519 `signature` (`algorithm`, `keyId`, `value`; null before signing) |
| `GET /api/public/results/package.json` | Anyone | Downloadable result package (the exact published bytes) |
| `GET /api/public/results/package.sig` | Anyone | Raw Ed25519 signature of the package (R-09), for checking with tools such as openssl; 404 for results published before signing |
| `GET /api/public/results/signing-key` | Anyone | The results signing key (`algorithm`, `keyId`, `publicKeyPem`), read from the key file, not Firestore |
| `GET /api/public/results/receipts.txt` | Anyone (30 per minute) | Receipt list: the hash of every receipt code (its receipt ID), sorted, one per line; its fingerprint is `receiptsFingerprint` in the package |
| `POST /api/public/receipts/verify` | Anyone (10 per minute) | Confirms a receipt's ballot was recorded, never its contents |

### Validate the three public pages from the frontend

The Published Results (`/results`), Verify receipt (`/verify-receipt`) and
Verify result package (`/verify-package`) pages need no sign-in. They read
everything from the API, so the steps below exercise the backend through the
real pages.

#### 1. Set up

1. Install the API dependencies into a virtual environment (once):

   ```powershell
   python -m venv .venv
   .venv\Scripts\python -m pip install -r backend/requirements.txt
   ```

2. Create `backend/.env` as described in [Run the staff API](#run-the-staff-api).
   `GOOGLE_APPLICATION_CREDENTIALS` must point to a service-account key for the
   project (Firebase console → Project settings → Service accounts → Generate
   new private key). Keep the key outside the repository and never commit it.
3. Make sure `.env.local` contains `NEXT_PUBLIC_API_BASE_URL=https://127.0.0.1:8000`.

#### 2. Seed a demo election

`backend/seed_demo_results.py` creates a demo election, enrols demo voters,
casts their encrypted ballots through the same code as
`POST /api/voter/ballots/{electionId}/submit` (without the voting session),
finalises the election and publishes the results through the same code as the
admin publish endpoint. It prints sample receipt codes and the published
fingerprint with its algorithm (SHA-256 by default); keep that output for the
checks below.

By default it only writes to the Firestore emulator. To use the shared
development project instead, add `--allow-live`. Tell the team first, because
each run adds one election and its demo voters (marked `demo: true`) to the
project.

```powershell
# Emulator: set the same variable in the API terminal too
$env:FIRESTORE_EMULATOR_HOST="127.0.0.1:8080"
.venv\Scripts\python -m backend.seed_demo_results

# Shared development project
.venv\Scripts\python -m backend.seed_demo_results --allow-live
```

To also check the "not yet published" behaviour, seed in two steps:

```powershell
.venv\Scripts\python -m backend.seed_demo_results --allow-live --skip-publish
# ...run the "before publishing" checks below, then:
.venv\Scripts\python -m backend.seed_demo_results --allow-live --publish <ELECTION_ID>
```

The seed refuses to run while another election is `open`. Other options:
`--voters N` (1 to 400, default 40) and `--seed N` (repeatable data).

#### 3. Start both servers

```powershell
.venv\Scripts\python -m backend.tls_server --reload --env-file backend\.env
npm run dev
```

`https://127.0.0.1:8000/health` should return `{"status":"ok"}`.

#### 4. Published Results: `/results`

| Check | Expected result |
| --- | --- |
| Open the page before results are published (`--skip-publish`) | "No results have been published yet" |
| Open the page after publishing | Summary cards (status Final, ballots cast, turnout, published time), then one table per House division and Senate state |
| Compare the "Published SHA-256 fingerprint" with the seed output | Identical |
| Click "Download result package (JSON)" | A file named `result-package-<electionId>.json` downloads |
| Click "Download receipt list (TXT)" | A file named `receipts-<electionId>.txt` downloads, one receipt hash per line (64 characters with the default SHA-256) |
| Read the note above the download links | "…cannot be deleted or changed until <date 7 years after publishing>" |
| Stop the API and reload the page | "Results Unavailable" |

#### 5. Verify receipt: `/verify-receipt`

| Check | Expected result |
| --- | --- |
| Enter a receipt printed by the seed, before publishing | Green: "Your ballot was recorded", "It will be included when the results are published" |
| Enter the same receipt after publishing | Green, "It is included in the published results" |
| Enter it in lower case, or without dashes | Same green result (input is normalised) |
| Change one character of a valid receipt | "No ballot was found for this receipt code…" |
| Type `0`, `1`, `I`, `L`, `O` or a symbol | Amber warning; the character is removed |
| Submit fewer than 16 characters | "Please enter all 16 characters…" (no request is sent) |
| Submit 11 lookups within one minute | "Too many attempts. Please wait a minute and try again." |
| DevTools → Network → the `verify` request | A `POST` with the code in the body, not the URL; the response contains only `recordedAt` and `includedInTally` |

#### 6. Verify result package: `/verify-package`

| Check | Expected result |
| --- | --- |
| Open the page | "Expected SHA-256 fingerprint" is pre-filled with the published fingerprint |
| Download the official package from the page, then click Verify | "This result package is genuine and consistent"; every check is ticked |
| Edit one vote count in the downloaded file and verify it | Fails "Fingerprint matches" and "Totals add up" for that contest |
| Edit a count and also the contest's `informal`, so the totals still add up | Totals pass, but "Fingerprint matches" still fails |
| Change `votersMarkedVoted` in the downloaded file and verify it | Fails "One ballot per voter who voted" and "Fingerprint matches" |
| Verify the untouched file with one character of the fingerprint changed | Fails "Fingerprint matches" |
| Choose a non-JSON file, or a file over 2 MB | A clear error, and nothing is checked |
| Add the downloaded receipt list and a receipt printed by the seed | "Receipt list matches the package", "Every receipt listed once" and "Your receipt is in the list" pass |
| Delete one line from the receipt list and verify again | Fails "Receipt list matches the package" and "Every receipt listed once" |
| Change one character of the receipt code | Fails "Your receipt is in the list" |
| DevTools → Network while verifying | No request is sent: the file is hashed in the browser |

#### Clean up

Delete the demo election (`elections/<id>`), its entry in `publishedResults`,
and the voters with `demo: true` from the Firebase console. Receipts for the
election are in `receipts`, filtered by `electionId`.

## Two-person approval of candidate and staff changes

Commissioner delegates cannot change candidates on their own, and admins cannot change staff
accounts on their own. Creating, editing, withdrawing or deactivating submits a *change request*;
another person must approve it before anything is applied.

| Change | Submitted by | Decided by |
| --- | --- | --- |
| Candidate create, edit, withdraw | Commissioner delegate | A different delegate in the **same state** |
| Staff account create, edit, deactivate | Admin | A different admin |

| Endpoint | Purpose |
| --- | --- |
| `POST/PATCH /api/delegate/elections/{id}/candidates[/{candidateId}[/withdraw]]` | Submit a candidate change (returns `202` with a `requestId`) |
| `GET /api/delegate/elections/{id}/change-requests` | Pending and recently decided candidate requests for your state |
| `POST /api/delegate/elections/{id}/change-requests/{requestId}/approve` or `/reject` | Decide a candidate request (`reject` needs a `reason`) |
| `POST/PATCH/DELETE /api/admin/staff[/{staffId}]` | Submit a staff change (returns `202` with a `requestId`) |
| `GET /api/admin/staff/change-requests` | Pending and recently decided staff requests |
| `POST /api/admin/staff/change-requests/{requestId}/approve` or `/reject` | Decide a staff request |

The API enforces the rules, not the browser. Approval re-validates against current data (election phase,
state scope, ballot positions, last-admin protection) and applies the change in one transaction.
See [firestore-schema.md](./firestore-schema.md#change-requests-approval-workflow) for the data model.

Operational consequences to plan for:

- **At least two active admins** are needed before any staff account can be created, edited or
  deactivated through the API, and **at least two active delegates per state** before that state's
  candidates can change. Provision a second admin out-of-band, as for the first.
- A staff account's sign-in is created disabled when requested and only enabled on approval, so no
  password is ever stored in Firestore. Rejecting a request deletes that sign-in account.
- Deploy the two new composite indexes in [firestore.indexes.json](./firestore.indexes.json).

## Two-factor authentication

Voters sign in with two factors: their **password** and a **one-time code sent
by SMS** (Firebase phone multi-factor authentication).

| Step | Page | What happens |
| --- | --- | --- |
| Enrol | `/mfa_setup` | After verifying their email, the voter adds a phone number and confirms it with a code, then logs in again |
| Sign in | `/login` → `/verify` | The password is checked first; Firebase completes the sign-in only after the SMS code is accepted |
| Time limit | `/verify` | The code must be entered within **60 seconds** of the password being accepted. A countdown is shown; when it reaches zero the pending login is discarded, the user is signed out and returned to `/login?reason=mfa-timeout` |
| Voter pages | `/voter/*` | Each page checks that the Firebase ID token records a completed second factor (`sign_in_second_factor`). A session without one is signed out and sent to `/login?reason=mfa-required`. `/voter/help` holds no personal data and is open to all |

The 60-second limit and the voter-page checks run in the browser; Firebase
handles the code check itself. The API accepts ID tokens with up to 10 seconds
of clock skew, so a server clock slightly behind Google's does not reject a
token issued moments earlier.

Firebase setup: SMS multi-factor authentication requires Firebase
Authentication with Identity Platform, with SMS multi-factor enabled under
Authentication → Sign-in method. For demos, add **test phone numbers** there:
they never send an SMS and always accept their fixed code. Real numbers
receive real messages, which need the Blaze plan and are charged per SMS.

Staff API protection additionally uses Firebase ID-token verification, the
server-side staff record and role, recent authentication, and the IP
allowlist.

## Account lockout

Voter and staff accounts are locked after **3 consecutive failed sign-in
attempts**: a wrong password on `/login` or a wrong SMS code on `/verify`.

| Consecutive failures | Lock |
| --- | --- |
| 3 | 5 minutes |
| 6 | 10 minutes |
| 9 | 20 minutes |
| 12 | 40 minutes |
| 15 and every 3 after | 60 minutes (maximum) |

| Endpoint | Purpose |
| --- | --- |
| `POST /api/auth/lockout/check` | Before signing in: is this email locked, and for how long |
| `POST /api/auth/lockout/failure` | Report a wrong password or SMS code; locks on every 3rd |
| `POST /api/auth/lockout/success` | Reset the count; needs the new sign-in's Firebase ID token |

- **Enforcement:** a lock disables the Firebase account, so Firebase refuses the
  sign-in even if the login page is bypassed. The account is re-enabled by the
  first check or report after the lock ends. Accounts that were already
  disabled (for example staff awaiting approval, or staff deactivated during the
  lock) stay disabled.
- **IP-based rate limiting:** `check` allows 30 requests per minute per IP
  address, `failure` and `success` 10. Over the limit, the login page asks the
  user to wait a minute.
- **No account discovery:** responses are the same whether or not an account
  exists for the email. Lock records are keyed by a hash of the email (see
  [firestore-schema.md](./firestore-schema.md#authlockoutsemailhash)).
- **Audit:** every lock is written to the audit log as `auth.lockout`.
- **Limitation:** failures are reported by the login and verify pages, because
  sign-in itself happens between the browser and Firebase. Attempts made
  directly against Firebase, bypassing these pages, are not counted; Firebase's
  own throttling (`auth/too-many-requests`) still applies to them.

## Inactivity timeout

Voter and staff sessions end after **2 minutes of inactivity**, enforced in the
browser and on the server.

| Where | What happens |
| --- | --- |
| Browser ([components/inactivityguard.tsx](./components/inactivityguard.tsx)) | On every `/voter` and `/staff` page, clicks, typing, scrolling and pointer movement count as activity, shared across open tabs. After 1:30 a warning ("Are you still there?") counts down; at 2:00 the user is signed out and sent to `/login?reason=session-timeout` |
| API ([backend/sessions.py](./backend/sessions.py)) | Every signed-in endpoint requires an `X-Session-Token`: a JWT signed by the API that expires 2.5 minutes after it was issued and is renewed while the user is active. An expired token is refused, and a sweep every 30 seconds ends sessions nobody renewed |

| Endpoint | Purpose |
| --- | --- |
| `POST /api/session/start` | Exchange a Firebase ID token for a session token. Allowed only within 5 minutes of signing in, so an ended session cannot be replaced without signing in again |
| `POST /api/session/renew` | Extend the session; called at most every 30 seconds while the user is active |
| `POST /api/session/end` | Close the session on sign-out |

- **Ending an idle session** revokes the user's Firebase refresh tokens, so the
  API rejects their existing ID tokens and Firebase stops issuing new ones. This
  signs the user out on all their devices. Each timeout is audited as
  `auth.sessionTimeout`.
- **Why 2.5 minutes on the server:** the browser renews at most every 30
  seconds, so the server's record of activity can be up to 30 seconds old. The
  browser always ends the session first; the server guarantees it ends.
- **Signing key:** generated automatically the first time the API needs it and
  stored in Firestore at `config/sessionSigning`, which only the API can read.
  There is nothing to configure, and restarts keep sessions valid. To replace
  the key, delete that document and restart the API; every session then ends.
  `SESSION_IDLE_SECONDS` in `backend/.env` (default `150`) sets the server limit.
- **Limitation:** voter pages read Firestore directly. Firestore cannot check
  the session, so a tampered page could still read the voter's own data until
  their current Firebase ID token expires (at most 1 hour after the session
  ended). The voter registration endpoint uses its own sign-in check and does
  not require a session.

## Data and security notes

Firestore structure is documented in [firestore-schema.md](./firestore-schema.md).
Apply [firestore.rules](./firestore.rules) and required composite indexes before
connecting a live Firebase project. Browser-side staff checks are UX only;
authorization is enforced by FastAPI.
