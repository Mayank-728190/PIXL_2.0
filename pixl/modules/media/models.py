from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, BigInteger, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pixl.core.database import Base, UUIDPrimaryKeyMixin, TimestampMixin


class MediaAsset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "media_assets"

    media_number: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True, nullable=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("brands.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0 for static image
    width: Mapped[int] = mapped_column(Integer, default=1920, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=1080, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default="PROCESSING",
        nullable=False
    )  # PROCESSING, READY, FAILED, QUARANTINED
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


class UploadTicket(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "upload_tickets"
    __table_args__ = (
        Index("ix_upload_tickets_dispatch", "status", "next_attempt_at"),
        Index("ix_upload_tickets_leases", "status", "lease_expires_at"),
        Index("ix_upload_tickets_cleanup", "status", "quarantine_cleaned_at", "updated_at"),
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_mime: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    presigned_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    # PENDING → UPLOADING → UPLOADED → QUEUED/PROCESSING → FINALIZED or FAILED; EXPIRED for abandonment.
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quarantine_cleaned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_brand_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    expected_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

