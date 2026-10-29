# ADR-005: ED25519 Signed Versioned Manifests for Resilient Offline Authorization

> **Implementation status: not implemented or verified in this repository.** Accepted records architectural direction only. Apply the [requirements baseline](../13_REQUIREMENTS_BASELINE_AND_DELIVERY_PLAN.md) and [security/protocol prerequisites](../18_SECURITY_AND_PROTOCOL_IMPLEMENTATION_PREREQUISITES.md) before implementation; stronger guarantee language below is not test evidence.

## Status
**Accepted**

## Context
Digital signage screens installed in airports, malls, and transit hubs frequently experience intermittent network cuts lasting hours or days. The player must operate autonomously without making real-time network requests for every ad play. However, screens must not execute tampered manifests or replay expired commercial campaigns indefinitely.

## Decision
We implement **Cryptographically Signed, Time-Bounded Manifests**:
1. When a campaign schedule is compiled, the backend packages the schedule and asset SHA-256 hashes into an immutable JSON manifest.
2. The payload is signed with a high-performance **ED25519** private key managed by the server.
3. The Android client verifies the signature against the server's public key (stored securely in Android Keystore / APK assets).
4. Manifests define strict temporal validity (`valid_from` and `valid_until`, default 72 hours).
5. If the network is unavailable, the device continues executing the verified manifest until `valid_until`. Past this boundary, the player transitions to a pre-cached fallback standby loop.

## Consequences
- **Positive**: Complete offline resiliency; zero playback stutter; immunity to man-in-the-middle manifest poisoning; provable contract boundaries for ad delivery.
- **Negative**: Immediate remote revocation cannot take effect while a screen is physically disconnected from the network.

