import asyncio
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient

from pixl.core.session import SessionManager
from pixl.core.security import verify_manifest_signature


@pytest.mark.asyncio
async def test_full_platform_concurrent_simulation(client: AsyncClient, master_auth_headers):
    """
    Executes all platform functions simultaneously in parallel:
    - Master provisions 3 agencies concurrently
    - 3 Agencies claim screens concurrently
    - Concurrent media uploads & finalization
    - Concurrent playlist compilation & duration mode checks
    - Concurrent campaign publishing & ED25519 signed manifest generation
    - Concurrent device heartbeat and monotonic PoP batch ingestion
    """
    # 1. Concurrent agency provisioning by Master
    async def provision_agency(idx: int):
        resp = await client.post(
            "/api/v1/master/agencies",
            headers=master_auth_headers,
            json={
                "name": f"Sim Agency {idx}",
                "slug": f"sim-agency-{idx}",
                "admin_email": f"admin{idx}@sim.com",
                "max_screens": 100
            }
        )
        assert resp.status_code == 200
        return resp.json()["agency"]

    agencies = await asyncio.gather(*(provision_agency(i) for i in range(1, 4)))
    assert len(agencies) == 3

    # 2. Concurrently provision screens for each agency
    async def setup_screen_for_agency(agency: dict, idx: int):
        org_id = agency["id"]
        # Master provisions screen
        s_resp = await client.post(
            "/api/v1/master/screens",
            headers=master_auth_headers,
            json={"name": f"Sim Screen {idx}", "organization_id": org_id}
        )
        assert s_resp.status_code == 200
        screen_id = s_resp.json()["id"]

        # Device requests PIN
        c_resp = await client.post(
            "/api/v1/device/enroll/challenge",
            json={"hardware_fingerprint": f"sim_hw_fingerprint_{idx}"}
        )
        assert c_resp.status_code == 200, f"Challenge creation failed: {c_resp.text}"
        challenge = c_resp.json()

        # Agency claims screen
        token = SessionManager.create_session(f"user_{idx}", "agency_admin", "pixl:audience:agency", organization_id=org_id)
        agency_headers = {"Cookie": f"__Host-PIXL-Agency-Session={token}"}

        claim_resp = await client.post(
            "/api/v1/agency/screens/claim",
            headers=agency_headers,
            json={"pin": challenge["pin"], "screen_id": screen_id}
        )
        assert claim_resp.status_code == 200, f"Claim failed: {claim_resp.text}"

        # Device exchanges credentials
        exchange = (await client.post(
            "/api/v1/device/enroll/exchange",
            json={"challenge_id": challenge["challenge_id"], "public_key_pem": f"pub_key_{idx}"}
        )).json()

        return agency_headers, screen_id, exchange["device_token"], exchange["server_public_key_pem"]

    screen_setups = await asyncio.gather(*(setup_screen_for_agency(agencies[i], i + 1) for i in range(3)))

    # 3. Concurrently upload media, create playlists, and publish campaigns for all agencies
    now = datetime.now(timezone.utc)

    async def workflow_per_agency(setup, idx: int):
        agency_headers, screen_id, device_token, server_pubkey = setup

        # Upload Media
        ticket = (await client.post(
            "/api/v1/agency/media/upload-ticket",
            headers=agency_headers,
            json={"filename": f"ad_{idx}.mp4", "size_bytes": 15000000, "declared_mime": "video/mp4"}
        )).json()

        media = (await client.post(
            "/api/v1/agency/media/finalize",
            headers=agency_headers,
            json={"ticket_id": ticket["ticket_id"]}
        )).json()

        # Create Playlist
        playlist = (await client.post(
            "/api/v1/agency/playlists",
            headers=agency_headers,
            json={
                "name": f"Sim Playlist {idx}",
                "items": [
                    {
                        "media_id": media["id"],
                        "sort_order": 0,
                        "duration_mode": "FULL_CLIP",
                        "configured_duration_ms": 15000
                    }
                ]
            }
        )).json()

        # Create and Publish Campaign
        camp = (await client.post(
            "/api/v1/agency/campaigns",
            headers=agency_headers,
            json={
                "name": f"Sim Campaign {idx}",
                "playlist_id": playlist["id"],
                "priority": 100,
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(days=3)).isoformat(),
                "screen_ids": [screen_id]
            }
        )).json()

        pub = await client.post(f"/api/v1/agency/campaigns/{camp['id']}/publish", headers=agency_headers)
        assert pub.status_code == 200

        # Device pulls manifest
        manifest_resp = await client.get("/api/v1/device/manifest", headers={"X-Device-Token": device_token})
        assert manifest_resp.status_code == 200
        m_data = manifest_resp.json()
        assert verify_manifest_signature(m_data["payload"], m_data["signature"], server_pubkey) is True

        # Agency Admin tests instant ad trigger to play a new ad on the screen
        play_ad_res = await client.post(
            f"/api/v1/agency/screens/{screen_id}/play-ad",
            headers=agency_headers,
            json={
                "media_id": media["id"],
                "duration_seconds": 12,
                "name": f"Flash Ad Broadcast {idx}",
                "priority": 250
            }
        )
        assert play_ad_res.status_code == 200
        assert play_ad_res.json()["status"] == "PLAYING"

        # Check live playback status
        playback_check = await client.get(f"/api/v1/agency/screens/{screen_id}/playback", headers=agency_headers)
        assert playback_check.status_code == 200
        assert playback_check.json()["current_campaign"]["name"] == f"Flash Ad Broadcast {idx}"

        # Device uploads PoP batch
        pop_resp = await client.post(
            "/api/v1/device/playback/batch",
            headers={"X-Device-Token": device_token},
            json={
                "device_id": screen_id,
                "epoch": 1,
                "batch": [
                    {
                        "local_sequence": 1,
                        "media_id": media["id"],
                        "started_at": now.isoformat(),
                        "duration_ms": 15000,
                        "outcome": "COMPLETED"
                    },
                    {
                        "local_sequence": 2,
                        "media_id": media["id"],
                        "started_at": (now + timedelta(seconds=15)).isoformat(),
                        "duration_ms": 15000,
                        "outcome": "COMPLETED"
                    }
                ]
            }
        )
        assert pop_resp.status_code == 200
        assert pop_resp.json()["last_committed_sequence"] == 2

    # Run workflows simultaneously
    await asyncio.gather(*(workflow_per_agency(screen_setups[i], i + 1) for i in range(3)))

    # Verify Browser Screen Simulator page renders with Kiosk disclaimer
    sim_resp = await client.get("/simulator")
    assert sim_resp.status_code == 200
    assert "PIXL 2.0 Screen Simulator" in sim_resp.text
    assert "not equivalent to Android Kiosk" in sim_resp.text

