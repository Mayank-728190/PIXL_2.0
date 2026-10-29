# PIXL 2.0: Capacity, Traffic & Infrastructure Cost Model

> **Status: planning only.** All provider prices and performance statements below are unverified planning estimates, not production guarantees. Raw-row storage excludes indexes/WAL/replicas/headroom, and baseline RPS excludes recovery traffic. See corrected workload and backlog requirements in [document 16](16_ANDROID_KIOSK_AND_DEVICE_RELIABILITY_SPEC.md).

## 1. Traffic & Ingestion Mathematics

### Baseline System Parameters:
- **Heartbeat Interval ($T_{hb}$)**: 60 seconds.
- **Reconciliation Check Interval ($T_{rec}$)**: 900 seconds (15 minutes).
- **Average Ad Duration ($D_{ad}$)**: 10 seconds.
- **PoP Batch Size ($B_{pop}$)**: 30 events per batch (or flush every 300 seconds).

---

### Quantitative Scaling Derivations across Fleet Sizes:

| Fleet Metric | **100 Screens** | **1,000 Screens** | **10,000 Screens** | Mathematical Derivation |
| :--- | :--- | :--- | :--- | :--- |
| **Concurrent Persistent Sockets (WSS)** | 100 | 1,000 | **10,000** | $N_{screens}$ concurrent TCP connections |
| **Heartbeat Ingress Rate** | 1.67 req/s | 16.67 req/s | **166.7 req/s** | $N_{screens} / T_{hb} = 10,000 / 60$ |
| **Daily Heartbeat Messages** | 144,000 / day | 1.44M / day | **14.4M / day** | $166.7 \times 86,400$ |
| **Raw Ad Playback Events Generated** | 10 events/s | 100 events/s | **1,000 events/s** | $N_{screens} / D_{ad} = 10,000 / 10$ |
| **Total Daily Playback Events** | 864,000 / day | 8.64M / day | **86.4M / day** | $1,000 \times 86,400$ |
| **PoP Batch Upload Rate** | 0.33 req/s | 3.33 req/s | **33.33 req/s** | $10,000 / 300\text{ sec}$ |
| **Database Insertion Transactions** | 0.33 tx/s | 3.33 tx/s | **33.33 tx/s** | Each batch writes 30 rows in single multi-row insert |
| **Rows Inserted into PostgreSQL** | 10 rows/s | 100 rows/s | **1,000 rows/s** | Absorbed easily by PostgreSQL with partitioned tables |
| **Hot Storage Growth (PostgreSQL 14 Days)** | 2.4 GB | 24 GB | **240 GB** | ~200 bytes per row $\times 86.4\text{M/day} \times 14\text{ days}$ |
| **Cold Storage Growth (Parquet / R2 Monthly)**| 5.1 GB / mo | 51 GB / mo | **510 GB / mo** | Compacted Parquet at ~20 bytes per event |

---

## 2. Infrastructure Sizing & Cost Models

*Historical planning assumptions labeled October 2026; provider prices, operation charges and configuration availability have not been verified. Obtain a current quote before budget approval.*

### Tier 1: Small Fleet (100 Screens)
- **API / Web Server**: 1x Basic Droplet (2 vCPU, 4 GB RAM) = **\$24/mo**
- **Database**: DigitalOcean Managed PostgreSQL (1 vCPU, 2 GB RAM) = **\$15/mo**
- **Cache**: Managed Redis (1 Node, 1 GB) = **\$15/mo**
- **Storage & CDN**: Cloudflare R2 (100 GB storage, zero egress) = **\$1.50/mo**
- **Domain & SSL**: Cloudflare Free tier = **\$0/mo**
- **Total Monthly Cost (100 Screens)**: **\$55.50 / month** (~**\$0.55 per screen/mo**)

---

### Tier 2: Mid Fleet (1,000 Screens)
- **API & Worker Servers**: 2x General Purpose Droplets (2 vCPU, 8 GB RAM) = **\$120/mo**
- **Load Balancer**: DigitalOcean Cloud Load Balancer = **\$12/mo**
- **Database**: DigitalOcean Managed PostgreSQL (2 vCPU, 8 GB RAM, 100 GB NVMe) = **\$70/mo**
- **Cache**: Managed Redis (2 vCPU, 4 GB RAM) = **\$35/mo**
- **Storage & CDN**: Cloudflare R2 (1 TB storage, 50 TB egress via R2 @ \$0/GB) = **\$15/mo**
- **Logging & Metrics**: Prometheus / Grafana self-hosted instance (2 vCPU, 4 GB) = **\$24/mo**
- **Total Monthly Cost (1,000 Screens)**: **\$276 / month** (~**\$0.28 per screen/mo**)

---

### Tier 3: Production Enterprise Fleet (10,000 Screens)
- **API & WebSocket Cluster**: 4x Compute Optimized Droplets (4 vCPU, 8 GB RAM) behind Traefik = **\$336/mo**
- **Background Worker Nodes**: 2x General Purpose Droplets (4 vCPU, 16 GB RAM) for FFmpeg & rollups = **\$168/mo**
- **Load Balancers**: 2x High-Availability Load Balancers = **\$24/mo**
- **Database Tier**: DigitalOcean Managed PostgreSQL (8 vCPU, 32 GB RAM, 1 TB NVMe, High Availability Standby Node) = **\$480/mo**
- **Cache / Presence Tier**: Managed Redis Cluster (4 vCPU, 8 GB RAM, High Availability Replica) = **\$120/mo**
- **Object Storage (Cloudflare R2)**: 10 TB Media + 15 TB Compressed PoP Archives (25 TB total @ \$0.015/GB) = **\$375/mo**
- **Media Egress Cost**: Cloudflare R2 \$0 Egress Policy = **\$0/mo** *(Savings vs AWS S3: >\$2,500/mo!)*
- **Monitoring & Log Retention**: Dedicated Observability Droplet (8 vCPU, 16 GB RAM) for Prometheus + Grafana + Loki = **\$96/mo**
- **Offsite Backups & WAL Archiving**: R2 Bucket backups = **\$20/mo**
- **Total Monthly Cost (10,000 Screens)**: **\$1,619 / month** (~**\$0.16 per screen/mo**)

> [!CAUTION]
> The estimated total is about **\$0.162 per screen/month**, not a validated production price. Batching reduces request/transaction overhead but not event volume. Add operation charges, realistic database/index/WAL capacity, recovery load, archive growth and headroom; demonstrate performance before publishing efficiency claims.

