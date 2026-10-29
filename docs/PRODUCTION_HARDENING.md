# Production hardening and release gate

This is a substantial hardening pass, **not a certification that every defect or
product requirement is complete**. Existing dashboard changes were retained.

## Implemented

### Durable media jobs

- `POST /api/v1/agency/media/process` accepts the existing finalize request shape
  and returns HTTP 202 with ticket status. `GET /api/v1/agency/media/uploads/{id}`
  returns tenant-scoped progress, attempts, safe error text and the completed media ID.
- `MEDIA_PROCESSING_MODE=inline` keeps development usable without Redis. In
  `worker` mode, the database commit is the durable enqueue: no work is lost
  between committing a ticket and publishing a Celery message. The old synchronous
  `/finalize` endpoint is rejected in worker mode so processing cannot bypass
  worker resource limits. Existing clients must adopt `/process` and status polling.
- Beat dispatches due jobs every 10 seconds. Workers atomically claim 15-minute
  leases. Duplicate deliveries cannot create duplicate assets. Three attempts,
  exponential retry delay, terminal validation failures and expired-lease recovery
  are persisted in the database. Normal task execution has a 300-second hard limit;
  the longer lease allows for shutdown/recovery. Do not lengthen task limits beyond
  the lease without updating and testing recovery.
- Publication commits asset metadata and final ticket status together. Temporary
  output names are lease-specific. Quarantine cleanup after a successful commit is
  best effort and subsequently reconciled.
- Quota accounting reads library usage and reservations in one SQL snapshot.
  Queued work retains its reservation beyond upload-URL expiry. Failed/expired
  uploads retain reservations until cleanup confirms deletion, preventing repeated
  invalid uploads from accumulating unaccounted disk usage.
- The portal frees browser upload slots after byte upload/processing request; it
  shows queued, processing, retry and terminal states. Pending ticket IDs/names
  survive reload in tab-scoped sessionStorage, not bearer credentials. Status
  checks resume after login. Sign-out clears private state and blocks stale
  responses from reopening a workspace.

### Scheduled maintenance

Every five minutes, a bounded lifecycle task:

1. Archives expired published campaigns and atomically invalidates affected screen
   manifests once. Devices **do not depend on scheduler punctuality**: manifests
   include start/end times and the next 72 hours of schedules; clients enforce them.
2. Expires enrollment challenges, recovers expired inline-processing leases and
   expires abandoned uploads with a one-hour grace period.
3. Reconciles up to 100 terminal tickets: removes abandoned quarantine/staging
   bytes and unpublished outputs, preserves existing library media and retains
   audit rows. Completed cleanup releases quota reservations.

The old fake processing, compilation and aggregation tasks were removed. Analytics
aggregation and manifest precompilation are **not** claimed as implemented. Real
manifests continue to be compiled and signed on authenticated device requests.

### Authentication and startup

- Removed the DEBUG-only static MFA bypass. Authenticator time steps are consumed
  atomically per account, blocking replay/concurrent reuse. An already-used code
  requires waiting for the next code; keep server/device clocks synchronized.
- Enabled MFA fails closed if its secret is missing. Invitation redemption cannot
  change an existing account's tenant/role or restore deleted access. New-user
  invitation audit records now reference the generated user ID.
- Invitation passwords require 12–128 characters. Login input sizes are bounded.
  Validation responses omit submitted values, including passwords and invitation
  capabilities. Database failures and unexpected exceptions return safe errors;
  request IDs support correlation without logging capability URLs or SQL values.
- Production fails startup for DEBUG, memory sessions, legacy-TV enablement,
  weak/default application secrets, non-PostgreSQL databases, invalid/non-HTTPS
  origins, unsupported storage or inline media processing. Persistent manifest
  signing keys are still required.
- `start_all.py` is development-only, verifies migration history, fails instead of
  ignoring migration errors, supervises API/worker/Beat, and never seeds accounts.
  Schema changes require explicit Alembic use or `start_all.py --migrate` after backup.
  `scripts.seed_users` is now a deprecated alias for explicit secure master bootstrap.
- The mistakenly tracked `.evn` is removed from version control and ignored; its
  local copy is retained. No real `.env`, database or existing account was rewritten.
  **Rotate any real credentials previously committed, including in Git history.**
  **Audit/remove old demo accounts**: changing the launcher does not change existing
  accounts created by earlier versions with publicly known passwords/TOTP secrets.

### Campaigns and UX

- Publishing an already-published campaign is idempotent. Manifest invalidations
  use atomic increments; screen capacity and organization activity are enforced
  when provisioning/assigning screens. Playback status honors the configured
  offline threshold and stable campaign tie-breaking.
- Saved drafts have a Publish action, including after an interrupted publication.
  Campaign labels distinguish scheduled/live eligibility/ended windows from actual
  playback. Empty states, media thumbnails, loading feedback, bounded requests,
  focus preservation and session-transition handling improve recovery and navigation.
- Browser validation now deliberately fails a publication once and verifies draft
  recovery without a second campaign.

## Deploy

1. Back up the database **and media volume**; verify restore and migration history.
   Do not blindly stamp metadata-created databases.
2. Configure production HTTPS origins, persistent Ed25519 keys, a strong random
   SECRET_KEY, a URL-safe POSTGRES_PASSWORD and adequate disk headroom. Remove old
   demo users and rotate any historically exposed credentials.
3. Run `docker compose up --build -d`. Compose runs Alembic before services and
   includes API, worker, exactly one Beat scheduler, PostgreSQL and Redis. Only
   loopback API access is published; supply and validate a TLS reverse proxy.
4. Verify readiness, an actual upload through QUEUED → PROCESSING → FINALIZED,
   worker termination/recovery, enrollment, manifest signatures and device playback.
5. Alert on old QUEUED jobs, expired PROCESSING leases, FAILED tickets, disk usage,
   reconciliation failures and service restarts. These alerts are operator work;
   no external monitoring stack is installed by this change.

Use **exactly one Beat instance per deployment/broker**. Scale workers, not Beat.
All API/worker instances must share the same local media volume, secrets, database
and broker. Separate hosts need a genuinely shared filesystem; external object
storage is not implemented. Reserve space for quarantine, thumbnails and temporary
publication copies as well as the nominal library quota.

For manually managed development services:

```sh
python -m celery -A pixl.workers.celery_app:celery_app worker --loglevel=INFO
# Windows development: append --pool=solo
python -m celery -A pixl.workers.celery_app:celery_app beat --loglevel=INFO
```

Production Linux/Python 3.12 runtime dependencies are pinned with hashes in
`requirements.lock`; Docker installs this file instead of unbounded development
requirements. To intentionally update, regenerate and review/audit/test the result:

```sh
python -m uv pip compile pyproject.toml --python-platform linux --python-version 3.12 --generate-hashes --output-file requirements.lock --no-emit-index-url
python -m pip_audit -r requirements.lock --disable-pip --no-deps
```

## Verification and remaining release blockers

Local evidence is recorded in [delivery status](DELIVERY_STATUS.md) and the
[Docker verification report](DOCKER_VERIFICATION.md). The full Docker run passed
105 tests with one Windows-specific skip, plus HTTPS browser, hard-kill/outage,
maintenance and database/media restore checks. It uses disposable databases,
volumes and credentials, never the existing development database or `.env`.

```sh
# Requires Docker and dev/browser extras; creates and removes its own stack:
python -m scripts.check_docker
```

A real PostgreSQL/Redis worker+Beat pytest run against manually provisioned test
infrastructure is also available:

```sh
# Point ONLY at disposable infrastructure. Tests drop/recreate tables.
# Set PIXL_TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test.
# Set PIXL_TEST_REDIS_URL to a dedicated Redis broker database numbered 10 or higher.
python -m pytest
```

CI defines SQLite/PostgreSQL jobs, the real worker/Beat test, hash-locked runtime
installation, dependency audit, compilation/JS and Chromium checks, plus the full
`docker-production-smoke` job. The checker ran locally, not as an observed remote
GitHub Actions execution.

Before production acceptance, still demonstrate:

- Actual deployment DNS/separate portal domains, public TLS/reverse-proxy routing,
  sustained load/soak, fresh-host restore and point-in-time recovery. Local production
  Docker, shared-volume permissions, worker crashes, service outages and quiescent
  PostgreSQL/media restore have passed; see the report for their limits.
- Media malware scanning and stronger decoder sandbox/isolation; bounded FFmpeg
  execution is not equivalent to safe execution of arbitrary hostile media.
- Android authenticated-client integration, proof of key possession/key lifecycle,
  physical kiosk/offline/power-loss acceptance. The Android source is not here.
- Missing product workflows, independent security/accessibility review, appropriate
  account-level abuse controls, monitoring and operational ownership.

Do not infer these outcomes from passing local tests, a vulnerability audit, or a
valid Compose file. Real Docker evidence is now available, but does not replace
independent security review or acceptance in the target deployment.
