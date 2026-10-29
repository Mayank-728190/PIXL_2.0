import pytest
from httpx import AsyncClient

from pixl.core.session import SessionManager


@pytest.mark.asyncio
async def test_screen_enrollment_and_agency_claiming(client: AsyncClient, master_auth_headers):
    # 1. Master creates Agency A and Agency B
    resp_a = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={"name": "Agency A", "slug": "agency-a", "admin_email": "admin@agencya.com"}
    )
    org_a_id = resp_a.json()["agency"]["id"]

    resp_b = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={"name": "Agency B", "slug": "agency-b", "admin_email": "admin@agencyb.com"}
    )
    org_b_id = resp_b.json()["agency"]["id"]

    # Agency A and Agency B session headers
    token_a = SessionManager.create_session("user_a", "agency_admin", "pixl:audience:agency", organization_id=org_a_id)
    token_b = SessionManager.create_session("user_b", "agency_admin", "pixl:audience:agency", organization_id=org_b_id)
    headers_a = {"Cookie": f"__Host-PIXL-Agency-Session={token_a}"}
    headers_b = {"Cookie": f"__Host-PIXL-Agency-Session={token_b}"}

    # 2. Master provisions a screen assigned to Agency A
    master_screen_resp = await client.post(
        "/api/v1/master/screens",
        headers=master_auth_headers,
        json={"name": "Airport Terminal 1", "organization_id": org_a_id}
    )
    assert master_screen_resp.status_code == 200
    screen_a_id = master_screen_resp.json()["id"]

    # 3. Unregistered Android device requests enrollment PIN
    dev_challenge_resp = await client.post("/api/v1/device/enroll/challenge", json={
        "hardware_fingerprint": "hw_fp_aml_s905x4_001",
        "model": "Amlogic S905X4 Box",
        "app_version": "2.0.0"
    })
    assert dev_challenge_resp.status_code == 200
    challenge_data = dev_challenge_resp.json()
    challenge_id = challenge_data["challenge_id"]
    pin = challenge_data["pin"]
    assert len(pin) == 6

    # 4. NEGATIVE TEST: Agency B attempts to claim Agency A's screen with PIN -> 403 Forbidden!
    rogue_claim = await client.post(
        "/api/v1/agency/screens/claim",
        headers=headers_b,
        json={"pin": pin, "screen_id": screen_a_id}
    )
    assert rogue_claim.status_code == 403

    # 5. POSITIVE TEST: Agency A claims screen with PIN -> 200 OK
    valid_claim = await client.post(
        "/api/v1/agency/screens/claim",
        headers=headers_a,
        json={"pin": pin, "screen_id": screen_a_id, "name": "Airport Gate 12"}
    )
    assert valid_claim.status_code == 200
    assert valid_claim.json()["status"] == "CLAIMED"

    # 6. Device completes exchange using Keystore public key
    exchange_resp = await client.post("/api/v1/device/enroll/exchange", json={
        "challenge_id": challenge_id,
        "public_key_pem": "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A...\n-----END PUBLIC KEY-----"
    })
    assert exchange_resp.status_code == 200
    cred_data = exchange_resp.json()
    device_token = cred_data["device_token"]
    assert cred_data["device_id"] == screen_a_id
    assert cred_data["epoch"] == 1
    assert "server_public_key_pem" in cred_data

    # 7. Device sends periodic heartbeat
    heartbeat_resp = await client.post(
        "/api/v1/device/heartbeat",
        headers={"X-Device-Token": device_token},
        json={
            "device_id": screen_a_id,
            "epoch": 1,
            "manifest_version": 0,
            "playback_state": "PLAYING",
            "storage_free_mb": 14200
        }
    )
    assert heartbeat_resp.status_code == 200
    assert "server_time" in heartbeat_resp.json()

    # 8. Verify Agency A sees the screen in its active fleet
    fleet_resp = await client.get("/api/v1/agency/screens", headers=headers_a)
    assert fleet_resp.status_code == 200
    screens = fleet_resp.json()
    assert len(screens) == 1
    assert screens[0]["id"] == screen_a_id
    assert screens[0]["status"] == "PLAYING"

