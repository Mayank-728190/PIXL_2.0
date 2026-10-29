# ADR-002: Monotonic Proof-of-Play Ingestion Cursor vs Streaming Kafka / ClickHouse

> **Implementation status: not implemented or verified in this repository.** Accepted records architectural direction only. Apply the [requirements baseline](../13_REQUIREMENTS_BASELINE_AND_DELIVERY_PLAN.md) and [security/protocol prerequisites](../18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md) before implementation; stronger guarantee language below is not test evidence.

## Status
**Accepted**

## Context
At 10,000 screens playing 10-second ads, the fleet generates 1,000 ad playback events per second (86.4M events/day). Ingesting events individually over HTTP would create 1,000 requests/sec, causing extreme connection churn and database contention. Introducing Apache Kafka and ClickHouse from Day 1 introduces massive infrastructure overhead and high hosting cost ($300-$500+/mo).

## Decision
We implement a **Client-Side Outbox with Monotonic Cursor Ingestion**:
1. **Android Room SQLite Outbox**: The Android client buffers events locally, assigning an atomic, strictly monotonic sequence number (`local_sequence`).
2. **Batched Uploads**: The device flushes in batches of 30-50 events every 5 minutes (or immediately for high-priority events). This drops the HTTP request rate across 10,000 screens to just **33.3 requests/sec**!
3. **Database Ingestion Cursor**: The server maintains a `device_cursors` record (`screen_id`, `epoch`, `last_committed_sequence`). During batch ingestion, the cursor row is locked with `FOR UPDATE`. Sequences $\le$ cursor are acknowledged as duplicates; contiguous sequences advance the cursor atomically; gaps trigger a `409 GAP_DETECTED` recovery response.
4. **Partitioned PostgreSQL**: Events are written using multi-row `INSERT` into weekly-partitioned tables in PostgreSQL.
5. **Cold Archive**: Background workers export weekly partitions into compacted Apache Parquet files on Cloudflare R2 for long-term historical querying.

## Consequences
- **Positive (target)**: Replay-safe billing and durable offline delivery when cursor, disposition, epoch and local-storage contracts are correctly implemented. The baseline averages ~33.3 ingestion transactions/sec; retries, recovery and multi-zone playback increase load.
- **Negative**: If an Android screen experiences a local corruption of its SQLite sequence counter, an epoch reset ceremony is required.

