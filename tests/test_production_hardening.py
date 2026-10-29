"""Regression coverage for durable jobs, auth replay and lifecycle maintenance."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pyotp
import pytest
from sqlalchemy import func, select

from pixl.core.config import Settings, settings
from pixl.core.exceptions import ConflictError
from pixl.core.security import matching_totp_counter, verify_totp_code
from pixl.core.session import SessionManager
from pixl.core.storage import storage_path
from pixl.modules.auth.models import AuditEvent, User, UserInvitation
from pixl.modules.campaigns.models import Campaign, ScreenAssignment
from pixl.modules.campaigns.service import CampaignService
from pixl.modules.media.models import MediaAsset, UploadTicket
from pixl.modules.media.service import MediaService
from pixl.modules.organizations.models import Organization
from pixl.modules.playlists.models import Playlist, PlaylistItem
from pixl.modules.screens.models import EnrollmentChallenge, Screen
from pixl.modules.screens.service import ScreenService
from pixl.workers.maintenance import maintain_lifecycle
from tests.conftest import TestingSessionLocal
from tests.media_helpers import sample_bytes


@pytest.fixture
async def job_agency(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_PROCESSING_MODE", "worker")
    async with TestingSessionLocal() as db:
        org = Organization(name="Jobs", slug="jobs")
        db.add(org)
        await db.commit()
        token = SessionManager.create_session("operator", "agency_admin", "pixl:audience:agency", organization_id=org.id)
        return org.id, {"Authorization": f"Bearer {token}"}


async def upload(client, headers, content=None):
    if content is None:
        content = sample_bytes("image/png")
    response = await client.post("/api/v1/agency/media/upload-ticket", headers=headers, json={
        "filename": "poster.png", "size_bytes": len(content), "declared_mime": "image/png"})
    assert response.status_code == 200, response.text
    ticket = response.json()
    assert (await client.put(ticket["presigned_upload_url"], content=content)).status_code == 200
    return ticket


async def queue(client, headers, ticket):
    response = await client.post("/api/v1/agency/media/process", headers=headers, json={"ticket_id": ticket["ticket_id"]})
    assert response.status_code == 202, response.text
    return response.json()


async def test_durable_enqueue_idempotent_worker_and_status(client, job_agency):
    org_id, headers = job_agency
    ticket = await upload(client, headers)
    first = await queue(client, headers, ticket)
    assert first["status"] == "QUEUED" and first["media_id"] is None
    assert await queue(client, headers, ticket) == first
    # Enqueue is independent of any Redis/broker availability.
    async with TestingSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 0
        result = await MediaService.process_queued_upload(db, ticket["ticket_id"])
        assert result["status"] == "FINALIZED"
    async with TestingSessionLocal() as db:
        assert (await MediaService.process_queued_upload(db, ticket["ticket_id"]))["claimed"] is False
        assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 1
    final = await queue(client, headers, ticket)
    assert final["status"] == "FINALIZED" and final["media_id"]
    bad_options = await client.post("/api/v1/agency/media/process", headers=headers, json={
        "ticket_id": ticket["ticket_id"], "expected_sha256": "0" * 64})
    assert bad_options.status_code == 409
    async with TestingSessionLocal() as db:
        other_org = Organization(name="Other", slug="other-jobs")
        db.add(other_org)
        await db.commit()
    other = SessionManager.create_session("another", "agency_admin", "pixl:audience:agency", organization_id=other_org.id)
    assert (await client.get(f'/api/v1/agency/media/uploads/{ticket["ticket_id"]}',
                             headers={"Authorization": f"Bearer {other}"})).status_code == 404


async def test_queued_jobs_keep_quota_and_survive_upload_url_expiry(client, job_agency):
    org_id, headers = job_agency
    content = sample_bytes("image/png")
    ticket = await upload(client, headers, content)
    await queue(client, headers, ticket)
    async with TestingSessionLocal() as db:
        stored = await db.get(UploadTicket, ticket["ticket_id"])
        stored.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        org = await db.get(Organization, org_id)
        org.storage_quota_bytes = len(content)
        await db.commit()
    extra = await client.post("/api/v1/agency/media/upload-ticket", headers=headers, json={
        "filename": "extra.png", "size_bytes": 1, "declared_mime": "image/png"})
    assert extra.status_code == 409
    async with TestingSessionLocal() as db:
        assert (await MediaService.process_queued_upload(db, ticket["ticket_id"]))["status"] == "FINALIZED"


async def test_worker_validation_failure_is_terminal(client, job_agency):
    _, headers = job_agency
    ticket = await upload(client, headers, b"not an image")
    await queue(client, headers, ticket)
    async with TestingSessionLocal() as db:
        assert (await MediaService.process_queued_upload(db, ticket["ticket_id"]))["status"] == "FAILED"
        stored = await db.get(UploadTicket, ticket["ticket_id"])
        assert stored.processing_attempts == 1 and stored.lease_token is None
        assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 0


async def test_worker_retries_transient_errors_and_caps_attempts(client, job_agency):
    _, headers = job_agency
    ticket = await upload(client, headers)
    await queue(client, headers, ticket)
    for attempt in range(1, 4):
        with patch("pixl.modules.media.service.inspect_media", side_effect=OSError("private-path-do-not-leak")):
            async with TestingSessionLocal() as db:
                result = await MediaService.process_queued_upload(db, ticket["ticket_id"])
                assert result["status"] == ("FAILED" if attempt == 3 else "QUEUED")
                stored = await db.get(UploadTicket, ticket["ticket_id"])
                assert stored.processing_attempts == attempt
                assert "private-path" not in stored.processing_error
                if attempt < 3:
                    # A duplicate delivery before backoff elapses cannot claim.
                    assert (await MediaService.process_queued_upload(db, stored.id))["claimed"] is False
                    stored.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                    await db.commit()


@pytest.mark.parametrize("attempts, expected", [(1, "FINALIZED"), (3, "FAILED")])
async def test_expired_worker_lease_recovery(client, job_agency, attempts, expected):
    _, headers = job_agency
    ticket = await upload(client, headers)
    await queue(client, headers, ticket)
    async with TestingSessionLocal() as db:
        stored = await db.get(UploadTicket, ticket["ticket_id"])
        stored.status = "PROCESSING"
        stored.processing_attempts = attempts
        stored.lease_token = "dead-worker"
        stored.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    async with TestingSessionLocal() as db:
        await MediaService.process_queued_upload(db, ticket["ticket_id"])
        assert (await db.get(UploadTicket, ticket["ticket_id"])).status == expected


async def test_active_lease_cannot_be_stolen(client, job_agency):
    _, headers = job_agency
    ticket = await upload(client, headers)
    await queue(client, headers, ticket)
    async with TestingSessionLocal() as db:
        stored = await db.get(UploadTicket, ticket["ticket_id"])
        stored.status = "PROCESSING"
        stored.processing_attempts = 1
        stored.lease_token = "live-worker"
        stored.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        await db.commit()
        assert (await MediaService.process_queued_upload(db, stored.id))["claimed"] is False
        assert stored.lease_token == "live-worker"


async def test_duplicate_worker_delivery_only_creates_one_asset(client, job_agency):
    _, headers = job_agency
    ticket = await upload(client, headers)
    await queue(client, headers, ticket)

    async def run():
        async with TestingSessionLocal() as db:
            return await MediaService.process_queued_upload(db, ticket["ticket_id"])
    results = await asyncio.gather(run(), run())
    assert sum(result.get("status") == "FINALIZED" for result in results) == 1
    async with TestingSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 1


async def test_inline_processing_endpoint_stays_compatible(client, job_agency, monkeypatch):
    _, headers = job_agency
    monkeypatch.setattr(settings, "MEDIA_PROCESSING_MODE", "inline")
    ticket = await upload(client, headers)
    result = await queue(client, headers, ticket)
    assert result["status"] == "FINALIZED" and not result["background"]
    assert (await queue(client, headers, ticket))["media_id"] == result["media_id"]


async def test_suspension_prevents_queued_publication(client, job_agency):
    org_id, headers = job_agency
    ticket = await upload(client, headers)
    await queue(client, headers, ticket)
    async with TestingSessionLocal() as db:
        org = await db.get(Organization, org_id)
        org.status = "SUSPENDED"
        await db.commit()
        assert (await MediaService.process_queued_upload(db, ticket["ticket_id"]))["status"] == "FAILED"
        assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 0


async def test_publication_is_idempotent_and_maintenance_archives_once(client, job_agency):
    org_id, headers = job_agency
    ticket = await upload(client, headers)
    await queue(client, headers, ticket)
    now = datetime.now(timezone.utc)
    async with TestingSessionLocal() as db:
        result = await MediaService.process_queued_upload(db, ticket["ticket_id"])
        screen = Screen(name="TV", organization_id=org_id)
        playlist = Playlist(name="Playlist", organization_id=org_id)
        db.add_all([screen, playlist])
        await db.flush()
        db.add(PlaylistItem(playlist_id=playlist.id, media_id=result["media_id"], sort_order=0,
                            duration_mode="IMAGE_DEFAULT", configured_duration_ms=10000))
        campaign = Campaign(name="Campaign", organization_id=org_id, playlist_id=playlist.id,
                            start_time=now - timedelta(hours=1), end_time=now + timedelta(hours=1))
        db.add(campaign)
        await db.flush()
        db.add(ScreenAssignment(campaign_id=campaign.id, screen_id=screen.id))
        await db.commit()
        await CampaignService.publish_campaign(db, org_id, campaign.id)
        await db.refresh(screen)
        version = screen.current_manifest_version
        await CampaignService.publish_campaign(db, org_id, campaign.id)
        await db.refresh(screen)
        assert screen.current_manifest_version == version
        campaign.end_time = now - timedelta(seconds=1)
        await db.commit()
        assert (await maintain_lifecycle(db))["archived_campaigns"] == 1
        assert (await maintain_lifecycle(db))["archived_campaigns"] == 0
        await db.refresh(screen)
        assert screen.current_manifest_version == version + 1


async def test_cleanup_preserves_library_and_queued_bytes(client, job_agency):
    _, headers = job_agency
    first = await upload(client, headers)
    second = await upload(client, headers)
    await queue(client, headers, second)
    source = storage_path(first["storage_key"])
    async with TestingSessionLocal() as db:
        stored = await db.get(UploadTicket, first["ticket_id"])
        stored.expires_at = datetime.now(timezone.utc) - timedelta(days=2)
        stored.updated_at = stored.expires_at
        challenge = EnrollmentChallenge(pin="ABCDEF", hw_fingerprint="expired", status="CLAIMED",
                                         expires_at=stored.expires_at)
        db.add(challenge)
        await db.commit()
        result = await maintain_lifecycle(db)
        assert result["expired_uploads"] == 1 and result["expired_challenges"] == 1
        # Status transition starts the grace period; reconciliation is delayed.
        stored.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await db.commit()
        await maintain_lifecycle(db)
        assert not source.exists()
        assert storage_path(second["storage_key"]).exists()


async def test_screen_limits_and_configured_offline_threshold(job_agency, monkeypatch):
    org_id, _ = job_agency
    monkeypatch.setattr(settings, "DEVICE_OFFLINE_THRESHOLD_SECONDS", 10)
    async with TestingSessionLocal() as db:
        org = await db.get(Organization, org_id)
        org.max_screens = 1
        await db.commit()
        screen = await ScreenService.master_provision_screen(db, "First", org_id)
        with pytest.raises(ConflictError, match="limit"):
            await ScreenService.master_provision_screen(db, "Second", org_id)
        screen.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        await db.commit()
        assert not (await ScreenService.get_current_playback(db, screen.id, org_id))["is_online"]


async def test_master_totp_is_consumed_once(client, master_admin_user):
    user, secret = master_admin_user
    payload = {"email": user.email, "password": "MasterPassword123!", "totp_code": pyotp.TOTP(secret).now()}
    first = await client.post("/api/v1/auth/master/login", json=payload)
    assert first.status_code == 200
    duplicate = await client.post("/api/v1/auth/master/login", json=payload)
    assert duplicate.status_code == 401 and "already used" in duplicate.text


def test_no_static_debug_mfa_bypass(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)
    secret = pyotp.random_base32()
    with patch("pixl.core.security.time.time", return_value=1700000000):
        assert verify_totp_code(secret, pyotp.TOTP(secret).at(1700000000))
        assert matching_totp_counter(secret, "１２３４５６") is None
        # Pick a static code that isn't a real code for this exact time window.
        with patch("pyotp.TOTP.generate_otp", return_value="123456"):
            assert not verify_totp_code(secret, "999999")


@pytest.mark.parametrize("override, message", [
    ({"DEBUG": True}, "DEBUG"), ({"SESSION_BACKEND": "memory"}, "redis"),
    ({"ALLOW_LEGACY_TV": True}, "LEGACY"), ({"SECRET_KEY": "short"}, "SECRET_KEY"),
    ({"MEDIA_PUBLIC_BASE_URL": ""}, "MEDIA_PUBLIC"),
    ({"AGENCY_ORIGIN": "https://user:password@example.com"}, "AGENCY_ORIGIN"),
    ({"DATABASE_URL": "sqlite+aiosqlite:///production.db"}, "PostgreSQL"),
])
def test_production_configuration_fails_closed(override, message):
    config = Settings(_env_file=None, ENVIRONMENT="production", DEBUG=False, SESSION_BACKEND="redis",
                      SECRET_KEY="random-looking-for-validation-only" * 2,
                      DATABASE_URL="postgresql+asyncpg://user:password@postgres/db", MEDIA_PROCESSING_MODE="worker",
                      MASTER_ORIGIN="https://master.example.com", AGENCY_ORIGIN="https://agency.example.com",
                      ADVERTISER_ORIGIN="https://advertiser.example.com", MEDIA_PUBLIC_BASE_URL="https://api.example.com")
    for key, value in override.items():
        setattr(config, key, value)
    with pytest.raises(RuntimeError, match=message):
        config.validate_production()


async def test_failed_upload_reservation_released_only_after_cleanup(client, job_agency):
    org_id, headers = job_agency
    ticket = await upload(client, headers, b"not an image")
    await queue(client, headers, ticket)
    async with TestingSessionLocal() as db:
        await MediaService.process_queued_upload(db, ticket["ticket_id"])
        org = await db.get(Organization, org_id)
        org.storage_quota_bytes = len(b"not an image")
        stored = await db.get(UploadTicket, ticket["ticket_id"])
        await db.commit()
        with pytest.raises(ConflictError, match="quota"):
            await MediaService.create_upload_ticket(db, org_id, "next.png", 1, "image/png")
        stored.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await db.commit()
        await maintain_lifecycle(db)
        assert stored.quarantine_cleaned_at is not None
        assert not storage_path(ticket["storage_key"]).exists()
        assert (await MediaService.create_upload_ticket(db, org_id, "next.png", 1, "image/png")).id


async def test_worker_mode_rejects_synchronous_api_bypass(client, job_agency):
    _, headers = job_agency
    ticket = await upload(client, headers)
    response = await client.post("/api/v1/agency/media/finalize", headers=headers, json={"ticket_id": ticket["ticket_id"]})
    assert response.status_code == 409 and "/process" in response.text


async def test_invitation_cannot_move_existing_user_to_another_tenant(client):
    async with TestingSessionLocal() as db:
        first, second = Organization(name="One", slug="one"), Organization(name="Two", slug="two")
        db.add_all([first, second])
        await db.flush()
        user = User(email="existing@example.com", organization_id=first.id, role="agency_admin",
                    status="ACTIVE", hashed_password="untouched")
        invitation = UserInvitation(email=user.email, organization_id=second.id, role="agency_admin",
                                    token="cross-tenant-invitation", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        db.add_all([user, invitation])
        await db.commit()
        user_id, first_id = user.id, first.id
    response = await client.post("/api/v1/auth/invitation/accept", json={
        "invitation_token": "cross-tenant-invitation", "password": "NewSecurePassword123!"})
    assert response.status_code == 409
    async with TestingSessionLocal() as db:
        assert (await db.get(User, user_id)).organization_id == first_id


async def test_invitation_audit_records_generated_user_id(client):
    async with TestingSessionLocal() as db:
        org = Organization(name="Audit", slug="audit")
        db.add(org)
        await db.flush()
        db.add(UserInvitation(email="invited@example.com", organization_id=org.id, role="agency_admin",
                              token="audit-invitation", expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        await db.commit()
    response = await client.post("/api/v1/auth/invitation/accept", json={
        "invitation_token": "audit-invitation", "password": "NewSecurePassword123!"})
    assert response.status_code == 200
    async with TestingSessionLocal() as db:
        event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "INVITATION_ACCEPTED"))
        assert event.user_id == response.json()["id"] == event.resource_id


async def test_validation_does_not_echo_credentials(client):
    response = await client.post("/api/v1/auth/agency/login", json={
        "email": "valid@example.com", "password": "pA5!q"})
    assert response.status_code == 422
    assert "pA5!q" not in response.text and "input" not in response.json()["detail"][0]


async def test_non_ascii_media_signatures_fail_closed(client):
    import time
    from pixl.core.storage import valid_media_signature
    assert not valid_media_signature("published/x.png", int(time.time()) + 30, "é" * 64)


async def test_api_security_headers(client):
    response = await client.get("/api/v1/health/live")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert len(response.headers["x-request-id"]) == 32


@pytest.mark.skipif(not os.environ.get("PIXL_TEST_REDIS_URL"), reason="Requires a dedicated real Redis test broker")
async def test_real_worker_and_beat_process_queued_media(client, job_agency, tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    from tests.conftest import TEST_DATABASE_URL
    from urllib.parse import urlsplit
    import redis

    broker = os.environ["PIXL_TEST_REDIS_URL"]
    # This integration check must never consume a normal application's broker.
    assert int(urlsplit(broker).path.strip("/") or "0") >= 10
    with redis.from_url(broker, socket_connect_timeout=2, socket_timeout=2) as connection:
        assert connection.ping()
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL, "LOCAL_STORAGE_PATH": settings.LOCAL_STORAGE_PATH,
           "CELERY_BROKER_URL": broker, "CELERY_RESULT_BACKEND": broker, "ENVIRONMENT": "development",
           "DEBUG": "false", "SESSION_BACKEND": "memory", "MEDIA_PROCESSING_MODE": "worker",
           "SECRET_KEY": settings.SECRET_KEY}
    root = Path(__file__).resolve().parents[1]
    processes = []
    with (tmp_path / "worker.log").open("w") as log:
        try:
            prefix = [sys.executable, "-m", "celery", "-A", "pixl.workers.celery_app:celery_app"]
            for arguments in (["worker", "--pool=solo", "--concurrency=1", "--loglevel=WARNING"],
                              ["beat", "--schedule=" + str(tmp_path / "beat"), "--loglevel=WARNING"]):
                processes.append(subprocess.Popen(prefix + arguments, cwd=root, env=env, stdout=log, stderr=log))
            _, headers = job_agency
            ticket = await upload(client, headers)
            await queue(client, headers, ticket)
            for _ in range(45):
                assert all(process.poll() is None for process in processes), "Worker or scheduler exited"
                response = await client.get(f'/api/v1/agency/media/uploads/{ticket["ticket_id"]}', headers=headers)
                status = response.json()
                if status["status"] == "FINALIZED":
                    assert status["attempts"] == 1 and status["media_id"]
                    break
                assert status["status"] != "FAILED", status
                await asyncio.sleep(1)
            else:
                pytest.fail("Real worker/Beat did not finish the durable job within 45 seconds")
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    await asyncio.to_thread(process.wait, timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


@pytest.mark.parametrize("failure", [OSError("private-connection-details"), TimeoutError("private-timeout")])
async def test_raw_connection_errors_return_safe_unavailable(client, master_auth_headers, failure):
    from unittest.mock import AsyncMock
    from pixl.main import app
    from pixl.core.database import get_db_session
    original = app.dependency_overrides[get_db_session]
    db = AsyncMock()
    db.execute.side_effect = failure
    db.get.side_effect = failure
    db.rollback.side_effect = OSError("rollback-disconnected")

    async def broken_connection():
        yield db

    app.dependency_overrides[get_db_session] = broken_connection
    try:
        ready = await client.get("/api/v1/health/ready")
        assert ready.status_code == 503 and ready.json()["database"] == "UNAVAILABLE"
        response = await client.get("/api/v1/master/screens", headers=master_auth_headers)
        assert response.status_code == 503 and response.headers["retry-after"] == "5"
        assert "private-" not in response.text
        assert (await client.get("/api/v1/health/live")).status_code == 200
    finally:
        app.dependency_overrides[get_db_session] = original


@pytest.mark.parametrize("environment, enabled, expected", [("production", True, 404), ("development", False, 404), ("development", True, 200)])
async def test_simulator_and_alias_respect_legacy_gate(client, monkeypatch, environment, enabled, expected):
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(settings, "ALLOW_LEGACY_TV", enabled)
    assert (await client.get("/simulator")).status_code == expected
    assert (await client.get("/player")).status_code == (307 if expected == 200 else 404)


def test_celery_registers_real_periodic_tasks():
    from pixl.workers.celery_app import celery_app
    import pixl.workers.tasks  # noqa: F401
    for entry in celery_app.conf.beat_schedule.values():
        assert entry["task"] in celery_app.tasks
    assert "tasks.compile_scheduled_manifests" not in celery_app.tasks
