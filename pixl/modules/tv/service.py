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
from pixl.core.security import generate_pin
from pixl.core.exceptions import NotFoundError, ForbiddenError


async def get_next_screen_number(db: AsyncSession) -> int:
    res = await db.execute(select(func.max(Screen.screen_number)))
    curr = res.scalar() or 1000
    return curr + 1


async def get_next_campaign_number(db: AsyncSession) -> int:
    res = await db.execute(select(func.max(Campaign.campaign_number)))
    curr = res.scalar() or 2000
    return curr + 1


async def get_next_playlist_number(db: AsyncSession) -> int:
    res = await db.execute(select(func.max(Playlist.playlist_number)))
    curr = res.scalar() or 3000
    return curr + 1


async def get_next_media_number(db: AsyncSession) -> int:
    res = await db.execute(select(func.max(MediaAsset.media_number)))
    curr = res.scalar() or 5000
    return curr + 1


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
                Campaign.end_time > now
            )
            .order_by(Campaign.priority.desc())
        )
        campaign = camp_res.scalars().first()

        campaign_id = campaign.campaign_number if campaign and campaign.campaign_number else (2001 if campaign else None)
        playlist_id = 3001 if campaign else None

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
            .where(Playlist.id == campaign.playlist_id)
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
            if not media:
                continue
            media_id = media.media_number or (5000 + idx + 1)
            media_type = "video" if "video" in (media.mime_type or "") else "image"
            
            # Build public URL accessible by Android device
            download_url = f"{base_url.rstrip('/')}/media/{media.storage_key}"

            duration_sec = max(1, item.configured_duration_ms // 1000)

            media_items.append({
                "id": media_id,
                "filename": media.filename,
                "publicUrl": download_url,
                "type": media_type,
                "durationSeconds": duration_sec
            })

        campaign_id = campaign.campaign_number or 2001
        playlist_id = playlist.playlist_number or 3001

        return {
            "isPaired": True,
            "status": "ACTIVE",
            "campaign": {
                "id": campaign_id,
                "name": campaign.name,
                "layoutType": "SINGLE",
                "splitRows": 1,
                "splitCols": 1,
                "startAtMs": int(campaign.start_time.timestamp() * 1000),
                "endAtMs": int(campaign.end_time.timestamp() * 1000),
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
        if screen:
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

        saved = 0
        now = datetime.now(timezone.utc)
        for idx, entry in enumerate(logs):
            try:
                media_id = str(entry.get("mediaId", "unknown"))
                campaign_id = str(entry.get("campaignId", "unknown"))
                duration_sec = int(entry.get("durationSeconds", 10))
                status = str(entry.get("status", "COMPLETED"))

                # Timestamp might be epoch ms or ISO string
                ts = entry.get("timestamp")
                if isinstance(ts, (int, float)):
                    played_at = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
                else:
                    played_at = now

                event = PlaybackEvent(
                    screen_id=screen.id,
                    device_epoch=1,
                    local_sequence=saved + 1,
                    started_at=played_at,
                    completed_at=played_at + timedelta(seconds=duration_sec),
                    organization_id=screen.organization_id or "unassigned",
                    campaign_id=campaign_id,
                    media_id=media_id,
                    duration_ms=duration_sec * 1000,
                    outcome=status,
                    clock_quality="DEVICE_LOCAL"
                )
                db.add(event)
                saved += 1
            except Exception:
                continue

        await db.commit()
        return saved
