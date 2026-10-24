# A3 Secure Software Systems

An academic e-voting prototype with a Next.js frontend and a Python FastAPI staff API.

## Run the frontend

Set the Firebase client configuration in `.env.local`, including:

```dotenv
NEXT_PUBLIC_FIREBASE_API_KEY=...
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=...
NEXT_PUBLIC_FIREBASE_PROJECT_ID=...
NEXT_PUBLIC_FIREBASE_APP_ID=...
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Then run:

```powershell
npm install
npm run dev
```

## Run the staff API

Install Python dependencies and configure `backend/.env` (do not commit credentials):

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json
FIREBASE_PROJECT_ID=a3-voting-system-dev
ALLOWED_ORIGINS=http://localhost:3000
```

Start the API from the repository root:

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload
```

If .env file is not detected:

```powershell
python -m uvicorn backend.main:app --reload --env-file backend\.env
```
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

## Results, receipts and verification

| Endpoint | Who | Purpose |
| --- | --- | --- |
| `POST /api/voter/ballots` | Enrolled voter (Firebase token) | Records House and Senate ballots and returns a one-time receipt code |
| `POST /api/admin/elections/{id}/results/publish` | Admin | Counts a finalised election and freezes the result package |
| `GET /api/public/results` | Anyone | Latest published results and their SHA-256 fingerprint |
| `GET /api/public/results/package.json` | Anyone | Downloadable result package (the exact published bytes) |
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
3. Make sure `.env.local` contains `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`.

#### 2. Seed a demo election

`backend/seed_demo_results.py` creates a demo election, enrols demo voters,
casts their ballots through the same code as `POST /api/voter/ballots`,
finalises the election and publishes the results through the same code as the
admin publish endpoint. It prints sample receipt codes and the published
SHA-256 fingerprint; keep that output for the checks below.

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
.venv\Scripts\python -m uvicorn backend.main:app --reload --env-file backend\.env
npm run dev
```

`http://127.0.0.1:8000/health` should return `{"status":"ok"}`.

#### 4. Published Results: `/results`

| Check | Expected result |
| --- | --- |
| Open the page before results are published (`--skip-publish`) | "No results have been published yet" |
| Open the page after publishing | Summary cards (status Final, ballots cast, turnout, published time), then one table per House division and Senate state |
| Compare the "Published SHA-256 fingerprint" with the seed output | Identical |
| Click "Download result package (JSON)" | A file named `result-package-<electionId>.json` downloads |
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
| Verify the untouched file with one character of the fingerprint changed | Fails "Fingerprint matches" |
| Choose a non-JSON file, or a file over 2 MB | A clear error, and nothing is checked |
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

## Authentication-code demo warning

The six-digit authentication code in `/verify` is a demo placeholder: any six
digits are accepted. It does **not** provide real second-factor security and
must not be used to protect a production account. Staff API protection instead
uses Firebase ID-token verification, the server-side staff record and role,
recent authentication, and the IP allowlist.

## Data and security notes

Firestore structure is documented in [firestore-schema.md](./firestore-schema.md).
Apply [firestore.rules](./firestore.rules) and required composite indexes before
connecting a live Firebase project. Browser-side staff checks are UX only;
authorization is enforced by FastAPI.
