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
FIREBASE_PROJECT_ID=your-firebase-project
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
