import pytest

from pixl.core.config import settings


@pytest.mark.parametrize("path,title", [("/master", "Master portal"), ("/agency", "Agency portal"), ("/accept-invitation", "Account activation")])
async def test_portals_render_without_public_registration(client, path, title):
    response = await client.get(path)
    assert response.status_code == 200
    assert title in response.text
    assert "public registration" not in response.text.lower()
    assert '<script src="/portal-assets/portal.js" defer>' in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_portal_deployment_isolation_and_static_allowlist(client, monkeypatch):
    monkeypatch.setattr(settings, "PORTAL_PANEL", "master")
    assert (await client.get("/master")).status_code == 200
    assert (await client.get("/agency")).status_code == 404
    assert (await client.get("/accept-invitation")).status_code == 404
    assert (await client.get("/portal-assets/portal.js")).status_code == 200
    assert (await client.get("/portal-assets/portal.css")).status_code == 200
    assert (await client.get("/portal-assets/config.py")).status_code == 404
