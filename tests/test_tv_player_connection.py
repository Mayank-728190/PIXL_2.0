import pytest
from tests.media_helpers import uploaded_ticket
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient

from pixl.core.session import SessionManager


@pytest.mark.asyncio
async def test_native_android_player_apk_end_to_end_flow(client: AsyncClient, master_auth_headers):
    """
    Validates exact compatibility with app-debug.apk / PixlTvClient:
    1. POST /api/tv/register
    2. GET /api/tv/player/{code}/assignment (unpaired)
    3. GET /api/tv/sync (unpaired)
    4. Agency claims screen via PIN
    5. GET /api/tv/player/{code}/assignment (paired)
    6. Agency publishes campaign
    7. GET /api/tv/sync (downloads campaign & playlist)
    8. Media download via publicUrl
    9. POST /api/tv/ping
    10. POST /api/tv/{screenId}/proof-of-play
    """
    # 1. Setup Agency
    org_resp = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={"name": "TV Fleet Agency", "slug": "tv-fleet", "admin_email": "admin@tvfleet.com"}
    )
    assert org_resp.status_code == 200
    agency_id = org_resp.json()["agency"]["id"]

    token_agency = SessionManager.create_session("u_tv", "agency_admin", "pixl:audience:agency", organization_id=agency_id)
    headers_agency = {"Cookie": f"__Host-PIXL-Agency-Session={token_agency}"}

    # 2. TV Player First Boot: Register
    reg_resp = await client.post("/api/tv/register", json={
        "name": "Sony Bravia 4K TV",
        "location": "HQ Lobby"
    })
    assert reg_resp.status_code == 200
    reg_data = reg_resp.json()
    screen_id = reg_data["screenId"]
    pairing_code = reg_data["pairingCode"]

    assert isinstance(screen_id, int) and screen_id > 0
    assert isinstance(pairing_code, str) and len(pairing_code) == 6
    assert reg_data["status"] == "UNPAIRED"

    # 3. TV Player polls assignment (before pairing)
    assign_resp1 = await client.get(f"/api/tv/player/{pairing_code}/assignment")
    assert assign_resp1.status_code == 200
    assert assign_resp1.json()["isPaired"] is False

    # 4. TV Player syncs (before pairing)
    sync_resp1 = await client.get(f"/api/tv/sync?screenId={screen_id}&pairingCode={pairing_code}")
    assert sync_resp1.status_code == 200
    assert sync_resp1.json()["isPaired"] is False

    # 5. Agency Admin claims the TV Screen using the PIN displayed on the TV
    claim_resp = await client.post(
        "/api/v1/agency/screens/claim",
        headers=headers_agency,
        json={"pin": pairing_code, "name": "Lobby Display Screen"}
    )
    assert claim_resp.status_code == 200
    claimed_screen_uuid = claim_resp.json()["screen_id"]

    # 6. TV Player polls assignment again -> now PAIRED!
    assign_resp2 = await client.get(f"/api/tv/player/{pairing_code}/assignment")
    assert assign_resp2.status_code == 200
    assign_data = assign_resp2.json()
    assert assign_data["isPaired"] is True
    assert assign_data["status"] == "PAIRED"
    assert assign_data["screenName"] == "Lobby Display Screen"

    # 7. Agency uploads media (image and video), creates playlist and publishes a campaign
    ticket_img = (await uploaded_ticket(client,
        "/api/v1/agency/media/upload-ticket",
        headers=headers_agency,
        json={"filename": "poster.png", "size_bytes": 500000, "declared_mime": "image/png"}
    )).json()
    media_img = (await client.post(
        "/api/v1/agency/media/finalize",
        headers=headers_agency,
        json={"ticket_id": ticket_img["ticket_id"]}
    )).json()

    ticket_vid = (await uploaded_ticket(client,
        "/api/v1/agency/media/upload-ticket",
        headers=headers_agency,
        json={"filename": "welcome_promo.mp4", "size_bytes": 10000000, "declared_mime": "video/mp4"}
    )).json()
    media_vid = (await client.post(
        "/api/v1/agency/media/finalize",
        headers=headers_agency,
        json={"ticket_id": ticket_vid["ticket_id"]}
    )).json()

    playlist = (await client.post(
        "/api/v1/agency/playlists",
        headers=headers_agency,
        json={
            "name": "TV Play Loop",
            "items": [
                {
                    "media_id": media_img["id"],
                    "sort_order": 0,
                    "duration_mode": "IMAGE_DEFAULT",
                    "configured_duration_ms": 7000
                },
                {
                    "media_id": media_vid["id"],
                    "sort_order": 1,
                    "duration_mode": "FULL_CLIP",
                    "configured_duration_ms": 13000
                }
            ]
        }
    )).json()

    now = datetime.now(timezone.utc)
    camp = (await client.post(
        "/api/v1/agency/campaigns",
        headers=headers_agency,
        json={
            "name": "Live TV Campaign",
            "playlist_id": playlist["id"],
            "priority": 100,
            "start_time": now.isoformat(),
            "end_time": (now + timedelta(days=7)).isoformat(),
            "screen_ids": [claimed_screen_uuid]
        }
    )).json()

    await client.post(f"/api/v1/agency/campaigns/{camp['id']}/publish", headers=headers_agency)

    # 8. TV Player syncs -> receives the active campaign and playable media
    sync_resp2 = await client.get(f"/api/tv/sync?screenId={screen_id}&pairingCode={pairing_code}")
    assert sync_resp2.status_code == 200
    sync_data = sync_resp2.json()
    assert sync_data["isPaired"] is True
    assert sync_data["status"] == "ACTIVE"
    campaign = sync_data["campaign"]
    assert campaign["id"] > 0
    assert campaign["layoutType"] == "SINGLE"
    assert campaign["endAtMs"] is not None
    assert len(campaign["playlist"]["mediaItems"]) == 2

    media_items = campaign["playlist"]["mediaItems"]
    assert [m["type"] for m in media_items] == ["image", "video"]
    assert [m["durationSeconds"] for m in media_items] == [7, 13]

    # 9. TV Player downloads the media items from publicUrl
    for item in media_items:
        media_url = item["publicUrl"]
        media_path = "/" + media_url.split("/", 3)[-1]
        download_resp = await client.get(media_path)
        assert download_resp.status_code == 200

    # 10. TV Player sends periodic ping
    ping_resp = await client.post("/api/tv/ping", json={
        "screenId": screen_id,
        "pairingCode": pairing_code
    })
    assert ping_resp.status_code == 200
    assert ping_resp.json()["status"] == "ok"

    # 11. TV Player reports Proof-of-Play receipts
    pop_receipts = [
        {
            "mediaId": media_items[0]["id"],
            "campaignId": str(campaign["id"]),
            "durationSeconds": 7,
            "timestamp": int(now.timestamp() * 1000),
            "status": "COMPLETED"
        },
        {
            "mediaId": media_items[1]["id"],
            "campaignId": str(campaign["id"]),
            "durationSeconds": 13,
            "timestamp": int((now + timedelta(seconds=15)).timestamp() * 1000),
            "status": "COMPLETED"
        }
    ]
    pop_resp = await client.post(f"/api/tv/{screen_id}/proof-of-play?pairingCode={pairing_code}", json=pop_receipts)
    assert pop_resp.status_code == 200
    assert pop_resp.json()["saved"] == 2
    replay = await client.post(
        f"/api/tv/{screen_id}/proof-of-play?pairingCode={pairing_code}", json=pop_receipts)
    assert replay.status_code == 200
    assert replay.json()["saved"] == 0
    from sqlalchemy import select
    from pixl.modules.ingestion.models import PlaybackEvent
    from tests.conftest import TestingSessionLocal
    async with TestingSessionLocal() as db:
        events = (await db.execute(select(PlaybackEvent))).scalars().all()
        assert len(events) == 2
        assert {event.media_id for event in events} == {media_img["id"], media_vid["id"]}
