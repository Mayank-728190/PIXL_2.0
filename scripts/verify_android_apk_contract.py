import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

# Ensure database URL is set for contract test environment before importing pixl
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///contract_test.db"

import httpx
import pyotp

import pixl.modules.organizations.models  # noqa
import pixl.modules.screens.models  # noqa
import pixl.modules.media.models  # noqa
import pixl.modules.playlists.models  # noqa
import pixl.modules.campaigns.models  # noqa
import pixl.modules.ingestion.models  # noqa

from pixl.core.database import AsyncSessionFactory
from pixl.core.security import hash_password
from pixl.modules.auth.models import User

SERVER_PORT = 8765
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"
ANDROID_PROJECT_DIR = r"C:\Users\user\Downloads\PIXL\app_Development\pixl-player-android"
FIXTURES_DIR = os.path.abspath(r"C:\Users\user\Downloads\PIXL2.0\fixtures")


def log(msg: str):
    print(f"[ContractVerifier] {msg}", flush=True)


async def wait_for_server():
    log("Waiting for backend to become healthy...")
    async with httpx.AsyncClient(timeout=2.0) as client:
        for _ in range(30):
            try:
                res = await client.get(f"{SERVER_URL}/health")
                if res.status_code == 200:
                    log("Backend is online and healthy.")
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError("Backend server failed to start within 15 seconds")


async def seed_data_for_contract_test():
    log("Seeding test data for Android contract test...")

    # 1. Seed master admin in database
    totp_secret = "JBSWY3DPEHPK3PXP"
    master_email = "master@pixl.io"
    master_pass = "MasterPassword123!"

    async with AsyncSessionFactory() as session:
        user = User(
            email=master_email,
            hashed_password=hash_password(master_pass),
            role="master_admin",
            status="ACTIVE",
            totp_secret=totp_secret,
            is_mfa_enabled=True,
        )
        session.add(user)
        await session.commit()
        log("Master administrator created in database.")

    async with httpx.AsyncClient(base_url=SERVER_URL, timeout=10.0) as client:
        # 2. Master login
        totp = pyotp.TOTP(totp_secret)
        master_login_res = await client.post("/api/v1/auth/master/login", json={
            "email": master_email,
            "password": master_pass,
            "totp_code": totp.now()
        })
        assert master_login_res.status_code == 200, master_login_res.text
        master_token = master_login_res.json()["session_token"]
        master_headers = {
            "Authorization": f"Bearer {master_token}",
            "Cookie": f"__Host-PIXL-Master-Session={master_token}"
        }

        # 3. Master creates agency
        agency_res = await client.post("/api/v1/master/agencies", headers=master_headers, json={
            "name": "Live Android Testing Agency",
            "slug": "android-agency",
            "admin_email": "admin@androidagency.com",
            "max_screens": 100
        })
        assert agency_res.status_code == 200, agency_res.text
        invitation_token = agency_res.json()["invitation_token"]

        # 4. Accept invitation
        agency_pass = "AgencySecret123!"
        accept_res = await client.post("/api/v1/auth/invitation/accept", json={
            "invitation_token": invitation_token,
            "password": agency_pass
        })
        assert accept_res.status_code == 200, accept_res.text

        # 5. Agency Admin logs in
        agency_login_res = await client.post("/api/v1/auth/agency/login", json={
            "email": "admin@androidagency.com",
            "password": agency_pass
        })
        assert agency_login_res.status_code == 200, agency_login_res.text
        agency_token = agency_login_res.json()["session_token"]
        agency_headers = {
            "Authorization": f"Bearer {agency_token}",
            "Cookie": f"__Host-PIXL-Agency-Session={agency_token}"
        }

        # 6. Screen registers itself via TV API
        tv_reg_res = await client.post("/api/tv/register", json={
            "name": "Conference Screen 1",
            "location": "Boardroom A"
        })
        assert tv_reg_res.status_code == 200, tv_reg_res.text
        screen_data = tv_reg_res.json()
        screen_id = screen_data["screenId"]
        pairing_code = screen_data["pairingCode"]
        log(f"Registered screen via /api/tv/register: screenId={screen_id}, code={pairing_code}")

        # 7. Agency claims screen
        claim_res = await client.post("/api/v1/agency/screens/claim", headers=agency_headers, json={
            "pin": pairing_code,
            "name": "Main Boardroom Screen"
        })
        assert claim_res.status_code == 200, claim_res.text
        screen_uuid = claim_res.json()["screen_id"]
        log(f"Screen claimed by agency: UUID={screen_uuid}")

        # 8. Upload 2 media files: image (7s) & video (13s)
        ticket_img = (await client.post(
            "/api/v1/agency/media/upload-ticket",
            headers=agency_headers,
            json={"filename": "poster.png", "size_bytes": 500000, "declared_mime": "image/png"}
        )).json()
        media_img = (await client.post(
            "/api/v1/agency/media/finalize",
            headers=agency_headers,
            json={"ticket_id": ticket_img["ticket_id"]}
        )).json()

        ticket_vid = (await client.post(
            "/api/v1/agency/media/upload-ticket",
            headers=agency_headers,
            json={"filename": "welcome_promo.mp4", "size_bytes": 10000000, "declared_mime": "video/mp4"}
        )).json()
        media_vid = (await client.post(
            "/api/v1/agency/media/finalize",
            headers=agency_headers,
            json={"ticket_id": ticket_vid["ticket_id"]}
        )).json()

        # 9. Create Playlist
        playlist = (await client.post(
            "/api/v1/agency/playlists",
            headers=agency_headers,
            json={
                "name": "TV Play Loop",
                "items": [
                    {
                        "media_id": media_img["id"],
                        "sort_order": 0,
                        "duration_mode": "IMAGE_DEFAULT",
                        "configured_duration_ms": 7000
                    },
                    {
                        "media_id": media_vid["id"],
                        "sort_order": 1,
                        "duration_mode": "FULL_CLIP",
                        "configured_duration_ms": 13000
                    }
                ]
            }
        )).json()

        # 10. Create and Publish Campaign
        now = datetime.now(timezone.utc)
        camp = (await client.post(
            "/api/v1/agency/campaigns",
            headers=agency_headers,
            json={
                "name": "Live TV Campaign",
                "playlist_id": playlist["id"],
                "priority": 100,
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(days=7)).isoformat(),
                "screen_ids": [screen_uuid]
            }
        )).json()

        pub_res = await client.post(f"/api/v1/agency/campaigns/{camp['id']}/publish", headers=agency_headers)
        assert pub_res.status_code == 200, pub_res.text

        # 11. Verify /api/tv/sync
        sync_res = await client.get(f"/api/tv/sync?screenId={screen_id}&pairingCode={pairing_code}")
        assert sync_res.status_code == 200, sync_res.text
        sync_data = sync_res.json()
        assert sync_data["isPaired"] is True
        assert sync_data["campaign"] is not None
        items = sync_data["campaign"]["playlist"]["mediaItems"]
        assert [m["type"] for m in items] == ["image", "video"]
        assert [m["durationSeconds"] for m in items] == [7, 13]
        log(f"Sync verified successfully for screen {screen_id}: {items}")

        return screen_id, pairing_code


def run_gradle_contract_tests(screen_id: int, pairing_code: str):
    log("Running Android Gradle Contract Tests...")
    env = os.environ.copy()
    env["PIXL_PLAYER_TEST_BASE_URL"] = SERVER_URL
    env["PIXL_PLAYER_TEST_SCREEN_ID"] = str(screen_id)
    env["PIXL_PLAYER_TEST_PIN"] = str(pairing_code)
    env["PIXL_PLAYER_FIXTURES_DIR"] = FIXTURES_DIR

    cmd = [
        r".\gradlew.bat",
        "testDebugUnitTest",
        "--tests",
        "com.pixl.player.BackendContractTest"
    ]
    log(f"Executing: {' '.join(cmd)} in {ANDROID_PROJECT_DIR}")
    result = subprocess.run(cmd, cwd=ANDROID_PROJECT_DIR, env=env, capture_output=True, text=True, shell=True)

    print("--- GRADLE STDOUT ---")
    print(result.stdout)
    if result.stderr:
        print("--- GRADLE STDERR ---")
        print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(f"Gradle contract test failed with exit code {result.returncode}")
    log("SUCCESS: All Gradle contract tests passed against the live PIXL backend!")


async def main():
    server_process = None
    if os.path.exists("contract_test.db"):
        try:
            os.remove("contract_test.db")
        except Exception:
            pass
    try:
        log("Launching FastAPI server via uvicorn...")
        env = os.environ.copy()
        env["DATABASE_URL"] = "sqlite+aiosqlite:///contract_test.db"
        server_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "pixl.main:app", "--host", "127.0.0.1", "--port", str(SERVER_PORT)],
            env=env
        )

        await wait_for_server()
        screen_id, pairing_code = await seed_data_for_contract_test()
        run_gradle_contract_tests(screen_id, pairing_code)
        log("All contract tests and compatibility validations completed successfully!")
    finally:
        if server_process:
            log("Terminating uvicorn server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
        if os.path.exists("contract_test.db"):
            try:
                os.remove("contract_test.db")
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
