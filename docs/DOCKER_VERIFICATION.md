# Docker verification results

**Latest full local run passed. This is deployment evidence, not full product or security acceptance.**

Reproduce from the repository root, with Docker Desktop running and dev/browser
extras installed:

```sh
python -m scripts.check_docker
```

The checker builds `pixl-verification:local`, derives a disposable stack from the
actual `docker-compose.yml`, and removes its containers/network/volumes in a
`finally` block. It generates a separate configuration, database credentials,
application/signing keys, HTTPS certificate and random Compose project name under
the operating system's temporary directory. It never loads the repository `.env`,
uses existing databases, or publishes PostgreSQL/Redis ports. The pre-existing
`pixl-postgres` PostgreSQL 15 container was left running and unchanged.

The image/build cache is retained for repeat checks; this is not a Docker prune.
`--skip-build`, `--skip-suite` and `--skip-browser` are focused rerun options, not
substitutes for the full command used for the results below.

## Environment

- Docker Desktop/WSL2, Linux containers, Python 3.12.
- PostgreSQL 16, Redis 7, Celery prefork worker with concurrency 2, real Beat.
- Actual production configuration: DEBUG disabled, Redis sessions, worker media
  processing, secure host-prefixed cookies and persistent generated signing keys.
- A disposable Nginx HTTPS reverse proxy bound only to a random loopback port.
- Host Chrome for the browser workflow; CI uses installed Chromium.

## Verified

| Check | Result |
| --- | --- |
| Hash-locked production image build | Passed |
| Non-root API and media volume permissions | Passed |
| Environment files excluded from the image | Passed |
| Compose startup, prerequisite migration, readiness and dependency consistency | Passed |
| PostgreSQL migration from old schema with retained data | Numeric identifier backfill and token hashing verified |
| Repeat upgrade, full PostgreSQL downgrade/re-upgrade, Alembic/model schema parity | Passed on a dedicated disposable migration database |
| Complete Linux/PostgreSQL pytest suite | **105 passed, 1 skipped**; only skip is Windows extended-path behavior |
| Real Redis/Celery/Beat integration test | Executed and passed, not skipped or eager-mode mocked |
| Chrome master/agency workflow over HTTPS | Provisioning, invitation, pairing, worker uploads, media dialog, graphs, saved-draft recovery, responsive widths, session persistence, admin revocation and logout passed |
| Authenticated API/device flow | Secure cookies, enrollment/exchange, image/video metadata and thumbnails, malformed-media rejection, signed downloads/manifests, ETag/304, heartbeat, ordered receipts and duplicate acknowledgement passed |
| Security-negative flows | Cross-role/tenant denial, CSRF origin rejection, CORS restrictions, invalid device tokens, unsigned media denial, production docs/legacy simulator gating passed |
| Small concurrent-flow check | 50 requests, up to 8 in flight, no errors; repeated publication did not inflate manifest versions |
| API restart | Redis sessions, device credentials, signing authorization and media survived |
| Worker downtime | A queued upload persisted and processed after restart |
| Expired processing lease | Real dispatch/worker path reclaimed persisted crash state |
| Actual worker hard kill | SIGKILL during video processing; subsequent worker published exactly one asset on attempt 2 |
| Redis outage/restart | Readiness and authenticated requests returned 503, liveness stayed up, sessions recovered from the persisted Redis volume |
| PostgreSQL outage/restart | Readiness returned 503, liveness stayed up, data recovered and a new upload processed successfully |
| Real maintenance task via broker | Archived an expired campaign, incremented its screen manifest once and removed failed upload bytes while retaining published library files |
| Backup/restore | `pg_dump`/`pg_restore` into a different database plus media archive restoration into a new volume; recreated API/worker/Beat processed new work against restored data |
| Restored data integrity | Media IDs and checksums, thumbnails, existing auth/device credentials and manifest signature verified |
| Cleanup | Only disposable test resources removed; existing services and repository credentials/data untouched |

The most recent concurrent-flow observation was **p95 0.437 seconds** on this local
machine. This is a small regression smoke check, not a promised latency, capacity
benchmark or sustained load/soak test.

The Windows/SQLite suite is checked separately. Its optional real Redis integration
test skips unless a dedicated test broker is configured; the Docker run above
executes that test against real infrastructure.

## Issues found and fixed during Docker testing

1. **Raw driver transport failures returned HTTP 500.** When PostgreSQL stopped,
   Docker DNS resolution could raise a raw `OSError` before SQLAlchemy wrapped it.
   Readiness now handles raw connection/time-out failures and even rollback failures
   as NOT_READY/503. Request-level storage/network failures receive safe 503 errors
   with retry hints instead of internal details. Added regression tests.
2. **Legacy simulator pages remained served in production.** `/simulator` and
   `/player` now share an explicit production/legacy-enable gate. The weak TV API
   was already disabled; the browser entry points now follow the same policy.
   Added regression tests for production, disabled development and enabled development.
3. **Checker incorrectly rejected an expected platform skip.** The Docker checker
   now verifies that the specific real worker/Beat test passed, rather than assuming
   a cross-platform suite must have zero skips.
4. **Restore checks left a formerly mounted test volume behind.** Compose can skip
   an unused volume after service mounts switch to a restored volume. Cleanup now
   checks this exact random project label and removes only its remaining prefixed
   volumes, without pruning Docker or touching other applications. A complete rerun
   passed with no disposable resources left behind.

## Controlled fault injection and limits

- To guarantee SIGKILL interrupts processing, only the disposable worker temporarily
  uses an ffprobe wrapper that waits before calling the real executable. After the
  kill, the checker advances the persisted lease deadline instead of waiting the
  normal 15 minutes. It restores the normal worker before testing recovery. There
  is no production fault-injection endpoint or permanent processing delay.
- The maintenance test ages disposable rows and sends the real task through Redis.
  Regular dispatch is exercised through Beat; it does not wait five minutes just
  to test archival and reconciliation.
- HTTPS uses a generated one-day self-signed certificate. HTTPX trusts that certificate;
  the browser context permits the self-signed test certificate. Public CA issuance,
  real separate-domain DNS/routing and the operator's production proxy are not tested.
- Backup/restore uses a quiescent test fixture and preserves the Redis volume. It
  proves PostgreSQL/media restoration and application container recreation, not
  live-backup consistency, point-in-time recovery or a complete fresh-host DR exercise.
- No physical Android kiosk/offline/power-loss acceptance, hostile-media sandbox
  audit, independent security/accessibility assessment or missing-product-workflow
  implementation is implied.

`.github/workflows/ci.yml` includes a dedicated `docker-production-smoke` job that
runs this checker with Chromium. The checker has run locally; remote GitHub
Actions execution has not been observed here.
