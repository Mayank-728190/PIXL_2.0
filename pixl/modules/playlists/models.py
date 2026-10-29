from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import String, Integer, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pixl.core.database import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Playlist(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "playlists"

    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_reusable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    items: Mapped[List["PlaylistItem"]] = relationship(
        "PlaylistItem",
        back_populates="playlist",
        order_by="PlaylistItem.sort_order",
        cascade="all, delete-orphan"
    )


class PlaylistItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "playlist_items"
    __table_args__ = (
        UniqueConstraint("playlist_id", "sort_order", name="uq_playlist_order"),
    )

    playlist_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("playlists.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    media_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("media_assets.id", ondelete="RESTRICT"),
        nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_mode: Mapped[str] = mapped_column(
        String(50),
        default="FULL_CLIP",
        nullable=False
    )  # FULL_CLIP, CUSTOM_DURATION, IMAGE_DEFAULT
    configured_duration_ms: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)

    playlist: Mapped["Playlist"] = relationship("Playlist", back_populates="items")
    media: Mapped["MediaAsset"] = relationship("MediaAsset")
