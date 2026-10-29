from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import String, Integer, BigInteger, DateTime, ForeignKey, Text, PrimaryKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pixl.core.database import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Screen(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "screens"

    screen_number: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True, nullable=True)
    pairing_code: Mapped[Optional[str]] = mapped_column(String(16), unique=True, index=True, nullable=True)
    organization_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    site_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("sites.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default="UNREGISTERED",
        nullable=False
    )  # UNREGISTERED, PAIRING, SYNCING, READY, PLAYING, OFFLINE, REVOKED
    orientation: Mapped[str] = mapped_column(String(20), default="LANDSCAPE", nullable=False)  # LANDSCAPE, PORTRAIT
    resolution: Mapped[str] = mapped_column(String(20), default="1920x1080", nullable=False)
    current_manifest_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    app_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    os_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    storage_free_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    organization: Mapped[Optional["Organization"]] = relationship("Organization", back_populates="screens")
    site: Mapped[Optional["Site"]] = relationship("Site", back_populates="screens")
    credential: Mapped[Optional["DeviceCredential"]] = relationship("DeviceCredential", back_populates="screen", uselist=False, cascade="all, delete-orphan")
    cursor: Mapped[Optional["DeviceCursor"]] = relationship("DeviceCursor", back_populates="screen", uselist=False, cascade="all, delete-orphan")


class EnrollmentChallenge(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "enrollment_challenges"
    __table_args__ = (Index("ix_enrollment_challenges_expiry", "status", "expires_at"),)

    pin: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)
    hw_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)  # PENDING, CLAIMED, EXPIRED
    organization_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True
    )
    screen_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("screens.id", ondelete="CASCADE"),
        nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DeviceCredential(Base, TimestampMixin):
    __tablename__ = "device_credentials"

    screen_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("screens.id", ondelete="CASCADE"),
        primary_key=True
    )
    key_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    screen: Mapped["Screen"] = relationship("Screen", back_populates="credential")


class DeviceCursor(Base):
    __tablename__ = "device_cursors"

    screen_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("screens.id", ondelete="CASCADE"),
        primary_key=True
    )
    epoch: Mapped[int] = mapped_column(Integer, default=1, primary_key=True)
    last_committed_sequence: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    screen: Mapped["Screen"] = relationship("Screen", back_populates="cursor")

