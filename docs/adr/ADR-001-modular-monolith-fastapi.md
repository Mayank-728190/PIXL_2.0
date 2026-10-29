# ADR-001: Modular Monolith in FastAPI + Celery vs Microservices

> **Implementation status: not implemented or verified in this repository.** Accepted records architectural direction only. Apply the [requirements baseline](../13_REQUIREMENTS_BASELINE_AND_DELIVERY_PLAN.md) and [security/protocol prerequisites](../18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md) before implementation; stronger guarantee language below is not test evidence.

## Status
**Accepted**

## Context
PIXL 2.0 must scale progressively from 100 to 10,000 concurrently connected screens. At 10,000 screens, the system experiences ~167 heartbeats/sec and ~33 PoP batch uploads/sec (totaling 1,000 ad events/sec). A premature microservice architecture would introduce distributed transactions, network latency across internal RPCs, complex deployment overhead, high observability costs, and fragile cross-service security boundaries.

## Decision
We build PIXL 2.0 as a **high-performance Modular Monolith** in Python using:
- **FastAPI** for asynchronous REST and WebSocket request handling.
- **SQLAlchemy 2 with Asyncpg** for robust, asynchronous PostgreSQL access with connection pooling.
- **Celery with Redis** for isolated background worker pools (FFmpeg media processing, manifest compilation, hourly PoP rollups).
- **PostgreSQL 16** as the single relational source of truth with table partitioning.
- **Redis 7** for ephemeral presence and caching.

## Consequences
- **Positive**: Single codebase, transactional database integrity (ACID), zero network hop latency between domain modules, simpler CI/CD and deployment, lower initial hosting cost.
- **Negative**: Heavy background processing (e.g. video transcoding) must be strictly isolated to Celery workers with dedicated CPU/memory limits to avoid starving API event loops.

