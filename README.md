# PIXL 2.0

Digital-signage backend and web portals: agency administration, screen assignment
and enrollment, real local media uploads, playlists, scheduled campaigns, signed
manifests and ordered playback receipts.

**This is a working core workflow, not a completed production product.** See
[delivery status](docs/DELIVERY_STATUS.md) for evidence and remaining requirements,
and [production hardening](docs/PRODUCTION_HARDENING.md) for jobs, deployment and release gates.

## Run locally

Requires Python 3.11+, FFmpeg and ffprobe on PATH. Chrome or Edge is needed only
for the optional browser smoke check.

```sh
python -m venv .venv
# Activate .venv (Windows: .venv\Scripts\activate)
pip install -e ".[dev]"
# Copy .env.example to .env; configure it and never commit credentials.
python -m alembic upgrade head
python -m scripts.create_master
python start_all.py
```

The bootstrap command prompts for an email, password (12+ characters) and a
random TOTP secret (32+ base32 characters) already stored in your authenticator
or password manager. It does not print credentials or overwrite existing users.
For controlled automation it accepts `MASTER_BOOTSTRAP_EMAIL`,
`MASTER_BOOTSTRAP_PASSWORD` and `MASTER_BOOTSTRAP_TOTP_SECRET` environment variables.
Remove those bootstrap variables after creating the account. The launcher never
creates default accounts or silently migrates a database. Old demo accounts are
not automatically removed: audit/remove them and rotate any historically exposed
credentials before deployment.

- Master: **http://localhost:8000/master**
- Agency: **http://localhost:8000/agency**
- API documentation: `/api/docs` when DEBUG is enabled
- Readiness: `/api/v1/health/ready`

For local portal invitations, set `MASTER_ORIGIN` and `AGENCY_ORIGIN` to
`http://localhost:8000` in your local `.env`. In production use the respective
HTTPS portal origins. `PORTAL_PANEL=master|agency|none` restricts which portal
pages an instance serves; `all` is convenient for local development. Proper
separate-domain routing/TLS must still be configured and verified in deployment.

## Main workflow

1. Master creates an agency and privately shares its one-time invitation.
2. The invited administrator activates their account and signs in at `/agency`.
3. Master provisions/assigns a screen. Its device requests an enrollment challenge;
   the agency completes pairing against its assigned screen. The device exchanges
   the challenge for an authenticated `/api/v1/device` credential.
4. Agency uploads multiple files from the library. Upload bytes, validation and
   publication are separate states; concurrency is bounded to two browser uploads.
5. Select READY media, configure durations, choose assigned screens and schedule,
   then create/publish a campaign from the same page. Fleet data refreshes automatically
   with request jitter and failure backoff. The overview includes live fleet graphs.
6. Master can invite additional agency admins and revoke their access from
   **Agencies & access → Admin accounts**. Business and audit records are retained.

See [dashboard upgrade notes](docs/DASHBOARD_UPGRADE.md) for the design, graph semantics,
account lifecycle, device polling hints and verification scope.

The portal does not implement advertiser purchasing, split layouts or full draft
editing yet. Browser playback is not Android kiosk enforcement.

## Upload protocol

1. `POST /api/v1/agency/media/upload-ticket` with filename, MIME and exact byte size.
2. `PUT` raw file bytes to `presigned_upload_url` before its expiry.
3. `POST /api/v1/agency/media/process` with `ticket_id` and optional SHA-256.
4. Poll `GET /api/v1/agency/media/uploads/{ticket_id}` until FINALIZED or FAILED.
   Repeating the processing request safely returns the same job/result.

Finalization verifies real content, dimensions, duration, checksum and quota,
generates a thumbnail, then publishes. Local storage is supported; unimplemented
providers such as R2 fail explicitly instead of returning fake URLs. Media files
require expiring signed download URLs; quarantine is never served. Configure
`MEDIA_PUBLIC_BASE_URL` to the HTTPS API origin for devices on other hosts.
With `MEDIA_PROCESSING_MODE=worker`, processing uses durable database jobs, Celery
workers and a single Beat scheduler, with leases, bounded retries and recovery.
Local `inline` mode requires no broker and offloads inspection from the event loop.
The older synchronous `/finalize` endpoint remains available only in inline mode.
FFmpeg is required for video processing. Failed/expired uploads keep their quota
reservation until scheduled cleanup confirms deletion.

## Legacy demo player

The bundled APK/browser simulator uses an older, weaker protocol. It is disabled
by default and **always blocked in production**. On a trusted development network
only, set `ALLOW_LEGACY_TV=true` to enable `/simulator`'s device API. Legacy receipt
uploads now require `?pairingCode=...`; an unmodified APK that omits it will need
an update. Use the authenticated `/api/v1/device` protocol for new clients.
The Android source is not part of this repository; APK rebuild and device-owner,
kiosk, offline/cache/power-loss testing remain separate work.

## Checks

```sh
python -m pytest
python -m pip check
python -m compileall -q pixl scripts start_all.py
# Optional real-browser workflow check (uses an isolated temporary database):
pip install -e ".[browser]"
python -m scripts.check_portals_browser
# For Edge instead of Chrome: set PIXL_BROWSER_CHANNEL=msedge
# Full isolated production-mode Docker/PostgreSQL/Redis/HTTPS verification:
python -m scripts.check_docker
```

The Docker checker builds and tears down its own stack without reading your `.env`
or using existing databases. See [Docker verification results](docs/DOCKER_VERIFICATION.md)
for the passing checks and remaining acceptance limits.

## Deployment and migrations

Back up databases before migrating. Production startup does not run `create_all`;
Compose runs a dedicated Alembic migration service before the API. A database
previously created directly from metadata may already contain migration columns
without an Alembic history: inspect it before upgrading or stamping. Existing
user databases and credentials are not automatically rewritten by these changes.

Production requires DEBUG disabled, PostgreSQL, Redis sessions, worker processing,
a strong random `SECRET_KEY`, persistent Ed25519 signing keys, valid HTTPS portal/media
origins, TLS and a URL-safe randomly generated `POSTGRES_PASSWORD`. Compose includes
API/worker/Beat services, keeps PostgreSQL/Redis internal, persists media and binds
the API to loopback for a TLS reverse proxy. Docker uses hash-locked Linux/Python
3.12 dependencies from `requirements.lock`. The isolated production-mode Docker
stack passed real PostgreSQL/Redis, HTTPS browser, worker crash/outage and backup/
restore checks. Validate your actual domains, certificates, proxy, workload and
recovery procedures separately; this is not full production acceptance.
Do not enable query-string access logging: invitation and media URLs contain
bearer capabilities. The supplied Uvicorn launch commands disable access logging;
configure your reverse proxy to omit or redact query strings as well.

[Requirements and architecture](docs/README.md) · [Review](docs/PROJECT_REVIEW.md).
