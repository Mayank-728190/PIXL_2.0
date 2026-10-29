from datetime import datetime, timezone, timedelta
from typing import Optional, List
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pixl.modules.media.models import MediaAsset, UploadTicket
from pixl.modules.organizations.models import Organization
from pixl.core.database import ensure_utc
from pixl.core.config import settings
from pixl.core.security import generate_secure_token
from pixl.core.exceptions import ConflictError, NotFoundError, ForbiddenError


class MediaService:
    @staticmethod
    async def create_upload_ticket(
        db: AsyncSession,
        organization_id: str,
        filename: str,
        size_bytes: int,
        declared_mime: str
    ) -> UploadTicket:
        # Check quota
        org_result = await db.execute(select(Organization).where(Organization.id == organization_id))
        org = org_result.scalar_one_or_none()
        if not org:
            raise NotFoundError("Organization not found")

        # Generate unique storage key in quarantine
        file_ext = filename.split(".")[-1] if "." in filename else "bin"
        storage_key = f"quarantine/{organization_id}/{uuid.uuid4()}.{file_ext}"
        
        # Simulated pre-signed URL for direct upload
        presigned_url = f"{settings.R2_PUBLIC_URL_PREFIX}/{storage_key}?token={generate_secure_token(16)}"
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

        ticket = UploadTicket(
            organization_id=organization_id,
            filename=filename,
            size_bytes=size_bytes,
            declared_mime=declared_mime,
            storage_key=storage_key,
            presigned_url=presigned_url,
            status="PENDING",
            expires_at=expires_at
        )
        db.add(ticket)
        await db.commit()
        return ticket

    @staticmethod
    async def finalize_upload(
        db: AsyncSession,
        organization_id: str,
        ticket_id: str,
        brand_id: Optional[str] = None,
        expected_sha256: Optional[str] = None
    ) -> MediaAsset:
        result = await db.execute(
            select(UploadTicket).where(
                UploadTicket.id == ticket_id,
                UploadTicket.organization_id == organization_id
            )
        )
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise NotFoundError("Upload ticket not found or does not belong to your agency")

        if ticket.status != "PENDING":
            raise ConflictError(f"Upload ticket is already {ticket.status.lower()}")

        if datetime.now(timezone.utc) > ensure_utc(ticket.expires_at):
            ticket.status = "EXPIRED"
            await db.commit()
            raise ConflictError("Upload ticket expired")

        # Mock / simulate content verification (in production Celery worker runs ffprobe & sha256)
        sha256 = expected_sha256 or f"mock_sha256_{generate_secure_token(16)}"
        published_key = f"published/{organization_id}/{sha256}.{ticket.filename.split('.')[-1]}"
        
        is_video = "video" in ticket.declared_mime
        duration_ms = 15000 if is_video else 0

        asset = MediaAsset(
            organization_id=organization_id,
            brand_id=brand_id,
            filename=ticket.filename,
            storage_key=published_key,
            sha256=sha256,
            mime_type=ticket.declared_mime,
            size_bytes=ticket.size_bytes,
            duration_ms=duration_ms,
            width=1920,
            height=1080,
            status="READY",
            thumbnail_url=f"{settings.R2_PUBLIC_URL_PREFIX}/thumbnails/{sha256}.webp"
        )
        db.add(asset)
        ticket.status = "FINALIZED"

        await db.commit()
        return asset

    @staticmethod
    async def list_media(
        db: AsyncSession,
        organization_id: str,
        brand_id: Optional[str] = None
    ) -> List[MediaAsset]:
        query = select(MediaAsset).where(MediaAsset.organization_id == organization_id)
        if brand_id:
            query = query.where(MediaAsset.brand_id == brand_id)
        result = await db.execute(query.order_by(MediaAsset.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def get_media(
        db: AsyncSession,
        organization_id: str,
        media_id: str
    ) -> MediaAsset:
        result = await db.execute(
            select(MediaAsset).where(
                MediaAsset.id == media_id,
                MediaAsset.organization_id == organization_id
            )
        )
        asset = result.scalar_one_or_none()
        if not asset:
            raise NotFoundError("Media asset not found in your agency library")
        return asset
