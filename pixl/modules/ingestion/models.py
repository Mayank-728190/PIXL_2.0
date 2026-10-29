from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, BigInteger, DateTime, Text, PrimaryKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from pixl.core.database import Base, UUIDPrimaryKeyMixin


class PlaybackEvent(Base):
    __tablename__ = "playback_events"
    __table_args__ = (
        PrimaryKeyConstraint("screen_id", "device_epoch", "local_sequence", "started_at"),
        Index("idx_pop_device_seq", "screen_id", "local_sequence"),
        Index("idx_pop_org_started", "organization_id", "started_at"),
    )

    screen_id: Mapped[str] = mapped_column(String(36), nullable=False)
    device_epoch: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    local_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    media_id: Mapped[str] = mapped_column(String(36), nullable=False)
    media_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    zone_id: Mapped[str] = mapped_column(String(50), default="zone_main", nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    outcome: Mapped[str] = mapped_column(String(50), nullable=False)  # COMPLETED, INTERRUPTED, DECODE_FAILED, SKIPPED
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    clock_quality: Mapped[str] = mapped_column(String(50), default="NTP_SYNCED", nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )


class QuarantinedPoPEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "quarantined_pop_events"

    screen_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    device_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    local_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rejection_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    quarantined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

