# Project review — current state

This supersedes the first review, which found 16 passing tests but many simulated
features. The core portal/backend workflow is now runnable. It is **not** a claim
that the entire requirements baseline is implemented or production accepted.
See [delivery status](DELIVERY_STATUS.md) and the [setup guide](../README.md).

## Implemented since review

### Portals

- Master and Agency login pages, invitation activation, agency provisioning and
  suspension, screen provisioning/assignment, pairing, playback inspection/stop.
- Media library with filename search, READY-only selection, multiple uploads,
  bounded concurrency, per-file progress/errors/retry and configured timing.
- A media-to-campaign composer that creates its playlist internally, schedule
  validation, target selection, publication and campaign listing.
- Five-second fleet polling with server-derived online/last-seen values and a
  visible stale-connection state. Responsive tables, labeled forms and focus styles.
- Restricted portal deployment mode and a strict content-security policy. No
  third-party scripts, frontend secrets or localStorage session tokens.

### Media

- Actual local signed upload URLs, bounded streaming, exact size checks,
  reserved quota checks, real SHA-256, image verification and FFprobe inspection.
- Real thumbnail generation and published-file delivery with expiring signed
  URLs. No fake checksums, video durations, thumbnails or successful empty files.
- Quarantine/path traversal protection, MIME/content checks, owned brand references,
  repeated-finalization protection and retryable validation failures.
- Unsupported storage providers fail explicitly. No Cloudflare/R2 support is claimed.

### Security and correctness

- Master MFA fails closed; organization suspension blocks new and existing sessions
  and device use. Cookie-authenticated writes check Origin; same-origin portals work.
- Redis-backed shared sessions, expiry, hashed cache keys and cross-worker revocation;
  Redis outages return 503 rather than silently accepting memory sessions.
- Fixed-window authentication/enrollment throttling, using shared atomic Redis
  counters in production. Password hashing/verification and Redis operations are
  offloaded from the API event loop where integrated into request flows.
- Device token hashes at rest, migration of older raw tokens, credential revocation
  on reassignment and new sequence epochs on credential replacement.
- Transactional TV numeric-ID allocation/backfill, without random or common fallback
  IDs. Future campaigns do not play early. UTC normalization fixes SQLite timestamps.
- READY/ownership checks before publishing and broadcasting. Stopping playback
  removes only that screen's assignment instead of stopping every screen globally.
- Ingestion rejects invented epochs, flushes poison events inside savepoints, and
  advances cursors using compare-and-set; enrollment/invitations use locks and
  compare-and-set claims to prevent repeated consumption.
- Legacy TV is explicitly opt-in for development and blocked in production. Its
  receipt uploads require pairing credentials, validate references, map numeric
  IDs to UUIDs and ignore identical retries using deterministic receipt identities.
- Signed manifest checks support ETag/304 with hourly offline-authorization renewal.

### Operations

- Database/Redis readiness; production startup guards; production migration flow.
- Dependency/package discovery fixes and packaged portal assets.
- Non-root Docker package/storage permissions, internal database/cache services,
  persistent media and no baked-in Compose database password.
- SQL bind parameters are hidden and default Uvicorn query-string access logging
  is disabled. Preserve that protection in reverse proxies.
- Bootstrap command for a master account without credentials in source or output.
- Launcher fails nonzero on service failure, uses readiness and waits for killed
  child processes. Existing .env and user databases were not altered.
- Tests use an isolated temporary database; duplicate conftest imports no longer
  mask database isolation errors.

## Evidence and limits

Automated API/regression/migration tests pass. A real Chrome smoke check passes
provisioning, invitation activation, pairing, actual image upload, campaign
publication, cookie persistence/logout and page-overflow checks at four widths.
Packaging, Python/JavaScript syntax, dependency consistency and Compose config
checks pass. The exact latest count is recorded in DELIVERY_STATUS.md.

Redis tests use fakeredis with Lua support: these are adapter/behavior tests, not
proof of real Redis networking or persistence. SQLite migrations are tested with
existing data, token hashing, backfill, schema comparison and downgrade/re-upgrade.
Docker Desktop's daemon was unavailable, so no running container/PostgreSQL claim
is made. Physical Android playback/kiosk/offline tests were not executed.

## Remaining release blockers

1. Android client migration to the authenticated device protocol, actual media
   downloads, atomic offline activation/cache verification, durable receipt queues,
   reboot/power-loss recovery and supported device-owner/Lock Task provisioning.
   The adjacent Android project requires a separate reviewed integration/build;
   the prebuilt APK in this repository has not been updated.
2. Full product scope beyond the portal MVP: advertiser purchasing/reporting,
   administrator deletion lifecycle, full campaign/draft editing and direct atomic
   composer backend, split-zone/layout parity, design approval and complete
   keyboard/zoom/accessibility acceptance. PORTAL_PANEL restricts rendered pages;
   separate portal artifacts/hosts/proxies still require deployment validation.
3. Real PostgreSQL concurrency/load/soak tests; real Redis restart/outage/persistence
   tests; Docker runtime, external TLS, backups, restore and rollback exercises.
4. Production media isolation/scanning, storage capacity/cleanup/reconciliation and
   provider-specific object storage. A crashed upload/processing operation can
   require a fresh ticket; a worker recovery/reconciliation queue is not implemented.
   Processing publishes via filesystem and DB operations, not a distributed atomic
   transaction. Cleanup/reconciliation is needed for orphaned files after failures.
5. MFA replay protection and full per-account/device abuse controls, public-key
   proof-of-possession/attestation, secure key rotation and an independent security
   review. Current rate limiting is a fixed-window IP control, not comprehensive
   abuse prevention. Existing memory sessions are development-only and are not
   security-equivalent to production Redis-backed sessions.
6. Background jobs in `pixl/workers/tasks.py` remain placeholders. The real core
   media flow does not use them, and production Compose no longer starts a worker
   claiming to process media. Durable scheduled compilation and hourly analytics
   require implementation before those features can be advertised.
7. Requirement-level traceability and human acceptance are not complete. Passing
   a smoke check does not establish physical kiosk enforcement, device reliability,
   fleet capacity, financial reporting accuracy or fulfillment of every matrix row.

## Compatibility and rollout

- New migrations add/backfill TV IDs and hash existing device credentials. A
  downgrade cannot reconstruct plaintext tokens; old-server rollback requires
  device credential rotation. Back up and rehearse before deployment.
- Legacy PoP now requires pairingCode and is unavailable in production. Do not
  silently re-enable the old insecure route to make an older APK appear compatible.
- Media finalization now requires a real uploaded file. Clients/tests that only
  requested tickets must implement PUT before finalize. Signed download URLs expire.
- No development database was upgraded or stamped automatically. Pre-existing
  edits were preserved, including the key-generation script's existing change.
