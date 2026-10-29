# PIXL 2.0 — Media and Campaign Workflow Specification

Status: Specified. Scope: MEDIA-01–05, CAMP-01–07. Existing direct-quarantine architecture remains the foundation; this document adds user workflows and acceptance rules.

## 1. Batch uploads

Allow multi-file picker and drag/drop from Media Library. One batch contains independent per-file tickets and results; one failed file must not fail successful siblings. Proposed initial guardrails: 50 files per selection, 3 concurrent uploads per browser session; enforce server-side quotas/rate limits independently. Values require product/operations approval.

Per-file states: SELECTED → VALIDATING → WAITING → UPLOADING → PROCESSING → READY, or FAILED/CANCELED. Show filename, size, progress, state and actionable error; aggregate progress is byte-weighted and distinguishes upload completion from media readiness. Retry failed items only; do not duplicate completed assets. Cancel before transfer or abort an active transfer; already-processing media needs an explicit delete/cancel policy.

Baseline limits: video ≤250 MB, image ≤20 MB. Exact allowed MIME/container/codec profiles follow the approved hardware matrix. Client checks improve feedback; backend and worker validation are authoritative. Do not trust filename, browser MIME, declared size or client hash.

### Upload API behavior

- Existing ticket/finalize operations may be called once per file; batch orchestration does not require bundling binaries through the API.
- Ticket creation atomically reserves organization storage quota, records expected size/type, actor and expiry, and assigns a unique non-user-controlled quarantine key.
- Verify actual object existence/size and ticket ownership at finalize. Repeated finalize is idempotent and returns the same media job. Reject expired, mismatched, cross-tenant and already-consumed incompatible requests.
- Release reservations on failure/expiry; cleanup abandoned objects with lifecycle jobs. Quotas must withstand concurrent batches.
- Prevent an upload URL being reused to mutate content while a worker validates it: use version-pinned input or a server-controlled immutable copy before processing. Publish only verified output.
- Persist task dispatch through a transactional outbox; workers are idempotent. Bound CPU, memory, execution time, output size and network access. MIME/magic-byte checks alone do not prove a file harmless.
- Never expose quarantine objects, bearer credentials, signed URLs or raw processing internals in logs or frontend bundles.

## 2. Media library and reuse

Provide search, type/status filters, grid/list views, previews, selection count, clear selection, and persistent selected IDs when paging. Campaign creation accepts READY assets only. Explain unavailable actions on PROCESSING/FAILED items.

Reuse existing asset identities across playlists and campaigns without reupload. Deletion is blocked or explicitly version-safe when assets are referenced by active/pending manifests. Brand users may select only their own authorized creatives. Menu behavior follows [document 14](14_UI_UX_AND_LIVE_DASHBOARD_SPEC.md).

## 3. Direct media-to-campaign flow

A selected media item or selection exposes **Create campaign**. Open the composer with those assets preselected in selection order; do not force the user to create a reusable playlist first. Campaign navigation offers the same composer with an asset picker. Saving a reusable playlist is optional.

Minimum happy path: select ready media → Create campaign → supply name, targets, schedule and duration choices → review validation → publish. Keep required information together in a focused composer; optional advanced options are progressively disclosed. Save draft and Publish are distinct; never lose user input after validation/server errors.

## 4. Validation contract

| Field/condition | Draft behavior | Publish/start requirement |
| --- | --- | --- |
| Name | Required, trimmed, proposed 1–120 characters | Required |
| Media | May be incomplete | At least one authorized READY asset, playable on target hardware |
| Targets | May be incomplete | At least one assigned screen/group; all resolve within owning organization |
| Schedule | May be incomplete | Valid start/end instants, end > start; valid site/timezone/day-part rules; no unsupported ambiguity |
| Duration | Preserve edits | Supported mode and valid positive duration where required |
| Layout/zones | Optional default full-screen | Valid geometry, item-zone bindings, supported decode/audio limits |
| Inventory/approval | Editable request | Required booking approval/capacity checks pass; no overselling |
| Dependencies | Report warnings | Published asset hashes, fallback, cache budget and manifest compilation succeed |

Frontend validates before submission; backend repeats all rules regardless of client. Return stable field paths and error codes with readable messages, e.g. `schedule.end_time: END_BEFORE_START`. Focus an error summary, associate inline errors, retain valid inputs. A failed publish must not partially activate a campaign. Drafts must not be mistaken for runnable content.

Use version/ETag conflict checks to avoid lost edits. Repeated create/publish with an idempotency key must not create duplicate campaigns, bookings or manifest versions. Record actor, organization, version and audit event.

## 5. Playback duration semantics

Canonical modes, shared by API, database, web preview, simulator and Android:

- `FULL_CLIP`: video advances at native end; duration derived from verified metadata. No arbitrary default truncation.
- `CUSTOM_DURATION`: positive configured milliseconds; longer video is truncated, shorter video repeats until the configured item window ends. Log one item-window receipt, not a billable event per internal repeat.
- `IMAGE_DEFAULT`: image uses configured positive milliseconds, default 10,000ms.

Provisional custom/image bounds: 1,000–300,000ms. Product may revise limits through a versioned shared contract. Show expected behavior before publication, including looping/truncation. Network state must not alter duration semantics. Record intended duration, actual duration, outcome and interruption reason; emergency/schedule preemption is not automatically a completed paid impression.

## 6. Compilation and delivery consistency

Validate using the same versioned schema across portal, compiler and players. Compile UTC interval boundaries at every relevant start/end/day-part change, not hour-sized approximations. Define deterministic priority/ties and budgeted share-of-voice before selling guaranteed inventory. Resolve DST nonexistent/ambiguous local times explicitly in the composer; do not silently duplicate paid plays.

Compiler atomically allocates monotonic per-screen manifest versions, snapshots approved media/layout/assignment dependencies, and signs immutable content. Manifest schedule items bind to zones; every fallback reference must appear in asset dependencies. Devices stage all required files, verify signature/hashes, and atomically activate a complete manifest while retaining the previous valid one on failure.

Acceptance compares the portal review, compiled schedule, simulator and Android against shared golden fixtures, including custom duration, image timing, boundary preemption, timezone changes and expired manifests.

## 7. Required feature tests

Mixed images/videos; unsupported/oversized/empty files; network failure; expired URL; canceled upload; duplicate finalize; concurrent quota reservations; worker retry; upload overwrite race; cross-tenant selection; partial batch success; referenced-media deletion; campaign-from-library; empty/invalid publish; save-draft; stale edit conflict; repeated publish; offline start after complete download; incomplete download retaining the previous manifest; duration modes on target devices.
