# PIXL 2.0: User Journeys & Operational Workflows

> **Status: planning only.** These sequences are illustrative, not final API contracts. Master-authorized assignment must precede Agency pairing; unrestricted Agency self-claim is superseded. Enrollment possession checks and durable sequence allocation are required by [document 18](18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md). See [document 15](15_MEDIA_AND_CAMPAIGN_WORKFLOW_SPEC.md) for the simplified media-to-campaign flow.

## 1. Journey 1: Master Admin Provisions Agency & Oversees Device
```mermaid
sequenceDiagram
    autonumber
    actor Master as Master Admin
    participant Portal as Master Portal (master.pixl.io)
    participant API as FastAPI Monolith
    participant DB as PostgreSQL
    participant Mail as Email Service (Transactional)
    actor Agency as Agency Admin

    Master->>Portal: Authenticate (Email + Password + TOTP MFA)
    Portal->>API: POST /api/v1/auth/master/login
    API->>Portal: Return HttpOnly Secure Session Cookie (__Host-Master-Session)
    Master->>Portal: Create New Agency ("Apex Media", admin: "alice@apex.com")
    Portal->>API: POST /api/v1/master/agencies
    API->>DB: INSERT INTO agencies, INSERT INTO users (status=INVITED)
    API->>DB: INSERT INTO audit_events
    API->>Mail: Send Expiring Invitation Link (Valid 24h)
    Mail-->>Agency: "Set up your Apex Media Admin Account"
    Agency->>Portal: Click Invitation Token
    Portal->>API: POST /api/v1/auth/invitation/accept (Set password + MFA)
    API->>DB: UPDATE users SET status=ACTIVE, hashed_password=...
```

---

## 2. Journey 2: Device Enrollment, Claiming, and Activation
```mermaid
sequenceDiagram
    autonumber
    actor Installer as Field Technician
    participant Screen as Android Device Player
    participant API as FastAPI Backend
    participant Redis as Redis Cache / Presence
    participant DB as PostgreSQL
    actor Agency as Agency Admin

    Installer->>Screen: Power On Device (First Boot)
    Screen->>API: POST /api/v1/device/enroll/challenge {hw_fingerprint, model}
    API->>Redis: Generate 6-Character Short PIN ("PK-8921"), TTL 15 mins
    API->>DB: INSERT INTO enrollment_challenges
    API-->>Screen: Return PIN "PK-8921"
    Screen->>Screen: Display full-screen Pairing Screen: "Enter PK-8921 on agency.pixl.io"

    Agency->>API: POST /api/v1/agency/screens/claim {pin: "PK-8921", name: "Lobby 01", site_id: "site_45"}
    Note over API,DB: Atomic Transaction: Verify PIN, lock challenge row, mark CLAIMED
    API->>DB: INSERT INTO screens (agency_id, name, status='ACTIVE')
    API->>DB: INSERT INTO device_credentials (device_id, public_key_hash)
    API->>Redis: Publish enrollment resolution to channel: enroll:PK-8921

    Screen->>API: POST /api/v1/device/enroll/poll-or-exchange {challenge_id, hw_keystore_pubkey}
    API-->>Screen: Return Device Scoped Credentials (device_token, device_id, server_pubkey)
    Screen->>Screen: Store credentials securely in Android Keystore & Room DB
    Screen->>API: Connect WSS wss://api.pixl.io/ws/v1/device with Device Auth
    Screen->>Screen: State Transition: PAIRING -> SYNCING -> READY
```

---

## 3. Journey 3: Agency Media Upload, Approval & Campaign Publishing
```mermaid
sequenceDiagram
    autonumber
    actor Agency as Agency Admin
    participant Dashboard as Agency Portal (agency.pixl.io)
    participant API as FastAPI Backend
    participant S3Q as S3 / Cloudflare R2 (Quarantine Bucket)
    participant Worker as FFmpeg Celery Worker
    participant S3Pub as S3 / Cloudflare R2 (Published Bucket)
    participant DB as PostgreSQL
    participant Redis as Redis / WebSockets
    participant Screen as Android Player

    Agency->>Dashboard: Drag-and-drop 1080p MP4 file ("Summer_Promo.mp4", 45MB)
    Dashboard->>API: POST /api/v1/agency/media/upload-ticket {filename, size, declared_mime}
    API->>API: Verify Agency storage quota & rate limits
    API->>S3Q: Generate Pre-Signed S3 PUT URL (Scoped, 15 min expiry)
    API-->>Dashboard: Return {upload_ticket_id, presigned_put_url}

    Dashboard->>S3Q: Direct HTTP PUT binary stream with upload progress bar
    S3Q-->>Dashboard: 200 OK (Upload Complete)
    Dashboard->>API: POST /api/v1/agency/media/{upload_ticket_id}/finalize
    API->>DB: INSERT INTO media_assets (status='PROCESSING')
    API->>Worker: Enqueue task: process_quarantine_media(media_id)

    Worker->>S3Q: Download raw file to isolated worker scratch volume
    Worker->>Worker: Execute ffprobe: inspect codecs, bitrates, audio tracks, duration
    Worker->>Worker: Calculate SHA-256 checksum over exact binary content
    Worker->>Worker: Generate 300x168 WebP thumbnail + 720p preview clip
    Worker->>S3Pub: Upload approved binary to published/assets/{sha256}.mp4
    Worker->>S3Q: Delete raw file from quarantine bucket
    Worker->>DB: UPDATE media_assets SET status='READY', sha256='...', duration_ms=15000, ...

    Agency->>Dashboard: Build Campaign: Select Media -> Target Screens -> Set Schedule -> Click Publish
    Dashboard->>API: POST /api/v1/agency/campaigns/publish {campaign_id}
    API->>DB: Compile immutable manifest version (version=104, hash=0x9f...)
    API->>API: Sign manifest payload with ED25519 Private Key
    API->>Redis: Publish to WebSocket channel "screen:updates:{screen_id}"
    Redis-->>Screen: WS Frame: {"type": "manifest_changed", "version": 104}
    Screen->>API: GET /api/v1/device/manifest (If local_version < 104)
    Screen->>S3Pub: Download missing verified assets to local storage cache
    Screen->>Screen: Atomic transition to new manifest playback
```

---

## 4. Journey 4: Proof-of-Play Local Outbox & Server Ingestion
```mermaid
sequenceDiagram
    autonumber
    participant Player as ExoPlayer / SurfaceView
    participant Room as Android Room SQLite
    participant Uploader as Android WorkManager Outbox Worker
    participant API as FastAPI Ingestion Endpoint
    participant DB as PostgreSQL (Partitioned Table)

    Player->>Player: Ad "Summer_Promo" plays to completion (15,000 ms)
    Player->>Room: BEGIN TX
    Player->>Room: sequence = SELECT MAX(local_seq) + 1 FROM outbox
    Player->>Room: INSERT INTO playback_events (seq, ad_id, started_at, completed_at, outcome='COMPLETED')
    Player->>Room: COMMIT TX

    Note over Uploader,API: Every 5 minutes or 30 events buffered:
    Uploader->>Room: SELECT * FROM playback_events WHERE acknowledged = 0 ORDER BY seq ASC LIMIT 50
    Uploader->>API: POST /api/v1/device/playback/batch {device_id, epoch, batch: [{seq: 101, ...}, {seq: 102, ...}]}
    
    API->>DB: BEGIN TX
    API->>DB: SELECT last_seq FROM device_cursors WHERE device_id = '...' FOR UPDATE
    Note over API,DB: Idempotency check: Reject duplicate sequences, accept new contiguous sequences
    API->>DB: INSERT INTO playback_events (device_id, started_at, seq, ...) VALUES (...)
    API->>DB: UPDATE device_cursors SET last_seq = 102, updated_at = NOW()
    API->>DB: COMMIT TX

    API-->>Uploader: HTTP 200 {status: "ACK", committed_seq: 102}
    Uploader->>Room: UPDATE playback_events SET acknowledged = 1 WHERE seq <= 102
    Uploader->>Room: Prune acknowledged events older than 48 hours
```

