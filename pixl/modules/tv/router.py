import os
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Request, Response, Query, Path
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from pixl.core.database import get_db_session
from pixl.core.config import settings
from pixl.modules.tv.service import PixlTvService

tv_router = APIRouter(prefix="/api/tv", tags=["Native Android Player TV Protocol"])
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
    db: AsyncSession = Depends(get_db_session)
):
    """Native Android Player Proof-of-Play receipt batch upload."""
    saved_count = await PixlTvService.record_proof_of_play(db=db, screen_number=screenId, logs=records)
    return {"saved": saved_count}


# 6. Direct Static Media Serving for Android Player
@media_file_router.get("/media/{file_path:path}")
async def serve_media_file(file_path: str):
    """
    Serves media files to Android ExoPlayer / ImageView.
    If physical file exists under local_storage, serves it directly.
    Otherwise returns a valid sample media byte stream.
    """
    local_path = os.path.join("local_storage", file_path)
    if os.path.exists(local_path) and os.path.isfile(local_path):
        return FileResponse(local_path)

    # 1x1 transparent/colored PNG fallback for image requests
    if file_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        # Minimal valid 1x1 PNG bytes
        png_1x1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return Response(content=png_1x1, media_type="image/png")

    # Fallback response for video requests
    return Response(content=b"", media_type="video/mp4")

