import pytest
from httpx import AsyncClient

from pixl.core.session import SessionManager


@pytest.mark.asyncio
async def test_media_quarantine_upload_pipeline(client: AsyncClient, master_auth_headers):
    # Setup Agency A and Agency B
    resp_a = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={"name": "Media Agency A", "slug": "media-a", "admin_email": "admin@media-a.com"}
    )
    org_a_id = resp_a.json()["agency"]["id"]

    resp_b = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={"name": "Media Agency B", "slug": "media-b", "admin_email": "admin@media-b.com"}
    )
    org_b_id = resp_b.json()["agency"]["id"]

    token_a = SessionManager.create_session("u_a", "agency_admin", "pixl:audience:agency", organization_id=org_a_id)
    token_b = SessionManager.create_session("u_b", "agency_admin", "pixl:audience:agency", organization_id=org_b_id)
    headers_a = {"Cookie": f"__Host-PIXL-Agency-Session={token_a}"}
    headers_b = {"Cookie": f"__Host-PIXL-Agency-Session={token_b}"}

    # 1. Invalid MIME type rejected
    bad_ticket = await client.post(
        "/api/v1/agency/media/upload-ticket",
        headers=headers_a,
        json={"filename": "script.exe", "size_bytes": 1024, "declared_mime": "application/x-msdownload"}
    )
    assert bad_ticket.status_code == 422

    # 2. File size exceeding 250MB rejected
    too_large = await client.post(
        "/api/v1/agency/media/upload-ticket",
        headers=headers_a,
        json={"filename": "huge.mp4", "size_bytes": 300 * 1024 * 1024, "declared_mime": "video/mp4"}
    )
    assert too_large.status_code == 422

    # 3. Valid upload ticket requested
    valid_ticket = await client.post(
        "/api/v1/agency/media/upload-ticket",
        headers=headers_a,
        json={"filename": "summer_sale.mp4", "size_bytes": 45 * 1024 * 1024, "declared_mime": "video/mp4"}
    )
    assert valid_ticket.status_code == 200
    ticket_data = valid_ticket.json()
    ticket_id = ticket_data["ticket_id"]
    assert "quarantine" in ticket_data["storage_key"]
    assert "presigned_upload_url" in ticket_data

    # 4. Finalize upload
    final_resp = await client.post(
        "/api/v1/agency/media/finalize",
        headers=headers_a,
        json={"ticket_id": ticket_id, "expected_sha256": "4b9e28f3a8b29c011e038f4d45543c8b417e170f80bc23df2f2a58b5e917d2a1"}
    )
    assert final_resp.status_code == 200
    media_data = final_resp.json()
    media_id = media_data["id"]
    assert media_data["status"] == "READY"
    assert media_data["duration_ms"] == 15000

    # 5. Ticket cannot be reused
    reuse_resp = await client.post(
        "/api/v1/agency/media/finalize",
        headers=headers_a,
        json={"ticket_id": ticket_id}
    )
    assert reuse_resp.status_code == 409

    # 6. NEGATIVE TEST: Agency B cannot read Agency A's media asset -> 404 Not Found
    rogue_read = await client.get(f"/api/v1/agency/media/{media_id}", headers=headers_b)
    assert rogue_read.status_code == 404
