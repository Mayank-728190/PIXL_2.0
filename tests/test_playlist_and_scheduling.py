from datetime import datetime, timezone, timedelta
import pytest
from tests.media_helpers import uploaded_ticket
from httpx import AsyncClient

from pixl.core.session import SessionManager
from pixl.core.security import verify_manifest_signature


@pytest.mark.asyncio
async def test_playlist_scheduling_and_manifest_signing(client: AsyncClient, master_auth_headers):
    # Setup Agency A and Agency B
    resp_a = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={"name": "Agency Alfa", "slug": "alfa", "admin_email": "admin@alfa.com"}
    )
    org_a_id = resp_a.json()["agency"]["id"]

    resp_b = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={"name": "Agency Beta", "slug": "beta", "admin_email": "admin@beta.com"}
    )
    org_b_id = resp_b.json()["agency"]["id"]

    token_a = SessionManager.create_session("u_alfa", "agency_admin", "pixl:audience:agency", organization_id=org_a_id)
    token_b = SessionManager.create_session("u_beta", "agency_admin", "pixl:audience:agency", organization_id=org_b_id)
    headers_a = {"Cookie": f"__Host-PIXL-Agency-Session={token_a}"}
    headers_b = {"Cookie": f"__Host-PIXL-Agency-Session={token_b}"}

    # Upload Media for Agency A and Media for Agency B
    ticket_a = await uploaded_ticket(client,
        "/api/v1/agency/media/upload-ticket",
        headers=headers_a,
        json={"filename": "clip_a.mp4", "size_bytes": 1000000, "declared_mime": "video/mp4"}
    )
    media_a = (await client.post(
        "/api/v1/agency/media/finalize",
        headers=headers_a,
        json={"ticket_id": ticket_a.json()["ticket_id"]}
    )).json()

    ticket_b = await uploaded_ticket(client,
        "/api/v1/agency/media/upload-ticket",
        headers=headers_b,
        json={"filename": "clip_b.mp4", "size_bytes": 1000000, "declared_mime": "video/mp4"}
    )
    media_b = (await client.post(
        "/api/v1/agency/media/finalize",
        headers=headers_b,
        json={"ticket_id": ticket_b.json()["ticket_id"]}
    )).json()

    # NEGATIVE TEST: Agency A attempts to add Agency B's media into its playlist -> 403 Forbidden!
    bad_playlist = await client.post(
        "/api/v1/agency/playlists",
        headers=headers_a,
        json={
            "name": "Cross Tenant Playlist",
            "items": [{"media_id": media_b["id"], "sort_order": 0, "duration_mode": "FULL_CLIP"}]
        }
    )
    assert bad_playlist.status_code == 403
    assert "Cross-tenant violation" in bad_playlist.json()["error"]["message"]

    # POSITIVE TEST: Agency A creates valid playlist with explicit duration modes
    valid_playlist = await client.post(
        "/api/v1/agency/playlists",
        headers=headers_a,
        json={
            "name": "Summer Loop",
            "items": [
                {
                    "media_id": media_a["id"],
                    "sort_order": 0,
                    "duration_mode": "CUSTOM_DURATION",
                    "configured_duration_ms": 12000
                }
            ]
        }
    )
    assert valid_playlist.status_code == 200
    playlist_id = valid_playlist.json()["id"]

    # Master provisions Screen for Agency A
    screen = (await client.post(
        "/api/v1/master/screens",
        headers=master_auth_headers,
        json={"name": "Screen 01", "organization_id": org_a_id}
    )).json()
    screen_id = screen["id"]

    # Device enrolls
    challenge = (await client.post("/api/v1/device/enroll/challenge", json={"hardware_fingerprint": "hw_fingerprint_01"})).json()
    assert "pin" in challenge, f"Challenge failed: {challenge}"
    await client.post(
        "/api/v1/agency/screens/claim",
        headers=headers_a,
        json={"pin": challenge["pin"], "screen_id": screen_id}
    )
    exchange = (await client.post(
        "/api/v1/device/enroll/exchange",
        json={"challenge_id": challenge["challenge_id"], "public_key_pem": "test_pub_key"}
    )).json()
    device_token = exchange["device_token"]
    server_pubkey = exchange["server_public_key_pem"]

    # Agency A creates Campaign
    now = datetime.now(timezone.utc)
    camp = (await client.post(
        "/api/v1/agency/campaigns",
        headers=headers_a,
        json={
            "name": "Summer Sale 2026",
            "playlist_id": playlist_id,
            "priority": 100,
            "start_time": now.isoformat(),
            "end_time": (now + timedelta(days=7)).isoformat(),
            "screen_ids": [screen_id]
        }
    )).json()

    # Agency A publishes Campaign
    pub = await client.post(
        f"/api/v1/agency/campaigns/{camp['id']}/publish",
        headers=headers_a
    )
    assert pub.status_code == 200
    assert pub.json()["status"] == "PUBLISHED"

    # Device fetches signed manifest
    manifest_resp = await client.get(
        "/api/v1/device/manifest",
        headers={"X-Device-Token": device_token}
    )
    assert manifest_resp.status_code == 200
    manifest_data = manifest_resp.json()
    signature = manifest_data["signature"]
    payload = manifest_data["payload"]

    assert payload["screen_id"] == screen_id
    assert len(payload["assets"]) == 1
    assert payload["assets"][0]["id"] == media_a["id"]
    assert len(payload["schedule"]) == 1
    assert payload["schedule"][0]["campaign_id"] == camp["id"]
    assert len(payload["fallback_playlist"]) >= 1

    # Cryptographically verify the signature
    is_valid_sig = verify_manifest_signature(payload, signature, server_pubkey)
    assert is_valid_sig is True
