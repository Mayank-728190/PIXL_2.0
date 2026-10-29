# PIXL 2.0: API & Device Protocol Specification

> **Status: planning only.** Payloads below are illustrative, not a complete interoperable protocol. Master authorization, enrollment possession proof, request authentication, canonical signatures, full asset/zone dependencies and durable dispositions must follow [document 18](18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md). Canonical role/duration names are in [document 13](13_REQUIREMENTS_BASELINE_AND_DELIVERY_PLAN.md).

## 1. REST API Routing Architecture

All API endpoints are versioned under `/api/v1/`.

| Route Prefix | Target Domain | Authorization Requirement | Session Cookie / Token |
| :--- | :--- | :--- | :--- |
| `/api/v1/auth/*` | Session Management | Public / Authenticated | HttpOnly Secure Cookie |
| `/api/v1/master/*` | Master Super Admin | `master_admin` Role | `__Host-PIXL-Master-Session` |
| `/api/v1/agency/*` | Agency Management | `agency_admin` or `agency_operator` | `__Host-PIXL-Agency-Session` |
| `/api/v1/advertiser/*`| Brand Advertiser | `brand_advertiser` | `__Host-PIXL-Brand-Session` |
| `/api/v1/device/*` | Screen Hardware | Device Token / HMAC Header | `X-Device-Token` |

---

## 2. Device Protocol Specification

### A. Device Enrollment Flow
#### 1. Request Enrollment Challenge
`POST /api/v1/device/enroll/challenge`
- **Request Body**:
  ```json
  {
    "hardware_fingerprint": "a8f3b92c4e112d",
    "model": "Amlogic S905X4 Digital Box",
    "os_version": "Android 12 (API 31)",
    "app_version": "2.0.0-release"
  }
  ```
- **Response (200 OK)**:
  ```json
  {
    "challenge_id": "c19b22e1-450a-4933-91d1-67823b18f0c2",
    "pin": "PK-8921",
    "expires_at": "2026-10-29T01:15:00Z",
    "poll_interval_seconds": 3
  }
  ```

#### 2. Agency Claims Screen
`POST /api/v1/agency/screens/claim`
- **Headers**: Cookie: `__Host-PIXL-Agency-Session`
- **Request Body**:
  ```json
  {
    "pin": "PK-8921",
    "name": "Reception Lobby Screen 01",
    "site_id": "4b68e987-7a2e-4364-883a-86cb70d6a95f",
    "orientation": "LANDSCAPE"
  }
  ```
- **Response (200 OK)**:
  ```json
  {
    "status": "CLAIMED",
    "screen_id": "8902ef14-f02a-41d3-a551-7ec64155b991",
    "assigned_to": "Apex Media"
  }
  ```

#### 3. Device Exchanges Challenge for Scoped Credentials
`POST /api/v1/device/enroll/exchange`
- **Request Body**:
  ```json
  {
    "challenge_id": "c19b22e1-450a-4933-91d1-67823b18f0c2",
    "public_key_pem": "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA..."
  }
  ```
- **Response (200 OK)**:
  ```json
  {
    "device_id": "8902ef14-f02a-41d3-a551-7ec64155b991",
    "device_token": "dev_tok_74fa90bce21...",
    "epoch": 1,
    "server_public_key_pem": "-----BEGIN PUBLIC KEY-----\n...",
    "ws_endpoint": "wss://api.pixl.io/ws/v1/device"
  }
  ```

---

### B. Device Heartbeat Protocol (HTTP / WebSocket)
`POST /api/v1/device/heartbeat` (Or periodic frame over WSS)
- **Headers**: `X-Device-Token: dev_tok_...`
- **Request Body**:
  ```json
  {
    "device_id": "8902ef14-f02a-41d3-a551-7ec64155b991",
    "epoch": 1,
    "manifest_version": 42,
    "playback_state": "PLAYING",
    "current_asset_id": "993a401c-6d4b-4b2e-a5bf-8f240212f43a",
    "storage_free_mb": 11250,
    "cpu_temp_celsius": 48.5,
    "display_power_state": "ON"
  }
  ```
- **Response (200 OK)**:
  ```json
  {
    "server_time": "2026-10-29T01:03:00Z",
    "latest_manifest_version": 42,
    "action_required": null
  }
  ```

---

### C. Signed Manifest Fetch
`GET /api/v1/device/manifest`
- **Headers**: `X-Device-Token: dev_tok_...`
- **Response (200 OK)**:
  ```json
  {
    "signature": "30450221008f1b2...",
    "payload": {
      "manifest_id": "man_v42_screen_8902",
      "screen_id": "8902ef14-f02a-41d3-a551-7ec64155b991",
      "version": 42,
      "valid_from": "2026-10-29T00:00:00Z",
      "valid_until": "2026-11-01T00:00:00Z",
      "timezone": "America/New_York",
      "assets": [
        {
          "id": "asset_101",
          "sha256": "4b9e28f3a8b29c011e038f4d45543c8b417e170f80bc23df2f2a58b5e917d2a1",
          "filename": "summer_promo.mp4",
          "size_bytes": 45219400,
          "download_url": "https://media.pixl.io/published/assets/summer_promo.mp4?exp=1793232000&sig=..."
        }
      ],
      "layout": {
        "width": 1920,
        "height": 1080,
        "zones": [
          {
            "id": "zone_main",
            "x": 0, "y": 0, "width": 1920, "height": 1080, "z_index": 0, "audio_enabled": true
          }
        ]
      },
      "schedule": [
        {
          "campaign_id": "camp_201",
          "priority": 100,
          "start_time": "2026-10-29T08:00:00",
          "end_time": "2026-10-29T22:00:00",
          "playlist": [
            { "asset_id": "asset_101", "duration_ms": 15000, "duration_mode": "FULL_CLIP" }
          ]
        }
      ],
      "fallback_playlist": [
        { "asset_id": "asset_default_logo", "duration_ms": 10000, "duration_mode": "CUSTOM_DURATION" }
      ]
    }
  }
  ```

---

### D. Monotonic Proof-of-Play Batch Ingestion
`POST /api/v1/device/playback/batch`
- **Headers**: `X-Device-Token: dev_tok_...`
- **Request Body**:
  ```json
  {
    "device_id": "8902ef14-f02a-41d3-a551-7ec64155b991",
    "epoch": 1,
    "batch": [
      {
        "local_sequence": 105,
        "campaign_id": "camp_201",
        "media_id": "asset_101",
        "media_sha256": "4b9e28f3a8b29c...",
        "zone_id": "zone_main",
        "started_at": "2026-10-29T01:00:00.120Z",
        "completed_at": "2026-10-29T01:00:15.120Z",
        "duration_ms": 15000,
        "outcome": "COMPLETED",
        "clock_quality": "NTP_SYNCED"
      },
      {
        "local_sequence": 106,
        "campaign_id": "camp_201",
        "media_id": "asset_101",
        "media_sha256": "4b9e28f3a8b29c...",
        "zone_id": "zone_main",
        "started_at": "2026-10-29T01:00:15.200Z",
        "completed_at": "2026-10-29T01:00:30.200Z",
        "duration_ms": 15000,
        "outcome": "COMPLETED",
        "clock_quality": "NTP_SYNCED"
      }
    ]
  }
  ```
- **Response (200 OK - Cursor Advanced)**:
  ```json
  {
    "status": "ACK",
    "device_id": "8902ef14-f02a-41d3-a551-7ec64155b991",
    "epoch": 1,
    "last_committed_sequence": 106,
    "dispositions": [
      { "local_sequence": 105, "status": "STORED" },
      { "local_sequence": 106, "status": "STORED" }
    ]
  }
  ```
- **Error Response (409 Conflict - Sequence Gap Detected)**:
  ```json
  {
    "status": "GAP_DETECTED",
    "expected_sequence": 103,
    "received_lowest_sequence": 105,
    "action": "RESEND_FROM_CURSOR"
  }
  ```

---

### E. WebSocket Push Protocol
- **Endpoint**: `wss://api.pixl.io/ws/v1/device`
- **Connection Handshake**: Initial auth frame sent by device within 5 seconds of connection:
  ```json
  {
    "type": "auth",
    "device_id": "8902ef14-f02a-41d3-a551-7ec64155b991",
    "token": "dev_tok_74fa90bce21..."
  }
  ```
- **Server Push: Manifest Invalidation**:
  ```json
  {
    "type": "manifest_changed",
    "version": 43,
    "timestamp": 1793232100
  }
  ```
- **Server Push: Remote Management Command**:
  ```json
  {
    "type": "command",
    "command_id": "cmd_501",
    "action": "RELOAD_MANIFEST"
  }
  ```

