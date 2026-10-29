from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pixl.modules.ingestion.models import PlaybackEvent, QuarantinedPoPEvent
from pixl.modules.screens.models import Screen, DeviceCursor
from pixl.modules.ingestion.schemas import PoPBatchRequest, PoPDisposition
from pixl.core.exceptions import ConflictError, NotFoundError, ForbiddenError


class IngestionService:
    @staticmethod
    async def ingest_batch(
        db: AsyncSession,
        req: PoPBatchRequest
    ) -> Tuple[int, List[PoPDisposition]]:
        # 1. Fetch screen and verify
        screen_res = await db.execute(select(Screen).where(Screen.id == req.device_id))
        screen = screen_res.scalar_one_or_none()
        if not screen or not screen.organization_id:
            raise NotFoundError("Screen or screen organization not found")

        # 2. Fetch or create device cursor for this epoch
        cursor_res = await db.execute(
            select(DeviceCursor).where(
                DeviceCursor.screen_id == req.device_id,
                DeviceCursor.epoch == req.epoch
            )
        )
        cursor = cursor_res.scalar_one_or_none()
        if not cursor:
            cursor = DeviceCursor(
                screen_id=req.device_id,
                epoch=req.epoch,
                last_committed_sequence=0
            )
            db.add(cursor)
            await db.flush()

        # Sort batch by sequence
        sorted_batch = sorted(req.batch, key=lambda x: x.local_sequence)
        
        current_cursor = cursor.last_committed_sequence
        dispositions = []

        # 3. Process each event in the batch
        for event in sorted_batch:
            seq = event.local_sequence

            # Duplicate: already committed sequence
            if seq <= current_cursor:
                dispositions.append(
                    PoPDisposition(local_sequence=seq, status="DUPLICATE_ACKNOWLEDGED")
                )
                continue

            # Gap check: must be exactly current_cursor + 1
            if seq > current_cursor + 1:
                # Sequence gap detected! Cannot advance cursor silently
                raise ConflictError(
                    detail="Sequence gap detected in upload batch",
                    extra={
                        "status": "GAP_DETECTED",
                        "expected_sequence": current_cursor + 1,
                        "received_sequence": seq,
                        "action": "RESEND_FROM_CURSOR"
                    }
                )

            # Valid contiguous new sequence: insert playback event
            try:
                pop_record = PlaybackEvent(
                    screen_id=req.device_id,
                    device_epoch=req.epoch,
                    local_sequence=seq,
                    started_at=event.started_at,
                    completed_at=event.completed_at,
                    organization_id=screen.organization_id,
                    campaign_id=event.campaign_id,
                    media_id=event.media_id,
                    media_sha256=event.media_sha256,
                    zone_id=event.zone_id,
                    duration_ms=event.duration_ms,
                    outcome=event.outcome,
                    failure_reason=event.failure_reason,
                    clock_quality=event.clock_quality
                )
                db.add(pop_record)
                current_cursor = seq
                dispositions.append(
                    PoPDisposition(local_sequence=seq, status="STORED")
                )
            except Exception as e:
                # Poison event handling: quarantine event so batch can advance
                q_event = QuarantinedPoPEvent(
                    screen_id=req.device_id,
                    device_epoch=req.epoch,
                    local_sequence=seq,
                    rejection_reason=str(e),
                    raw_payload_json=json.dumps(event.model_dump(), default=str)
                )
                db.add(q_event)
                current_cursor = seq
                dispositions.append(
                    PoPDisposition(local_sequence=seq, status="QUARANTINED")
                )

        # 4. Advance cursor atomically
        cursor.last_committed_sequence = current_cursor
        cursor.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        return current_cursor, dispositions
