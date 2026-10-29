import asyncio
import hmac
import os
import tempfile
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Request
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pixl.core.config import settings
from pixl.core.identifiers import next_number
from pixl.core.database import ensure_utc
from pixl.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from pixl.core.storage import (
    MIME_EXTENSIONS, generate_thumbnail, inspect_media, public_media_url,
    storage_path, upload_signature,
)
from pixl.modules.media.models import MediaAsset, UploadTicket
from pixl.modules.organizations.models import Brand, Organization


class MediaService:
    @staticmethod
    async def create_upload_ticket(db: AsyncSession, organization_id: str, filename: str,
                                   size_bytes: int, declared_mime: str) -> UploadTicket:
        org = await db.scalar(select(Organization).where(
            Organization.id == organization_id).with_for_update())
        if not org or org.status != "ACTIVE":
            raise NotFoundError("Active organization not found")
        if declared_mime not in MIME_EXTENSIONS or not 0 < size_bytes <= settings.MAX_UPLOAD_BYTES:
            raise UnprocessableError("Unsupported MIME type or upload size")
        used = select(func.coalesce(func.sum(MediaAsset.size_bytes), 0)).where(
            MediaAsset.organization_id == organization_id).scalar_subquery()
        reserved = select(func.coalesce(func.sum(UploadTicket.size_bytes), 0)).where(
            UploadTicket.organization_id == organization_id,
            UploadTicket.status != "FINALIZED",
            UploadTicket.quarantine_cleaned_at.is_(None)).scalar_subquery()
        # Failed/expired bytes retain their reservation until cleanup confirms
        # deletion, preventing repeated invalid uploads from exhausting the disk.
        # One database snapshot prevents publication between two separate reads
        # from hiding bytes in both the reservation and library totals.
        occupied = await db.scalar(select(used + reserved))
        if occupied + size_bytes > org.storage_quota_bytes:
            raise ConflictError("Organization storage quota exceeded")
        ticket_id = str(uuid.uuid4())
        key = f"quarantine/{organization_id}/{ticket_id}.{MIME_EXTENSIONS[declared_mime]}"
        storage_path(key)  # Fail explicitly for unsupported storage providers.
        ticket = UploadTicket(
            id=ticket_id, organization_id=organization_id, filename=filename,
            size_bytes=size_bytes, declared_mime=declared_mime, storage_key=key,
            presigned_url=f"/api/v1/agency/media/uploads/{ticket_id}?signature={upload_signature(ticket_id)}",
            status="PENDING", expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        db.add(ticket)
        await db.commit()
        return ticket

    @staticmethod
    async def receive_upload(db: AsyncSession, ticket_id: str, signature: str, request: Request):
        if not hmac.compare_digest(signature, upload_signature(ticket_id)):
            raise ForbiddenError("Invalid upload signature")
        ticket = await db.get(UploadTicket, ticket_id)
        if not ticket:
            raise NotFoundError("Upload ticket not found")
        if ensure_utc(ticket.expires_at) <= datetime.now(timezone.utc):
            raise ConflictError("Upload ticket expired")
        org = await db.get(Organization, ticket.organization_id)
        if not org or org.status != "ACTIVE":
            raise ForbiddenError("Organization is not active")
        claimed = await db.execute(update(UploadTicket).execution_options(synchronize_session="fetch").where(
            UploadTicket.id == ticket_id, UploadTicket.status == "PENDING"
        ).values(status="UPLOADING"))
        if claimed.rowcount != 1:
            raise ConflictError("Upload is already in progress or complete")
        await db.commit()
        temp_name = None
        try:
            target = storage_path(ticket.storage_key)
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(dir=target.parent, suffix=".part")
            size = 0
            with os.fdopen(fd, "wb") as output:
                async with asyncio.timeout(300):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > ticket.size_bytes or size > settings.MAX_UPLOAD_BYTES:
                            raise UnprocessableError("Upload exceeds declared size")
                        await asyncio.to_thread(output.write, chunk)
            if size != ticket.size_bytes:
                raise UnprocessableError("Uploaded size does not match the ticket")
            os.replace(temp_name, target)
            ticket.status = "UPLOADED"
            await db.commit()
        except BaseException as exc:
            await db.rollback()
            await db.execute(update(UploadTicket).execution_options(synchronize_session="fetch").where(
                UploadTicket.id == ticket_id, UploadTicket.status == "UPLOADING"
            ).values(status="PENDING"))
            await db.commit()
            if isinstance(exc, TimeoutError):
                raise UnprocessableError("Upload timed out. Retry with a new upload ticket.") from exc
            raise
        finally:
            from pathlib import Path
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)

    @staticmethod
    async def finalize_upload(db: AsyncSession, organization_id: str, ticket_id: str,
                              brand_id: Optional[str] = None,
                              expected_sha256: Optional[str] = None) -> MediaAsset:
        ticket = await db.scalar(select(UploadTicket).where(
            UploadTicket.id == ticket_id, UploadTicket.organization_id == organization_id))
        if not ticket:
            raise NotFoundError("Upload ticket not found in your agency")
        if brand_id:
            brand = await db.get(Brand, brand_id)
            if not brand or brand.organization_id != organization_id:
                raise ForbiddenError("Brand does not belong to your agency")
        if ensure_utc(ticket.expires_at) <= datetime.now(timezone.utc):
            raise ConflictError("Upload ticket expired")
        lease = str(uuid.uuid4())
        claimed = await db.execute(update(UploadTicket).execution_options(synchronize_session="fetch").where(
            UploadTicket.id == ticket_id, UploadTicket.status == "UPLOADED"
        ).values(status="PROCESSING", lease_token=lease, processing_brand_id=brand_id,
                 expected_sha256=expected_sha256.lower() if expected_sha256 else None,
                 lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15)))
        if claimed.rowcount != 1:
            raise ConflictError("Upload must be completed before finalizing, and cannot be finalized twice")
        await db.commit()
        try:
            return await MediaService._publish_ticket(db, ticket, brand_id, expected_sha256, lease)
        except BaseException:
            await db.rollback()
            await db.execute(update(UploadTicket).execution_options(synchronize_session="fetch").where(
                UploadTicket.id == ticket_id, UploadTicket.lease_token == lease,
                UploadTicket.status == "PROCESSING"
            ).values(status="UPLOADED", lease_token=None, lease_expires_at=None))
            await db.commit()
            raise

    @staticmethod
    async def _publish_ticket(db, ticket, brand_id, expected_sha256, lease):
        # The caller owns a bounded lease. Files use ticket-specific names, so a
        # retry after a worker crash cannot create a second library record.
        source = storage_path(ticket.storage_key)
        org = await db.get(Organization, ticket.organization_id)
        if not org or org.status != "ACTIVE":
            raise ForbiddenError("Organization is not active")
        if brand_id:
            brand = await db.get(Brand, brand_id)
            if not brand or brand.organization_id != ticket.organization_id:
                raise ForbiddenError("Brand does not belong to your agency")
        if not source.is_file() or source.stat().st_size != ticket.size_bytes:
            raise UnprocessableError("Uploaded content is missing or has changed")
        metadata = await asyncio.to_thread(inspect_media, source, ticket.declared_mime)
        if expected_sha256 and not hmac.compare_digest(expected_sha256.lower(), metadata["sha256"]):
            raise UnprocessableError("SHA-256 checksum mismatch")
        ext = MIME_EXTENSIONS[ticket.declared_mime]
        # Ticket-specific names allow authorized reuse of identical bytes.
        key = f"published/{ticket.organization_id}/{ticket.id}.{ext}"
        thumb_key = f"published/{ticket.organization_id}/{ticket.id}.thumbnail.webp"
        target = storage_path(key)
        thumbnail = storage_path(thumb_key)
        temporary_thumbnail = thumbnail.with_name(f"{ticket.id}.{lease}.part.webp")
        temporary_target = target.with_name(f"{ticket.id}.{lease}.part")
        try:
            await asyncio.to_thread(generate_thumbnail, source, temporary_thumbnail, ticket.declared_mime)
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copyfile, source, temporary_target)
            await asyncio.to_thread(os.replace, temporary_thumbnail, thumbnail)
            await asyncio.to_thread(os.replace, temporary_target, target)
        finally:
            for temporary in (temporary_thumbnail, temporary_target):
                try:
                    await asyncio.to_thread(temporary.unlink, missing_ok=True)
                except OSError:
                    pass
        asset = MediaAsset(
            media_number=await next_number(db, MediaAsset, "media_number", 5000),
            organization_id=ticket.organization_id, brand_id=brand_id, filename=ticket.filename,
            storage_key=key, mime_type=ticket.declared_mime, size_bytes=ticket.size_bytes,
            status="READY", thumbnail_url=public_media_url(thumb_key), **metadata,
        )
        db.add(asset)
        completed = await db.execute(update(UploadTicket).execution_options(synchronize_session="fetch").where(
            UploadTicket.id == ticket.id, UploadTicket.status == "PROCESSING",
            UploadTicket.lease_token == lease,
            UploadTicket.lease_expires_at > datetime.now(timezone.utc)
        ).values(status="FINALIZED", lease_token=None, lease_expires_at=None,
                 processing_error=None, next_attempt_at=None))
        if completed.rowcount != 1:
            raise ConflictError("Processing lease expired; retry through job status")
        await db.commit()
        # Cleanup is best effort after commit; a filesystem cleanup failure
        # must not turn a successfully published ticket back into UPLOADED.
        try:
            source.unlink(missing_ok=True)
        except OSError:
            pass
        return asset

    @staticmethod
    async def processing_status(db: AsyncSession, organization_id: str, ticket_id: str):
        ticket = await db.scalar(select(UploadTicket).where(
            UploadTicket.id == ticket_id, UploadTicket.organization_id == organization_id))
        if not ticket:
            raise NotFoundError("Upload ticket not found in your agency")
        key = f"published/{organization_id}/{ticket.id}.{MIME_EXTENSIONS[ticket.declared_mime]}"
        media_id = await db.scalar(select(MediaAsset.id).where(MediaAsset.storage_key == key))
        return {"ticket_id": ticket.id, "status": ticket.status,
                "attempts": ticket.processing_attempts, "error": ticket.processing_error,
                "media_id": media_id, "background": settings.MEDIA_PROCESSING_MODE == "worker"}

    @staticmethod
    async def request_processing(db: AsyncSession, organization_id: str, ticket_id: str,
                                 brand_id=None, expected_sha256=None):
        ticket = await db.scalar(select(UploadTicket).where(
            UploadTicket.id == ticket_id, UploadTicket.organization_id == organization_id))
        if not ticket:
            raise NotFoundError("Upload ticket not found in your agency")
        if brand_id:
            brand = await db.get(Brand, brand_id)
            if not brand or brand.organization_id != organization_id:
                raise ForbiddenError("Brand does not belong to your agency")
        # A retry after an HTTP timeout returns the existing job, not another asset.
        if ticket.status in {"QUEUED", "PROCESSING", "FINALIZED"}:
            if (ticket.processing_brand_id != brand_id or
                    ticket.expected_sha256 != (expected_sha256.lower() if expected_sha256 else None)):
                raise ConflictError("Processing was already requested with different options")
            return await MediaService.processing_status(db, organization_id, ticket_id)
        if ensure_utc(ticket.expires_at) <= datetime.now(timezone.utc):
            raise ConflictError("Upload ticket expired")
        if settings.MEDIA_PROCESSING_MODE == "inline":
            await MediaService.finalize_upload(db, organization_id, ticket_id, brand_id, expected_sha256)
            return await MediaService.processing_status(db, organization_id, ticket_id)
        if ticket.status != "UPLOADED":
            raise ConflictError("Upload must be completed before requesting processing")
        queued = await db.execute(update(UploadTicket).execution_options(synchronize_session="fetch").where(
            UploadTicket.id == ticket_id, UploadTicket.status == "UPLOADED"
        ).values(status="QUEUED", processing_brand_id=brand_id,
                 expected_sha256=expected_sha256.lower() if expected_sha256 else None,
                 processing_error=None, next_attempt_at=datetime.now(timezone.utc)))
        if queued.rowcount != 1:
            raise ConflictError("Processing was already requested; check upload status")
        # Database commit is the durable enqueue. Beat rediscovers outstanding
        # work even if the broker is down or a worker dies before acknowledgement.
        await db.commit()
        return await MediaService.processing_status(db, organization_id, ticket_id)

    @staticmethod
    def runnable_jobs(now):
        return or_(and_(UploadTicket.status == "QUEUED", UploadTicket.next_attempt_at <= now),
                   and_(UploadTicket.status == "PROCESSING", UploadTicket.processing_attempts > 0,
                        UploadTicket.lease_expires_at <= now))

    @staticmethod
    async def process_queued_upload(db: AsyncSession, ticket_id: str):
        now = datetime.now(timezone.utc)
        # A job killed on its final attempt must not be retried forever.
        await db.execute(update(UploadTicket).execution_options(synchronize_session="fetch").where(
            UploadTicket.id == ticket_id, MediaService.runnable_jobs(now),
            UploadTicket.processing_attempts >= 3
        ).values(status="FAILED", lease_token=None, lease_expires_at=None,
                 processing_error="Processing stopped after three attempts; upload the file again."))
        lease = str(uuid.uuid4())
        claimed = await db.execute(update(UploadTicket).execution_options(synchronize_session="fetch").where(
            UploadTicket.id == ticket_id, MediaService.runnable_jobs(now),
            UploadTicket.processing_attempts < 3
        ).values(status="PROCESSING", lease_token=lease, lease_expires_at=now + timedelta(minutes=15),
                 processing_attempts=UploadTicket.processing_attempts + 1))
        await db.commit()
        if claimed.rowcount != 1:
            return {"ticket_id": ticket_id, "claimed": False}
        ticket = await db.get(UploadTicket, ticket_id, populate_existing=True)
        attempts = ticket.processing_attempts
        try:
            asset = await MediaService._publish_ticket(
                db, ticket, ticket.processing_brand_id, ticket.expected_sha256, lease)
            return {"ticket_id": ticket_id, "status": "FINALIZED", "media_id": asset.id}
        except Exception as exc:
            from pixl.core.exceptions import PixlException
            # Bad content/ownership is terminal. Infrastructure failures receive
            # bounded exponential retries; never expose subprocess paths/errors.
            terminal = attempts >= 3 or (isinstance(exc, PixlException) and exc.status_code in {403, 404, 422})
            message = exc.detail if isinstance(exc, PixlException) else "Media processing temporarily unavailable."
            await db.rollback()
            await db.execute(update(UploadTicket).execution_options(synchronize_session="fetch").where(
                UploadTicket.id == ticket_id, UploadTicket.lease_token == lease,
                UploadTicket.status == "PROCESSING"
            ).values(status="FAILED" if terminal else "QUEUED", processing_error=message,
                     lease_token=None, lease_expires_at=None,
                     next_attempt_at=None if terminal else now + timedelta(seconds=30 * 2 ** attempts)))
            await db.commit()
            await db.refresh(ticket)
            return {"ticket_id": ticket_id, "status": "FAILED" if terminal else "QUEUED"}

    @staticmethod
    async def list_media(db: AsyncSession, organization_id: str,
                         brand_id: Optional[str] = None) -> List[MediaAsset]:
        query = select(MediaAsset).where(MediaAsset.organization_id == organization_id)
        if brand_id:
            query = query.where(MediaAsset.brand_id == brand_id)
        result = await db.execute(query.order_by(MediaAsset.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def get_media(db: AsyncSession, organization_id: str, media_id: str) -> MediaAsset:
        asset = await db.scalar(select(MediaAsset).where(
            MediaAsset.id == media_id, MediaAsset.organization_id == organization_id))
        if not asset:
            raise NotFoundError("Media asset not found in your agency library")
        return asset
