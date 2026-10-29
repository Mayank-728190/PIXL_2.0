"""Regression coverage for master account lifecycle and dashboard contracts."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from pixl.core.session import SessionManager
from pixl.modules.auth.models import AuditEvent, User, UserInvitation
from pixl.modules.organizations.models import Organization
from tests.conftest import TestingSessionLocal


async def test_master_can_revoke_admin_but_not_other_roles(client, master_auth_headers):
    async with TestingSessionLocal() as db:
        agency = Organization(name="Agency one", slug="agency-one")
        other = Organization(name="Agency two", slug="agency-two")
        db.add_all([agency, other])
        await db.flush()
        admin = User(organization_id=agency.id, email="admin@example.com",
                     hashed_password="unused", role="agency_admin", status="ACTIVE")
        operator = User(organization_id=agency.id, email="operator@example.com",
                        hashed_password="unused", role="agency_operator", status="ACTIVE")
        db.add_all([admin, operator])
        invitation = UserInvitation(organization_id=agency.id, email=admin.email,
                                    role="agency_admin", token="pending-test-invitation",
                                    expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        db.add(invitation)
        await db.commit()
        org_id, other_id, admin_id, operator_id = agency.id, other.id, admin.id, operator.id
    token = SessionManager.create_session(user_id=admin_id, role="agency_admin",
                                         audience="pixl:audience:agency", organization_id=org_id)
    agency_headers = {"Authorization": f"Bearer {token}"}
    path = f"/api/v1/master/agencies/{org_id}/admins"
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=agency_headers)).status_code == 403
    assert (await client.delete(path + f"/{admin_id}", headers=agency_headers)).status_code == 403
    rows = (await client.get(path, headers=master_auth_headers)).json()
    assert len(rows) == 1 and rows[0]["email"] == "admin@example.com"
    assert "hashed_password" not in rows[0] and "totp_secret" not in rows[0]
    assert (await client.delete(f"/api/v1/master/agencies/{other_id}/admins/{admin_id}", headers=master_auth_headers)).status_code == 404
    assert (await client.delete(path + f"/{operator_id}", headers=master_auth_headers)).status_code == 404
    response = await client.delete(path + f"/{admin_id}", headers=master_auth_headers)
    assert response.status_code == 200
    assert SessionManager.get_session(token) is None
    # Idempotent removal and rejected access through a newly forged stale session.
    assert (await client.delete(path + f"/{admin_id}", headers=master_auth_headers)).status_code == 200
    stale = SessionManager.create_session(user_id=admin_id, role="agency_admin",
                                         audience="pixl:audience:agency", organization_id=org_id)
    assert (await client.get("/api/v1/agency/screens", headers={"Authorization": f"Bearer {stale}"})).status_code == 401
    async with TestingSessionLocal() as db:
        assert (await db.get(User, admin_id)).status == "DELETED"
        assert (await db.get(User, operator_id)).status == "ACTIVE"
        invitation = (await db.execute(select(UserInvitation))).scalar_one()
        assert invitation.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)
        audits = (await db.execute(select(AuditEvent).where(AuditEvent.action == "ADMIN_ACCESS_DELETED"))).scalars().all()
        assert len(audits) == 1


async def test_admin_invitation_requires_master_and_active_agency(client, master_auth_headers):
    async with TestingSessionLocal() as db:
        agency = Organization(name="Invite agency", slug="invite-agency")
        db.add(agency)
        await db.commit()
        org_id = agency.id
    path = f"/api/v1/master/agencies/{org_id}/admins"
    assert (await client.post(path, json={"email": "new@example.com"})).status_code == 401
    assert (await client.post(path, headers=master_auth_headers, json={"email": "bad"})).status_code == 422
    response = await client.post(path, headers=master_auth_headers, json={"email": "new@example.com"})
    assert response.status_code == 200
    from urllib.parse import urlparse, parse_qs
    token = parse_qs(urlparse(response.json()["invitation_link"]).query)["token"][0]
    assert (await client.post(path, headers=master_auth_headers, json={"email": "new@example.com"})).status_code == 409
    accepted = await client.post("/api/v1/auth/invitation/accept", json={"invitation_token": token, "password": "NewAdminPassword123!"})
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "agency_admin"
    assert accepted.json()["organization_id"] == org_id
    await client.post(f"/api/v1/master/agencies/{org_id}/suspend", headers=master_auth_headers)
    assert (await client.post(path, headers=master_auth_headers, json={"email": "other@example.com"})).status_code == 409


def test_campaign_name_cannot_be_only_whitespace():
    import pytest
    from pydantic import ValidationError
    from pixl.modules.campaigns.schemas import CampaignCreateRequest
    with pytest.raises(ValidationError):
        CampaignCreateRequest(name="   ", playlist_id="playlist", screen_ids=["screen"],
                              start_time=datetime.now(timezone.utc), end_time=datetime.now(timezone.utc))


async def test_registration_routes_are_not_available(client):
    for path in ("/api/v1/auth/register", "/api/v1/auth/signup", "/register"):
        assert (await client.post(path, json={"email": "public@example.com"})).status_code in (404, 405)


async def test_overview_and_accessible_media_dialog_are_served(client):
    page = (await client.get("/agency")).text
    assert 'id="pulse-chart"' in page
    assert 'id="health-chart"' in page
    assert '<dialog id="media-actions"' in page
    assert 'role="alert"' in page
    assert "not historical uptime" in page


def test_device_poll_settings_are_bounded_and_exposed():
    import pytest
    from pydantic import ValidationError
    from pixl.core.config import Settings
    from pixl.modules.screens.schemas import ScreenHeartbeatResponse
    with pytest.raises(ValidationError):
        Settings(DEVICE_HEARTBEAT_INTERVAL_SECONDS=0)
    with pytest.raises(ValidationError):
        Settings(DEVICE_CONTENT_CHECK_INTERVAL_SECONDS=1)
    response = ScreenHeartbeatResponse(server_time=datetime.now(timezone.utc), latest_manifest_version=1)
    assert response.recommended_jitter_percent == 15
    assert response.heartbeat_interval_seconds >= 10
