# PIXL 2.0 — Test and Acceptance Plan

## 1. Evidence and scope

**Status: planned, not executed.** This repository has no runnable test suite or application. All previous checked boxes represented specifications, not verified results, and are replaced by the pending gates below.

Every requirement maps to an acceptance condition and future test/evidence ID in [document 17](17_REQUIREMENTS_TRACEABILITY_MATRIX.md). Documents [13](13_REQUIREMENTS_BASELINE_AND_DELIVERY_PLAN.md)–[18](18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md) define the implementation baseline. A test ID is not proof that a test exists or passed.

For each run record requirement/test IDs, build/commit, environment, dataset, device/OS, date, expected/actual results, artifacts and reviewer. Use production-like role/database policies and real target Android hardware for kiosk acceptance. Never use production personal data or log credentials/signed URLs in fixtures.

## 2. P0 security and deployment gate

- [ ] Registration removed from login, frontend routes, backend routes and legacy aliases; anonymous signup cannot create a user. Invitation acceptance remains authenticated by single-use expiring token.
- [ ] Only Master creates/suspends/deletes Agency admins; session/invitation revocation and audit pass; Agency admin cannot create a peer admin by request tampering.
- [ ] Master screen assignment required; unauthorized/unassigned Agency claim fails. Reassignment revokes old access and preserves original attribution for late receipts.
- [ ] Agency A cannot read/mutate Agency B screens/media/playlists/campaigns/bookings/exports. Test guessed IDs and cross-tenant association creation, not just collection filtering.
- [ ] Brand 1 cannot view Brand 2 creatives/bookings/reports or arbitrary fleet details; advertiser purchasing stays within authorized agency inventory.
- [ ] Device 01 cannot access management APIs or submit for Device 02. Enrollment rejects swapped public keys, replayed exchanges, expired/consumed challenges and brute-force attempts.
- [ ] Missing tenant context fails closed; composite constraints reject cross-tenant references; RLS works with real non-owner application role and pooled connection reuse.
- [ ] Host-only cookies, role/audience checks, CSRF, Origin/CORS and WSS scope pass across Master/Agency/advertiser/staging/production.
- [ ] Revoked/expired sessions and tokens fail HTTP/WSS/download access; Redis outage never grants access.
- [ ] Injection/path traversal/malformed payload/security-file corpus tests pass defined rejection criteria. No finite corpus proves all malicious uploads harmless; worker containment is tested independently.
- [ ] Distinct frontend deployments securely route to shared backend; configuration mistakes fail safely; built bundles/source maps/CI logs contain no secrets.

Negative cases in document 03 remain required regression cases, expanded by SEC/ENV/QA IDs in document 17.

## 3. P1 UI, critical bugs and campaign validation gate

- [ ] Approved reference boards, design tokens/components and Master/Agency key screens; product reviews actual workflows, empty/loading/error states and visual audit.
- [ ] 360×800, 768×1024, 1366×768 and 1920×1080 viewports plus 200% zoom; keyboard navigation, focus, readable errors and contrast checks.
- [ ] Three-dot menu at bottom/right edges, nested scroll containers, long labels, resize/scroll, keyboard/Escape and focus restoration; every item reachable.
- [ ] Live status without refresh; precise last heartbeat; ONLINE/STALE/OFFLINE thresholds; stream failure warning; reconnect snapshot/gap repair; Redis uncertainty does not mark whole fleet offline.
- [ ] Required campaign fields validated in client and direct API requests; inline errors/error summary retain input. Incomplete draft cannot start/publish. Failed publish cannot partially activate.
- [ ] Master/Agency role-specific navigation and assignment tasks pass usability review.

## 4. P2 media and workflow gate

- [ ] Multi-file image/video upload at and beyond size/count limits; unsupported/empty/mismatched files; byte progress and processing states; bounded concurrency and partial batch success.
- [ ] Interrupted/canceled/expired upload, per-file retry, duplicate finalize, object overwrite race, worker retry, abandoned-object cleanup and concurrent quota reservation tests.
- [ ] Selection across paging/filtering, authorized reuse without reupload, referenced-asset deletion safety and cross-tenant/brand rejection.
- [ ] Create campaign from library selection with IDs/order retained; direct Campaigns entry uses same composer; no mandatory separate playlist step.
- [ ] `FULL_CLIP`, `CUSTOM_DURATION`, `IMAGE_DEFAULT` match shared fixtures across web preview, compiler, simulator and Android; long clips truncate, short clips repeat for one configured item window.
- [ ] Save draft, stale edit conflict, repeated create/publish idempotency, inventory approval and no overselling.
- [ ] Exact schedule boundaries, tie-breaking, SOV allocation, DST gap/fold decisions and zone bindings verified against golden fixtures.

## 5. P3 offline playback and ingestion gate

- [ ] Verified cached campaign starts and continues offline; expired authorization moves to pinned standby online or offline.
- [ ] Interrupted 100 MB download, one-byte hash mutation, expired URL refresh, missing media and oversized pinned manifest cannot activate partial/unverified content.
- [ ] Kill power/process before/after local event transaction, durable rename, manifest metadata commit and activation; restore previous complete authorized state and record interrupted attempts where applicable.
- [ ] Room sequence allocator survives outbox pruning/reboot; event and counter transaction cannot diverge.
- [ ] Duplicate batch, lost ACK, timeout-after-commit, concurrent batches and altered duplicate payload preserve logical identity and billing counts.
- [ ] Cursor 102 receiving 105 returns GAP_DETECTED/expected 103. One invalid contiguous event advances only after a durable rejected disposition; valid siblings store atomically with the agreed quarantine strategy.
- [ ] Authorized epoch reset/device replacement, old-epoch replay/drain and reassignment attribution follow the contract.
- [ ] Clock rollback, reboot with invalid RTC, future/expired manifest, wrong screen/assignment, signature corruption, signing-key rotation and version rollback fail safely.
- [ ] Offline queue retention/capacity, disk full, all-assets-decode-fail and repeated network flaps have explicit safe behavior; no silent unacknowledged receipt deletion.
- [ ] Reconnection drains receipts; counts reconcile from device queue through raw archive and rollups without duplicate billing or missing dispositions.

## 6. P3 physical Android kiosk gate

Execute every scenario in document 16 §4 on each approved SKU/OS; include rooted/non-owner controls. Record provisioning method, policy configuration, firmware and limitations.

- [ ] Home/Back/Recents/gestures, notification shade/settings, keyboard/overlay escapes and authorized maintenance.
- [ ] Cold boot, offline reboot, app crash, foreground return, app update/failed update and preserved enrollment.
- [ ] Video evidence of system UI flashes with a product-approved device-specific threshold.
- [ ] Documented rooted/unrestricted limitations and accurate support classification; do not claim universal exit prevention.

## 7. P3 load, soak and operations gate

Audit the existing application's 10s polling first when its code/runtime becomes available. Proposed baseline: 60s heartbeat, 900s reconciliation, 10s single-zone playback, 30-event batches. At 10k screens: 166.67 heartbeats/s, 33.33 batches/s and 1,000 events/s; backlogs/multiple zones increase these.

| Workload | Required evidence |
| --- | --- |
| 100/1,000 screens | Baseline HTTP/WSS latency, CPU/RAM, database pool/IO, storage/event, unchanged checks |
| 5,000 screens | WSS memory/connection stability and fan-out; validate memory budget by measurement rather than assuming <250 MB total |
| 10,000 screens, 24h | Expected event totals, zero unexplained receipt loss, error/latency percentiles, DB/WAL/queue/storage growth, archive and rollup concurrency |
| 10,000 reconnects within 30s | Jitter/backoff effectiveness, bounded retries, rate-limit behavior and eventual recovery without permanent device loss |
| 72h offline backlog | Baseline 259.2M fleet events; agreed catch-up SLA, controlled drain and foreground service protection |
| Multi-zone and simultaneous publishes | Peak event amplification, compiler/version contention, asset downloads and accurate zone receipts |
| Redis/worker/database failures | Fail-closed auth, UNKNOWN presence, durable task recovery, bounded retries and demonstrated restore |

Proposed release targets: user-facing API P99 <1,000ms and unexpected 5xx <0.5% under agreed load; normal push/status transition propagation <5s after server determination. Endpoint-specific heartbeat targets and backlog-drain SLA require approval before the run. The prior <20ms heartbeat P99 is a stretch target, not a demonstrated guarantee. Reconnect rate-limiting may return retryable responses; test eventual recovery, not an unrealistic zero-rejection promise.

- [ ] Configurable interval bounds, bad-config rollback, staggered rollout, ETag/no-change responses and Retry-After behavior verified.
- [ ] Expand/backfill/contract compatibility, canary abort, WSS draining and image rollback demonstrated.
- [ ] PITR/backup/object/key restore drill measures RTO <2h and RPO <15min; archive deletion blocked until completeness verification.
- [ ] Provider prices, API operation costs, archive retention growth and infrastructure headroom validated before budget approval.

## 8. Communication and final acceptance

Calendar/message/notes delivery must be verified from actual authorized systems, not checked off because a draft exists. See COM-01–09 and the communication document.

A release report lists each requirement as Accepted, Blocked or explicitly excepted by a named approver. Attach implementation/test evidence and remaining risks. No critical/high security defect, cross-tenant access, unexplained receipt loss or incorrect-billing defect is acceptable. Document 13 defines the final release gate.
