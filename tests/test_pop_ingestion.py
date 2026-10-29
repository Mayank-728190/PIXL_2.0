from datetime import datetime, timezone
import pytest
from httpx import AsyncClient

from pixl.core.session import SessionManager


@pytest.mark.asyncio
async def test_monotonic_pop_ingestion_and_idempotency(client: AsyncClient, master_auth_headers):
    # Setup Agency and Screen
    org = (await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={"name": "PoP Agency", "slug": "pop-agency", "admin_email": "admin@pop.com"}
    )).json()["agency"]
    org_id = org["id"]

    token_agency = SessionManager.create_session("u_pop", "agency_admin", "pixl:audience:agency", organization_id=org_id)
    headers_agency = {"Cookie": f"__Host-PIXL-Agency-Session={token_agency}"}

    # Provision and pair screen
    screen = (await client.post(
        "/api/v1/master/screens",
        headers=master_auth_headers,
        json={"name": "PoP Screen 01", "organization_id": org_id}
    )).json()
    screen_id = screen["id"]

    challenge = (await client.post("/api/v1/device/enroll/challenge", json={"hardware_fingerprint": "hw_pop_01"})).json()
    await client.post(
        "/api/v1/agency/screens/claim",
        headers=headers_agency,
        json={"pin": challenge["pin"], "screen_id": screen_id}
    )
    exchange = (await client.post(
        "/api/v1/device/enroll/exchange",
        json={"challenge_id": challenge["challenge_id"], "public_key_pem": "pub_key_pem"}
    )).json()
    device_token = exchange["device_token"]
    dev_headers = {"X-Device-Token": device_token}

    now = datetime.now(timezone.utc)

    # 1. First valid batch: sequences 1, 2, 3
    batch_1 = {
        "device_id": screen_id,
        "epoch": 1,
        "batch": [
            {
                "local_sequence": 1,
                "media_id": "media_001",
                "started_at": now.isoformat(),
                "duration_ms": 15000,
                "outcome": "COMPLETED"
            },
            {
                "local_sequence": 2,
                "media_id": "media_001",
                "started_at": now.isoformat(),
                "duration_ms": 15000,
                "outcome": "COMPLETED"
            },
            {
                "local_sequence": 3,
                "media_id": "media_002",
                "started_at": now.isoformat(),
                "duration_ms": 10000,
                "outcome": "COMPLETED"
            }
        ]
    }
    resp_1 = await client.post("/api/v1/device/playback/batch", headers=dev_headers, json=batch_1)
    assert resp_1.status_code == 200
    data_1 = resp_1.json()
    assert data_1["status"] == "ACK"
    assert data_1["last_committed_sequence"] == 3
    assert len(data_1["dispositions"]) == 3
    assert all(d["status"] == "STORED" for d in data_1["dispositions"])

    # 2. Duplicate retry test (network timeout simulation): resending batch_1
    resp_dupe = await client.post("/api/v1/device/playback/batch", headers=dev_headers, json=batch_1)
    assert resp_dupe.status_code == 200
    data_dupe = resp_dupe.json()
    assert data_dupe["status"] == "ACK"
    assert data_dupe["last_committed_sequence"] == 3
    assert len(data_dupe["dispositions"]) == 3
    # Confirms idempotent acknowledgment without creating new rows
    assert all(d["status"] == "DUPLICATE_ACKNOWLEDGED" for d in data_dupe["dispositions"])

    # 3. Contiguous progression: sequence 4
    batch_2 = {
        "device_id": screen_id,
        "epoch": 1,
        "batch": [
            {
                "local_sequence": 4,
                "media_id": "media_002",
                "started_at": now.isoformat(),
                "duration_ms": 10000,
                "outcome": "COMPLETED"
            }
        ]
    }
    resp_2 = await client.post("/api/v1/device/playback/batch", headers=dev_headers, json=batch_2)
    assert resp_2.status_code == 200
    assert resp_2.json()["last_committed_sequence"] == 4

    # 4. Sequence Gap Detection: Device skips sequence 5 and sends sequence 6!
    batch_gap = {
        "device_id": screen_id,
        "epoch": 1,
        "batch": [
            {
                "local_sequence": 6,
                "media_id": "media_003",
                "started_at": now.isoformat(),
                "duration_ms": 15000,
                "outcome": "COMPLETED"
            }
        ]
    }
    resp_gap = await client.post("/api/v1/device/playback/batch", headers=dev_headers, json=batch_gap)
    assert resp_gap.status_code == 409
    gap_data = resp_gap.json()["error"]["details"]
    assert gap_data["status"] == "GAP_DETECTED"
    assert gap_data["expected_sequence"] == 5
    assert gap_data["received_sequence"] == 6
    assert gap_data["action"] == "RESEND_FROM_CURSOR"

    # 5. Token Impersonation Rejection: Device 1 attempts to submit batch for different screen_id
    rogue_batch = {
        "device_id": "foreign_screen_id",
        "epoch": 1,
        "batch": [
            {
                "local_sequence": 1,
                "media_id": "m1",
                "started_at": now.isoformat(),
                "duration_ms": 5000,
                "outcome": "COMPLETED"
            }
        ]
    }
    resp_impersonate = await client.post("/api/v1/device/playback/batch", headers=dev_headers, json=rogue_batch)
    assert resp_impersonate.status_code == 403
