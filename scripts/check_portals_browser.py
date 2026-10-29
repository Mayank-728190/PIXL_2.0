"""Real-browser portal smoke check against an isolated temporary server/database.

Run: python -m scripts.check_portals_browser
Requires pip install -e '.[browser]' and installed Chrome or Edge.
Never connects to the existing development database or changes .env.
"""
import asyncio
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile

import httpx
import pyotp
from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


async def run_check(base_url, password, totp_secret, temporary, *, verify_tls=True):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ.get("PIXL_BROWSER_CHANNEL", "chrome") or None, headless=True)
        try:
            context = await browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=not verify_tls)
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(base_url + "/master")
            await page.locator('#login-form [name="email"]').fill("master@example.com")
            await page.locator('#login-form [name="password"]').fill(password)
            await page.locator('#login-form [name="totp_code"]').fill(pyotp.TOTP(totp_secret).now())
            await page.locator('#login-form button').click()
            await expect(page.locator("#workspace")).to_be_visible()
            await expect(page.locator("#metrics .metric")).to_have_count(4)
            await expect(page.locator("#pulse-chart")).to_have_attribute("aria-label", "Online screens over 1 observations this session. Latest: 0 of 0.")
            await page.locator('#provision-agency [name="name"]').fill("Browser agency")
            await page.locator('#provision-agency [name="slug"]').fill("browser-agency")
            await page.locator('#provision-agency [name="admin_email"]').fill("agency@example.com")
            await page.locator('#provision-agency button').click()
            await expect(page.locator("#invite-result")).to_be_visible()
            invitation = await page.locator("#invitation-link").input_value()
            await expect(page.locator("#screen-agency option")).to_have_count(2)
            await page.locator('#provision-screen [name="name"]').fill("Browser screen")
            await page.locator("#screen-agency").select_option(label="Browser agency")
            await page.locator('#provision-screen button').click()
            await expect(page.locator("#screens")).to_contain_text("Browser screen")

            agency_context = await browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=not verify_tls)
            agency_page = await agency_context.new_page()
            agency_page.on("pageerror", lambda error: errors.append(str(error)))
            await agency_page.goto(invitation)
            await expect(agency_page.locator("#invitation")).to_be_visible()
            await agency_page.locator('#invitation-form [name="password"]').fill(password)
            await agency_page.locator('#invitation-form button').click()
            await expect(agency_page.locator("#notice")).to_contain_text("Account activated")
            await agency_page.goto(base_url + "/agency")
            await agency_page.locator('#login-form [name="email"]').fill("agency@example.com")
            await agency_page.locator('#login-form [name="password"]').fill(password)
            await agency_page.locator('#login-form button').click()
            await expect(agency_page.locator("#workspace")).to_be_visible()
            await expect(agency_page.locator("#screens")).to_contain_text("Browser screen")
            async with httpx.AsyncClient(base_url=base_url, verify=verify_tls) as client:
                challenge = (await client.post("/api/v1/device/enroll/challenge", json={"hardware_fingerprint": "browser-test-hardware"})).json()
                await agency_page.locator("#claim-target").select_option(label="Browser screen")
                await agency_page.locator('#claim-screen [name="pin"]').fill(challenge["pin"])
                await agency_page.locator('#claim-screen button').click()
                await expect(agency_page.locator("#notice")).to_contain_text("paired successfully")

            from PIL import Image
            image = Path(temporary) / "poster.png"
            Image.new("RGB", (64, 32), "green").save(image)
            second_image = Path(temporary) / "landscape.png"
            Image.new("RGB", (128, 64), "orange").save(second_image)
            await agency_page.locator("#files").set_input_files([image, second_image])
            await expect(agency_page.locator("#upload-progress")).to_contain_text("poster.png: ready", timeout=30000)
            await expect(agency_page.locator("#media-rows")).to_contain_text("poster.png")
            await expect(agency_page.locator("#upload-progress")).to_contain_text("landscape.png: ready", timeout=30000)
            await expect(agency_page.locator("#media-rows tr")).to_have_count(2)
            # The action dialog must fit the viewport, even at a narrow screen size.
            await agency_page.set_viewport_size({"width": 390, "height": 640})
            await agency_page.locator('#media-rows button[aria-haspopup="dialog"]').first.click()
            await expect(agency_page.locator("#media-actions")).to_be_visible()
            box = await agency_page.locator("#media-actions").bounding_box()
            assert box and box["x"] >= 0 and box["y"] >= 0 and box["y"] + box["height"] <= 640
            await agency_page.get_by_role("button", name="Use in a new campaign").click()
            await expect(agency_page.locator("#media-actions")).not_to_be_visible()
            await expect(agency_page.locator("#selection-summary")).to_contain_text("1 selected")
            await agency_page.set_viewport_size({"width": 1440, "height": 900})
            await agency_page.locator('#campaign-form [name="name"]').fill("Browser campaign")
            await agency_page.locator('#campaign-targets input[type="checkbox"]').check()
            # Simulate one failed publish response. The UI must recover the
            # saved draft rather than creating another playlist/campaign.
            await agency_page.route("**/api/v1/agency/campaigns/*/publish",
                                    lambda route: route.fulfill(status=503, json={"error": {"message": "Temporary publish failure"}}),
                                    times=1)
            await agency_page.locator('#campaign-form button').click()
            await expect(agency_page.locator("#campaign-error")).to_contain_text("Use “Publish draft”", timeout=15000)
            await expect(agency_page.locator("#campaign-rows")).to_contain_text("DRAFT")
            await agency_page.get_by_role("button", name="Publish draft").click()
            await expect(agency_page.locator("#notice")).to_contain_text("Saved campaign published")
            await expect(agency_page.locator("#campaign-rows")).to_contain_text("LIVE WINDOW")
            await expect(agency_page.locator("#campaign-rows tr")).to_have_count(1)
            # Verify that cookie sessions survive navigation without a localStorage token.
            await agency_page.reload()
            await expect(agency_page.locator("#workspace")).to_be_visible()
            assert await agency_page.evaluate("localStorage.length") == 0
            for width in (390, 768, 1440, 1920):
                await agency_page.set_viewport_size({"width": width, "height": 900})
                assert await agency_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), f"Page overflow at {width}px"
            # Admin access is managed only in the master workspace.
            await page.get_by_role("button", name="Admin accounts", exact=True).click()
            await expect(page.locator("#media-actions")).to_contain_text("agency@example.com")
            page.once("dialog", lambda dialog: dialog.accept())
            await page.get_by_role("button", name="Delete admin access", exact=True).click()
            await expect(page.locator("#notice")).to_contain_text("Admin access deleted")
            await agency_page.locator("#refresh").click()
            await expect(agency_page.locator("#login")).to_be_visible()
            # Master can still sign out after the agency account was removed.
            await page.locator("#logout").click()
            await expect(page.locator("#login")).to_be_visible()
            # Agency session already expired by revocation.
            await agency_page.reload()
            # Verify the signed-out screen remains available.

            await expect(agency_page.locator("#login")).to_be_visible()
            assert not errors, "Browser JavaScript errors: " + "; ".join(errors)
        finally:
            await browser.close()


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="pixl-browser-") as temporary:
        password = secrets.token_urlsafe(24)
        totp_secret = pyotp.random_base32()
        env = {**os.environ,
            "DATABASE_URL": "sqlite+aiosqlite:///" + (Path(temporary) / "browser.db").as_posix(),
            "LOCAL_STORAGE_PATH": str(Path(temporary) / "storage"),
            "ENVIRONMENT": "development", "DEBUG": "false", "SESSION_BACKEND": "memory",
            "PORTAL_PANEL": "all", "SESSION_COOKIE_SECURE": "false", "MEDIA_PROCESSING_MODE": "inline",
            "AGENCY_ORIGIN": base_url, "MASTER_ORIGIN": base_url,
            "MASTER_BOOTSTRAP_EMAIL": "master@example.com", "MASTER_BOOTSTRAP_PASSWORD": password,
            "MASTER_BOOTSTRAP_TOTP_SECRET": totp_secret,
        }
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True, capture_output=True)
        subprocess.run([sys.executable, "-m", "scripts.create_master"], cwd=ROOT, env=env, check=True, capture_output=True)
        with (Path(temporary) / "server.log").open("w") as log:
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "pixl.main:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"], cwd=ROOT, env=env, stdout=log, stderr=log)
            async def wait_and_check():
                async with httpx.AsyncClient() as client:
                    for _ in range(60):
                        if server.poll() is not None:
                            raise RuntimeError("Temporary browser-check server failed to start")
                        try:
                            response = await client.get(base_url + "/api/v1/health/ready")
                            if response.status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(0.25)
                    else:
                        raise RuntimeError("Temporary server did not become ready")
                await run_check(base_url, password, totp_secret, temporary)
            try:
                asyncio.run(wait_and_check())
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    print("Portal browser smoke check passed: provisioning, invitation, pairing, batch upload, media dialog, graphs, draft publication recovery, responsive layouts, cookie session, admin revocation and logout.")


if __name__ == "__main__":
    main()
