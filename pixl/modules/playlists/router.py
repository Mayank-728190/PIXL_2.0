from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pixl.core.database import get_db_session
from pixl.core.dependencies import require_role, require_tenant_context
from pixl.modules.playlists.schemas import PlaylistCreateRequest, PlaylistResponse
from pixl.modules.playlists.service import PlaylistService

router = APIRouter(prefix="/api/v1/agency/playlists", tags=["Agency: Playlists"])


@router.post("", response_model=PlaylistResponse)
async def create_playlist_endpoint(
    req: PlaylistCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Agency creates ordered playlist with duration mode policies."""
    playlist = await PlaylistService.create_playlist(
        db=db,
        organization_id=org_id,
        name=req.name,
        is_reusable=req.is_reusable,
        items=req.items
    )
    return PlaylistResponse.model_validate(playlist)


@router.get("", response_model=List[PlaylistResponse])
async def list_agency_playlists(
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Agency views its own playlists."""
    playlists = await PlaylistService.list_playlists(db=db, organization_id=org_id)
    return [PlaylistResponse.model_validate(p) for p in playlists]


@router.get("/{playlist_id}", response_model=PlaylistResponse)
async def get_agency_playlist(
    playlist_id: str,
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Get single playlist; returns 404 if belonging to another agency."""
    pl = await PlaylistService.get_playlist(db=db, organization_id=org_id, playlist_id=playlist_id)
    return PlaylistResponse.model_validate(pl)

