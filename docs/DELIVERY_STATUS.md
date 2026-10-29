# Delivery status

**Core workflow implemented and tested; complete product/release not yet accepted.**

## Verified locally

| Area | Implementation / evidence |
| --- | --- |
| Master portal | Agency invitation/suspension; screen provisioning and assignment; real Chrome workflow |
| Agency portal | Invitation/login, assigned fleet, pairing, real uploads, selection/timing, composer/publication; real Chrome workflow |
| Media | Signed local uploads/downloads, SHA-256, real inspection/thumbnails, durable queued processing, leases/retries/recovery and reservation-safe cleanup; pytest and FFmpeg fixtures |
| Auth | MFA enforcement/replay protection, removed static bypass/default-account seeding, panel cookies, Origin checks, throttling, shared-session adapter/revocation and safe error responses; pytest |
| Device/backend | Token hashing/rotation, ordered epoch/cursor ingestion, signed manifests/ETag, scheduling/ownership; pytest |
| Database | SQLite and real PostgreSQL fresh upgrade, existing-data backfill/token hashing, schema diff, downgrade and re-upgrade; disposable databases |
| Browser | Chrome headless end-to-end; no page overflow at 390/768/1440/1920 px; cookie persistence and logout |
| Packaging | Wheel build; portal HTML/CSS/JS packaged; Python compilation, JavaScript syntax and dependency checks |
| Deployment | Real production-mode Compose stack, prerequisite migrations, non-root API, worker/Beat, PostgreSQL 16/Redis 7 and local HTTPS proxy passed |
| Scheduling | Real dispatch/lifecycle tasks, worker SIGKILL/lease recovery, campaign archival, manifest invalidation and failed-byte cleanup passed |
| Recovery | API/Redis/PostgreSQL restarts, PostgreSQL/media restore to different database/volume and application container recreation passed |
| Supply chain | Wheel/assets/workers verified, pip check clean and pip-audit found no known vulnerabilities in locked runtime dependencies |

Docker Linux/PostgreSQL suite: **105 passed, 1 skipped**. The real Redis worker/Beat
integration test executed and passed; the only skip was Windows-specific path behavior.
The production-mode HTTPS Chrome workflow passed, including saved-draft publication
recovery. Additional Docker checks passed for image/video processing, signatures,
negative security cases, a 50-request concurrent-flow smoke, SIGKILL/outage recovery,
maintenance, PostgreSQL migration/backfill/rollback and database/media restoration.

See [Docker verification results](DOCKER_VERIFICATION.md) for the exact scope,
reproduction command and controlled fault-injection/restore limitations. Earlier
Redis adapter unit tests still use fakeredis; they are not the sole Redis evidence.

See [production hardening and release gate](PRODUCTION_HARDENING.md) and
[dashboard upgrade](DASHBOARD_UPGRADE.md) for scope. CI now defines PostgreSQL/Redis
integration, Chromium and a complete Docker production smoke job. The checker ran
locally; remote GitHub Actions execution has not been observed here.
These results are local evidence, not acceptance of every requirement.

## Still required before full delivery

1. **Android integration and physical tests**: authenticated protocol, updated APK,
   offline downloads/playback/receipts, power loss/reboot, kiosk/device-owner input
   and escape-path matrix. No APK rebuild or physical acceptance was performed.
2. **Remaining product workflows**: advertiser purchasing/reporting, draft editing,
   split-zone layouts and cross-client parity. Master-only admin invitation and
   access deletion (retained records, revoked sessions) are now implemented.
3. **Remaining media/background operations**: malware scanning/decoder isolation,
   deployment-specific infrastructure validation, monitoring, analytics and external object
   storage if required. Durable jobs, recovery and cleanup are implemented; only
   local storage is supported. Manifests are compiled on demand, not precompiled.
4. **Deployment acceptance**: real separate-domain DNS/TLS/proxy configuration,
   sustained load/soak and full fresh-host/PITR disaster recovery. Local Docker,
   fault recovery and quiescent database/media restore are now verified.
5. **Security and UX acceptance**: key lifecycle/proof of possession, historical
   credential/demo-account cleanup, account-level abuse controls, independent
   security review, accessibility/200%
   zoom/keyboard acceptance and product/design signoff.
6. **Traceability and operations**: review each requirement row against evidence;
   assign owners/deadlines and perform actual operational/team acceptance tasks.

## Start and validate

See [README](../README.md) for first-account bootstrap and configuration.

```sh
python -m pytest
python -m scripts.check_portals_browser
# With Docker Desktop running and browser extras installed:
python -m scripts.check_docker
```

Do not apply migrations to an existing development/customer database until it is
backed up and its migration history is understood. The new migration changes
credential storage; older-server rollback needs token rotation.

Docker verification was completed once the daemon became available. Disposable
projects were removed and the pre-existing PostgreSQL container was left unchanged.
The Android source is outside this repository, so physical/device acceptance still
requires a separate integration review. Full product acceptance must not be inferred
from either the portal smoke or the Docker checks.
