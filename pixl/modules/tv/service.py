from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from pixl.modules.screens.models import Screen, EnrollmentChallenge
from pixl.modules.campaigns.models import Campaign, ScreenAssignment
from pixl.modules.playlists.models import Playlist, PlaylistItem
from pixl.modules.media.models import MediaAsset
from pixl.modules.ingestion.models import PlaybackEvent
from pixl.core.database import ensure_utc
from pixl.core.storage import public_media_url
from pixl.core.identifiers import next_number
from pixl.core.security import generate_pin
from pixl.core.exceptions import NotFoundError, ForbiddenError, ConflictError


async def get_next_screen_number(db: AsyncSession) -> int:
    return await next_number(db, Screen, "screen_number", 1000)


async def get_next_campaign_number(db: AsyncSession) -> int:
    return await next_number(db, Campaign, "campaign_number", 2000)


async def get_next_playlist_number(db: AsyncSession) -> int:
    return await next_number(db, Playlist, "playlist_number", 3000)


async def get_next_media_number(db: AsyncSession) -> int:
    return await next_number(db, MediaAsset, "media_number", 5000)


class PixlTvService:
    @staticmethod
    async def register_screen(
        db: AsyncSession,
        name: str,
        location: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Implements POST /api/tv/register
        Used by native Android Player (PixlTvClient.registerScreen)
        """
        screen_number = await get_next_screen_number(db)
        pin = generate_pin(6)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=60)

        # Create unassigned Screen
        screen = Screen(
            name=name,
            screen_number=screen_number,
            pairing_code=pin,
            status="UNPAIRED",
            orientation="LANDSCAPE",
            resolution="1920x1080"
        )
        db.add(screen)
        await db.flush()

        # Create challenge associated with this screen
        challenge = EnrollmentChallenge(
            pin=pin,
            hw_fingerprint=f"tv_{name}",
            screen_id=screen.id,
            status="PENDING",
            expires_at=expires_at
        )
        db.add(challenge)
        await db.commit()

        return {
            "screenId": screen_number,
            "pairingCode": pin,
            "status": "UNPAIRED",
            "name": name
        }

    @staticmethod
    async def get_assignment(
        db: AsyncSession,
        code: str
    ) -> Dict[str, Any]:
        """
        Implements GET /api/tv/player/{code}/assignment
        Used by native Android Player (PixlTvClient.checkAssignment)
        """
        clean_code = code.strip().upper()
        res = await db.execute(select(Screen).where(Screen.pairing_code == clean_code))
        screen = res.scalar_one_or_none()

        if not screen or screen.status == "UNPAIRED" or not screen.organization_id:
            return {
                "screenId": screen.screen_number if screen and screen.screen_number else -1,
                "pairingCode": clean_code,
                "status": "UNPAIRED",
                "isPaired": False
            }

        # Screen is claimed/paired by an Agency
        # Find active campaign if any
        now = datetime.now(timezone.utc)
        camp_res = await db.execute(
            select(Campaign)
            .join(ScreenAssignment, ScreenAssignment.campaign_id == Campaign.id)
            .where(
                ScreenAssignment.screen_id == screen.id,
                Campaign.status == "PUBLISHED",
                Campaign.start_time <= now,
                Campaign.end_time > now
            )
            .order_by(Campaign.priority.desc())
        )
        campaign = camp_res.scalars().first()

        campaign_id = campaign.campaign_number if campaign else None
        playlist = await db.get(Playlist, campaign.playlist_id) if campaign and campaign.playlist_id else None
        playlist_id = playlist.playlist_number if playlist else None

        return {
            "screenId": screen.screen_number,
            "pairingCode": clean_code,
            "status": "PAIRED",
            "isPaired": True,
            "screenName": screen.name,
            "campaignId": campaign_id,
            "playlistId": playlist_id,
            "layoutType": "SINGLE"
        }

    @staticmethod
    async def sync_screen(
        db: AsyncSession,
        screen_number: int,
        pairing_code: str,
        base_url: str
    ) -> Dict[str, Any]:
        """
        Implements GET /api/tv/sync?screenId={id}&pairingCode={code}
        Used by native Android Player (PixlTvClient.syncScreen)
        """
        clean_code = pairing_code.strip().upper()
        res = await db.execute(
            select(Screen).where(
                Screen.screen_number == screen_number,
                Screen.pairing_code == clean_code
            )
        )
        screen = res.scalar_one_or_none()

        if not screen or screen.status == "UNPAIRED" or not screen.organization_id:
            return {
                "isPaired": False,
                "status": "UNPAIRED"
            }

        now = datetime.now(timezone.utc)
        screen.last_sync_at = now
        await db.commit()

        # Find active campaign
        camp_res = await db.execute(
            select(Campaign)
            .join(ScreenAssignment, ScreenAssignment.campaign_id == Campaign.id)
            .where(
                ScreenAssignment.screen_id == screen.id,
                Campaign.status == "PUBLISHED",
                Campaign.start_time <= now,
                Campaign.end_time > now
            )
            .order_by(Campaign.priority.desc())
        )
        campaign = camp_res.scalars().first()

        if not campaign or not campaign.playlist_id:
            return {
                "isPaired": True,
                "status": "PAIRED_NO_CAMPAIGN",
                "campaign": None
            }

        # Fetch playlist with media items
        pl_res = await db.execute(
            select(Playlist)
            .where(Playlist.id == campaign.playlist_id, Playlist.organization_id == screen.organization_id)
            .options(selectinload(Playlist.items).selectinload(PlaylistItem.media))
        )
        playlist = pl_res.scalar_one_or_none()

        if not playlist or not playlist.items:
            return {
                "isPaired": True,
                "status": "PAIRED_NO_CAMPAIGN",
                "campaign": None
            }

        media_items = []
        for idx, item in enumerate(playlist.items):
            media = item.media
            if not media or media.status != "READY" or media.organization_id != screen.organization_id:
                continue
            if media.media_number is None:
                raise ConflictError("Missing numeric media ID; run database migrations")
            media_id = media.media_number
            media_type = "video" if "video" in (media.mime_type or "") else "image"
            
            # Build public URL accessible by Android device
            download_url = public_media_url(media.storage_key, base_url)

            duration_sec = max(1, item.configured_duration_ms // 1000)

            media_items.append({
                "id": media_id,
                "filename": media.filename,
                "publicUrl": download_url,
                "type": media_type,
                "durationSeconds": duration_sec
            })

        if campaign.campaign_number is None or playlist.playlist_number is None:
            raise ConflictError("Missing numeric campaign/playlist ID; run database migrations")
        campaign_id = campaign.campaign_number
        playlist_id = playlist.playlist_number

        return {
            "isPaired": True,
            "status": "ACTIVE",
            "campaign": {
                "id": campaign_id,
                "name": campaign.name,
                "layoutType": "SINGLE",
                "splitRows": 1,
                "splitCols": 1,
                "startAtMs": int(ensure_utc(campaign.start_time).timestamp() * 1000),
                "endAtMs": int(ensure_utc(campaign.end_time).timestamp() * 1000),
                "playlist": {
                    "id": playlist_id,
                    "name": playlist.name,
                    "mediaItems": media_items
                }
            }
        }

    @staticmethod
    async def record_ping(
        db: AsyncSession,
        screen_number: int,
        pairing_code: str
    ) -> bool:
        """
        Implements POST /api/tv/ping
        Used by native Android Player (PixlTvClient.sendPing)
        """
        clean_code = pairing_code.strip().upper()
        res = await db.execute(
            select(Screen).where(
                Screen.screen_number == screen_number,
                Screen.pairing_code == clean_code
            )
        )
        screen = res.scalar_one_or_none()
        if screen and screen.organization_id and screen.status != "UNPAIRED":
            screen.last_heartbeat_at = datetime.now(timezone.utc)
            screen.status = "PLAYING"
            await db.commit()
            return True
        return False

    @staticmethod
    async def record_proof_of_play(
        db: AsyncSession,
        screen_number: int,
        logs: List[Dict[str, Any]]
    ) -> int:
        """
        Implements POST /api/tv/{screenId}/proof-of-play
        Used by native Android Player (PixlTvClient.uploadProofOfPlay)
        """
        res = await db.execute(select(Screen).where(Screen.screen_number == screen_number))
        screen = res.scalar_one_or_none()
        if not screen:
            return 0

        import hashlib
        import json
        from pydantic import BaseModel, Field, ValidationError
        from typing import Literal
        from pixl.core.exceptions import UnprocessableError
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        class Receipt(BaseModel):
            mediaId: int = Field(gt=0)
            campaignId: int = Field(gt=0)
            timestamp: int = Field(gt=0)
            durationSeconds: int = Field(ge=1, le=86400)
            status: Literal["COMPLETED", "INTERRUPTED", "DECODE_FAILED", "SKIPPED"] = "COMPLETED"

        saved = 0
        for entry in logs:
            try:
                receipt = Receipt.model_validate(entry)
                played_at = datetime.fromtimestamp(receipt.timestamp / 1000, tz=timezone.utc)
            except (ValidationError, ValueError, OverflowError, OSError) as exc:
                raise UnprocessableError("Invalid playback receipt") from exc
            campaign = await db.scalar(select(Campaign).join(ScreenAssignment).where(
                Campaign.campaign_number == receipt.campaignId,
                Campaign.organization_id == screen.organization_id,
                ScreenAssignment.screen_id == screen.id,
            ))
            media = await db.scalar(select(MediaAsset).where(
                MediaAsset.media_number == receipt.mediaId,
                MediaAsset.organization_id == screen.organization_id,
            ))
            if not campaign or not media:
                raise UnprocessableError("Receipt references unknown or unauthorized media/campaign")
            item = await db.scalar(select(PlaylistItem).where(
                PlaylistItem.playlist_id == campaign.playlist_id, PlaylistItem.media_id == media.id,
            ).limit(1))
            if not item:
                raise UnprocessableError("Receipt media is not part of the campaign")
            canonical = json.dumps(receipt.model_dump(), sort_keys=True).encode()
            sequence = int.from_bytes(hashlib.sha256(canonical).digest()[:8], "big") & ((1 << 63) - 1)
            insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
            statement = insert(PlaybackEvent).values(
                screen_id=screen.id, device_epoch=0, local_sequence=sequence,
                started_at=played_at, completed_at=played_at + timedelta(seconds=receipt.durationSeconds),
                organization_id=screen.organization_id, campaign_id=campaign.id, media_id=media.id,
                media_sha256=media.sha256, duration_ms=receipt.durationSeconds * 1000,
                outcome=receipt.status, clock_quality="DEVICE_LOCAL",
            ).on_conflict_do_nothing().returning(PlaybackEvent.screen_id)
            saved += int((await db.execute(statement)).scalar_one_or_none() is not None)
        await db.commit()
        return saved
