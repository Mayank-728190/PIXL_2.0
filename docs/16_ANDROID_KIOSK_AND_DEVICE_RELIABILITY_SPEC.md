# PIXL 2.0 — Android Kiosk and Device Reliability Specification

Status: Specified. Scope: KIOSK-01–07, OFF-01–06, SCALE-01–07. This is an implementation/research plan, not a verified Android compatibility claim. External Android/OEM documentation has not been researched as part of writing this baseline.

## 1. Supported security boundary

A normal application cannot guarantee exit prevention on every device. Strong kiosk support targets approved, managed, non-rooted hardware using Android device-owner provisioning and Lock Task Mode where supported. Screen pinning or immersive UI alone is not a security boundary. Rooted/unrestricted hardware is best effort and must be reported as unsupported for strong enforcement; do not promise resistance to root, firmware changes, recovery, physical power removal, or factory reset.

Baseline Android 9+ remains provisional pending hardware validation. Do not assume Play Services, StrongBox, a particular codec, or Ed25519 hardware key support across all AOSP devices. Device authentication key choice is separate from server manifest signing.

## 2. Research/prototype deliverables

Before implementation commitments, inspect current official Android provisioning/Lock Task documentation and approved OEM guidance. Record URLs, retrieval dates and OS/API differences in a compatibility report. Follow configured research-provider policy. A proposal or source citation does not replace physical-device testing.

For each target SKU/firmware, record: Android/API, AOSP/GMS, owner-provisioning path and reset prerequisites, supported DevicePolicyManager restrictions, lock-task allowlisting, launcher/boot behavior, system UI behavior, codec support, available storage, hardware-backed key support, root state and remote maintenance capability.

Compare factory-reset QR/enterprise provisioning, supported installer/ADB lab provisioning and OEM management. Production provisioning must not depend on an undocumented developer-only shortcut.

## 3. Managed kiosk behavior

- Provision a device-owner/DPC arrangement supported by approved hardware; allowlist the signage package for Lock Task Mode. Record provisioning result and enrollment identity.
- Enter the supported kiosk mode after enrollment; maintain a dedicated launcher/boot flow where platform policy permits.
- Home, Back, Recents and navigation gestures must not leave the approved signage experience on supported managed devices. Test notification shade, settings shortcuts, overlays and external keyboard navigation as well.
- Apply least-privilege restrictions; do not blindly disable emergency, accessibility or required maintenance features.
- On restart or app/process crash, recover the last valid manifest and resume without operator login/network when content remains authorized.
- Use supported immersive/system-bar APIs and lifecycle handling to minimize foreground-return flashes. Measure visible flashes with recordings; zero flash is a hardware-dependent target, not an unconditional guarantee.
- Provide an authenticated, audited maintenance/exit flow for authorized technicians. No hardcoded universal exit PIN. A short-lived device-scoped authorization may be cached only under an explicitly approved offline maintenance policy.
- Package updates must preserve identity, counter, manifests and cache; failed update rolls back safely where supported. Decommission revokes identity and removes tenant data according to policy.

## 4. Kiosk acceptance matrix

Run on every approved non-rooted SKU/OS and representative rooted/unrestricted samples. Record pass/fail and limitations, not a universal Android result.

| Scenario | Managed supported-device expectation |
| --- | --- |
| Home/Back/Recents, gestures, repeated input | Remains in signage or authorized maintenance only |
| Notification shade/settings/keyboard shortcuts | Restricted according to approved policy |
| Cold boot/reboot with and without internet | Automatic player recovery; no unexpected public launcher access |
| Force process termination/decoder crash | Controlled recovery without receipt corruption |
| Foreground return | Minimum achievable system UI exposure recorded; product-approved threshold |
| App update/failed update | Preserves enrollment and durable playback state |
| Rooted/non-owner device | Explicit weak-enforcement warning and documented escape paths |
| Authorized maintenance | Scoped authorization, audit, timeout and reliable return to kiosk |

Kiosk prototype should run early; complete reliability acceptance is P3. Unsafe device-exit assumptions cannot be hidden by a late milestone.

## 5. Offline playback and receipt durability

1. Cache by verified SHA-256, not expiring URL. Download to temporary files, bound size/time, check size/hash and durably promote before use. Clean abandoned temporary files; refresh expired URLs through authenticated asset authorization.
2. Enforce the 16 GiB maximum, device free-space reserve, and separate outbox budget from document 13. Pin active/staged and fallback dependencies. Reject an oversized manifest before replacing the active one; never evict active media to partially stage a replacement.
3. Preserve complete manifests and use atomic activation with crash-safe persisted active-version metadata. Missing/corrupt content retains previous valid playback or standby; partial content is never played.
4. Test initial campaign start after complete download, power loss at each activation step, network interruption, decoder failure, all-assets-failed fallback and online/offline transitions.
5. Maintain a durable per-epoch sequence allocator independent of outbox pruning; write counter advancement and event insertion in one Room transaction. Persist playback start/checkpoint where needed to report interrupted attempts after process death.
6. On reconnect, drain ordered batches with bounded concurrency, ACK-based pruning, retry jitter and no duplicate billing. See document 18 for poison events and epoch recovery.
7. Manifest authorization expires at signed `valid_until` regardless of network state. Use a trusted server-time anchor and elapsed time where possible; detect rollback/reboot uncertainty. If valid time cannot be established, use standby rather than silently extending commercial authorization.
8. Reserve event capacity for at least the approved offline window and catch-up delay; measure actual bytes/event. A 10s single-zone loop creates 25,920 events over 72 hours per screen. Multi-zone/error events increase this. Never silently discard unacknowledged events on disk exhaustion; alert, preserve evidence and apply an approved degraded-operation policy.

## 6. Configurable heartbeat and reconciliation

First inspect the actual existing application's 10-second heartbeat/content polling; it is not present in this repository. Capture baseline request rate, payloads, latency and behavior before changing it.

Proposed defaults: heartbeat 60s, manifest reconciliation 900s, reconnect backoff exponential full jitter from 1s up to 300s. Proposed supported config bounds: heartbeat 15–300s, reconciliation 60–3,600s. Validate centrally, version config, retain last-known-good settings, and prevent a fleet-wide config change from synchronizing requests. Timing applies to the foreground managed player; do not assume WorkManager provides exact periodic deadlines.

Use WSS for manifest invalidation, with periodic reconciliation to repair dropped Pub/Sub messages. Use version/ETag requests and a no-change response (e.g. 304 for matching If-None-Match), no repeated compilation or asset downloads when unchanged. Honor Retry-After, bound timeouts and concurrent downloads/uploads. Jitter heartbeat/flush/reconciliation phases. Device config cannot disable mandatory authorization or receipt durability.

## 7. Load verification and capacity corrections

For 10,000 single-zone devices and 10-second items: 1,000 events/s, 86.4M/day; 30-event batches produce about 33.33 requests/s; 60s heartbeats produce 166.67/s. A 10s heartbeat instead produces 1,000/s. A 5-minute timer does not guarantee these averages if batches are smaller, multi-zone events grow, or devices reconnect together.

Hot retention is 1.2096 billion events over 14 days. At 200 bytes/event, payload alone is ~241.92 GB decimal, before indexes, WAL, replicas, backups and headroom. A 72h fleet outage creates 259.2M baseline queued events. Specify catch-up SLA and rate budget before declaring capacity sufficient.

Benchmark 100/1,000/5,000/10,000 devices, publish fan-out, unchanged checks, concurrent operators, multi-zone playback, archive/rollup jobs, reconnect herd and bounded backlog drain. Measure CPU, memory, DB pools/locks/IO, WAL, storage growth, queue age and receipt reconciliation, not just average HTTP RPS. Report P50/P95/P99 and errors. The old cost model and latency targets remain unverified until provider pricing and representative tests support them.
