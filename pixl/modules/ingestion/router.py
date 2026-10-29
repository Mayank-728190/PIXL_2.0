from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pixl.core.database import get_db_session
from pixl.core.dependencies import get_authenticated_device
from pixl.core.exceptions import ForbiddenError
from pixl.modules.ingestion.schemas import PoPBatchRequest, PoPBatchResponse
from pixl.modules.ingestion.service import IngestionService

router = APIRouter(prefix="/api/v1/device/playback", tags=["Device: Proof-of-Play Ingestion"])


@router.post("/batch", response_model=PoPBatchResponse)
async def ingest_playback_batch(
    req: PoPBatchRequest,
    credential=Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Durable, idempotent proof-of-play batch ingestion.
    Locks device cursor, dedupes past sequences, requires contiguous ordering, advances cursor atomically.
    """
    if credential.screen_id != req.device_id:
        raise ForbiddenError("Device token does not match payload device_id")

    last_seq, dispositions = await IngestionService.ingest_batch(db=db, req=req)

    return PoPBatchResponse(
        status="ACK",
        device_id=req.device_id,
        epoch=req.epoch,
        last_committed_sequence=last_seq,
        dispositions=dispositions
    )

