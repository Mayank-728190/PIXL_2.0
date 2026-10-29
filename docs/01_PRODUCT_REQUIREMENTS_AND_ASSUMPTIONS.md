# PIXL 2.0: Product Requirements & Engineering Assumptions

> **Status: planning only.** Product scope and provisional decisions are normalized in [document 13](13_REQUIREMENTS_BASELINE_AND_DELIVERY_PLAN.md), with item-by-item acceptance in [document 17](17_REQUIREMENTS_TRACEABILITY_MATRIX.md). Architectural objectives below are targets, not demonstrated capabilities.

## 1. System Vision and Objectives
PIXL 2.0 is a multi-tenant, enterprise-grade digital signage platform designed to reliably support from 100 up to **10,000 concurrently connected screens**. The architecture prioritizes:
1. **Security & Zero-Trust Tenant Isolation**: No cross-tenant data leakage; strict separation between Master/Super-Admin, Agency Administrators, and Brand/Advertiser users.
2. **Deterministic Playback & Verifiable Proof-of-Play (PoP)**: Every ad played on every screen produces a cryptographically attributable, monotonically sequenced business event.
3. **Resilient Offline Operation**: Screens must continue seamless loop playback according to compiled local schedules even during extended network outages (up to 72 hours).
4. **Low Operational Overhead & Cost**: Zero egress fees via Cloudflare R2, batched database ingestion, and lean containerized infrastructure instead of premature microservice sprawl.
5. **Measurable Scalability**: Designed and benchmarked specifically for 10,000 active devices generating ~86.4M playback events per day.

---

## 2. Unresolved Product Questions & Engineering Baselines

The following matrix documents critical business variables, our baseline engineering assumptions, and the exact decisions required from stakeholders:

| Domain | Baseline Engineering Assumption | Stakeholder Decision Required / Options | Impact on Architecture |
| :--- | :--- | :--- | :--- |
| **Target Android Hardware** | Android 9.0+ (API 28+) up to Android 14 (API 34). Dedicated signage boxes (Rockchip RK3399/RK3568, Amlogic S905X4, Philips/Sony Commercial Displays). | Confirm whether consumer Android TV sticks (e.g. Fire TV) or non-Google AOSP devices must be supported. | Determines whether Google Play Services can be assumed, or if pure AOSP Device Owner provisioning via ADB/NFC/QR is mandatory. |
| **Asset Profiles & Media Quotas** | 1080p @ 60fps (H.264/H.265) and 4K @ 30fps. Max asset size: 250 MB for video, 20 MB for image. Max storage per device: 16 GB cache. | Confirm maximum supported video bitrate (default: 15 Mbps) and container support (MP4/MKV/WebM). | Dictates worker transcoding profiles, FFmpeg CPU budgeting, and device storage eviction policies. |
| **Update Latency SLA** | **Soft real-time**: < 5 seconds for push notification via WebSocket. Manifest download & validation: < 60 seconds over stable connection. | What is the maximum acceptable delay between an Agency clicking "Publish" and the screen displaying new content? | Governs WebSocket connection pooling, CDN cache-invalidation TTLs, and push fan-out queue architecture. |
| **Max Offline Duration** | **72 hours** default offline manifest validity. After 72 hours, screen transitions to fallback agency emergency/standby loop. | Should screens ever display black screen, or loop fallback media indefinitely until re-connected? | Defines cryptographic manifest TTL (`valid_until` timestamp) and offline security risk appetite. |
| **Playback Log Retention** | Hot DB (PostgreSQL): 14 days.<br>Hourly Aggregates: 365 days.<br>Raw Archives (Compressed JSONL/Parquet on R2): 3 years. | Are raw millisecond-level receipts legally required for advertiser auditing beyond 90 days? | Sizes PostgreSQL disk IOPS and storage growth; defines when/if ClickHouse or Athena querying is introduced. |
| **Billing & Payments** | Manual Agency credit invoicing and optional Stripe/Razorpay direct card checkout for Brand self-serve slots. | Confirm primary currency (USD / INR / EUR) and whether payment gateways must support split payments / marketplace escrows. | Dictates ACID transaction boundaries for inventory reservations, tax handling, and webhook reconciliation workflows. |
| **Availability (RTO / RPO)** | SLA: 99.9% uptime.<br>RTO (Recovery Time Objective): < 2 hours.<br>RPO (Recovery Point Objective): < 15 minutes (continuous WAL archiving). | Confirm acceptable downtime window during database migrations or catastrophic cloud provider outages. | Influences multi-region disaster recovery vs single-region active-standby database topology. |
| **Media Visibility** | **Private**: All media stored in private Cloudflare R2 buckets. Devices receive short-lived pre-signed download URLs. | Should media URLs be public with unguessable hashes, or strictly authenticated/signed? | Pre-signed URLs require devices to decouple asset cache keys (`sha256_hash`) from ephemeral download URLs. |
| **Tenant Scale** | 100 Agencies, 2,500 Brands, 10,000 Screens, 200 concurrent web dashboard operators. | Confirm if any single agency will control > 50% of the entire screen fleet. | Affects database indexing, sharding keys, and WebSocket channel fan-out limits. |
| **Data Residency** | Single primary datacenter region (e.g., DigitalOcean Bangalore or Frankfurt) with global edge delivery via Cloudflare. | Are there strict national sovereign data residency requirements for ad playback logs? | Governs whether raw playback events must be physically partitioned into localized storage buckets. |

---

## 3. Product Roles & Tenancy Structure

```
                      ┌────────────────────────────────────────┐
                      │        Master / Super Admin            │
                      │  - Global Fleet Observability          │
                      │  - Agency Provisioning & Suspension    │
                      │  - Screen Enrollment Oversight         │
                      │  - Platform Configuration & Audits     │
                      └──────────────────┬─────────────────────┘
                                         │ Provisions & Assigns Screens
                                         ▼
                      ┌────────────────────────────────────────┐
                      │          Agency Administrator          │
                      │  - Manages Assigned Screens & Groups   │
                      │  - Media Library & FFmpeg Transcoding  │
                      │  - Playlists & Scheduling Engine       │
                      │  - Brand Management & Booking Approvals│
                      │  - Proof-of-Play Verification Reports  │
                      └──────────────────┬─────────────────────┘
                                         │ Invites & Sells Inventory
                                         ▼
                      ┌────────────────────────────────────────┐
                      │          Brand / Advertiser            │
                      │  - Submit Creative Assets              │
                      │  - Browse Agency-Approved Inventory    │
                      │  - Reserve / Purchase Ad Slots         │
                      │  - Audit Campaign Delivery Proofs      │
                      └────────────────────────────────────────┘
```

---

## 4. Architectural Decision Rules for Tenancy
1. **No Shared Database Leaks**: Every query filtering tenant-owned resources (`screens`, `media`, `playlists`, `campaigns`, `bookings`) must bind `tenant_id` at the database level.
2. **Explicit Foreign Key Ownership**: Subordinate resources (e.g., `playlist_items`) cannot be linked across different `agency_id` domains. Database constraints enforce that `media_id` belongs to the same `agency_id` as `playlist_id`.
3. **Fail-Closed Design**: If a request lacks an authenticated and authorized tenant context, the API immediately halts with `401 Unauthorized` or `403 Forbidden` without executing partial application queries.

