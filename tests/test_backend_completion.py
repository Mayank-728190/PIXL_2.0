import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import fakeredis
import pytest
import redis
from sqlalchemy import func, select

from pixl.core import session_store
from pixl.core.config import settings
from pixl.core.exceptions import ConflictError, PixlException
from pixl.core.identifiers import next_number
from pixl.core.rate_limit import check_rate
from pixl.core.security import hash_device_token
from pixl.core.session import SessionManager
from pixl.modules.campaigns.models import Campaign, ScreenAssignment
from pixl.modules.ingestion.models import PlaybackEvent
from pixl.modules.media.models import MediaAsset, UploadTicket
from pixl.modules.organizations.models import Organization, Site
from pixl.modules.playlists.models import Playlist, PlaylistItem
from pixl.modules.screens.models import DeviceCredential, DeviceCursor, Screen
from pixl.modules.screens.service import ScreenService
from tests.conftest import TestingSessionLocal
from tests.media_helpers import sample_bytes, uploaded_ticket


@pytest.fixture
async def agency():
    async with TestingSessionLocal() as db:
        org = Organization(name="Backend tests", slug="backend-tests")
        db.add(org)
        await db.commit()
        token = SessionManager.create_session("test-operator", "agency_admin", "pixl:audience:agency",
                                              organization_id=org.id)
        return org.id, {"Authorization": f"Bearer {token}"}


async def ticket(client, headers, content, mime="image/png"):
    response = await client.post("/api/v1/agency/media/upload-ticket", headers=headers, json={
        "filename": "test.png", "size_bytes": len(content), "declared_mime": mime,
    })
    assert response.status_code == 200, response.text
    return response.json()


async def test_real_image_upload_checksum_and_thumbnail(client, agency):
    _, headers = agency
    content = sample_bytes("image/png")
    data = await ticket(client, headers, content)
    assert (await client.get(f'/media/{data["storage_key"]}')).status_code == 404
    assert (await client.put(data["presigned_upload_url"], content=content)).status_code == 200
    response = await client.post("/api/v1/agency/media/finalize", headers=headers, json={
        "ticket_id": data["ticket_id"], "expected_sha256": hashlib.sha256(content).hexdigest(),
    })
    assert response.status_code == 200, response.text
    asset = response.json()
    assert (asset["width"], asset["height"], asset["duration_ms"]) == (64, 32, 0)
    assert asset["sha256"] == hashlib.sha256(content).hexdigest()
    from pixl.core.storage import public_media_url
    assert (await client.get(f'/media/{asset["storage_key"]}')).status_code == 404
    download = await client.get(public_media_url(asset["storage_key"]))
    assert download.content == content
    thumb = await client.get(asset["thumbnail_url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    assert (await client.put(data["presigned_upload_url"], content=content)).status_code == 409


def test_media_signatures_reject_tampering_and_expiry():
    import time
    from pixl.core.storage import media_signature, valid_media_signature
    expires = int(time.time()) + 3600
    signature = media_signature("published/a.png", expires)
    assert valid_media_signature("published/a.png", expires, signature)
    assert not valid_media_signature("published/b.png", expires, signature)
    assert not valid_media_signature("published/a.png", expires + 1, signature)
    expired = int(time.time()) - 1
    assert not valid_media_signature("published/a.png", expired, media_signature("published/a.png", expired))


async def test_upload_requires_bytes_before_finalize(client, agency):
    _, headers = agency
    data = await ticket(client, headers, b"bytes")
    response = await client.post("/api/v1/agency/media/finalize", headers=headers,
                                 json={"ticket_id": data["ticket_id"]})
    assert response.status_code == 409


@pytest.mark.parametrize("content", [b"x", b"longer than declared"])
async def test_upload_size_mismatch_can_be_retried(client, agency, content):
    _, headers = agency
    data = await ticket(client, headers, b"12345")
    assert (await client.put(data["presigned_upload_url"], content=content)).status_code == 422
    assert (await client.put(data["presigned_upload_url"], content=b"12345")).status_code == 200


async def test_forged_or_expired_upload_url_is_rejected(client, agency):
    _, headers = agency
    data = await ticket(client, headers, b"bytes")
    forged = data["presigned_upload_url"].split("?")[0] + "?signature=" + "0" * 64
    assert (await client.put(forged, content=b"bytes")).status_code == 403
    async with TestingSessionLocal() as db:
        stored = await db.get(UploadTicket, data["ticket_id"])
        stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    assert (await client.put(data["presigned_upload_url"], content=b"bytes")).status_code == 409


async def test_invalid_media_content_is_not_published(client, agency):
    _, headers = agency
    data = await ticket(client, headers, b"not an image")
    await client.put(data["presigned_upload_url"], content=b"not an image")
    response = await client.post("/api/v1/agency/media/finalize", headers=headers,
                                 json={"ticket_id": data["ticket_id"]})
    assert response.status_code == 422
    async with TestingSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 0


async def test_checksum_mismatch_does_not_publish(client, agency):
    _, headers = agency
    content = sample_bytes("image/png")
    data = await ticket(client, headers, content)
    await client.put(data["presigned_upload_url"], content=content)
    bad = await client.post("/api/v1/agency/media/finalize", headers=headers,
                           json={"ticket_id": data["ticket_id"], "expected_sha256": "0" * 64})
    assert bad.status_code == 422
    retry = await client.post("/api/v1/agency/media/finalize", headers=headers,
                             json={"ticket_id": data["ticket_id"]})
    assert retry.status_code == 200


async def test_upload_reserves_quota(client, agency):
    org_id, headers = agency
    async with TestingSessionLocal() as db:
        org = await db.get(Organization, org_id)
        org.storage_quota_bytes = 5
        await db.commit()
    await ticket(client, headers, b"12345")
    response = await client.post("/api/v1/agency/media/upload-ticket", headers=headers, json={
        "filename": "extra.png", "size_bytes": 1, "declared_mime": "image/png",
    })
    assert response.status_code == 409


async def test_unsupported_storage_provider_fails_explicitly(client, agency, monkeypatch):
    _, headers = agency
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "r2")
    response = await client.post("/api/v1/agency/media/upload-ticket", headers=headers, json={
        "filename": "image.png", "size_bytes": 1, "declared_mime": "image/png",
    })
    assert response.status_code == 409


@pytest.fixture
async def device(agency):
    org_id, headers = agency
    async with TestingSessionLocal() as db:
        screen = Screen(name="Authenticated screen", organization_id=org_id, status="READY", screen_number=1001)
        db.add(screen)
        await db.flush()
        token = "dev_tok_test_random_credential"
        db.add(DeviceCredential(screen_id=screen.id, key_id="test-key", public_key_pem="test",
                                token_hash=hash_device_token(token)))
        db.add(DeviceCursor(screen_id=screen.id, epoch=1, last_committed_sequence=0))
        await db.commit()
        return screen.id, {"X-Device-Token": token}, headers


async def test_hashed_device_tokens_and_manifest_etag(client, device):
    screen_id, headers, _ = device
    async with TestingSessionLocal() as db:
        credential = await db.get(DeviceCredential, screen_id)
        assert credential.token_hash.startswith("sha256:")
        assert headers["X-Device-Token"] not in credential.token_hash
    first = await client.get("/api/v1/device/manifest", headers=headers)
    assert first.status_code == 200
    second = await client.get("/api/v1/device/manifest", headers={**headers, "If-None-Match": first.headers["etag"]})
    assert second.status_code == 304 and not second.content
    invalid = await client.get("/api/v1/device/manifest", headers={"X-Device-Token": "wrong"})
    assert invalid.status_code == 401


async def test_receipts_reject_invented_epoch(client, device):
    screen_id, headers, _ = device
    response = await client.post("/api/v1/device/playback/batch", headers=headers, json={
        "device_id": screen_id, "epoch": 2, "batch": [{"local_sequence": 1,
        "media_id": "media", "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": 1000, "outcome": "COMPLETED"}],
    })
    assert response.status_code == 409


async def test_reassignment_revokes_device_and_requires_correct_site(client, device, master_auth_headers):
    screen_id, headers, _ = device
    async with TestingSessionLocal() as db:
        org = Organization(name="Next agency", slug="next-agency")
        other = Organization(name="Other", slug="other")
        db.add_all([org, other])
        await db.flush()
        site = Site(name="Wrong site", organization_id=other.id)
        db.add(site)
        await db.commit()
        org_id, site_id = org.id, site.id
    bad = await client.post(f"/api/v1/master/screens/{screen_id}/assign", headers=master_auth_headers,
                            json={"organization_id": org_id, "site_id": site_id})
    assert bad.status_code == 403
    assigned = await client.post(f"/api/v1/master/screens/{screen_id}/assign", headers=master_auth_headers,
                                 json={"organization_id": org_id})
    assert assigned.status_code == 200
    assert (await client.get("/api/v1/device/manifest", headers=headers)).status_code == 401


async def test_suspension_blocks_existing_agency_and_device_sessions(client, device, agency):
    _, device_headers, agency_headers = device
    org_id, _ = agency
    async with TestingSessionLocal() as db:
        org = await db.get(Organization, org_id)
        org.status = "SUSPENDED"
        await db.commit()
    assert (await client.get("/api/v1/agency/screens", headers=agency_headers)).status_code == 403
    assert (await client.get("/api/v1/device/manifest", headers=device_headers)).status_code == 403


async def test_legacy_tv_is_disabled_by_default_and_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_LEGACY_TV", False)
    assert (await client.post("/api/tv/register", json={})).status_code == 410
    monkeypatch.setattr(settings, "ALLOW_LEGACY_TV", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert (await client.post("/api/tv/register", json={})).status_code == 410


async def test_legacy_receipts_require_pairing_credentials(client):
    response = await client.post("/api/tv/1001/proof-of-play?pairingCode=ABCDEF", json=[{}])
    assert response.status_code == 401


async def test_numeric_id_allocation_recovers_after_imported_ids():
    async with TestingSessionLocal() as db:
        assert await next_number(db, Screen, "screen_number", 1000) == 1001
        db.add(Screen(name="Imported", screen_number=9000))
        await db.commit()
        assert await next_number(db, Screen, "screen_number", 1000) == 9001


async def test_numeric_id_allocation_is_concurrent_safe():
    async def allocate():
        async with TestingSessionLocal() as db:
            number = await next_number(db, Screen, "screen_number", 1000)
            db.add(Screen(name="Concurrent", screen_number=number))
            await db.commit()
            return number
    numbers = await asyncio.gather(*(allocate() for _ in range(8)))
    assert sorted(numbers) == list(range(1001, 1009))


@pytest.fixture
async def shared_sessions(monkeypatch):
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    monkeypatch.setattr(settings, "SESSION_BACKEND", "redis")
    monkeypatch.setattr(session_store, "cache", lambda: client)
    return server, client


async def test_redis_sessions_are_shared_revocable_and_do_not_store_tokens(shared_sessions, monkeypatch):
    server, client = shared_sessions
    one = SessionManager.create_session("user", "agency_admin", "pixl:audience:agency")
    two = SessionManager.create_session("user", "agency_admin", "pixl:audience:agency")
    assert one not in client.get(session_store.session_key(one))
    assert client.ttl(session_store.session_key(one)) > 0
    second_process = fakeredis.FakeRedis(server=server, decode_responses=True)
    monkeypatch.setattr(session_store, "cache", lambda: second_process)
    assert SessionManager.get_session(one)["user_id"] == "user"
    assert SessionManager.revoke_all_user_sessions("user") == 2
    assert SessionManager.get_session(one) is None
    assert SessionManager.get_session(two) is None


async def test_redis_single_session_revocation(shared_sessions):
    token = SessionManager.create_session("user", "agency_admin", "pixl:audience:agency")
    assert SessionManager.revoke_session(token)
    assert SessionManager.get_session(token) is None


async def test_redis_outage_fails_closed(shared_sessions):
    server, _ = shared_sessions
    server.connected = False
    with pytest.raises(PixlException) as exc:
        SessionManager.get_session("token")
    assert exc.value.status_code == 503


async def test_rate_limiter_uses_shared_atomic_counter(shared_sessions):
    for _ in range(3):
        check_rate("test", 3, 60)
    with pytest.raises(PixlException) as exc:
        check_rate("test", 3, 60)
    assert exc.value.status_code == 429


async def test_cookie_authenticated_write_rejects_foreign_origin(client, agency):
    _, headers = agency
    token = headers["Authorization"].removeprefix("Bearer ")
    response = await client.post("/api/v1/agency/screens/claim", headers={
        "Cookie": f"PIXL-Agency-Session={token}", "Origin": "https://attacker.invalid",
    }, json={"pin": "ABCDEF"})
    assert response.status_code == 403
