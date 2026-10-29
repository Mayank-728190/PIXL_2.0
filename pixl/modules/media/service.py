import asyncio
import hmac
import os
import tempfile
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Request
from sqlalchemy import func, select, update
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
        used = await db.scalar(select(func.coalesce(func.sum(MediaAsset.size_bytes), 0)).where(
            MediaAsset.organization_id == organization_id))
        reserved = await db.scalar(select(func.coalesce(func.sum(UploadTicket.size_bytes), 0)).where(
            UploadTicket.organization_id == organization_id,
            UploadTicket.status.in_(["PENDING", "UPLOADED", "PROCESSING", "UPLOADING"]),
            UploadTicket.expires_at > datetime.now(timezone.utc)))
        if used + reserved + size_bytes > org.storage_quota_bytes:
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
        claimed = await db.execute(update(UploadTicket).where(
            UploadTicket.id == ticket_id, UploadTicket.status == "PENDING"
        ).values(status="UPLOADING"))
        if claimed.rowcount != 1:
            raise ConflictError("Upload is already in progress or complete")
        await db.commit()
        target = storage_path(ticket.storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=target.parent, suffix=".part")
        try:
            size = 0
            with os.fdopen(fd, "wb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > ticket.size_bytes or size > settings.MAX_UPLOAD_BYTES:
                        raise UnprocessableError("Upload exceeds declared size")
                    output.write(chunk)
            if size != ticket.size_bytes:
                raise UnprocessableError("Uploaded size does not match the ticket")
            os.replace(temp_name, target)
            ticket.status = "UPLOADED"
            await db.commit()
        except BaseException:
            await db.rollback()
            await db.execute(update(UploadTicket).where(UploadTicket.id == ticket_id).values(status="PENDING"))
            await db.commit()
            raise
        finally:
            from pathlib import Path
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
        claimed = await db.execute(update(UploadTicket).where(
            UploadTicket.id == ticket_id, UploadTicket.status == "UPLOADED"
        ).values(status="PROCESSING"))
        if claimed.rowcount != 1:
            raise ConflictError("Upload must be completed before finalizing, and cannot be finalized twice")
        await db.commit()
        source = storage_path(ticket.storage_key)
        try:
            if not source.is_file() or source.stat().st_size != ticket.size_bytes:
                raise UnprocessableError("Uploaded content is missing or has changed")
            metadata = await asyncio.to_thread(inspect_media, source, ticket.declared_mime)
            if expected_sha256 and not hmac.compare_digest(expected_sha256.lower(), metadata["sha256"]):
                raise UnprocessableError("SHA-256 checksum mismatch")
            ext = MIME_EXTENSIONS[ticket.declared_mime]
            # Ticket-specific names allow authorized reuse of identical bytes.
            key = f"published/{organization_id}/{ticket.id}.{ext}"
            thumb_key = f"published/{organization_id}/{ticket.id}.thumbnail.webp"
            target = storage_path(key)
            thumbnail = storage_path(thumb_key)
            await asyncio.to_thread(generate_thumbnail, source, thumbnail, ticket.declared_mime)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary_target = target.with_suffix(target.suffix + ".part")
            await asyncio.to_thread(shutil.copyfile, source, temporary_target)
            await asyncio.to_thread(os.replace, temporary_target, target)
            asset = MediaAsset(
                media_number=await next_number(db, MediaAsset, "media_number", 5000),
                organization_id=organization_id, brand_id=brand_id, filename=ticket.filename,
                storage_key=key, mime_type=ticket.declared_mime, size_bytes=ticket.size_bytes,
                status="READY", thumbnail_url=public_media_url(thumb_key), **metadata,
            )
            db.add(asset)
            ticket.status = "FINALIZED"
            await db.commit()
            # Cleanup is best effort after commit; a filesystem cleanup failure
            # must not turn a successfully published ticket back into UPLOADED.
            try:
                source.unlink(missing_ok=True)
            except OSError:
                pass
            return asset
        except BaseException:
            await db.rollback()
            # A validation failure is retryable while the original bytes remain.
            await db.execute(update(UploadTicket).where(UploadTicket.id == ticket_id).values(status="UPLOADED"))
            await db.commit()
            raise

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
