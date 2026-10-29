# PIXL 2.0: Role-Permission Matrix & Negative Authorization Specification

> **Status: planning only.** The [requirements baseline](13_REQUIREMENTS_BASELINE_AND_DELIVERY_PLAN.md) governs permissions: Master alone manages Agency administrator accounts and authorizes screen assignment. Agency pairing only completes an existing authorized assignment. Session/tenant enforcement details are in [document 18](18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md).

## 1. Role Taxonomy

| Role | Scope | Description |
| :--- | :--- | :--- |
| **`master_admin`** | Platform Global | Super administrator with access to all agency records, global device provisioning, billing configurations, and system audit logs. |
| **`agency_admin`** | Agency Tenant | Full administrative rights within a single organization (screens, media, playlists, campaigns, bookings, advertiser invitations). |
| **`agency_operator`** | Agency Tenant | Day-to-day operations (media uploads, playlist editing, monitoring); cannot invite admins, delete agency, or alter billing. |
| **`brand_advertiser`** | Brand (Sub-tenant) | Access limited to a single Brand assigned by an Agency. Can submit creatives and view delivery reports for their bookings. |
| **`device_agent`** | Device Hardware | Machine identity tied to physical screen hardware. Access strictly limited to device synchronization and ingestion endpoints. |

---

## 2. Granular Permission Grid

| Resource & Operation | `master_admin` | `agency_admin` | `agency_operator` | `brand_advertiser` | `device_agent` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Agencies: Create / Suspend / Delete** | **YES** | NO | NO | NO | NO |
| **Agency Admin Accounts: Create / Suspend / Delete** | **YES** | NO | NO | NO | NO |
| **Agencies: View Details** | **YES (Global)** | YES (Own Agency) | YES (Own Agency) | NO | NO |
| **Screens: Enroll / View Global Fleet** | **YES** | NO | NO | NO | NO |
| **Screens: Assign / Reassign to Tenant** | **YES** | NO | NO | NO | NO |
| **Screens: Complete Master-Authorized Pairing** | **YES** | YES (Already Assigned Only) | NO | NO | NO |
| **Screens: View Fleet & Telemetry** | **YES (All)** | YES (Own Agency) | YES (Own Agency) | NO | NO |
| **Screens: Reboot / Maintenance Commands** | **YES** | **YES** | YES | NO | NO |
| **Media: Upload Ticket Request** | **YES** | **YES** | YES | YES (To Own Brand) | NO |
| **Media: Delete Asset** | **YES** | **YES** | NO | NO | NO |
| **Playlists: Create / Edit / Delete** | **YES** | **YES** | YES | NO | NO |
| **Campaigns: Build & Publish** | **YES** | **YES** | YES | NO | NO |
| **Inventory / Bookings: Reserve Slots** | **YES** | **YES** | YES | YES (Own Brand) | NO |
| **Bookings: Approve & Schedule** | **YES** | **YES** | NO | NO | NO |
| **Proof-of-Play: Aggregate Reports** | **YES** | **YES** | YES | YES (Own Brand Ads) | NO |
| **Proof-of-Play: Ingest Batches** | NO | NO | NO | NO | **YES (Own Device)** |
| **Device: Pull Signed Manifest** | NO | NO | NO | NO | **YES (Own Device)** |
| **Audit Logs: Global Access** | **YES** | NO | NO | NO | NO |
| **Audit Logs: Tenant Scoped** | **YES** | **YES** | NO | NO | NO |

---

## 3. Negative Authorization Test Matrix (Strict Fail-Closed Enforcements)

Every negative case documented below must be backed by automated regression tests in the test suite (`tests/security/`):

| Test ID | Acting Persona | Target Resource ID | Attempted Action | Expected Result | Enforced Mechanism |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **NEG-AUTH-001** | Anonymous Public User | `/api/v1/master/agencies` | `POST` (Attempt signup/creation) | `401 Unauthorized` | HTTP Authentication Middleware |
| **NEG-AUTH-002** | Anonymous Public User | `/api/v1/auth/register` | `POST` (Attempt register) | `404 Not Found` | No public registration endpoint exists |
| **NEG-AUTH-003** | Agency A Admin | Screen belonging to Agency B | `GET /api/v1/agency/screens/{id_b}` | `404 Not Found` (Masked) | Tenant Context Filter in DB Query |
| **NEG-AUTH-004** | Agency A Admin | Media belonging to Agency B | `DELETE /api/v1/agency/media/{media_b}` | `404 Not Found` | Tenant Filter + Row-Level Security |
| **NEG-AUTH-005** | Agency A Admin | Playlist belonging to Agency A | `POST /items` with `media_id` of Agency B | `400 Bad Request` or `403` | Cross-tenant resource linking validation |
| **NEG-AUTH-006** | Brand 1 Advertiser | Screen fleet | `GET /api/v1/agency/screens` | `403 Forbidden` | Role check (`agency_admin`/`operator` required) |
| **NEG-AUTH-007** | Brand 1 Advertiser | Campaign of Brand 2 | `GET /api/v1/advertiser/campaigns/{c_2}` | `404 Not Found` | Brand Context Scoping |
| **NEG-AUTH-008** | Device 01 Token | `/api/v1/agency/media` | `GET` (Attempt read agency media) | `403 Forbidden` | Device tokens rejected from management API |
| **NEG-AUTH-009** | Device 01 Token | Screen 02 Ingestion | `POST /api/v1/device/playback/batch` with `device_id="screen_02"` | `403 Forbidden` | Device token subject mismatch with payload `device_id` |
| **NEG-AUTH-010** | Expired Session | Any private API | Any verb | `401 Unauthorized` | Session expiration check + Redis session blacklist |
| **NEG-AUTH-011** | Agency Admin | Master config | `GET /api/v1/master/config` | `403 Forbidden` | Panel / Audience barrier: Master vs Agency origin |

---

## 4. Origin & Cookie Isolation Architecture

To completely eliminate cross-origin token leakages and credential theft:
- **Master Portal Origin**: `https://master.pixl.io`
  - Cookie: `__Host-PIXL-Master-Session` (`Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`)
  - Audience claim: `pixl:audience:master`
- **Agency Portal Origin**: `https://agency.pixl.io`
  - Cookie: `__Host-PIXL-Agency-Session` (`Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`)
  - Audience claim: `pixl:audience:agency`
- **Advertiser Portal Origin**: `https://advertiser.pixl.io` (or unified under agency domain with brand scoping)
  - Cookie: `__Host-PIXL-Brand-Session` (`Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`)
- **CORS Policy**: Strictly explicit whitelist matching only authorized front-end domain names. Never use `Access-Control-Allow-Origin: *` with credentials.

