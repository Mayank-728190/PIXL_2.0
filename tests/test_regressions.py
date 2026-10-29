"""Regression coverage for issues found during the project review."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from pixl.core.config import settings
from pixl.core.database import get_db_session
from pixl.core.exceptions import ConflictError, ForbiddenError
from pixl.core.security import (
    generate_ed25519_keypair, get_server_signing_keys,
    sign_manifest_payload, verify_manifest_signature, verify_totp_code,
)
from pixl.main import app
from pixl.modules.auth.models import User
from pixl.modules.campaigns.models import Campaign, ScreenAssignment
from pixl.modules.campaigns.schemas import CampaignCreateRequest
from pixl.modules.campaigns.service import CampaignService
from pixl.modules.organizations.models import Organization
from pixl.modules.playlists.models import Playlist
from pixl.modules.screens.models import EnrollmentChallenge, Screen
from pixl.modules.screens.service import ScreenService
from tests.conftest import TestingSessionLocal
from pixl.core.session import SessionManager
from starlette.requests import Request
from starlette.responses import Response


def test_bearer_token_is_not_shadowed_by_panel_cookie():
    request = Request({"type": "http", "headers": [
        (b"authorization", b"Bearer explicit-token"),
        (b"cookie", b"__Host-PIXL-Master-Session=other-panel"),
    ]})
    assert SessionManager.extract_session_token(request) == "explicit-token"


@pytest.mark.parametrize("secure", [False, True])
def test_cookie_prefix_and_logout_security(monkeypatch, secure):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", secure)
    response = Response()
    SessionManager.attach_session_cookie(response, "token", "pixl:audience:master")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-" if secure else "PIXL-")
    assert ("Secure" in cookie) is secure
    logout = Response()
    SessionManager.clear_session_cookie(logout, "pixl:audience:master")
    assert ("Secure" in logout.headers["set-cookie"]) is secure


@pytest.mark.parametrize("path", ["../outside.txt", "..\\outside.txt"])
async def test_media_path_cannot_escape_storage(client, tmp_path, monkeypatch, path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "local_storage").mkdir()
    (tmp_path / "outside.txt").write_text("private data")
    encoded = path.replace("..", "%2E%2E").replace("\\", "%5C")
    response = await client.get(f"/media/{encoded}")
    assert response.status_code == 404
    assert "private data" not in response.text


async def test_real_media_is_served_and_production_missing_media_is_404(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "LOCAL_STORAGE_PATH", str(tmp_path / "local_storage"))
    (tmp_path / "local_storage" / "published").mkdir(parents=True)
    (tmp_path / "local_storage" / "published" / "clip.mp4").write_bytes(b"actual media")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    from pixl.core.storage import public_media_url
    assert (await client.get(public_media_url("published/clip.mp4"))).content == b"actual media"
    assert (await client.get("/media/missing.mp4")).status_code == 404
    assert (await client.get("/media/missing.png")).status_code == 404


async def test_readiness_checks_database(client):
    assert (await client.get("/api/v1/health/ready")).status_code == 200
    original = app.dependency_overrides[get_db_session]
    db = AsyncMock()
    db.execute.side_effect = OperationalError("SELECT 1", {}, Exception("unavailable"))

    async def unavailable_db():
        yield db

    app.dependency_overrides[get_db_session] = unavailable_db
    try:
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["database"] == "UNAVAILABLE"
        assert (await client.get("/health")).status_code == 200
    finally:
        app.dependency_overrides[get_db_session] = original


async def test_master_without_mfa_cannot_login(client, master_admin_user):
    user, _ = master_admin_user
    async with TestingSessionLocal() as db:
        stored = await db.get(User, user.id)
        stored.is_mfa_enabled = False
        stored.totp_secret = None
        await db.commit()
    response = await client.post("/api/v1/auth/master/login", json={
        "email": user.email, "password": "MasterPassword123!",
    })
    assert response.status_code == 401


async def test_suspended_agency_cannot_login_again(client, master_admin_user):
    user, _ = master_admin_user
    async with TestingSessionLocal() as db:
        org = Organization(name="Suspended", slug="suspended", status="SUSPENDED")
        db.add(org)
        await db.flush()
        stored = await db.get(User, user.id)
        stored.role = "agency_admin"
        stored.organization_id = org.id
        await db.commit()
    response = await client.post("/api/v1/auth/agency/login", json={
        "email": user.email, "password": "MasterPassword123!",
    })
    assert response.status_code == 403


def test_signing_derives_public_key_and_rejects_mismatch(monkeypatch):
    private, public = generate_ed25519_keypair()
    monkeypatch.setattr(settings, "MANIFEST_SIGNING_PRIVATE_KEY_B64", private)
    monkeypatch.setattr(settings, "MANIFEST_SIGNING_PUBLIC_KEY_B64", "")
    assert get_server_signing_keys() == (private, public)
    payload = {"version": 1}
    assert verify_manifest_signature(payload, sign_manifest_payload(payload, private), public)
    _, other_public = generate_ed25519_keypair()
    monkeypatch.setattr(settings, "MANIFEST_SIGNING_PUBLIC_KEY_B64", other_public)
    with pytest.raises(ValueError, match="does not match"):
        get_server_signing_keys()


def test_production_requires_persistent_signing_key(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "MANIFEST_SIGNING_PRIVATE_KEY_B64", "")
    monkeypatch.setattr(settings, "MANIFEST_SIGNING_PUBLIC_KEY_B64", "")
    with pytest.raises(ValueError, match="private key is required"):
        get_server_signing_keys()


def test_malformed_totp_secret_fails_closed():
    assert verify_totp_code("not valid base32!", "123456") is False


async def test_future_campaign_is_not_played_or_stopped(client):
    now = datetime.now(timezone.utc)
    async with TestingSessionLocal() as db:
        org = Organization(name="Scheduling", slug="scheduling")
        db.add(org)
        await db.flush()
        screen = Screen(name="TV", screen_number=1001, organization_id=org.id,
                        pairing_code="ABCDEF", status="PAIRED")
        playlist = Playlist(name="Future playlist", organization_id=org.id)
        db.add_all([screen, playlist])
        await db.flush()
        campaign = Campaign(name="Future", organization_id=org.id,
                            playlist_id=playlist.id, status="PUBLISHED", priority=999,
                            start_time=now + timedelta(days=1), end_time=now + timedelta(days=2))
        db.add(campaign)
        await db.flush()
        db.add(ScreenAssignment(screen_id=screen.id, campaign_id=campaign.id))
        await db.commit()
        screen_id = screen.id
        assert (await ScreenService.get_current_playback(db, screen_id, org.id))["current_campaign"] is None
        assert (await ScreenService.stop_ad_on_screen(db, screen_id, org.id))["status"] == "NO_ACTIVE_AD"
    assignment = await client.get("/api/tv/player/ABCDEF/assignment")
    assert assignment.json()["campaignId"] is None
    sync = await client.get("/api/tv/sync?screenId=1001&pairingCode=ABCDEF")
    assert sync.json()["campaign"] is None


async def test_unpaired_ping_cannot_mark_screen_playing(client):
    registered = (await client.post("/api/tv/register", json={"name": "TV"})).json()
    await client.post("/api/tv/ping", json={
        "screenId": registered["screenId"], "pairingCode": registered["pairingCode"],
    })
    async with TestingSessionLocal() as db:
        from sqlalchemy import select
        screen = (await db.execute(select(Screen))).scalar_one()
        assert screen.status == "UNPAIRED"
        assert screen.last_heartbeat_at is None


async def test_heartbeat_records_zero_free_space():
    async with TestingSessionLocal() as db:
        screen = Screen(name="Full disk", storage_free_bytes=1024)
        db.add(screen)
        await db.commit()
        await ScreenService.process_heartbeat(db, screen.id, 0, "PLAYING", 0)
        assert screen.storage_free_bytes == 0


async def test_expired_claimed_challenge_cannot_be_exchanged():
    async with TestingSessionLocal() as db:
        screen = Screen(name="Expired")
        db.add(screen)
        await db.flush()
        challenge = EnrollmentChallenge(pin="ABCDEF", hw_fingerprint="test",
            screen_id=screen.id, status="CLAIMED",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        db.add(challenge)
        await db.commit()
        with pytest.raises(ConflictError, match="expired"):
            await ScreenService.exchange_device_credentials(db, challenge.id, "test key")


async def test_bound_pairing_challenge_cannot_claim_different_screen():
    async with TestingSessionLocal() as db:
        first, second = Screen(name="First"), Screen(name="Second")
        db.add_all([first, second])
        await db.flush()
        challenge = EnrollmentChallenge(pin="ABCDEF", hw_fingerprint="test",
            screen_id=first.id, status="PENDING",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        db.add(challenge)
        await db.commit()
        with pytest.raises(ForbiddenError, match="different screen"):
            await ScreenService.agency_claim_screen(db, "agency", "ABCDEF", second.id)


async def test_duplicate_campaign_screen_ids_are_rejected():
    now = datetime.now(timezone.utc)
    req = CampaignCreateRequest(name="Duplicate", playlist_id="playlist",
        start_time=now, end_time=now + timedelta(hours=1), screen_ids=["screen", "screen"])
    async with TestingSessionLocal() as db:
        with pytest.raises(ConflictError, match="Duplicate"):
            await CampaignService.create_campaign(db, "agency", req)
