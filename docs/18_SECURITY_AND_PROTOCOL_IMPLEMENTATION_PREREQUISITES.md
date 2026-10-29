# PIXL 2.0 — Security and Protocol Implementation Prerequisites

Status: Specified. This document explicitly refines older illustrative schemas and protocols. These requirements must be resolved in executable contracts before exposing affected features.

## 1. Accounts, tenant ownership and screen assignment

Only Master creates/deletes Agency administrator accounts. Provide audited create/invite, resend, suspend, revoke sessions, and delete actions; invitations are expiring/single-use and acceptance cannot select a higher role. Agency-created advertiser invitations cannot become Agency administrator invitations. No `/auth/register` public route or hidden legacy signup path.

Define soft deletion, retention and safe recovery before account deletion launches. On deletion/suspension revoke sessions, pending invitations and applicable API access; no orphaned active credentials. Prevent deleting the final active Master without a controlled recovery procedure.

Use `organization_id` consistently. Put `(organization_id, id)` unique keys on parent resources and composite ownership foreign keys on site/screen, playlist/item/media, campaign/brand, campaign/assignment/screen/group, brand/media and booking references. Tenant-owned association rows carry organization context. Declare appropriate nullable-reference deletion behavior explicitly; do not null the owning organization accidentally.

Enable and force RLS where appropriate with a non-owner, non-BYPASSRLS application role. Set tenant context transaction-locally after authentication; unset/deny missing context and test pooled-connection reuse. Define narrowly scoped Master/system access rather than accidentally bypassing all policies. Workers and exports receive authenticated/persisted scope, not a client-selected tenant. Define complete DDL for users, brands, groups, versions, layouts, bookings, payments, audit and job outboxes before calling the schema executable.

Master assignment/reassignment is atomic and audited. Agencies can finish pairing only an already authorized assignment. On reassignment, revoke old device access, terminate old subscriptions, prevent old media downloads and establish a new assignment version/epoch. Old offline receipts remain attributable to the original assignment and cannot be relabeled to the new tenant. Specify acceptance/quarantine of late receipts before enabling reassignment.

## 2. Session and deployment isolation

Serve Master and Agency bundles from distinct origins. Each portal proxies same-origin `/api` requests to the shared DigitalOcean backend with the intended portal audience. Issue host-only `__Host-` Secure/HttpOnly cookies with Path=/ and no Domain attribute; the public shared API must not silently create one common privileged browser cookie for all portals.

Verify session role and audience server-side; reject cross-panel sessions. Protect state-changing cookie-authenticated requests with validated CSRF tokens and Origin checks. CORS is an additional allowlist, not authorization or CSRF protection. Do not trust a client-supplied proxy/audience header; sanitize at ingress and derive trust from deployment routing/configuration.

Define absolute and idle session expiry, renewal/rotation, logout, password reset, invitation acceptance and MFA recovery. Bound expensive password verification and enrollment/login attempts against resource exhaustion. Use mandatory Master MFA. Revalidate revoked users/roles promptly; Redis loss must not fail open.

Only public non-secret configuration belongs in frontend build variables. Credentials, signing keys, provider keys and database URLs stay in supported server credential storage/environment. Scan built bundles, source maps, logs and CI artifacts. Test staging/production host isolation, secure backend transport, CORS/CSRF, cookie flags and forbidden cross-panel access.

## 3. Enrollment and device request authentication

Generate a device-authentication key before requesting enrollment. Bind public key/hash and a high-entropy device-held enrollment secret to the challenge at creation. The display PIN is for authorized human lookup, not sufficient credential exchange authority. Master authorizes assignment; claim is atomic and scoped.

Exchange requires proof of possession over a server nonce, challenge, assigned screen and key binding. Enforce expiry, one-time consumption and replay protection. Specify retry-safe exchange when the response is lost; do not let a second arbitrary key take over the identity. Rate-limit challenge creation, PIN lookup and exchange per IP, account/challenge and fleet policy. Normalize PIN alphabet/length consistently; the legacy `PK-8921` example is not a six-random-character entropy guarantee.

Choose a documented request-auth scheme: hardware-backed asymmetric proof of possession where supported, with short-lived scoped tokens bound to that key. Define algorithm, canonical request components (method/path/body digest/timestamp/nonce), replay window and nonce retention. A bearer-token-only compatibility profile must explicitly disclose its weaker theft resistance. Android hardware support is validated per SKU; do not assume the Ed25519 server signing key algorithm is supported in Android secure hardware.

Revocation must terminate WSS and deny subsequent HTTP requests, downloads, token refresh and enrollment reuse. Document rotation, app reinstall/device replacement, decommission and offline limitations.

## 4. Manifest format, time and activation

Before implementation, publish a versioned JSON Schema and golden cross-language fixtures. Define one exact signing representation, e.g. canonical UTF-8 JSON payload bytes, with a base64 Ed25519 signature. Include schema version, signing key ID, screen ID, assignment version, monotonic manifest version, issue/validity instants, hashes, full asset dependencies, layout/zone bindings, compiled UTC schedule and pinned fallback.

Pin the trust root in the application/provisioning chain; an arbitrary enrollment-returned public key is not automatically trusted. Define offline-verifiable rotation, overlap, retirement and compromise recovery. Reject wrong-screen/assignment, invalid signature/schema, future or expired authorization and version rollback; define explicit authorized recovery rather than accepting older manifests silently.

Keep signed content identity stable. Refresh ephemeral download URLs through a separately authenticated authorization response bound to an asset hash, rather than rewriting signed immutable manifests. All fallback asset IDs must resolve to verified dependencies.

Trusted-time rules account for wall-clock rollback, time zones, reboot and lost server-time anchors. Expiry applies online and offline; a heartbeat does not extend a signature. On uncertainty use standby under an approved policy. Stage complete files and persist activation crash-safely; preserve a previously valid manifest on failed download/validation.

## 5. Durable PoP cursor and audit boundary

- Persist a sequence allocator per device epoch independently of prunable events. Allocate and insert in one local transaction; never derive the next value solely from `MAX` of a deletable outbox.
- Bind server-authorized epochs to device identity and assignment. Document reset challenge/approval, old-epoch drain, stale-epoch rejection and recovery after Room corruption. A client cannot unilaterally reset its cursor.
- Serialize ingestion on `(screen_id, epoch)` and validate identity, assignment, schema, batch ordering, count, body size, timestamp bounds and referenced published content.
- Every contiguous sequence receives a durable disposition in the same transaction: STORED or REJECTED_TO_QUARANTINE. A poison event can advance the cursor only when its raw evidence/digest and rejection reason are durably stored. A true absent sequence returns GAP_DETECTED; a recoverable gap must not be silently skipped.
- Acknowledge only after commit. Client prunes only acknowledged sequences in the matching epoch. Retries return consistent ACK/dispositions without new billing rows. Reject or quarantine conflicting content for the same logical sequence.
- Correct event identity to `(screen_id, epoch, local_sequence)`. For time-partitioned tables, include partition key in physical uniqueness as PostgreSQL requires and use the locked cursor plus a durable disposition/identity strategy for logical deduplication. The old primary key omitting epoch is not the final design.
- Late/future timestamps need bounded acceptance/quarantine and partition management. Dropping hot partitions requires verified archive completeness and replay-safe rollups. Keep independent durable rollup/checkpoint accounting to prevent double counting after worker retry.
- If cryptographic attribution is a product requirement, define signed batch envelopes and retained signature/key metadata. A monotonic cursor and bearer token alone are not cryptographic proof of each play. Even signed client receipts do not independently prove physical pixels/display visibility.

## 6. Durable asynchronous work and operations

Persist job intent in the same database transaction as media finalize/publish. An outbox dispatcher sends retryable tasks; workers are idempotent with bounded retry/dead-letter handling. Redis Pub/Sub is lossy notification transport, not the only source of schedule truth. Reconciliation repairs missed pushes.

Separate ephemeral cache eviction from durable Celery broker/credential/session semantics; document Redis persistence, failover, session invalidation and job recovery. Presence must expose UNKNOWN during observation failure instead of declaring the fleet OFFLINE.

Choose actual orchestration before claiming zero-downtime rolling updates. Expand/backfill/contract spans separate compatible releases with explicit rollback boundaries; `alembic upgrade head --expand only` is illustrative, not a built-in migration guarantee. Define readiness/liveness, graceful WSS draining, canary sample size, alerts, image rollback and irreversible migration handling.

Add database point-in-time restore, signing-key backup/recovery, object restore, archive retention/immutability configuration, regional outage and restore-drill procedures. Measure stated RTO <2h/RPO <15min. WORM/immutability claims require demonstrated provider configuration and retention permissions, not a bucket name.
