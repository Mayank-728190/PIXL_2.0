from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pixl.modules.playlists.models import Playlist, PlaylistItem
from pixl.modules.media.models import MediaAsset
from pixl.modules.playlists.schemas import PlaylistItemCreate
from pixl.core.exceptions import ForbiddenError, NotFoundError, ConflictError


class PlaylistService:
    @staticmethod
    async def create_playlist(
        db: AsyncSession,
        organization_id: str,
        name: str,
        is_reusable: bool = True,
        items: Optional[List[PlaylistItemCreate]] = None
    ) -> Playlist:
        # 1. Create playlist
        playlist = Playlist(
            organization_id=organization_id,
            name=name,
            is_reusable=is_reusable
        )
        db.add(playlist)
        await db.flush()

        # 2. Add and validate items
        if items:
            # Check sort_order uniqueness
            orders = [item.sort_order for item in items]
            if len(orders) != len(set(orders)):
                raise ConflictError("Playlist items have duplicate sort_order values")

            for item_data in items:
                # Verify cross-tenant boundary: media must belong to organization_id!
                media_res = await db.execute(
                    select(MediaAsset).where(MediaAsset.id == item_data.media_id)
                )
                media = media_res.scalar_one_or_none()
                if not media:
                    raise NotFoundError(f"Referenced media '{item_data.media_id}' not found")
                
                if media.organization_id != organization_id:
                    raise ForbiddenError(
                        f"Cross-tenant violation: Media '{item_data.media_id}' belongs to another agency"
                    )

                playlist_item = PlaylistItem(
                    playlist_id=playlist.id,
                    media_id=item_data.media_id,
                    sort_order=item_data.sort_order,
                    duration_mode=item_data.duration_mode,
                    configured_duration_ms=item_data.configured_duration_ms
                )
                db.add(playlist_item)

        await db.commit()
        await db.refresh(playlist)
        
        # Load items
        res = await db.execute(
            select(Playlist)
            .where(Playlist.id == playlist.id)
            .options(selectinload(Playlist.items))
        )
        return res.scalar_one()

    @staticmethod
    async def list_playlists(db: AsyncSession, organization_id: str) -> List[Playlist]:
        res = await db.execute(
            select(Playlist)
            .where(Playlist.organization_id == organization_id)
            .options(selectinload(Playlist.items))
            .order_by(Playlist.created_at.desc())
        )
        return list(res.scalars().all())

    @staticmethod
    async def get_playlist(db: AsyncSession, organization_id: str, playlist_id: str) -> Playlist:
        res = await db.execute(
            select(Playlist)
            .where(Playlist.id == playlist_id, Playlist.organization_id == organization_id)
            .options(selectinload(Playlist.items))
        )
        pl = res.scalar_one_or_none()
        if not pl:
            raise NotFoundError("Playlist not found in your agency library")
        return pl
