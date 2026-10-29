from pathlib import Path
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse

from pixl.core.config import settings

router = APIRouter(tags=["Web portals"])
ASSETS = Path(__file__).parent


def portal(panel, title):
    required = "agency" if panel == "invitation" else panel
    if settings.PORTAL_PANEL not in {"all", required}:
        raise HTTPException(404, "Portal not available on this deployment")
    # Thumbnails may use the separately configured API/media origin. Never
    # interpolate arbitrary configuration text into a policy header.
    media_source = ""
    try:
        media_url = urlsplit(settings.MEDIA_PUBLIC_BASE_URL)
        if media_url.scheme in {"https", "http"} and re.fullmatch(r"[A-Za-z0-9.\-\[\]:]+", media_url.netloc):
            _ = media_url.port
            media_source = f" {media_url.scheme}://{media_url.netloc}"
    except ValueError:
        pass
    content = (ASSETS / "index.html").read_text(encoding="utf-8")
    content = content.replace("__PANEL__", panel).replace("__TITLE__", title)
    return HTMLResponse(content, headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                                   f"connect-src 'self'; img-src 'self' data:{media_source}; "
                                   "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    })


@router.get("/", include_in_schema=False)
async def portal_home():
    target = "/master" if settings.PORTAL_PANEL == "master" else "/agency"
    return RedirectResponse(target)


@router.get("/master", response_class=HTMLResponse, include_in_schema=False)
async def master_portal():
    return portal("master", "Master portal")


@router.get("/agency", response_class=HTMLResponse, include_in_schema=False)
async def agency_portal():
    return portal("agency", "Agency portal")


@router.get("/accept-invitation", response_class=HTMLResponse, include_in_schema=False)
async def accept_invitation_portal():
    return portal("invitation", "Account activation")


@router.get("/portal-assets/{name}", include_in_schema=False)
async def portal_asset(name: str):
    media_types = {"portal.js": "text/javascript", "portal.css": "text/css"}
    if name not in media_types:
        raise HTTPException(404)
    return FileResponse(ASSETS / name, media_type=media_types[name],
                        headers={"X-Content-Type-Options": "nosniff"})
