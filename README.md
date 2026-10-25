# A3 Secure Software Systems

An academic e-voting prototype with a Next.js frontend and a Python FastAPI staff API.

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
| TLS 1.3 with a cipher outside the TLS 1.3 AEAD suites | Closed | `cipherNotAllowed` |
| TLS 1.3 with an allowed cipher | Passed to Next.js | — |

Rejections are printed to the console and appended as JSON lines to
`logs/tls-security.log`. Override the defaults with `TLS_CERT_FILE`,
`TLS_KEY_FILE`, `TLS_LOG_FILE`, `HOST` and `PORT`.

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

## Results, receipts and verification

| Endpoint | Who | Purpose |
| --- | --- | --- |
| `POST /api/voter/ballots` | Enrolled voter (Firebase token) | Records House and Senate ballots and returns a one-time receipt code |
| `POST /api/admin/elections/{id}/results/publish` | Admin | Counts a finalised election and freezes the result package |
| `POST /api/admin/elections/{id}/phase` with `{"to": "finalised"}` | Admin | Finalises only if voters marked voted, House ballots, Senate ballots and receipts all match (R-05); a mismatch is refused and logged |
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
3. Make sure `.env.local` contains `NEXT_PUBLIC_API_BASE_URL=https://127.0.0.1:8000`.

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

## Data and security notes

Firestore structure is documented in [firestore-schema.md](./firestore-schema.md).
Apply [firestore.rules](./firestore.rules) and required composite indexes before
connecting a live Firebase project. Browser-side staff checks are UX only;
authorization is enforced by FastAPI.
