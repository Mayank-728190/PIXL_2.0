import pytest
import pyotp
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_no_public_registration_endpoint(client: AsyncClient):
    """AUTH-01 & AUTH-02: Public signup endpoints are strictly absent."""
    response = await client.post("/api/v1/auth/register", json={"email": "hacker@test.com"})
    assert response.status_code == 404

    # Also check legacy variants
    response2 = await client.post("/api/v1/users/register", json={})
    assert response2.status_code == 404

    response3 = await client.post("/api/v1/signup", json={})
    assert response3.status_code == 404


@pytest.mark.asyncio
async def test_master_login_with_totp_mfa(client: AsyncClient, master_admin_user):
    """Verify Master Admin login enforces and succeeds with valid TOTP MFA."""
    user, totp_secret = master_admin_user
    totp = pyotp.TOTP(totp_secret)
    valid_code = totp.now()

    # 1. Missing TOTP -> 401 Unauthorized
    resp_no_mfa = await client.post("/api/v1/auth/master/login", json={
        "email": "master@pixl.io",
        "password": "MasterPassword123!"
    })
    assert resp_no_mfa.status_code == 401
    assert "TOTP" in resp_no_mfa.json()["error"]["message"]

    # 2. Invalid TOTP -> 401 Unauthorized
    resp_bad_mfa = await client.post("/api/v1/auth/master/login", json={
        "email": "master@pixl.io",
        "password": "MasterPassword123!",
        "totp_code": "000000"
    })
    assert resp_bad_mfa.status_code == 401

    # 3. Valid TOTP -> 200 OK and returns Master session cookie
    resp_ok = await client.post("/api/v1/auth/master/login", json={
        "email": "master@pixl.io",
        "password": "MasterPassword123!",
        "totp_code": valid_code
    })
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert data["audience"] == "pixl:audience:master"
    assert "session_token" in data
    from pixl.core.session import SessionManager
    cookie_name = SessionManager.get_cookie_name_for_audience("pixl:audience:master")
    assert cookie_name in resp_ok.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_audience_isolation_cross_panel_rejection(client: AsyncClient, master_admin_user):
    """SEC-06: Master credentials cannot authenticate to Agency panel, and vice versa."""
    user, totp_secret = master_admin_user
    totp = pyotp.TOTP(totp_secret)

    # Master user attempting Agency panel login -> 403 Forbidden
    response = await client.post("/api/v1/auth/agency/login", json={
        "email": "master@pixl.io",
        "password": "MasterPassword123!",
        "totp_code": totp.now()
    })
    assert response.status_code == 403
    assert "Access restricted to Agency members" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_invitation_acceptance_lifecycle(client: AsyncClient, master_auth_headers):
    """AUTH-03: Master creates Agency with expiring invite; user accepts and sets password."""
    # 1. Master creates agency
    create_resp = await client.post(
        "/api/v1/master/agencies",
        headers=master_auth_headers,
        json={
            "name": "Horizon Digital",
            "slug": "horizon",
            "admin_email": "admin@horizon.com",
            "max_screens": 50
        }
    )
    assert create_resp.status_code == 200
    invitation_token = create_resp.json()["invitation_token"]

    # 2. Unregistered user attempts agency login before accepting invite -> 401
    pre_login = await client.post("/api/v1/auth/agency/login", json={
        "email": "admin@horizon.com",
        "password": "AnyPassword"
    })
    assert pre_login.status_code == 401

    # 3. Redeem invitation token
    accept_resp = await client.post("/api/v1/auth/invitation/accept", json={
        "invitation_token": invitation_token,
        "password": "StrongAgencyPassword456!"
    })
    assert accept_resp.status_code == 200
    user_data = accept_resp.json()
    assert user_data["email"] == "admin@horizon.com"
    assert user_data["role"] == "agency_admin"
    assert user_data["status"] == "ACTIVE"

    # 4. Token cannot be reused (one-time consumption) -> 409 Conflict
    reuse_resp = await client.post("/api/v1/auth/invitation/accept", json={
        "invitation_token": invitation_token,
        "password": "AnotherPassword!"
    })
    assert reuse_resp.status_code == 409

    # 5. Agency Admin can now log in successfully
    login_resp = await client.post("/api/v1/auth/agency/login", json={
        "email": "admin@horizon.com",
        "password": "StrongAgencyPassword456!"
    })
    assert login_resp.status_code == 200
    assert login_resp.json()["user"]["role"] == "agency_admin"

