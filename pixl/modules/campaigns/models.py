from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pixl.core.database import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Campaign(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "campaigns"
    __table_args__ = (Index("ix_campaigns_expiry", "status", "end_time"),)

    campaign_number: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True, nullable=True)
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
    playlist_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("playlists.id", ondelete="SET NULL"),
        nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default="DRAFT",
        nullable=False
    )  # DRAFT, APPROVED, PUBLISHED, ARCHIVED
    priority: Mapped[int] = mapped_column(
        Integer,
        default=100,
        nullable=False
    )  # 1000=Emergency, 500=Sponsorship, 100=Commercial, 10=Filler
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    assignments: Mapped[List["ScreenAssignment"]] = relationship(
        "ScreenAssignment",
        back_populates="campaign",
        cascade="all, delete-orphan"
    )
    versions: Mapped[List["CampaignVersion"]] = relationship(
        "CampaignVersion",
        back_populates="campaign",
        cascade="all, delete-orphan"
    )
    playlist: Mapped[Optional["Playlist"]] = relationship("Playlist")


class ScreenAssignment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "screen_assignments"

    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    screen_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("screens.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="assignments")
    screen: Mapped["Screen"] = relationship("Screen")


class CampaignVersion(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "campaign_versions"

    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    compiled_manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="versions")

