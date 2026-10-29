# Delivery status

**Core workflow implemented and tested; complete product/release not yet accepted.**

## Verified locally

| Area | Implementation / evidence |
| --- | --- |
| Master portal | Agency invitation/suspension; screen provisioning and assignment; real Chrome workflow |
| Agency portal | Invitation/login, assigned fleet, pairing, real uploads, selection/timing, composer/publication; real Chrome workflow |
| Media | Signed local upload/download, SHA-256, metadata inspection, thumbnails, path/MIME/size/quota validation; pytest and actual FFmpeg fixtures |
| Auth | MFA enforcement, panel cookies, Origin checking, throttling, shared-session adapter and revocation; pytest |
| Device/backend | Token hashing/rotation, ordered epoch/cursor ingestion, signed manifests/ETag, scheduling/ownership; pytest |
| Database | Alembic fresh upgrade, existing-data backfill/token hashing, schema diff, downgrade and re-upgrade; isolated SQLite test |
| Browser | Chrome headless end-to-end; no page overflow at 390/768/1440/1920 px; cookie persistence and logout |
| Packaging | Wheel build; portal HTML/CSS/JS packaged; Python compilation, JavaScript syntax and dependency checks |
| Deployment config | Compose validates; secrets no longer baked into database config, migration prerequisite, internal services, persisted media |

Current automated suite: **62 tests passing**. Browser workflow is a separate
smoke script, not counted in pytest. Redis tests are fakeredis adapter tests.
These results are local evidence, not acceptance of every requirement.

## Still required before full delivery

1. **Android integration and physical tests**: authenticated protocol, updated APK,
   offline downloads/playback/receipts, power loss/reboot, kiosk/device-owner input
   and escape-path matrix. No APK rebuild or physical acceptance was performed.
2. **Remaining product workflows**: advertiser purchasing/reporting, complete admin
   deletion lifecycle, draft editing, split-zone layouts and cross-client parity.
3. **Production media/background operations**: malware scanning/isolation, durable
   processing recovery, cleanup/reconciliation, worker compilation and analytics,
   external object storage if required. Only local storage is implemented.
4. **Live deployment validation**: start Docker Desktop; run PostgreSQL/real Redis,
   separate portal domains/proxies/TLS, load/soak and disaster recovery tests.
5. **Security and UX acceptance**: key lifecycle/proof of possession, MFA replay,
   account-level abuse controls, independent security review, accessibility/200%
   zoom/keyboard acceptance and product/design signoff.
6. **Traceability and operations**: review each requirement row against evidence;
   assign owners/deadlines and perform actual operational/team acceptance tasks.

## Start and validate

See [README](../README.md) for first-account bootstrap and configuration.

```sh
python -m pytest
python -m scripts.check_portals_browser
```

Do not apply migrations to an existing development/customer database until it is
backed up and its migration history is understood. The new migration changes
credential storage; older-server rollback needs token rotation.

The Docker daemon was unavailable during this work. The Android source is outside
this repository (an adjacent development tree was found), so it was not modified
without a separate integration review. UI pages are now included here, but full
product acceptance and infrastructure/device behavior must not be inferred from
the portal smoke check.
