# PIXL 2.0 — UI/UX and Live Dashboard Specification

Status: Specified; no UI implementation exists in this repository. Scope IDs: UX-01–08, DASH-01–05; see [traceability](17_REQUIREMENTS_TRACEABILITY_MATRIX.md).

## 1. Design direction and approval

Redesign both Master and Agency dashboards as client-ready operational tools. Present two reference boards using familiar applications such as Instagram or a UPI app for hierarchy, navigation, feedback, and task simplicity. Do not copy branding or assume a reference has been approved.

Use neutral surfaces, one restrained accent, clear typography and purposeful density. Avoid generic purple/blue gradient backgrounds, excessive pill/rounded cards, and unnecessary card-per-field/boxy layouts. Prefer tables/lists for fleet and media operations; cards only where grouping improves comprehension.

Approve these screens before full implementation: login, Master agency/admin management, global screen assignment, Agency fleet, media library and upload tray, campaign composer, advertiser purchase/request view, empty/error/loading states.

## 2. Design system

Proposed starting tokens, subject to design approval:

- Spacing: 4, 8, 12, 16, 24, 32, 48 px; consistent page gutters and form rhythm.
- Typography: one accessible sans-serif family; body 16px; supporting text at least 12px; explicit heading/body/label hierarchy.
- Color roles: background, surface, text-primary/secondary, border, accent, success, warning, danger. Status must use text/icon as well as color.
- Controls: shared button variants, text/select/date/time inputs, validation messages, tables, dialogs, tooltips, toast notifications, menus, upload rows, status badges.
- Corners: restrained default 4–8px; avoid pervasive oversized rounding.
- Interaction: visible focus, keyboard traversal, disabled/loading/destructive states, confirmations for destructive actions; touch targets normally at least 44px.
- Contrast: WCAG AA contrast targets; errors associated with fields and announced to assistive technology.

Implement reusable tokens and components, not per-page approximations. Test light/dark themes only if both are explicitly in scope; a second theme is not required by this baseline.

## 3. Information architecture

Master navigation: overview, agencies, administrator accounts, global screens/assignments, audit/settings. Agency navigation: overview, screens/groups, media, campaigns, bookings/brands, reports. Advertiser views expose approved inventory, own media, own bookings and delivery only.

Primary actions remain discoverable and consistently placed. Preserve table filters and selections during navigation where safe. Provide breadcrumbs/back paths, meaningful empty states and recovery actions. Never present a control the backend will systematically reject for that role.

## 4. Responsive behavior

Acceptance viewports: 360×800, 768×1024, 1366×768, 1920×1080; also exercise 200% browser zoom. Navigation collapses predictably; forms become single-column where needed; primary actions remain visible. Tables may have labeled internal horizontal scrolling, but the page must not overflow horizontally. Dialogs and menus fit the viewport, with focus restored on close.

## 5. Media three-dot menu fix

Render contextual menus in a portal/overlay outside clipping/scroll containers. Calculate available viewport space and flip above/left when needed; constrain height and permit internal scrolling. Support scrolling, resize, browser zoom, keyboard activation, arrows, Escape, outside click, and focus return. Use a stacking layer above table rows without covering unrelated modal dialogs.

Acceptance: every action remains reachable for the last media item at the bottom/right edge at each viewport and at 200% zoom. Test media grid and list views, long translated labels, and nested scroll containers.

## 6. Live presence contract

Use authenticated SSE/WebSocket dashboard updates or an equivalent asynchronous fallback. No full-page refresh required. Backend observes device heartbeats; browser connectivity is a separate state.

Proposed tunable defaults (D07): heartbeat H=60s; ONLINE if last authenticated heartbeat age ≤90s, STALE if >90s and ≤180s, OFFLINE if >180s. UNKNOWN means observation infrastructure cannot establish current presence. REVOKED is an administrative state, not proof of physical disconnection. Persist last-known heartbeat; expose current connection state and data observation time. Use server receive time rather than device clock to determine liveness.

- Fleet API returns `screen_id`, `last_heartbeat_at`, `connection_status`, `status_observed_at`, `manifest_version`, and synchronization summary.
- Push subscription scope is enforced by backend role and organization; clients cannot subscribe by arbitrary tenant ID.
- Dashboard shows last seen in relative form with exact timestamp on demand, current connection status, stale-data indicator, and last successful observation.
- A status transition should appear within 5s of the server determining it under normal connectivity. Offline determination itself follows configured thresholds, not a 5s heartbeat promise.
- On page load/reconnect, retrieve an authoritative scoped snapshot before accepting deltas; use event version/cursor or refetch on gaps. Redis restart marks observation uncertainty rather than falsely declaring all devices offline.
- On push loss, show reconnecting and fall back to jittered asynchronous polling, default 30s while visible. Pause/reduce background-tab polling. Re-authenticate after expiration; never keep displaying unauthorized tenant data after tenant/account changes.
- Distinguish network online, player playing, media ready, and PoP backlog. A connected device may still be stalled or syncing.

## 7. Dashboard acceptance scenarios

1. Heartbeat arrives: last-seen and status update without reload; revoked devices cannot refresh presence.
2. Disconnect: STALE then OFFLINE according to configured server thresholds.
3. Extended outage then reconnect: snapshot repairs missed changes; last-seen advances; pending receipts drain without duplicate counts.
4. Browser stream disconnect: existing data is labeled stale, not presented as live.
5. Tenant switch/reassignment: old subscriptions and rows are removed; unauthorized deltas are rejected server-side.
6. Screen detail displays queued/last-acknowledged PoP sync information when reported; server receipt counts reconcile after reconnection.

E2E tests must cover all six, viewport/menu cases, keyboard use, loading/empty/error states and design review approval.
