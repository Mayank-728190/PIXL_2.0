import pytest
from httpx import AsyncClient

from pixl.core.session import SessionManager


@pytest.mark.asyncio
async def test_neg_auth_001_anonymous_request_rejected(client: AsyncClient):
    """NEG-AUTH-001: Anonymous requests to protected administrative endpoints return 401."""
    resp = await client.post("/api/v1/master/agencies", json={"name": "Rogue"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_neg_auth_002_public_signup_absent(client: AsyncClient):
    """NEG-AUTH-002: Public signup endpoints return 404."""
    resp = await client.post("/api/v1/auth/register", json={"email": "intruder@pixl.io"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_neg_auth_003_and_004_cross_tenant_read_rejected(client: AsyncClient, master_auth_headers):
    """NEG-AUTH-003 & NEG-AUTH-004: Agency A cannot read Agency B's screens or media (404 masked)."""
    # Create Agency A & B
    resp_a = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={"name": "Org A", "slug": "orga", "admin_email": "a@org.com"}
    )
    org_a_id = resp_a.json()["agency"]["id"]

    resp_b = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={"name": "Org B", "slug": "orgb", "admin_email": "b@org.com"}
    )
    org_b_id = resp_b.json()["agency"]["id"]

    token_a = SessionManager.create_session("u_a", "agency_admin", "pixl:audience:agency", organization_id=org_a_id)
    token_b = SessionManager.create_session("u_b", "agency_admin", "pixl:audience:agency", organization_id=org_b_id)
    headers_a = {"Cookie": f"__Host-PIXL-Agency-Session={token_a}"}
    headers_b = {"Cookie": f"__Host-PIXL-Agency-Session={token_b}"}

    # Master provisions Screen for Agency B
    screen_b = (await client.post(
        "/api/v1/master/screens",
        headers=master_auth_headers,
        json={"name": "Screen B", "organization_id": org_b_id}
    )).json()

    # Agency A tries to read Screen B -> 404 Not Found!
    resp_screen = await client.get(f"/api/v1/agency/screens/{screen_b['id']}", headers=headers_a)
    assert resp_screen.status_code == 404

    # Agency B uploads media
    ticket_b = (await client.post(
        "/api/v1/agency/media/upload-ticket",
        headers=headers_b,
        json={"filename": "asset_b.mp4", "size_bytes": 1000, "declared_mime": "video/mp4"}
    )).json()
    media_b = (await client.post(
        "/api/v1/agency/media/finalize",
        headers=headers_b,
        json={"ticket_id": ticket_b["ticket_id"]}
    )).json()

    # Agency A tries to read Media B -> 404 Not Found!
    resp_media = await client.get(f"/api/v1/agency/media/{media_b['id']}", headers=headers_a)
    assert resp_media.status_code == 404


@pytest.mark.asyncio
async def test_neg_auth_008_agency_admin_cannot_access_master_routes(client: AsyncClient, master_auth_headers):
    """NEG-AUTH-008: Agency credentials cannot access Master administrative endpoints (403 Forbidden)."""
    resp_a = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={"name": "Sub Agency", "slug": "subagency", "admin_email": "sub@agency.com"}
    )
    org_id = resp_a.json()["agency"]["id"]

    token_agency = SessionManager.create_session("u_sub", "agency_admin", "pixl:audience:agency", organization_id=org_id)
    headers_agency = {"Cookie": f"__Host-PIXL-Agency-Session={token_agency}"}

    # Agency Admin attempts to list all agencies -> 403 Forbidden!
    resp = await client.get("/api/v1/master/agencies", headers=headers_agency)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_neg_auth_009_missing_tenant_context_fails_closed(client: AsyncClient):
    """NEG-AUTH-009: Missing tenant context in session fails closed with 403 Forbidden."""
    # Session created with role agency_admin but missing organization_id
    token_orphan = SessionManager.create_session("orphan_user", "agency_admin", "pixl:audience:agency", organization_id=None)
    headers_orphan = {"Cookie": f"__Host-PIXL-Agency-Session={token_orphan}"}

    resp = await client.get("/api/v1/agency/screens", headers=headers_orphan)
    assert resp.status_code == 403
    assert "Missing tenant context" in resp.json()["error"]["message"]

