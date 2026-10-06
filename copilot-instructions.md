# GitHub Copilot Instructions: AEC Electronic Voting Platform

> Place this file at `.github/copilot-instructions.md` in the repository root.
> Copilot reads it automatically for every chat and code suggestion in this repo.

## 1. Project context

We are building a digital voting platform for **Australian federal elections**, replacing paper balloting with electronic balloting. It supports:

- Voting on **polling-station terminals** (approx. 7,000 web terminals, scalable to 40,000).
- **Online voting from home** for citizens within Australia.
- **Overseas voting** only from Australian diplomatic missions (whitelisted IP ranges).
- Voter enrolment, enrolment checks, and address updates.
- Candidate management by state AEC Commissioner's delegates.
- House of Representatives (preferential) and Senate (above/below the line) ballots.
- Tallying, Senate election-order calculation, recounts with manual candidate exclusion, and result export to external systems.
- Ingestion of scanned paper ballots for the final count.

This is **security-critical software**. When in doubt, choose the more secure, more auditable, more explicit option, even if it is more verbose. Never trade security for convenience.

## 2. Technology stack (do not deviate without approval)

| Layer | Choice |
|---|---|
| Language | Python 3.12+ with full type hints |
| Backend | Django 5.x LTS + Django REST Framework |
| Frontend (voter and staff) | Server-rendered Django templates + HTMX + minimal vanilla JS / Alpine.js, strict CSP. **No React/Vue/npm-heavy frameworks in the voter UI.** |
| Database | PostgreSQL 16+ (separate databases per data class, see §4) |
| Cache / counters | Redis (rate limiting, lockouts, session inactivity timers) |
| Background jobs | Celery |
| Crypto | `cryptography` library and PyNaCl only. **Never implement your own crypto primitives.** |
| MFA | `django-otp` (TOTP) and `py_webauthn` (passkeys) |
| Lockout | `django-axes` (customised) plus Redis throttling |
| Versioning | `django-simple-history` |
| Testing | `pytest`, `pytest-django`, `hypothesis`, `factory_boy`, `coverage` |
| Static analysis | `ruff`, `mypy --strict`, `bandit`, `pip-audit`, `semgrep` |
| Packaging | `uv` or `pip-tools` with **hash-pinned** requirements |
| Containers | **Docker** (multi-stage images) + Docker Compose; Gunicorn app server; Nginx reverse proxy (see §7) |

Add dependencies sparingly. Every new dependency needs justification in the PR description, must be actively maintained, and must pass `pip-audit`.

## 3. Repository layout

Monorepo with **independently deployable services**. Each service is its own Django project with its own settings, database credentials, and Dockerfile. Services communicate only over authenticated internal APIs (mTLS), never by importing each other's models.

```
.
├── .github/
│   ├── copilot-instructions.md
│   └── workflows/                  # CI: lint, type-check, test, bandit, pip-audit
├── libs/
│   ├── evcrypto/                   # Crypto abstraction layer (the ONLY place crypto is called)
│   ├── evcommon/                   # Shared types, constants, DTOs (no business logic)
│   └── evaudit_client/             # Client for writing to the audit service
├── services/
│   ├── enrolment/                  # Voter roll, enrolment, address updates, eligibility
│   │   └── Dockerfile              # Every service has its own Dockerfile (+ .dockerignore)
│   ├── authn/                      # Authentication, MFA, lockout, session control
│   ├── ballot/                     # Ballot issuing, casting, proof of submission
│   ├── candidates/                 # Candidate records, two-person approval, versioning
│   ├── tally/                      # Counting, Senate calc, recounts, reconciliation (isolated)
│   ├── audit/                      # Append-only signed hash-chained logs
│   └── export_gateway/             # Results export (mTLS, signed bundles)
├── compose.yaml                    # Base Compose file (all services, networks, volumes)
├── compose.dev.yaml                # Dev overrides (hot reload, synthetic data, exposed ports)
├── compose.prod.yaml               # Prod overrides (secrets, limits, replicas, read-only FS)
├── Makefile                        # make up / down / test / migrate / scan / seed-dev
├── deploy/
│   ├── nginx/                      # nginx.conf (TLS 1.3, security headers, rate limits, IP allow-list)
│   ├── postgres/                   # init scripts: roles, grants, per-DB config, pg_hba.conf
│   ├── certs/README.md             # How internal CA / mTLS certs are provisioned (no real certs in git)
│   ├── monitoring/                 # Prometheus, Grafana, alert rules, log pipeline
│   └── scripts/                    # entrypoints, healthchecks, backup/restore
├── docs/                           # Architecture, threat model, requirement traceability
└── tests/                          # Cross-service integration and security tests
```

Each service has the structure: `config/` (settings split into `base.py`, `dev.py`, `prod.py`), `apps/<app>/{models,services,selectors,api,views,forms,tests}`, `templates/`.

### Layering rules
- `views`/`api` (thin) → `services` (business logic, write operations) → `models`.
- `selectors` contain read queries. No business logic in views, serializers, or models' `save()`.
- Cross-service calls go through a typed client class in `libs/`, never raw `requests` scattered around.

## 4. Database design rules (PostgreSQL)

Use **separate databases (or clusters) with separate DB roles** per data class. Configure Django `DATABASES` and a **database router** so models only touch their own database.

| Database | Contents | Notes |
|---|---|---|
| `identity_db` | Voter roll, PII, voting status flags | PII fields encrypted at field level |
| `ballot_db` | Anonymised ballots | **No foreign key, ID, or column that can link to a voter** |
| `audit_db` | Admin/security logs | Append-only; role has `INSERT`/`SELECT` only, no `UPDATE`/`DELETE`/`TRUNCATE` |
| `proof_db` | Proofs of submission (retained 7+ years) | Supports crypto-shredding for lawful destruction |
| `candidate_db` | Candidates, versions, approvals | History via `django-simple-history` |

Rules:
- Always use the Django ORM or parameterised queries. **Never** build SQL with f-strings, `%`-formatting, or concatenation. Never use `.extra()`; avoid `.raw()` unless reviewed, and when used, always pass params.
- Wrap multi-step state changes in `transaction.atomic()`. Use `select_for_update()` when changing voter status to prevent races (double voting).
- Add explicit DB constraints (`UniqueConstraint`, `CheckConstraint`, `NOT NULL`) in addition to validation in Python.
- Use UUIDv4 primary keys for voters and ballots (no sequential IDs that leak ordering or counts).
- Never store timestamps on ballots at a precision that allows correlation with the voter's session. Round to the election-day hour or store none.
- All migrations must be reviewed; never edit applied migrations.

## 5. Security requirements and how to implement them

Every requirement below must be traceable. When writing code for one, add a comment `# R-xx` at the relevant place and update `docs/traceability.md`.

### R-01: Encryption at rest (AES-256, key rotation every 90 days)
- Encrypt all vote data, PII, and credentials at the field level with **AES-256-GCM** via `libs/evcrypto`. Use a unique random 96-bit nonce per encryption; never reuse a nonce.
- Use **envelope encryption**: data keys (DEKs) wrapped by a key-encryption key (KEK) held in a KMS/HSM. Rotation re-wraps DEKs.
- Store a `key_id`/`key_version` alongside every ciphertext so old and new keys can coexist during rotation.
- Provide a Celery beat task that rotates keys every 90 days and a management command to re-encrypt/re-wrap data.
- Passwords: Django's Argon2 hasher (`argon2-cffi`). Never store or log plaintext secrets.
- Keys, secrets, and connection strings come from environment/secret manager. **Never hard-code or commit secrets**, never log them.

### R-02: TLS 1.3 only
- Terminate TLS at the Nginx reverse-proxy container with `ssl_protocols TLSv1.3;`. Plain HTTP must be rejected and logged, not redirected silently for API endpoints.
- Django settings: `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS` (≥ 1 year), `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`, `SECURE_PROXY_SSL_HEADER`.
- Internal service-to-service traffic also uses TLS 1.3 (mTLS).
- Database connections use `sslmode=verify-full`.

### R-03 and R-04: Voter/ballot separation and voting status
Implement this exact flow in the `ballot` and `enrolment` services:

1. Voter authenticates (see R-10). `enrolment` verifies enrolment and eligibility.
2. In one atomic transaction with `select_for_update()`, `enrolment` checks status is `NOT_VOTED`, sets it to `VOTING`, and records the audit event. If status is `VOTING` or `VOTED`, **reject** and log.
3. `enrolment` issues a **single-use, short-lived, unlinkable ballot token** (random, signed by the service, containing election/division scope but **no voter ID**). Use a blind-signature or token-issuance scheme behind the `evcrypto` interface so identity is not recoverable from the token.
4. The voter submits the ballot to the `ballot` service **with the token only**. The ballot service has no access to `identity_db`.
5. The ballot service validates and burns the token, stores the encrypted ballot, signs it, and generates the proof of submission (R-06).
6. On confirmation, `enrolment` sets status to `VOTED`. Handle failure/timeout: a session stuck in `VOTING` is resolved by a documented, audited staff procedure, never by silently resetting.

Hard rules: no log line, exception message, or metric may contain both voter identity and ballot content or ballot ID. Do not pass voter IDs to the ballot service, even in headers.

### R-05: Reconciliation
- Implement a `reconcile_election` service function and Celery task comparing the count of `VOTED` voters against the count of stored ballots per election and division. Output a signed reconciliation report; mismatches raise a high-severity alert (R-19).
- Also verify that no voter is flagged `VOTED` without a corresponding token redemption (false flag detection) using counts and token-redemption records that carry no ballot content.

### R-06: Proof of submission and 7-year retention
- For every ballot produce a **signed receipt**: `hash(ballot_ciphertext || ballot_nonce)`, election ID, and a coarse timestamp, signed with the election signing key. The receipt contains no voter identity.
- Append receipt hashes into a **Merkle tree**, publish periodic signed tree roots so any party can independently verify inclusion.
- Retention: a Celery task enforces a minimum 7-year retention; after expiry, destroy records via **crypto-shredding** (destroy the wrapping keys) plus hard delete, and write an audit entry. Never delete earlier than the lawful period.

### R-07: Availability and DDoS
- Services are stateless containers (state in PostgreSQL/Redis), horizontally scalable (`deploy.replicas` / `--scale`), with `/healthz` and `/readyz` endpoints used by Docker healthchecks. A single Docker host cannot deliver 99.9%: production runs the same images across multiple hosts (Docker Swarm or equivalent) with a replicated PostgreSQL (Patroni or managed HA).
- Use connection pooling (PgBouncer), query timeouts, `select_related`/`prefetch_related`, and avoid N+1 queries. Add idempotency keys on ballot submission.
- Rate limiting and request size limits at the edge and in DRF throttles.
- Include load-test scripts (Locust/k6) targeting 40,000 concurrent terminals.

### R-08: Signed immutable audit logs
- All admin actions (candidate changes, exclusion decisions, recounts, enrolment, staff logins, system/software management access) are written through `evaudit_client` to the `audit` service.
- Each entry: `id`, UTC timestamp, actor, action, target, details (no secrets/PII beyond what is necessary), `prev_hash`, `entry_hash`, `signature`. Hash-chain entries and sign with Ed25519 via `evcrypto`.
- Provide a `verify_chain` management command and API that walks the chain and verifies signatures.
- Audit-write failure must **fail the action** (no unaudited admin operations).

### R-09: Result export
- Only the `export_gateway` service may send results externally, via dedicated endpoints requiring **mTLS plus an authenticated client identity**.
- Results are exported as a bundle with a SHA-256 manifest and a digital signature. Include a verification endpoint/tool for recipients.
- Log every export/transfer end to end (request, bundle hash, recipient, outcome).

### R-10: Two-factor authentication (< 1 minute)
- Factor 1: credential (e.g. voter ID/knowledge-based credential or passcode). Factor 2: TOTP or WebAuthn/passkey, or a one-time code via a secure channel.
- A ballot token is issued **only after both factors succeed**. Enforce a 60-second maximum authentication-attempt window server-side (signed challenge with expiry) and measure it.
- Use constant-time comparisons (`hmac.compare_digest`). Generic error messages (don't reveal which factor failed).

### R-11: Lockout and rate limiting
- 3 consecutive failures → lock 5 minutes; then double the period every 3 further consecutive failures, capped at 1 hour (5, 10, 20, 40, 60, 60, …). Reset the counter on success.
- Log events from the 3rd failure onward. Polling staff can manually override (audited, role-restricted).
- Implement as a pure, unit-tested function `compute_lockout(consecutive_failures) -> timedelta` backed by Redis counters. Also apply generic IP/identity rate limiting.

### R-12 and R-18: RBAC, MFA for admin, permission change review
- Roles: `voter`, `delegate`, `staff`, `admin` (extend only via ADR). Use Django groups/permissions with **least privilege**; deny by default. Every view/API must declare required permission explicitly; add a test that fails if any endpoint lacks a permission class.
- Admin access requires **named individual accounts** (no shared accounts) and MFA before any admin function.
- Any permission/role/account-config change creates a `PermissionChangeRequest` that must be reviewed; granting above the minimum requires a recorded approver (different from the requester). All steps are audited.
- Unauthorised attempts return 403 and are logged (target: 100% rejection; write tests proving it).
- Provide a management command that exports a role/permission report to support quarterly access audits.

### R-13: Overseas access restriction
- Access from outside Australia is allowed only from whitelisted IP ranges of Australian diplomatic missions. Enforce at the WAF/proxy **and** in a Django middleware as defence in depth (whitelist loaded from config, deny by default).
- Blocked attempts are logged and an alert is dispatched within 3 minutes (Celery task with a SLA test).
- Never trust `X-Forwarded-For` blindly; only accept it from configured trusted proxies.

### R-14: Candidate management
- Only users with the `delegate` role may create/modify/delete candidate records.
- Any modification creates a **pending change** requiring approval from **at least two authorised delegates** (the proposer cannot be an approver); apply only after approval.
- Version everything with `django-simple-history`; provide a **rollback** operation that can restore a prior version within 12 hours, audited.
- Candidate data includes party grouping and the order within the group (needed for Senate ballot layout).

### R-15: Ballot validity and integrity before counting
- Every ballot (including scanned paper ballots matched against the original form) is signature-verified before counting. Failures are **excluded from the count**, flagged, and routed to an administrator/independent audit review queue. Results cannot be finalised while any flagged ballot is unresolved.
- Scanned paper ballot ingestion: store the image hash, the digitised preference data, and a link to the source form record; verify the match, and record who digitised and verified.

### R-16: Input sanitisation
- Validate every user-controlled input with Django Forms or DRF serializers using strict allow-list validation (type, length, charset, range). Reject, don't "fix".
- Rely on auto-escaping in templates; **never** use `|safe`, `mark_safe`, `autoescape off`, or `format_html` with untrusted input. No `eval`/`exec`/`pickle` on user data. Validate file uploads (type by content, size) and never serve uploads from the app origin.
- Strict CSP (no inline scripts, nonce-based if required), `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`.

### R-17: Session inactivity
- Voter and admin sessions lock/terminate after 2 minutes of inactivity (configurable constant). Enforce **server-side** (Redis-backed last-activity timestamp), with a client-side countdown for UX only.
- Bind sessions to the authentication context, rotate session ID on login/privilege change, `HttpOnly`, `Secure`, `SameSite=Strict` cookies. Ballot-in-progress timeouts must not lose or duplicate votes.

### R-19: Monitoring and anomaly detection
- Emit structured JSON logs and Prometheus metrics (login failures, lockouts, rejected tokens, invalid ballots, 403s, export events).
- Implement threshold/anomaly rules (e.g. spikes in failures or invalid ballots) that trigger alerts. Logs must never include secrets, PII, or ballot content.

### R-20: Modularity and crypto agility
- All cryptography goes through `libs/evcrypto` interfaces (`Encryptor`, `Signer`, `Hasher`, `KeyProvider`, `TokenIssuer`) with algorithm identifiers stored alongside outputs. Swapping an algorithm must require changing config/an implementation, not business logic.
- Business logic depends on interfaces (dependency injection), not concrete implementations. Services don't import each other's models. Keep at least 80% of subsystems upgradeable without touching core voting logic, and document this in `docs/architecture.md`.

## 6. Domain rules (voting logic)

Implement counting in the isolated `tally` service as **pure, deterministic, well-tested Python** (no I/O inside algorithms), and **verify details against the Commonwealth Electoral Act 1918 and current AEC rules; make the following configurable where they may change**.

### House of Representatives
- One member per electoral division, **full preferential** (instant-runoff) counting: count first preferences, exclude the lowest candidate, redistribute to next valid preference, repeat until a candidate has an absolute majority.
- Handle exhausted ballots and formality rules (including any savings provisions) via a configurable `FormalityPolicy`.
- Define a documented, deterministic tie-break procedure (and flag for manual/legal resolution, never an arbitrary random choice without audit).

### Senate
- Voters in each state elect 12 senators (6 in a half-Senate election, configurable), the ACT and NT elect 2 each. Make seats a parameter of the election, not a constant.
- Ballot supports **above the line (groups)**, **below the line (candidates)**, or **both**. Respect party group ordering and each candidate's order within the group. Use a configurable formality policy for minimum preferences.
- Count by **single transferable vote with a Droop quota** and fractional transfer values. Confirm the exact transfer method against current legislation. Use `fractions.Fraction` or `decimal.Decimal`, **never floats**, for transfer values and quotas.
- Support **manual exclusion of candidates** by the state's AEC Commissioner's delegate(s) for recounts ordered by the High Court sitting as the Court of Disputed Returns. Recount = re-run the algorithm from the verified ballot set with the exclusion list; log inputs, exclusion decisions, approvers, and outputs (R-08).
- Output a full, step-by-step **count log** (exclusions, transfers, quotas, elected order) so the result is independently verifiable.

### Enrolment
- AEC staff can register citizens; eligible citizens can check status and self-enrol; enrolled voters can update their address. Eligibility validation (citizenship, age 18+, enrolled in the right division, not already voted) runs before any ballot request.
- Overseas voting only at diplomatic missions (R-13); in-Australia citizens can use polling stations or online.

## 7. Docker deployment

The whole platform must be **built, run, tested, and deployed as Docker containers**. Nothing may require manual installation on a host beyond Docker itself. When generating Docker/Compose files, follow these rules.

### 7.1 Images (one Dockerfile per service)
- **Multi-stage builds**: a `builder` stage installs dependencies from the hash-pinned lockfile (`pip install --require-hashes`) into a virtualenv/wheels; the `runtime` stage copies only the result. No compilers, git, or pip cache in the final image.
- Base image: `python:3.12-slim`, **pinned by digest** (`FROM python:3.12-slim@sha256:...`). Rebuild regularly to pick up OS patches.
- Run as a **non-root user** with a fixed UID/GID. Never `USER root` in the runtime stage.
- Set `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`. Run `collectstatic` at build time.
- Serve with **Gunicorn** (never `runserver`) using an explicit worker/thread config from environment variables. Use `exec` form for `ENTRYPOINT`/`CMD` so signals reach the process (graceful shutdown).
- Include a `HEALTHCHECK` that hits `/healthz` (no `curl` dependency; use a tiny Python script).
- Every service has a `.dockerignore` excluding `.git`, `.env*`, tests, docs, `__pycache__`, local DB dumps, and any key/cert material.
- **No secrets in images**: no `ENV SECRET_KEY=...`, no `COPY` of `.env`, certs, or keys, and no secrets passed via `ARG` (they persist in image history).
- Label images (`org.opencontainers.image.*`) with version and git SHA. Tag with immutable versions (git SHA / semver); **never deploy `latest`**.
- Lint Dockerfiles with `hadolint`; scan images with `trivy` (fail CI on HIGH/CRITICAL); generate an SBOM (`syft`); sign images (`cosign`).

### 7.2 Compose topology
Use `compose.yaml` as the base with `compose.dev.yaml` and `compose.prod.yaml` overrides (`docker compose -f compose.yaml -f compose.prod.yaml up -d`). Containers:

| Container | Notes |
|---|---|
| `proxy` (Nginx) | Only container publishing host ports (443; 80 only to reject and log). TLS 1.3 only, security headers, rate limiting, overseas IP allow-list (R-13) |
| `enrolment`, `authn`, `ballot`, `candidates`, `tally`, `audit`, `export-gateway` | Gunicorn/Django, one container type per service, scalable replicas |
| `celery-worker-*`, `celery-beat` | Same image as their service with a different command; beat runs as exactly **one** replica |
| `identity-db`, `ballot-db`, `audit-db`, `proof-db`, `candidate-db` | Separate PostgreSQL containers (or clusters), each with its own volume, credentials, and `pg_hba.conf` |
| `pgbouncer-*` | Connection pooling in front of busy databases |
| `redis` | Auth enabled, TLS where supported, no persistence of sensitive data beyond counters/timers |
| `migrate-*` | **One-shot jobs** that run `manage.py migrate` per service/database, then exit. App containers `depends_on` them with `condition: service_completed_successfully`. Never run migrations inside the app entrypoint across multiple replicas |
| `prometheus`, `grafana`, log pipeline (e.g. Loki/OpenSearch) | Monitoring and alerting for R-19 |

### 7.3 Network segmentation (this enforces R-03)
Define multiple Compose networks, marking backend networks `internal: true` (no outbound internet):
- `edge`: `proxy` only (plus the services it fronts).
- `svc-net`: service-to-service mTLS traffic.
- One private network **per database** (`identity-net`, `ballot-net`, `audit-net`, `proof-net`, `candidate-net`) attached only to the services allowed to reach that database.
- **The `ballot` and `tally` containers must never be attached to `identity-net`.** Treat this as a security invariant and add a CI test that parses the resolved Compose config (`docker compose config`) and fails if it is violated.
- Databases and Redis **never publish host ports** in prod (use `expose`, not `ports`).
- `export-gateway` is the only container with a controlled outbound route to external systems.

### 7.4 Secrets and configuration
- Config comes from environment variables (12-factor). Secrets come from **Docker secrets** (mounted at `/run/secrets/*`) or a secrets manager. Support the `*_FILE` convention (e.g. `POSTGRES_PASSWORD_FILE`, `DJANGO_SECRET_KEY_FILE`) via a small helper in `config/base.py`.
- `.env` files are allowed in **dev only**, must be git-ignored, and `.env.example` must contain only dummy values. Production Compose files must not reference `.env`.
- Encryption keys (R-01) and signing keys (R-06/R-08/R-15) live in the KMS/HSM; containers receive only short-lived access credentials or wrapped keys. Never bake keys into images or volumes.
- mTLS certificates (service-to-service and `export-gateway`) are provisioned as secrets from an internal CA with short lifetimes and automated renewal. Document the process in `deploy/certs/README.md`.

### 7.5 Runtime hardening (apply in `compose.prod.yaml`)
```yaml
x-hardened: &hardened
  read_only: true                 # read-only root filesystem
  tmpfs: [/tmp]                   # writable scratch only where needed
  cap_drop: [ALL]
  security_opt: ["no-new-privileges:true"]
  restart: unless-stopped
  logging:
    driver: json-file
    options: { max-size: "10m", max-file: "5" }
```
- Apply `<<: *hardened` to all app containers; add `cap_add` only with a written justification.
- Set `mem_limit`/`cpus` (or `deploy.resources`) and `pids_limit` on every container.
- Use `healthcheck` plus `depends_on: condition: service_healthy` for ordering; the app must still retry DB connections on startup.
- Never use `privileged: true`, host networking, or mount the Docker socket into any container. Never bind-mount source code in prod.
- Volumes: named volumes for PostgreSQL/Redis data on **encrypted host storage**; one volume per database. Provide backup/restore scripts (`deploy/scripts/`) with encrypted backups and a documented, tested restore. The audit and proof volumes need the strictest backup/retention handling (R-06, R-08).
- Logs go to **stdout/stderr as structured JSON**, passed through the redaction filter (no PII, secrets, or ballot content), and shipped to the monitoring pipeline. Containers must not write log files to disk.
- Handle `SIGTERM` gracefully: Gunicorn graceful timeout must allow in-flight ballot submissions to finish. Ballot submission endpoints must be idempotent so a restart never loses or duplicates a vote.

### 7.6 Development workflow in Docker
- `make up` starts the full stack with synthetic seed data (`make seed-dev`); `make test` runs pytest **inside containers**; `make migrate`, `make scan`, `make down`.
- `compose.dev.yaml` may enable hot reload, bind-mount source, expose ports, and use self-signed certs. It must **never** be used for production, and prod settings must refuse to start if `DEBUG=True` or dev TLS settings are detected.
- Integration tests use the same Compose topology (or Testcontainers) so tests run against real PostgreSQL and Redis, never SQLite.
- Dev seed data is synthetic only. Never copy real electoral roll data into any image, volume, or fixture.

### 7.7 CI/CD
- GitHub Actions: lint → type-check → unit tests → build images → `hadolint` and `trivy` → SBOM → push to registry → `cosign sign` → integration tests against the built images → `docker compose config` validation (network-segmentation and no-published-DB-ports checks).
- Deploy only signed, scanned, immutable-tag images; pull by digest in production. Roll back by redeploying the previous digest.

## 8. Coding standards

- Type-hint everything; `mypy --strict` must pass. Use `dataclasses`/Pydantic or typed DTOs for service boundaries.
- Follow PEP 8 via `ruff`. Small functions, explicit names, docstrings on public functions (state the requirement IDs they satisfy).
- Raise specific domain exceptions (`AlreadyVotedError`, `LockoutActiveError`, …) and translate them at the API boundary. Never leak stack traces or internals to clients (`DEBUG = False` outside dev).
- No `print`; use the structured logger with a **redaction filter** for PII/secrets.
- Prefer immutability and pure functions in tally and crypto code.
- Settings: never put secrets in settings files; use environment variables; `prod.py` must fail to start if insecure settings are detected (e.g. `DEBUG=True`, weak `SECRET_KEY`, missing TLS settings). Run `manage.py check --deploy` in CI.
- UI: accessible (WCAG 2.1 AA), keyboard-navigable, clear language, works without heavy JavaScript. Ballot paper layouts must mirror the real AEC ballots in ordering and clarity, with confirmation and review steps before submission.

## 9. Testing requirements

For every feature, generate tests alongside the code:

- **Unit tests** for services and algorithms (pytest). Aim for ≥ 90% coverage in `tally`, `evcrypto`, `authn`, `ballot`.
- **Property-based tests** (`hypothesis`) for counting algorithms (e.g. quota invariants, elected count = seats, transfer value conservation) and for `compute_lockout`.
- **Security tests**: double-voting attempts (including concurrent requests), replayed/forged/expired ballot tokens, SQL injection and XSS payloads on every input field, IDOR/permission bypass on every endpoint, non-TLS requests, non-whitelisted overseas IPs, session timeout, lockout sequence, audit-chain tampering detection, tampered ballot signature rejection.
- **Unlinkability test**: assert that no table, log, or API response in the ballot path can link a voter to a ballot.
- **Integration tests** across services using test containers (PostgreSQL, Redis).
- **Known-answer tests** for the Senate/House counts using published AEC examples and hand-computed cases.
- Tests must never use real voter data. Use `factory_boy` and synthetic data only.

## 10. Things Copilot must NOT do

- Do not invent crypto, hashing, randomness, or token schemes. Use `evcrypto`, `secrets`, and vetted libraries. Never use `random` for anything security-related; never use MD5/SHA-1, DES, ECB mode, or RSA < 3072 bits.
- Do not log, print, or return PII, credentials, tokens, keys, or ballot contents.
- Do not add any link between voter identity and ballot data, directly or via timestamps, sequential IDs, session IDs, IPs, or user agents.
- Do not disable CSRF, TLS verification (`verify=False`), CSP, or auth checks, even in tests or "temporary" code.
- Do not use `DEBUG = True`, `ALLOWED_HOSTS = ['*']`, or `csrf_exempt` outside of explicitly justified, reviewed cases.
- Do not add third-party scripts, CDNs, analytics, or trackers to voter-facing pages. Serve all static assets from our own origin.
- Do not use floating point for vote counting or transfer values.
- Do not add UPDATE/DELETE paths for audit logs or ballots.
- Do not write code that bypasses two-person approval or the audit service.
- Do not hard-code secrets, IP whitelists, seat counts, or election parameters.
- Do not run containers as root, use `privileged`, host networking, the Docker socket, or the `latest` tag, and do not publish database/Redis ports in prod.
- Do not put secrets in Dockerfiles, `ENV`, `ARG`, Compose files, or images, and do not attach `ballot`/`tally` containers to the identity network.
- Do not use `runserver`, SQLite, or bind-mounted source code outside `compose.dev.yaml`.

## 11. Suggested build order

When asked to start or continue implementation, work in this order and keep each step shippable and tested:

1. Repo scaffolding, CI (ruff, mypy, bandit, pip-audit, pytest), settings split, per-service Dockerfiles, `compose.yaml` with segmented networks, per-database PostgreSQL containers and Redis, plus the `Makefile`.
2. `libs/evcrypto` (interfaces + AES-256-GCM, Ed25519, hashing, envelope encryption, key rotation) with tests.
3. `audit` service (hash-chained signed log + verifier) and `evaudit_client`.
4. `authn` (users, RBAC, MFA, lockout, session inactivity).
5. `enrolment` (voter roll, eligibility, status flags, address update).
6. `candidates` (CRUD, two-person approval, versioning, rollback).
7. `ballot` (token issuing, casting, signatures, receipts, Merkle tree).
8. `tally` (House IRV, Senate STV, recount with exclusions, reconciliation, scanned-ballot validation).
9. `export_gateway` (mTLS, signed bundles).
10. Nginx proxy hardening (TLS 1.3, WAF/IP allow-list), `compose.prod.yaml` hardening and secrets, monitoring/alerting containers, image scanning/signing in CI, backup/restore scripts, load tests, requirement traceability matrix.

## 12. Pull request checklist (Copilot should remind about this when generating PRs)

- [ ] Requirement IDs (R-xx) referenced in code and `docs/traceability.md`
- [ ] Tests added/updated, including security and negative tests
- [ ] No secrets, PII, or ballot data in code, logs, fixtures, or errors
- [ ] `ruff`, `mypy --strict`, `bandit`, `pip-audit`, and `manage.py check --deploy` pass
- [ ] Migrations reviewed; DB roles and constraints unchanged or justified
- [ ] Audit events emitted for every administrative action
- [ ] Crypto only via `evcrypto`; no voter-ballot linkage introduced
- [ ] Docker: images build, run as non-root, pass `hadolint`/`trivy`; no secrets baked in
- [ ] Compose: network segmentation intact (`ballot`/`tally` not on identity network), no published DB/Redis ports in prod
- [ ] Docs/ADR updated for any architectural change
