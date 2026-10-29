import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient

from pixl.core.session import SessionManager
from pixl.modules.auth.models import User
from pixl.modules.organizations.models import Organization


@pytest.mark.asyncio
async def test_admin_instant_ad_playback_and_preemption_lifecycle(client: AsyncClient, master_auth_headers):
    """
    Validates end-to-end admin ad playback:
    1. Screen pairs with agency.
    2. Admin uploads ad media (video and image).
    3. Admin triggers 'play-ad' on screen.
    4. TV Player receives the ad manifest on sync and plays it.
    5. TV Player uploads Proof-of-Play receipt.
    6. Admin triggers higher priority ad takeover.
    7. TV Player syncs and immediately switches to the higher priority ad.
    8. Admin stops the ad campaign.
    """
    # 1. Native TV Player registers
    reg_resp = await client.post("/api/tv/register", json={
        "name": "Times Square LED Billboard",
        "location": "Broadway & 45th"
    })
    assert reg_resp.status_code == 200
    reg_data = reg_resp.json()
    screen_id = reg_data["screenId"]
    pairing_code = reg_data["pairingCode"]

    # 2. Master creates Agency
    agency_resp = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={
            "name": "Apex Billboard Agency",
            "slug": "apex-ads",
            "admin_email": "admin@apexads.com",
            "max_screens": 20
        }
    )
    assert agency_resp.status_code == 200
    invitation_token = agency_resp.json()["invitation_token"]

    # Agency admin accepts invite
    await client.post("/api/v1/auth/invitation/accept", json={
        "invitation_token": invitation_token,
        "password": "ApexPassword123!"
    })

    # Agency admin logs in
    login_resp = await client.post("/api/v1/auth/agency/login", json={
        "email": "admin@apexads.com",
        "password": "ApexPassword123!"
    })
    assert login_resp.status_code == 200
    agency_token = login_resp.json()["session_token"]
    headers_agency = {
        "Authorization": f"Bearer {agency_token}",
        "Cookie": f"__Host-PIXL-Agency-Session={agency_token}"
    }

    # 3. Agency claims screen
    claim_resp = await client.post(
        "/api/v1/agency/screens/claim",
        headers=headers_agency,
        json={"pin": pairing_code, "name": "Times Square Screen #1"}
    )
    assert claim_resp.status_code == 200
    screen_uuid = claim_resp.json()["screen_id"]

    # 4. TV Player checks sync before any ad is assigned -> PAIRED_NO_CAMPAIGN
    sync_init = await client.get(f"/api/tv/sync?screenId={screen_id}&pairingCode={pairing_code}")
    assert sync_init.status_code == 200
    assert sync_init.json()["isPaired"] is True
    assert sync_init.json()["campaign"] is None

    # 5. Agency uploads 2 ads: Nike Video Ad & Coke Image Ad
    t_video = (await client.post(
        "/api/v1/agency/media/upload-ticket",
        headers=headers_agency,
        json={"filename": "nike_air_max.mp4", "size_bytes": 15000000, "declared_mime": "video/mp4"}
    )).json()
    m_video = (await client.post(
        "/api/v1/agency/media/finalize",
        headers=headers_agency,
        json={"ticket_id": t_video["ticket_id"]}
    )).json()

    t_image = (await client.post(
        "/api/v1/agency/media/upload-ticket",
        headers=headers_agency,
        json={"filename": "coca_cola_summer.jpg", "size_bytes": 800000, "declared_mime": "image/jpeg"}
    )).json()
    m_image = (await client.post(
        "/api/v1/agency/media/finalize",
        headers=headers_agency,
        json={"ticket_id": t_image["ticket_id"]}
    )).json()

    # 6. Admin wants to play the Nike Ad on the screen!
    play_resp1 = await client.post(
        f"/api/v1/agency/screens/{screen_uuid}/play-ad",
        headers=headers_agency,
        json={
            "media_id": m_video["id"],
            "duration_seconds": 15,
            "name": "Nike Air Max Campaign",
            "priority": 150
        }
    )
    assert play_resp1.status_code == 200
    play_data1 = play_resp1.json()
    assert play_data1["status"] == "PLAYING"
    assert play_data1["media_count"] == 1
    assert play_data1["media_items"][0]["type"] == "video"

    # 7. TV Player syncs -> receives the Nike Ad immediately!
    sync_ad1 = await client.get(f"/api/tv/sync?screenId={screen_id}&pairingCode={pairing_code}")
    assert sync_ad1.status_code == 200
    sync_data1 = sync_ad1.json()
    assert sync_data1["isPaired"] is True
    assert sync_data1["status"] == "ACTIVE"
    camp1 = sync_data1["campaign"]
    assert camp1["name"] == "Nike Air Max Campaign"
    assert len(camp1["playlist"]["mediaItems"]) == 1
    assert camp1["playlist"]["mediaItems"][0]["type"] == "video"
    assert camp1["playlist"]["mediaItems"][0]["durationSeconds"] == 15
    nike_media_id = camp1["playlist"]["mediaItems"][0]["id"]

    # 8. TV Player reports Proof-of-Play receipt for the Nike Ad
    now = datetime.now(timezone.utc)
    pop_resp1 = await client.post(f"/api/tv/{screen_id}/proof-of-play", json=[
        {
            "mediaId": nike_media_id,
            "campaignId": str(camp1["id"]),
            "durationSeconds": 15,
            "timestamp": int(now.timestamp() * 1000),
            "status": "COMPLETED"
        }
    ])
    assert pop_resp1.status_code == 200
    assert pop_resp1.json()["saved"] == 1

    # 9. Admin checks live screen playback status
    playback_status = await client.get(
        f"/api/v1/agency/screens/{screen_uuid}/playback",
        headers=headers_agency
    )
    assert playback_status.status_code == 200
    status_data = playback_status.json()
    assert status_data["is_online"] is True
    assert status_data["current_campaign"]["name"] == "Nike Air Max Campaign"
    assert status_data["current_campaign"]["priority"] == 150

    # 10. Admin wants to trigger an Urgent Ad Takeover (Coca Cola, Priority 300)
    play_resp2 = await client.post(
        f"/api/v1/agency/screens/{screen_uuid}/play-ad",
        headers=headers_agency,
        json={
            "media_id": m_image["id"],
            "duration_seconds": 8,
            "name": "Coca Cola Flash Takeover",
            "priority": 300
        }
    )
    assert play_resp2.status_code == 200
    assert play_resp2.json()["priority"] == 300

    # 11. TV Player syncs again -> high priority 300 overrides priority 150!
    sync_ad2 = await client.get(f"/api/tv/sync?screenId={screen_id}&pairingCode={pairing_code}")
    assert sync_ad2.status_code == 200
    sync_data2 = sync_ad2.json()
    camp2 = sync_data2["campaign"]
    assert camp2["name"] == "Coca Cola Flash Takeover"
    assert camp2["playlist"]["mediaItems"][0]["type"] == "image"
    assert camp2["playlist"]["mediaItems"][0]["durationSeconds"] == 8

    # 12. Admin stops the ad broadcast
    stop_resp = await client.post(
        f"/api/v1/agency/screens/{screen_uuid}/stop-ad",
        headers=headers_agency
    )
    assert stop_resp.status_code == 200
    assert stop_resp.json()["status"] == "STOPPED"

    # 13. Screen syncs after stopping high priority ad -> falls back to previous or idle
    sync_after_stop = await client.get(f"/api/tv/sync?screenId={screen_id}&pairingCode={pairing_code}")
    assert sync_after_stop.status_code == 200
    # Because Nike campaign (priority 150) is still valid and not expired, it resumes!
    assert sync_after_stop.json()["campaign"]["name"] == "Nike Air Max Campaign"
