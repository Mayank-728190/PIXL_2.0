# ADR-003: Direct-to-Quarantine Object Storage Uploads vs Backend Streaming

> **Implementation status: not implemented or verified in this repository.** Accepted records architectural direction only. Apply the [requirements baseline](../13_REQUIREMENTS_BASELINE_AND_DELIVERY_PLAN.md) and [security/protocol prerequisites](../18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md) before implementation; stronger guarantee language below is not test evidence.

## Status
**Accepted**

## Context
Video files uploaded by agency users range from 10 MB to 250 MB. Streaming multipart uploads through the Python FastAPI web servers would saturate server network bandwidth, consume large amounts of ASGI memory, and tie up worker processes.

## Decision
We implement a **Direct Pre-Signed Upload to Quarantine Bucket Pipeline**:
1. Frontend requests an upload authorization ticket from the API (`POST /api/v1/agency/media/upload-ticket`).
2. API validates tenant quotas, verifies file extension/size, and issues a short-lived pre-signed S3/R2 `PUT` URL pointing directly to an isolated **Quarantine Bucket**.
3. Frontend uploads directly to the quarantine bucket with browser upload progress.
4. Upon completion, frontend notifies API (`POST /api/v1/agency/media/{id}/finalize`), which enqueues an asynchronous Celery task.
5. Isolated worker scans the file with `ffprobe`, verifies magic bytes, computes SHA-256, generates thumbnails, moves approved immutable files to the **Published Bucket**, and purges the quarantine file.

## Consequences
- **Positive**: Zero bandwidth bottleneck on FastAPI API servers; frontend receives native upload progress; uploads cannot compromise web API memory; malicious files are quarantined before verification.
- **Negative**: Requires careful CORS configuration on the Cloudflare R2 bucket and cleanup lifecycle policies for abandoned quarantine files.

