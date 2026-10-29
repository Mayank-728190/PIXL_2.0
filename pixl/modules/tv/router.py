from pathlib import Path as FilePath
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from pixl.core.database import get_db_session
from pixl.core.config import settings
from pixl.modules.tv.service import PixlTvService

def require_legacy_tv():
    if settings.ENVIRONMENT == "production" or not settings.ALLOW_LEGACY_TV:
        raise HTTPException(410, "Legacy TV protocol is disabled; use authenticated /api/v1/device endpoints")


tv_router = APIRouter(prefix="/api/tv", tags=["Native Android Player TV Protocol"],
                      dependencies=[Depends(require_legacy_tv)])
media_file_router = APIRouter(tags=["Media File Serving"])


class TvRegisterRequest(BaseModel):
    name: str = "Android Player"
    location: Optional[str] = None


class TvPingRequest(BaseModel):
    screenId: int
    pairingCode: str


# 1. Device Registration (First Boot)
@tv_router.post("/register")
async def register_tv_device(
    req: TvRegisterRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """Native Android Player registration endpoint."""
    return await PixlTvService.register_screen(db=db, name=req.name, location=req.location)


# 2. Assignment Check (Polling for PIN pairing)
@tv_router.get("/player/{code}/assignment")
async def check_tv_assignment(
    code: str,
    db: AsyncSession = Depends(get_db_session)
):
    """Native Android Player assignment check endpoint."""
    return await PixlTvService.get_assignment(db=db, code=code)


# 3. Screen Sync & Manifest Fetch
@tv_router.get("/sync")
async def sync_tv_device(
    request: Request,
    screenId: int = Query(...),
    pairingCode: str = Query(...),
    db: AsyncSession = Depends(get_db_session)
):
    """Native Android Player content synchronization endpoint."""
    # Determine base URL of this request
    base_url = str(request.base_url).rstrip('/')
    return await PixlTvService.sync_screen(
        db=db,
        screen_number=screenId,
        pairing_code=pairingCode,
        base_url=base_url
    )


# 4. Telemetry Ping
@tv_router.post("/ping")
async def ping_tv_device(
    req: TvPingRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """Native Android Player periodic heartbeat."""
    await PixlTvService.record_ping(db=db, screen_number=req.screenId, pairing_code=req.pairingCode)
    return {"status": "ok"}


# 5. Proof of Play Receipts Upload
@tv_router.post("/{screenId}/proof-of-play")
async def upload_tv_proof_of_play(
    screenId: int,
    records: List[Dict[str, Any]],
    pairingCode: str = Query(..., min_length=6, max_length=8),
    db: AsyncSession = Depends(get_db_session)
):
    """Native Android Player Proof-of-Play receipt batch upload."""
    from sqlalchemy import select
    from pixl.modules.screens.models import Screen
    screen = await db.scalar(select(Screen).where(
        Screen.screen_number == screenId, Screen.pairing_code == pairingCode.strip().upper(),
        Screen.organization_id.is_not(None),
    ))
    if not screen:
        raise HTTPException(401, "Invalid screen pairing credentials")
    if not 1 <= len(records) <= 100:
        raise HTTPException(422, "Receipt batch must contain 1 to 100 records")
    saved_count = await PixlTvService.record_proof_of_play(db=db, screen_number=screenId, logs=records)
    return {"saved": saved_count}


# 6. Direct Static Media Serving for Android Player
@media_file_router.get("/media/{file_path:path}")
async def serve_media_file(file_path: str, expires: Optional[int] = None, signature: Optional[str] = None):
    """Serve actual published content only; quarantine and missing files are private."""
    from pixl.core.storage import storage_path, valid_media_signature
    from pixl.core.exceptions import UnprocessableError
    # Reject Windows separators as well as POSIX traversal before resolving.
    if "\\" in file_path or not file_path.startswith("published/") or ".." in file_path.split("/"):
        raise HTTPException(status_code=404, detail="Media file not found")
    try:
        local_path = storage_path(file_path)
    except UnprocessableError:
        raise HTTPException(status_code=404, detail="Media file not found")
    if (not local_path.is_file() or expires is None or not signature
            or not valid_media_signature(file_path, expires, signature)):
        raise HTTPException(status_code=404, detail="Media file not found")
    from pixl.core.storage import MIME_EXTENSIONS
    mime = {ext: mime for mime, ext in MIME_EXTENSIONS.items()}.get(local_path.suffix.lstrip("."))
    return FileResponse(local_path, media_type=mime, headers={"X-Content-Type-Options": "nosniff"})
