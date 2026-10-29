# PIXL 2.0: Scheduling & Conflict-Resolution Specification

> **Status: planning only.** The pseudocode is illustrative. Final scheduling uses precise UTC change boundaries, explicit DST/tie/SOV rules, shared duration enums and atomic version allocation as required by [document 15](15_MEDIA_AND_CAMPAIGN_WORKFLOW_SPEC.md). Do not implement hour-level approximation or unspecified DST behavior as a completed contract.

## 1. Multi-Tier Deterministic Priority Architecture

When multiple campaigns or bookings target the same screen during the same time window, PIXL 2.0 arbitrates playback order using deterministic priority tiers:

| Tier | Priority Value | Campaign Class | Preemption Behavior |
| :--- | :---: | :--- | :--- |
| **Tier 1** | **1000** | **Emergency Alert / Public Safety** | Immediately interrupts any current playback; loops exclusively until revoked. |
| **Tier 2** | **500** | **Guaranteed Sponsorship / Takeover** | 100% Share of Voice (SOV) for contracted hours; preempts standard commercial ads. |
| **Tier 3** | **100** | **Standard Commercial Campaigns** | Interleaved in a round-robin loop according to contracted frequency / hourly impression targets. |
| **Tier 4** | **10** | **Filler / Agency House Promos** | Plays only when Tier 2/3 inventory does not fill the loop cycle. |
| **Tier 5** | **0** | **Default Standby Offline Loop** | Plays when zero campaigns are scheduled or network/manifest is expired. |

---

## 2. Scheduling & Manifest Compilation Algorithm

The schedule compiler runs on the server whenever an Agency clicks **Publish** (and runs periodically in the Celery worker for recurring schedules):

```text
Algorithm CompileScreenManifest(screen_id, window_start, window_end):
  screen = FetchScreenWithSiteAndTimezone(screen_id)
  screen_tz = ZoneInfo(screen.site.timezone)

  // 1. Identify all active, approved campaigns targeting this screen or its groups
  candidate_campaigns = QueryCampaigns(
    screen_id = screen_id,
    status = 'PUBLISHED',
    window_overlaps = (window_start, window_end)
  )

  compiled_schedule_blocks = []

  // 2. Partition evaluation window into discrete time slices (or hour blocks)
  for hour in TimeSlices(window_start, window_end, interval = 1 Hour):
    eligible = FilterCampaignsForHour(candidate_campaigns, hour, screen_tz)
    
    if HasEmergencyTier(eligible):
      compiled_schedule_blocks.append(GetEmergencyBlock(eligible))
      continue

    if HasGuaranteedSponsorshipTier(eligible):
      compiled_schedule_blocks.append(GetSponsorshipBlock(eligible))
      continue

    // Tier 3: Standard Commercial Interleaving (Share of Voice calculation)
    commercial_playlist = BuildInterleavedLoop(eligible, target_loop_duration_sec = 120)
    
    if IsLoopUnderFilled(commercial_playlist):
      commercial_playlist.append(GetHouseAds(screen.organization_id))

    compiled_schedule_blocks.append(commercial_playlist)

  // 3. Extract unique asset dependencies
  referenced_assets = ExtractAssets(compiled_schedule_blocks)

  // 4. Build manifest payload
  manifest_payload = {
    "manifest_id": GenerateUUID(),
    "screen_id": screen_id,
    "version": screen.current_manifest_version + 1,
    "valid_from": window_start.isoformat(),
    "valid_until": window_end.isoformat(),
    "timezone": screen.site.timezone,
    "assets": referenced_assets,
    "schedule": compiled_schedule_blocks,
    "fallback_playlist": FetchTenantDefaultFallback(screen.organization_id)
  }

  // 5. Sign with ED25519
  signature = ED25519_Sign(manifest_payload, SERVER_PRIVATE_KEY)

  return { "signature": signature, "payload": manifest_payload }
```

---

## 3. Video Duration & Truncation Policies

PIXL 2.0 strictly disallows silent assumptions regarding video durations. Every item in a playlist explicitly defines its `duration_mode`:

1. **`FULL_CLIP`**: The video plays until its native EOF container event (reported by Media3/ExoPlayer). The player waits for `onPlaybackStateChanged(STATE_ENDED)` before triggering the next playlist item.
2. **`CUSTOM_DURATION`**: The user configures an explicit playback duration (e.g., exactly 10,000 ms).
   - If the native clip is longer (e.g. 30 seconds), the player stops playback and advances at exactly 10,000 ms.
   - If the native clip is shorter (e.g. 6 seconds), the video loops seamlessly until the 10,000 ms window expires.
3. **`IMAGE_DEFAULT`**: Still images require an explicit duration configuration (default: 10,000 ms).

---

## 4. Timezone & Daylight Saving Time (DST) Handling
1. All timestamp instants are stored internally in PostgreSQL as UTC with timezone (`TIMESTAMPTZ`).
2. Each Screen inherits its physical Site's IANA timezone (e.g., `America/New_York`, `Asia/Kolkata`, `Europe/London`).
3. Schedule day-parting (e.g., "Play Monday to Friday from 08:00 to 20:00") is evaluated on the device using the screen's local clock translated through its assigned IANA timezone database.
4. During daylight saving transitions (spring forward / fall back), schedules adjust smoothly without negative or duplicate hour playback loops.

