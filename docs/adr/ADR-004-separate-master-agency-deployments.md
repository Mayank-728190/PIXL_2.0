# ADR-004: Separate Master and Agency Frontend Deployments with HttpOnly Session Isolation

> **Implementation status: not implemented or verified in this repository.** Accepted records architectural direction only. Apply the [requirements baseline](../13_REQUIREMENTS_BASELINE_AND_DELIVERY_PLAN.md) and [security/protocol prerequisites](../18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md) before implementation; stronger guarantee language below is not test evidence.

## Status
**Accepted**

## Context
Master (Super Admin) operations involve critical infrastructure privileges: provisioning agencies, inspecting global device fleets, and configuring platform keys. Hosting master administrative tools inside the same single-page application as agency dashboards increases attack surface (accidental privilege leaks, bundle analysis, XSS cross-contamination).

## Decision
We maintain **physically separate static frontend deployments**:
1. `master.pixl.io`: Dedicated Master Portal bundle.
2. `agency.pixl.io`: Agency Administrator & Operator bundle.
3. `advertiser.pixl.io`: Dedicated Advertiser Portal bundle.

**Security Enforcements**:
- Separate session cookies with domain/host isolation: `__Host-PIXL-Master-Session` vs `__Host-PIXL-Agency-Session`.
- Master session requires mandatory TOTP MFA.
- Separate deployments are accompanied by strict backend route authorization (`require_role("master_admin")`); frontend separation is an added defense-in-depth layer, never a substitute for backend authorization.
- Explicit CORS whitelist per origin; never wildcard `*` with credentials.

## Consequences
- **Positive**: Strict blast radius isolation; Master JavaScript assets and administrative schemas are never bundled into agency-facing builds.
- **Negative**: Requires independent static deployment pipelines (e.g. Cloudflare Pages or separate S3 buckets).

