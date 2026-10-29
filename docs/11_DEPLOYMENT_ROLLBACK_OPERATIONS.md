# PIXL 2.0: Deployment, Operations & Rollback Plan

> **Status: planning only.** This is a proposed runbook, not installed automation. Choose actual orchestration, implement compatible migration phases and demonstrate restore/rollback before claiming readiness; see [document 18](18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md). The shown `--expand only` is illustrative, not an assumed Alembic flag.

## 1. Zero-Downtime Deployment Architecture

PIXL 2.0 uses containerized rolling deployments managed via Docker Compose / Nomad or Kubernetes with Traefik ingress:

```
[ Git Push to main ] ──► [ CI / CD Pipeline: Lint, Test, Security Scan ]
                                    │
                                    ▼
                         [ Build Docker Containers ]
                         - pixl-api:v2.0.4
                         - pixl-worker:v2.0.4
                                    │
                                    ▼
                         [ Phase 1: Pre-Deployment DB Migration ]
                         (alembic upgrade head --expand only)
                                    │
                                    ▼
                         [ Phase 2: Rolling Container Replacement ]
                         - Start new containers (pixl-api-new)
                         - Health check (/api/v1/health/live & /ready)
                         - Drain traffic from old containers (Traefik)
                         - Stop old containers
                                    │
                                    ▼
                         [ Phase 3: Post-Deployment Contract Migration ]
                         (Runs only after 100% stability confirmed)
```

---

## 2. Database Migration Discipline: Expand / Contract Pattern

To prevent locking tables or breaking active API instances during schema changes, migrations **never** make breaking alterations in a single step:

1. **Phase 1 (Expand)**:
   - Add nullable new columns, new tables, or composite indexes (`CONCURRENTLY`).
   - Old code continues to read and write without error.
2. **Phase 2 (Dual Write / Backfill)**:
   - Code writes to both old and new schema fields.
   - Background worker backfills historical data.
3. **Phase 3 (Contract)**:
   - Deploy code that only uses the new columns.
   - Remove deprecated columns in a separate subsequent deployment.

---

## 3. Automated Circuit Breakers & Rollback Triggers

Automatic rollback to the previous container image is immediately executed if any of the following health thresholds are breached during a 10-minute deployment canary window:

| Metric | Threshold Triggering Rollback | Monitoring Mechanism |
| :--- | :--- | :--- |
| **API 5xx Error Rate** | $> 0.5\%$ of total requests over 3 minutes | Prometheus Alert / Traefik metrics |
| **WebSocket Drop Rate** | $> 5\%$ of screens disconnected without clean reconnect | Redis presence gauge / WSS metric |
| **P99 API Latency** | $> 1,000$ ms for consecutive 2-minute window | OpenTelemetry / Traefik histogram |
| **PoP Ingestion Failure** | $> 1\%$ batches failing cursor verification | Ingestion error counter |

---

## 4. Disaster Recovery & Emergency Runbook

### Incident A: Redis Crash or Memory Exhaustion
1. **Symptom**: Presence indicators show stale; WebSocket notifications stall.
2. **Operational Safeguard**: PostgreSQL is the durable source of truth. Redis restart **must not** mark the fleet offline.
3. **Recovery Procedure**:
   - Redis automatically restarts via systemd/container health check.
   - Active WebSocket instances re-hydrate screen presence incrementally upon the next 60s device heartbeat.
   - Run presence reconciler script to rebuild sorted set index without bulk database locking.

### Incident B: Corrupt Media File Causing Screen Crash Loop
1. **Symptom**: Screen logs `DECODE_FAILED` repeatedly on asset `asset_xyz`.
2. **Automated Recovery**: Player skips the offending asset after 2 consecutive failures and records an `INTERRUPTED / DECODE_FAILED` event in the outbox. Screen continues to the next playlist item.
3. **Agency Action**: Media dashboard highlights asset in red; agency admin clicks "Quarantine Asset", triggering an immediate `manifest_changed` push to purge the asset from all target screen caches.

