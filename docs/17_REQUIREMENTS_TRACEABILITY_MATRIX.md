# PIXL 2.0 — Requirements Traceability Matrix

## Reading this matrix

Each row maps one bullet from the supplied 11-section checklist, in order. The hierarchy sub-bullets are included in AUTH-04. IDs are stable; tests named below are planned and do not exist yet. All rows are **Specified**, not Implemented, Tested or Accepted. Proposed owner roles and delivery gates are in document 13; assign named owners/dates before implementation.

References: [B = baseline](13_REQUIREMENTS_BASELINE_AND_DELIVERY_PLAN.md), [U = UI/live status](14_UI_UX_AND_LIVE_DASHBOARD_SPEC.md), [M = media/campaign](15_MEDIA_AND_CAMPAIGN_WORKFLOW_SPEC.md), [K = kiosk/reliability](16_ANDROID_KIOSK_AND_DEVICE_RELIABILITY_SPEC.md), [S = security prerequisites](18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md), [T = test plan](12_TEST_ACCEPTANCE_PLAN.md), [C = communication](COMMUNICATION_AND_MEETING_DRAFTS.md).

## 1. UI/UX redesign

| ID | Requirement and measurable acceptance | Priority | Spec | Planned test/evidence | Status |
| --- | --- | --- | --- | --- | --- |
| UX-01 | Redesign existing dashboard; product/design approve actual Master and Agency key screens as client-ready | P1 | U §1 | UI-01 design review + E2E walkthrough | Specified |
| UX-02 | Use polished application references; approve reference boards and rationale before implementation | P1 | U §1 | UI-02 approved boards | Specified |
| UX-03 | Shared typography, spacing, colors, buttons, forms and navigation tokens/components used on all key screens | P1 | U §2 | UI-03 component inventory/visual review | Specified |
| UX-04 | No generic purple/blue gradients, excessive rounded cards or gratuitous box layouts; approved visual audit | P1 | U §1 | UI-04 visual audit | Specified |
| UX-05 | Responsive, polished navigation; no page overflow at four target viewports or 200% zoom | P1 | U §3–4 | UI-05 responsive/keyboard E2E | Specified |
| UX-06 | Media three-dot menu options reachable at viewport bottom without clipping | P1 | U §5 | UI-06 bottom-edge menu E2E | Specified |
| UX-07 | Master dashboard tasks discoverable, coherent and approved through role-specific walkthrough | P1 | U §1–3 | UI-07 Master workflow review | Specified |
| UX-08 | Agency dashboard tasks discoverable, coherent and approved through role-specific walkthrough | P1 | U §1–3 | UI-08 Agency workflow review | Specified |

The checklist's final UI bullet covers both dashboards; UX-07 and UX-08 deliberately split it for separate acceptance evidence.

## 2. Authentication and access control

| ID | Requirement and measurable acceptance | Priority | Spec | Planned test/evidence | Status |
| --- | --- | --- | --- | --- | --- |
| AUTH-01 | Login has no public registration link/form or reachable alternate signup route | P0 | B §2; S §1 | SEC-01 frontend route/navigation tests | Specified |
| AUTH-02 | Public registration backend endpoint/logic removed; legacy route attempts cannot create users | P0 | S §1 | SEC-02 endpoint/route inventory tests | Specified |
| AUTH-03 | Only Master creates/deletes Agency admins; deletion revokes sessions/invites and is audited | P0 | B §2; S §1 | SEC-03 lifecycle positive/negative tests | Specified |
| AUTH-04 | Master manages global screens/admins and assignments; Agency accesses assigned resources only; advertiser purchases through Agency and sees own data | P0 | B §2; S §1 | SEC-04 full role/tenant/brand/assignment matrix | Specified |
| AUTH-05 | Backend denies forbidden HTTP, WSS, exports/jobs/downloads even when UI is bypassed | P0 | S §1–3 | SEC-05 direct requests and worker scope tests | Specified |
| AUTH-06 | Master and Agency run on distinct hosts/deployments with audience-isolated sessions | P0 | S §2 | SEC-06 cross-panel session/CSRF tests | Specified |

## 3. Dashboard improvements

| ID | Requirement and measurable acceptance | Priority | Spec | Planned test/evidence | Status |
| --- | --- | --- | --- | --- | --- |
| DASH-01 | Status automatically updates via push or asynchronous polling, normally within 5s of server transition | P1 | U §6 | LIVE-01 asynchronous transition test | Specified |
| DASH-02 | Fleet status changes without manual page refresh; loss of live transport is visible | P1 | U §6 | LIVE-02 no-reload/browser-disconnect test | Specified |
| DASH-03 | Show latest server-received heartbeat, exact last-seen time and connection status | P1 | U §6 | LIVE-03 timestamp/status rendering test | Specified |
| DASH-04 | After outage, snapshot reconciliation repairs stale dashboard state without false mass-offline on Redis loss | P1 | U §6–7 | LIVE-04 reconnect/observation failure test | Specified |
| DASH-05 | Offline PoP backlog drains after reconnect; displayed sync totals reconcile without duplicate billing | P3 | U §7; K §5; S §5 | LIVE-05 receipt count reconciliation | Specified |

## 4. Media library and uploads

| ID | Requirement and measurable acceptance | Priority | Spec | Planned test/evidence | Status |
| --- | --- | --- | --- | --- | --- |
| MEDIA-01 | Upload multiple files with per-file state, bounded concurrency and independent retry | P2 | M §1 | MED-01 mixed batch/partial failure tests | Specified |
| MEDIA-02 | Create campaign directly from selected READY media, preserving selected IDs/order | P2 | M §3 | MED-02 library-to-composer E2E | Specified |
| MEDIA-03 | Three-dot action menu flips/repositions and remains keyboard-accessible on scroll/resize | P1 | U §5 | MED-03 menu position/focus tests | Specified |
| MEDIA-04 | Search/select/reuse authorized media across playlists/campaigns without reupload | P2 | M §2 | MED-04 reuse/permissions/references tests | Specified |
| MEDIA-05 | Upload progress, authoritative validation and actionable retry/errors distinguish upload from processing | P2 | M §1 | MED-05 progress/invalid file/retry tests | Specified |

## 5. Campaign creation and management

| ID | Requirement and measurable acceptance | Priority | Spec | Planned test/evidence | Status |
| --- | --- | --- | --- | --- | --- |
| CAMP-01 | Focused composer avoids mandatory separate playlist creation; required happy path accepted by product | P2 | M §3 | CAM-01 simplified workflow review/E2E | Specified |
| CAMP-02 | Direct media-library entry opens the same composer with preselected media | P2 | M §3 | CAM-02 direct-entry consistency test | Specified |
| CAMP-03 | Campaign form validates required fields; incomplete draft cannot publish | P1 | M §4 | CAM-03 missing-field UI/API tests | Specified |
| CAMP-04 | Missing information produces readable inline errors and accessible summary, retaining inputs | P1 | M §4 | CAM-04 error/focus/retention E2E | Specified |
| CAMP-05 | Video full/custom modes and explicit image timing work; custom clips truncate/repeat as specified | P2 | M §5 | CAM-05 portal/simulator/Android fixtures | Specified |
| CAMP-06 | Server validates create-draft minimum and all publish/start conditions; no partial activation on failure | P1 | M §4–6 | CAM-06 tampered request/atomic publish tests | Specified |
| CAMP-07 | Dashboard review, compiler and display use same schema/duration/zone/time semantics | P2 | M §5–6 | CAM-07 cross-client golden fixtures | Specified |

## 6. Android display application and kiosk mode

| ID | Requirement and measurable acceptance | Priority | Spec | Planned test/evidence | Status |
| --- | --- | --- | --- | --- | --- |
| KIOSK-01 | Research and implement stronger exit lock on supported managed devices; publish compatibility report | P3 | K §1–3 | AND-01 source report + physical prototype | Specified |
| KIOSK-02 | Normal navigation cannot leave signage on approved provisioned devices except authorized maintenance | P3 | K §3–4 | AND-02 navigation/escape-path tests | Specified |
| KIOSK-03 | Evaluate Lock Task Mode/device-owner provisioning and document reproducible supported setup | P3 | K §2–3 | AND-03 clean-device provisioning test | Specified |
| KIOSK-04 | Home, Back, Recents and restart behavior recorded on every supported SKU/OS | P3 | K §4 | AND-04 hardware input/reboot matrix | Specified |
| KIOSK-05 | Minimize foreground system UI flash; record observed duration and product approval per device | P3 | K §3–4 | AND-05 screen recordings | Specified |
| KIOSK-06 | Test rooted and non-rooted devices; identify unsupported enforcement combinations | P3 | K §1,4 | AND-06 root-state matrix | Specified |
| KIOSK-07 | Explicitly document inability to guarantee exit prevention on rooted/unrestricted hardware | P3 | K §1 | AND-07 support/limitations review | Specified |

The supplied kiosk section has seven top-level bullets. KIOSK-01–07 map them in order.

## 7. Offline playback and synchronization

| ID | Requirement and measurable acceptance | Priority | Spec | Planned test/evidence | Status |
| --- | --- | --- | --- | --- | --- |
| OFF-01 | Verified cached content plays without internet until authorization expiry, then standby | P3 | K §5 | OFFT-01 offline/expiry playback test | Specified |
| OFF-02 | Configured campaign starts after complete verified download; incomplete replacement retains valid playback | P3 | M §6; K §5 | OFFT-02 first-start/staged activation tests | Specified |
| OFF-03 | Offline receipts and sequence counter survive app kill/reboot without silent loss | P3 | K §5; S §5 | OFFT-03 Room/power-loss tests | Specified |
| OFF-04 | Reconnect drains ordered queue with ACK-only pruning and no duplicate billing | P3 | S §5 | OFFT-04 retry/ACK-loss/gap/poison tests | Specified |
| OFF-05 | Interrupted downloads, missing/corrupt media and network failures cannot activate partial assets | P3 | K §5 | OFFT-05 download/hash/cache-pressure tests | Specified |
| OFF-06 | Repeated online/offline transitions preserve playback, receipt ordering and accurate state | P3 | U §7; K §5 | OFFT-06 network-flap chaos test | Specified |

## 8. Backend scalability and polling

| ID | Requirement and measurable acceptance | Priority | Spec | Planned test/evidence | Status |
| --- | --- | --- | --- | --- | --- |
| SCALE-01 | Audit actual existing 10s heartbeat/content check and capture baseline requests/payloads | P3 | K §6 | LOAD-01 baseline audit/report | Specified |
| SCALE-02 | Heartbeat/reconciliation intervals configurable within server-validated bounds; bad config retains safe default | P3 | K §6 | LOAD-02 config validation/rollout test | Specified |
| SCALE-03 | Measure backend at increasing fleet sizes including storage, operators, zones and offline backlog | P3 | K §7 | LOAD-03 representative capacity report | Specified |
| SCALE-04 | Unchanged manifest checks avoid recompilation/media download using version/ETag/no-change response | P3 | K §6 | LOAD-04 unchanged-content request test | Specified |
| SCALE-05 | Reconnect/full-jitter backoff and push evaluated; no synchronized retry storm | P3 | K §6–7 | LOAD-05 10k reconnect/fan-out test | Specified |
| SCALE-06 | Heartbeat endpoint stays efficient under concurrent load with bounded DB writes/pool use | P3 | K §7 | LOAD-06 heartbeat latency/resource test | Specified |
| SCALE-07 | Content-check endpoint stays efficient under concurrent unchanged/changed workloads | P3 | K §6–7 | LOAD-07 manifest latency/cache test | Specified |

The final scalability bullet is split into SCALE-06 and SCALE-07 for independent endpoint evidence.

## 9. Deployment and environment separation

| ID | Requirement and measurable acceptance | Priority | Spec | Planned test/evidence | Status |
| --- | --- | --- | --- | --- | --- |
| DEP-01 | Distinct Master/Agency URLs and deployable frontend artifacts | P0 | B §2; S §2 | ENV-01 host/artifact inspection | Specified |
| DEP-02 | Correct per-deployment audience, role permissions and validated configuration | P0 | S §2 | ENV-02 wrong-config/role tests | Specified |
| DEP-03 | Both panels use secured portal proxies to shared DigitalOcean backend | P0 | S §2 | ENV-03 TLS/routing integration test | Specified |
| DEP-04 | Test authentication, authorization and APIs across hosts/environments; no cross-panel session escalation | P0 | S §2 | ENV-04 cross-host auth suite | Specified |
| DEP-05 | Frontend bundles/source maps contain no secrets; only approved public settings exposed | P0 | S §2 | ENV-05 bundle/CI secret scanning | Specified |

## 10. Testing and quality assurance

| ID | Requirement and measurable acceptance | Priority | Spec | Planned test/evidence | Status |
| --- | --- | --- | --- | --- | --- |
| QA-01 | Positive/negative Master/Agency and unassigned/cross-tenant screen permission tests pass | P0 | S §1; T | QA-T01 security report | Specified |
| QA-02 | Frontend/backend public registration removal tests pass, including legacy paths | P0 | S §1; T | QA-T02 signup removal report | Specified |
| QA-03 | Mixed-type/large-file batch, partial failure and quota tests pass | P2 | M §1,7; T | QA-T03 upload report | Specified |
| QA-04 | Mandatory campaign fields and direct API bypass tests pass | P1 | M §4; T | QA-T04 validation report | Specified |
| QA-05 | Library-to-campaign selection and publish tests pass | P2 | M §3; T | QA-T05 workflow report | Specified |
| QA-06 | Dashboard auto-update, disconnect and recovery tests pass without refresh | P1 | U §6–7; T | QA-T06 live-status report | Specified |
| QA-07 | Offline playback, receipt reconciliation and power-loss tests pass | P3 | K §5; S §5; T | QA-T07 offline integrity report | Specified |
| QA-08 | Kiosk tests executed on approved physical hardware; limitations approved | P3 | K §4; T | QA-T08 device matrix/report | Specified |
| QA-09 | UI passes target screen-size/resolution/zoom and keyboard checks | P1 | U §4–5; T | QA-T09 responsive evidence | Specified |
| QA-10 | Simulated high-device workload, soak and reconnect/backlog tests pass agreed thresholds | P3 | K §7; T | QA-T10 load report | Specified |

## 11. Communication and project management

| ID | Requirement and measurable acceptance | Priority | Spec | Planned test/evidence | Status |
| --- | --- | --- | --- | --- | --- |
| COM-01 | Organizer sends check-in calendar invitation with confirmed recurrence/timezone and working link | Continuous | B §5; C | TEAM-01 sent event/link evidence | Specified |
| COM-02 | Aniket required, Aayog optional on actual invitation | Continuous | C | TEAM-02 attendee flags verified | Specified |
| COM-03 | Approved meeting notes shared with Raj via authorized channel | Continuous | C | TEAM-03 delivery record | Specified |
| COM-04 | Relevant Granola notes sent to authorized relevant team members after review | Continuous | C | TEAM-04 recipient/delivery record | Specified |
| COM-05 | Slack response expectations agreed; absence announced in advance where possible | Continuous | C | TEAM-05 agreement and availability posts | Specified |
| COM-06 | Exams/other commitments have timely availability updates and handoff | Continuous | C | TEAM-06 availability/handoff evidence | Specified |
| COM-07 | Tasks have owner/deadline; blockers proactively reported with impact and next action | Continuous | B §4; C | TEAM-07 task/blocker review | Specified |
| COM-08 | Early completion reported promptly with artifacts/test evidence rather than waiting for meeting | Continuous | C | TEAM-08 completion update | Specified |
| COM-09 | Work includes user/product acceptance criteria and proactive clarification of ambiguity | Continuous | B §4–6; C | TEAM-09 task/decision review | Specified |

## Evidence ledger template

For each requirement: `ID | named owner | due date | implementation artifact/commit | test/environment/device | timestamp | result | reviewer | acceptance/exception | blocker`.

No external calendar event, Slack message, Granola sync, implementation or passing test is asserted by this matrix. QA rows require evidence from the underlying feature tests rather than duplicate untraceable check marks.
