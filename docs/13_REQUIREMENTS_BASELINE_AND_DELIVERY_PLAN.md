# PIXL 2.0 — Requirements Baseline and Delivery Plan

## 1. Scope and evidence

Deliver a professional digital signage platform with separate Master and Agency portals, agency-scoped advertiser purchasing, streamlined media/campaign workflows, live fleet status, local offline playback and receipt synchronization, and supported Android kiosk operation.

This is a requirements baseline, not a completion report. The repository now contains backend code and automated tests; implementation remains partial. See [delivery status](DELIVERY_STATUS.md) for current evidence and outstanding work. [Document 17](17_REQUIREMENTS_TRACEABILITY_MATRIX.md) maps every checklist bullet to acceptance criteria and a planned test. Test identifiers there name future tests, not existing files.

## 2. Authoritative product decisions

### Access and ownership

- No public human registration UI or endpoint. Invitation acceptance is distinct from public signup and requires a single-use, expiring invitation.
- Only Master can create, suspend, or delete Agency administrator accounts. Agency administrators cannot create peer administrators. Agency invitations may create advertisers only; any future operator-management privilege needs an explicit permission decision.
- Master oversees all screens and explicitly assigns/reassigns them to agencies. Agency administrators manage only already-assigned screens. Pairing a device is not permission to choose its owning agency.
- Enrollment begins with a Master-authorized device assignment. The Agency may finish pairing only against that assignment. An unassigned challenge must not be claimed by an Agency. This replaces unrestricted Agency self-claim in older examples.
- Advertisers purchase agency-approved inventory and see only their own creatives, bookings, and reports. Checkout provider/currency are unresolved; manual agency purchase requests are the provisional initial flow, not a claim of implemented card checkout.
- Backend authorization is mandatory for every HTTP route, WebSocket subscription, worker job, export, and object-download authorization.

### Consistent contracts

- Canonical tenant field: `organization_id`; “agency” is the product term. Legacy `tenant_id`/`agency_id` examples must be normalized in executable contracts.
- Canonical role: `agency_operator`, not `operator`.
- Duration modes: `FULL_CLIP`, `CUSTOM_DURATION`, `IMAGE_DEFAULT`. Replace legacy `CUSTOM` in implementation contracts.
- Device media cache: provisional maximum **16 GiB**, constrained further by device capacity and a 2 GiB free-space reserve. Supersedes the older 24 GB ceiling. Media cache and durable event storage have separate budgets.
- Signed manifest validity: maximum 72 hours from issuance, not 72 hours guaranteed after any disconnection. On expiry, commercial playback stops and a pinned standby loop starts, whether online or offline.
- Master and Agency frontends use separate hostnames/deployments, with portal-local API proxy routes to the shared backend. This preserves host-only cookies; CORS alone does not isolate sessions.

## 3. Milestones and release gates

| Priority | Deliverable | Exit evidence |
| --- | --- | --- |
| P0 Security/access | Remove signup; Master-only admin lifecycle; screen assignment; tenant constraints/RLS; session isolation; secure enrollment | Positive/negative integration tests across tenants, roles, hosts, invitations, device identities; reviewed schema and auth contracts |
| P1 UI/critical bugs | Approved design system and responsive dashboards; visible menus; live presence; campaign validation | Design approval; keyboard/responsive E2E evidence; reconnect/status tests; matching client/server validation |
| P2 Feature completion | Batch upload; reusable selection; direct media-to-campaign flow; configurable duration | Mixed-file/retry tests; minimal campaign happy path; duration tests on portal and player |
| P3 Reliability/scale | Provisioned kiosk; offline recovery; configurable polling/backoff/push; fleet tests; deployment/restore drills | Target-hardware reports; offline reconciliation evidence; representative load reports; operational runbooks and restore results |

Communication requirements apply throughout. Security/data-integrity prerequisites for a feature must be completed before that feature is exposed, even when its full reliability milestone is P3. No production launch before all mandatory release gates pass.

## 4. Proposed ownership and execution

Roles below are responsibility proposals, not assignments to named people. Engineering lead must assign a person and due date before work begins.

| Workstream | Accountable role | First implementation artifact |
| --- | --- | --- |
| Scope/design | Product owner + design lead | Approved key screens and decisions log |
| Security/backend | Backend lead | Executable schema, OpenAPI, authorization tests |
| Web experience | Frontend lead | Design tokens, portal shells, workflow tests |
| Android | Android lead | Hardware matrix, provisioning and kiosk prototype |
| Infrastructure | Platform lead | Environment config, deploy/restore runbooks |
| Verification | QA lead | Test mapping, evidence store, release report |
| Team communication | Engineering lead | Calendar event, notes distribution and availability agreement |

Every task records requirement IDs, owner, dependencies, due date, status, evidence, and blocker. A completed task includes a reviewable artifact and tests; a written spec alone does not close implementation.

## 5. Decision register

| ID | Decision needed | Provisional position | Owner role / gate |
| --- | --- | --- | --- |
| D01 | Visual reference and brand identity | Use familiar app interaction clarity, not copied branding; approve design boards | Product/design / P1 |
| D02 | Android models, OS, AOSP, rooted support | Dedicated devices; managed non-rooted devices for supported secure kiosk; rooted best effort | Product/Android / before kiosk commitments |
| D03 | Purchase/payment flow and currency | Manual agency approval/request first; no automatic charging until agreed | Product/finance / before advertiser launch |
| D04 | Account/agency deletion and retention | Immediate access revocation; soft-delete operational identity; retain legally required receipts | Product/security/legal / P0 |
| D05 | Playback after expiry and emergency policy | Pinned standby indefinitely; never extend commercial authorization silently | Product / before player release |
| D06 | Reassignment with offline receipts | Versioned device assignment history; attribute receipts to original assignment | Backend/product / P0 contract |
| D07 | Heartbeat/status tuning | 60s heartbeat, 15min reconciliation, offline after 180s; configuration versioned | Platform/product / P1 status and P3 tuning |
| D08 | Meeting recurrence, organizer, link and recipients | Tuesday/Thursday 11:00–11:30 Asia/Kolkata draft; invitation not sent | Engineering lead / kickoff |
| D09 | Validated hosting prices, residency and retention | Treat document 10 figures as estimates pending provider verification | Platform/product / production budget |

These are transparent defaults, not stakeholder sign-off. Unresolved security/financial decisions block affected release gates.

## 6. Release acceptance

- Every mandatory requirement in document 17 is Accepted or has a named, approved, scoped exception.
- Tests have build/commit, environment, device/OS where relevant, timestamps, expected/actual results, and reviewer.
- No critical/high unresolved security defect; no known receipt-loss, cross-tenant access, or incorrect-billing defect.
- Capacity statements are supported by measured workload and storage results, including offline backlogs and multi-zone playback.
- Deployment, rollback, backup restore, monitoring, and incident ownership are demonstrated.
- Product/design approves the actual UI and workflow, not only screenshots of a proposal.
