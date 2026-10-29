# PIXL 2.0 — Requirements and Delivery Documentation

## Current state

This repository now contains a FastAPI backend, Alembic migrations, automated tests, deployment configuration, a browser simulator, and a prebuilt Android APK. The specifications below are requirements, not evidence that every feature is implemented or accepted. See the [project README](../README.md) for setup and [review findings](PROJECT_REVIEW.md) for known limitations.

Current implementation evidence: [delivery status](DELIVERY_STATUS.md).

## Reading order

1. [Requirements baseline and delivery plan](13_REQUIREMENTS_BASELINE_AND_DELIVERY_PLAN.md): scope, priorities, decisions, release gates.
2. [UI/UX and live dashboard specification](14_UI_UX_AND_LIVE_DASHBOARD_SPEC.md).
3. [Media and campaign workflow specification](15_MEDIA_AND_CAMPAIGN_WORKFLOW_SPEC.md).
4. [Android kiosk and device reliability specification](16_ANDROID_KIOSK_AND_DEVICE_RELIABILITY_SPEC.md).
5. [Requirements traceability matrix](17_REQUIREMENTS_TRACEABILITY_MATRIX.md): every supplied checklist item, acceptance criteria, planned test, status.
6. [Security and protocol implementation prerequisites](18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md).
7. [Test and acceptance plan](12_TEST_ACCEPTANCE_PLAN.md).
8. [Communication and meeting drafts](COMMUNICATION_AND_MEETING_DRAFTS.md).

## Existing architecture references

- [01 Product requirements and assumptions](01_PRODUCT_REQUIREMENTS_AND_ASSUMPTIONS.md)
- [02 User journeys](02_USER_JOURNEYS_AND_WORKFLOWS.md)
- [03 Roles and permissions](03_ROLE_PERMISSION_MATRIX.md)
- [04 Threat model](04_THREAT_MODEL_AND_SECURITY.md)
- [05 Architecture](05_SYSTEM_ARCHITECTURE.md)
- [06 Database design](06_DATABASE_ERD_AND_SCHEMA.md)
- [07 API and device protocol](07_API_AND_DEVICE_PROTOCOL_SPEC.md)
- [08 Offline playback](08_OFFLINE_SYNC_AND_PLAYBACK_SPEC.md)
- [09 Scheduling](09_SCHEDULING_AND_CONFLICT_RESOLUTION.md)
- [10 Capacity and cost estimates](10_CAPACITY_TRAFFIC_AND_COST_MODEL.md)
- [11 Operations](11_DEPLOYMENT_ROLLBACK_OPERATIONS.md)

ADRs: [001 modular monolith](adr/ADR-001-modular-monolith-fastapi.md), [002 ingestion cursor](adr/ADR-002-monotonic-pop-ingestion-cursor.md), [003 quarantine uploads](adr/ADR-003-direct-quarantine-object-storage-uploads.md), [004 frontend separation](adr/ADR-004-separate-master-agency-deployments.md), [005 signed manifests](adr/ADR-005-ed25519-signed-offline-manifests.md).

## Precedence and status

The supplied changes checklist is the product scope. Document 13 is its normalized delivery baseline; document 17 maps each individual requirement. Documents 14–16 and 18 refine older architecture examples where explicitly stated. Older SQL, JSON, algorithms, prices, and performance claims are illustrative until implemented and validated.

An accepted ADR records an architectural direction, not working software. Product decisions marked provisional require stakeholder approval. Resolve conflicts by updating the baseline, affected specs, traceability, and tests together; do not silently implement whichever example is easiest.

Status vocabulary: **Specified → Implemented → Tested → Accepted**. Blocked work records its blocker separately. Each transition requires linked evidence; all new matrix entries start at Specified.
