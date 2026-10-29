from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pixl.core.database import get_db_session
from pixl.core.dependencies import require_role, require_tenant_context
from pixl.modules.media.schemas import (
    UploadTicketRequest, UploadTicketResponse,
    FinalizeUploadRequest, MediaAssetResponse
)
from pixl.modules.media.service import MediaService

router = APIRouter(prefix="/api/v1/agency/media", tags=["Agency: Media Library"])


@router.post("/upload-ticket", response_model=UploadTicketResponse)
async def request_upload_ticket(
    req: UploadTicketRequest,
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Agency requests pre-signed direct upload ticket to private quarantine bucket."""
    ticket = await MediaService.create_upload_ticket(
        db=db,
        organization_id=org_id,
        filename=req.filename,
        size_bytes=req.size_bytes,
        declared_mime=req.declared_mime
    )
    return UploadTicketResponse(
        ticket_id=ticket.id,
        storage_key=ticket.storage_key,
        presigned_upload_url=ticket.presigned_url,
        expires_at=ticket.expires_at
    )


@router.put("/uploads/{ticket_id}")
async def upload_media_bytes(
    ticket_id: str,
    request: Request,
    signature: str = Query(..., min_length=64, max_length=64),
    db: AsyncSession = Depends(get_db_session),
):
    """Upload raw bytes using a single-use, expiring signed ticket URL."""
    await MediaService.receive_upload(db, ticket_id, signature, request)
    return {"status": "UPLOADED"}


@router.post("/finalize", response_model=MediaAssetResponse)
async def finalize_media_upload(
    req: FinalizeUploadRequest,
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Validate uploaded bytes, inspect media, generate a thumbnail and publish."""
    asset = await MediaService.finalize_upload(
        db=db,
        organization_id=org_id,
        ticket_id=req.ticket_id,
        brand_id=req.brand_id,
        expected_sha256=req.expected_sha256
    )
    return MediaAssetResponse.model_validate(asset)


@router.get("", response_model=List[MediaAssetResponse])
async def list_agency_media(
    brand_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Agency views its own media library."""
    assets = await MediaService.list_media(db=db, organization_id=org_id, brand_id=brand_id)
    return [MediaAssetResponse.model_validate(a) for a in assets]


@router.get("/{media_id}", response_model=MediaAssetResponse)
async def get_agency_media(
    media_id: str,
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Get single media asset; returns 404 if belonging to another agency."""
    asset = await MediaService.get_media(db=db, organization_id=org_id, media_id=media_id)
    return MediaAssetResponse.model_validate(asset)

