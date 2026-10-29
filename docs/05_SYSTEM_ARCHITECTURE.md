# PIXL 2.0: System Architecture & Technical Topography

> **Status: planning only.** This is a target architecture, not deployed infrastructure. Durable dispatch, cache/broker failure boundaries and deployment security must follow [document 18](18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md). User-visible workflows and kiosk behavior are specified in documents 14–16.

## 1. High-Level Modular Monolith Architecture

PIXL 2.0 avoids premature microservice fragmentation. It is built as a high-performance **Modular Monolith** using Python (FastAPI + SQLAlchemy 2 + Asyncpg) paired with Celery asynchronous background workers and persistent caching/presence via Redis 7 and PostgreSQL 16.

```mermaid
flowchart TD
    subgraph Clients["Edge Clients & Frontends"]
        MP["Master Portal<br/>(React + Vite + TS)<br/>master.pixl.io"]
        AP["Agency Portal<br/>(React + Vite + TS)<br/>agency.pixl.io"]
        AdvP["Advertiser Portal<br/>(React + Vite + TS)<br/>advertiser.pixl.io"]
        Sim["Browser Screen Simulator<br/>(React + Media3 Web)"]
        D1["Android Hardware Screen 1<br/>(Kotlin + Media3 + Room)"]
        D10k["Android Hardware Screen 10,000<br/>(Kotlin + Media3 + Room)"]
    end

    subgraph CDN["Edge Acceleration & Security Layer (Cloudflare)"]
        CF_DNS["Cloudflare DNS & WAF"]
        CF_R2["Cloudflare R2 Object Storage<br/>(Zero Egress Media Delivery)"]
    end

    subgraph Ingress["Ingress & Gateway Layer"]
        Traefik["Traefik / Caddy Reverse Proxy<br/>- TLS Termination<br/>- IP Rate Limiting<br/>- WebSocket Sticky Termination"]
    end

    subgraph Monolith["PIXL Core Modular Monolith (FastAPI)"]
        AuthMod["Auth & Session Module<br/>(Argon2id, MFA, HttpOnly Cookies)"]
        TenantMod["Tenancy & IAM Module<br/>(Master, Agency, Brand Context)"]
        FleetMod["Fleet & Device Module<br/>(Enrollment, Presence, Health)"]
        MediaMod["Media & Asset Module<br/>(Quarantine Ticket, Quotas)"]
        SchedMod["Scheduling & Manifest Module<br/>(Conflict Resolution, ED25519 Signing)"]
        IngestMod["PoP Ingestion Engine<br/>(Monotonic Cursor, Atomic Batches)"]
        WSGateway["WebSocket Gateway<br/>(Push Fan-out, Heartbeat Handler)"]
    end

    subgraph Workers["Asynchronous Background Workers (Celery)"]
        FFmpegWorker["Media Transcoding Worker<br/>(ffprobe, ffmpeg, WebP, Hash)"]
        SchedWorker["Manifest Compiler Worker<br/>(Pre-computes Daily Schedules)"]
        AggWorker["PoP Rollup Worker<br/>(Hourly/Daily Reporting Rollups)"]
        ArchWorker["Storage Archival Worker<br/>(Cold Parquet/JSONL Export to R2)"]
    end

    subgraph DataTier["Data Tier"]
        PG[(PostgreSQL 16 Enterprise<br/>- Relational Source of Truth<br/>- Partitioned PoP Events<br/>- Row Level Security)]
        RedisCache[(Redis 7 Cluster / Replica<br/>- Ephemeral Presence ZSET<br/>- Manifest Version Cache<br/>- Distributed Rate Limits<br/>- Pub/Sub Channel Broker)]
    end

    %% Client Ingress Connections
    MP -->|HTTPS| CF_DNS
    AP -->|HTTPS| CF_DNS
    AdvP -->|HTTPS| CF_DNS
    Sim -->|HTTPS / WSS| CF_DNS
    D1 -->|WSS Heartbeat / HTTPS REST| CF_DNS
    D10k -->|WSS Heartbeat / HTTPS REST| CF_DNS

    CF_DNS --> Traefik
    Traefik --> Monolith
    Traefik --> WSGateway

    %% Storage Direct Access
    D1 -.->|Direct Download via Pre-signed URL| CF_R2
    D10k -.->|Direct Download via Pre-signed URL| CF_R2
    AP -.->|Direct Upload via Pre-signed PUT| CF_R2

    %% Monolith internal links
    Monolith --> PG
    Monolith --> RedisCache
    WSGateway --> RedisCache

    %% Worker links
    Monolith -.->|Enqueue Task| RedisCache
    Workers -->|Poll Tasks| RedisCache
    Workers --> PG
    FFmpegWorker <--> CF_R2
    ArchWorker --> CF_R2
```

---

## 2. Component Boundaries & Isolation

### A. FastAPI Modular Monolith
The backend codebase is organized into bounded modules with strict isolation:
- `app/modules/auth`: Session management, Argon2id verification, TOTP MFA, cookie handling.
- `app/modules/tenancy`: Agency & Brand hierarchy, invitation token redemption, tenant switching.
- `app/modules/fleet`: Screen registration, 6-character pairing PIN lifecycle, telemetry ingest, presence tracking.
- `app/modules/media`: Pre-signed quarantine upload authorization, asset verification, metadata persistence.
- `app/modules/scheduling`: Zone layout resolution, priority arbitration, ED25519 manifest signing.
- `app/modules/ingestion`: Monotonic sequence validator, device cursor locks, bulk proof-of-play writer.
- `app/modules/reporting`: Hourly rollup generation, advertiser audit exports.

### B. Worker Pools (Celery with Redis Broker)
- **Quarantine Media Pool**: Resource-capped worker containers with FFmpeg installed. Strictly limited CPU/memory limits (`--cpus=2 --memory=2g`) to prevent CPU starvation of the web API during video transcoding.
- **Reporting & Archival Pool**: Long-running read-heavy database aggregation jobs, isolated from the synchronous API request pool.

### C. Android Display Client
- Native Kotlin application built with **AndroidX Media3 (ExoPlayer)** for video decode and hardware surface rendering.
- **Room SQLite** for offline manifest persistence and durable outbox buffer.
- **WorkManager** with network constraints (`NetworkType.CONNECTED`) for reliable background telemetry synchronization.
- **Android Keystore** for cryptographic storage of the device private key.

### D. Browser Screen Simulator
- React/TypeScript application rendering scheduled playlists in standard browser viewports (16:9, 9:16).
- Implements the exact same manifest schema and state machine as the Android player for local agency testing.
- Clearly flags that browser fullscreen is not equivalent to Android Kiosk / Lock Task Mode.

