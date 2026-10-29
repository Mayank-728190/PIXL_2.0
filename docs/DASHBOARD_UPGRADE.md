# Dashboard and access-control upgrade

## Implemented in this change

- Responsive neutral/olive design system, desktop workspace navigation, mobile navigation, consistent forms, focus indicators, skip link, useful empty states and clearer primary actions.
- Master/agency overview metrics from their existing authorized API responses. Fleet-health ring and network-pulse SVG chart use actual screen data, no fabricated revenue or impressions. Pulse is the last 30 successful refresh observations **in this browser session**, not historical uptime. Connection status is not proof of playback.
- Screen table distinguishes latest server-received activity from the actual heartbeat timestamp. Failed refreshes show a stale-data warning.
- Media three-dot actions use a native top-layer dialog, so table overflow cannot clip them; Escape/close and native focus handling work. Use an asset directly in a campaign or manage its selection.
- Fixed an intermittent Windows concurrent-upload containment failure: resolved paths with and without the extended namespace prefix are compared consistently, without weakening traversal checks. Added deterministic Windows and traversal regressions.
- Existing bounded batch uploads and duration modes retained. Full-clip videos disable the irrelevant duration field. Campaign validation errors appear beside the submit button as well as the global status; names are trimmed and validated on the backend too.
- Master can invite additional admins into an existing active agency, view admins and delete admin **access**. Deletion is a retained `DELETED` account record, not erasure of campaign/audit history. Existing sessions are revoked, pending invitations for that identity/agency expire and backend authorization rejects stale sessions. Existing identities cannot be reassigned using the new invitation endpoint.
- Existing invitation-only authentication, separate `/master` and `/agency` paths, deployment panel allowlisting and tenant-scoped APIs are preserved. Public registration routes are tested as unavailable.
- Dashboard polling uses jitter, visibility awareness and exponential failure backoff (roughly 5–60 seconds). Agency fleet refreshes remain frequent; library/campaign lists refresh about every sixth background cycle or on an explicit workflow refresh. No WebSocket service is implied.
- Authenticated heartbeat responses advertise `heartbeat_interval_seconds`, `content_check_interval_seconds` and `recommended_jitter_percent`. Intervals are bounded configuration values. **Device clients must be updated to honor these hints**; this does not modify the bundled APK. Set the offline threshold above several effective heartbeat intervals.

## Local verification

Results: **70 pytest tests passed**; expanded Chrome browser workflow passed twice consecutively after fixing the Windows upload regression; JavaScript syntax, Python compilation and `pip check` passed. Browser layout checks cover 390/768/1440/1920px; action-dialog bounds are also checked at 390×640px.

Run:

```sh
python -m pytest
python -m scripts.check_portals_browser
node --check pixl/portals/portal.js
python -m compileall -q pixl scripts
```

The browser workflow covers provisioning, invitation activation, pairing, two-file upload, mobile dialog bounds, media-to-campaign publication, graphs, responsive layouts, cookie persistence, master-only admin revocation and logout. Automated backend tests cover invitation restrictions, cross-agency deletion rejection, role boundaries, revoked sessions, expired invitations, retained audit records, configuration bounds and registration removal.

## Android research and integration boundary

Firecrawl retrieved the official [Android Lock task mode guide](https://developer.android.com/work/dpc/dedicated-devices/lock-task-mode). Its evidence distinguishes DPC-allowlisted lock task mode from removable screen pinning:

1. Provision a managed dedicated device through a reviewed DPC/device-owner workflow; do not reset customer devices without approval.
2. DPC allowlists the player using `setLockTaskPackages`. Check `isLockTaskPermitted` before entering lock task. Without allowlisting, `startLockTask` enters screen pinning instead.
3. Enter from a foreground lifecycle callback after checking keyguard, or use the manifest's `if_whitelisted` behavior. On supported Android versions, review `setLockTaskFeatures(..., LOCK_TASK_FEATURE_NONE)` and overlay restrictions.
4. Confirm `ActivityManager.LOCK_TASK_MODE_LOCKED`, not merely PINNED. Keep authenticated maintenance/recovery access and test reboot provisioning separately.
5. Test physical Home/Back/Recents, gesture navigation, notifications/overlays, power/reboot, crash, remote maintenance and root/non-root variants. Record OEM/version and system-UI flash with video evidence.

These are integration recommendations based on the retrieved guide, **not compiled or device-tested code in this repository**. A normal app cannot promise exit prevention on every rooted/unrestricted device. Android source and target devices are required; an APK alone is not sufficient for a maintainable implementation.

## Not completed / external dependencies

- Brand/advertiser purchasing, payment rules and purchasing UI remain product work; no payment provider or commercial model was supplied.
- Durable historical analytics and PoP aggregation are not implemented by the session graphs.
- Actual APK offline cache, receipt persistence/retry, interrupted downloads, reboot recovery and kiosk enforcement need Android source and physical acceptance. Backend PoP tests are not evidence of APK offline correctness.
- DigitalOcean deployment, TLS/proxy/CORS across separate domains, real PostgreSQL/Redis operation and high-device-count load/soak tests still need infrastructure access. At 10,000 devices, 60-second heartbeat plus 60-second manifest polling is approximately 333 requests/second before receipt traffic; conditional 304 responses save bytes, not request count. This is a capacity estimate, not a measured result.
- Meeting invitations, Granola sharing and Slack messages were not sent: accounts, attendee addresses, meeting time/link and authorization are required. Existing communication drafts remain drafts.

See [delivery status](DELIVERY_STATUS.md) and [Android reliability specification](16_ANDROID_KIOSK_AND_DEVICE_RELIABILITY_SPEC.md) for remaining release acceptance work. Do not treat passing local checks as a production-ready certification.
