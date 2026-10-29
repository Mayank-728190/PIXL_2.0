from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import json
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pixl.modules.campaigns.models import Campaign, ScreenAssignment, CampaignVersion
from pixl.modules.campaigns.schemas import CampaignCreateRequest
from pixl.modules.playlists.models import Playlist, PlaylistItem
from pixl.modules.media.models import MediaAsset
from pixl.modules.organizations.models import Brand
from pixl.core.tenancy import require_owned_reference
from pixl.modules.screens.models import Screen
from pixl.core.security import get_server_signing_keys, sign_manifest_payload
from pixl.core.config import settings
from pixl.core.identifiers import next_number
from pixl.core.storage import public_media_url
from pixl.core.database import ensure_utc
from pixl.core.exceptions import NotFoundError, ForbiddenError, ConflictError


class CampaignService:
    @staticmethod
    async def create_campaign(
        db: AsyncSession,
        organization_id: str,
        req: CampaignCreateRequest
    ) -> Campaign:
        # 1. Validate times
        start_time = ensure_utc(req.start_time)
        end_time = ensure_utc(req.end_time)
        if start_time >= end_time:
            raise ConflictError("start_time must precede end_time")
        if len(req.screen_ids) != len(set(req.screen_ids)):
            raise ConflictError("Duplicate screen assignments are not allowed")

        await require_owned_reference(db, Brand, req.brand_id, organization_id)

        # 2. Validate playlist ownership
        pl_res = await db.execute(
            select(Playlist).where(Playlist.id == req.playlist_id, Playlist.organization_id == organization_id)
        )
        playlist = pl_res.scalar_one_or_none()
        if not playlist:
            raise ForbiddenError("Referenced playlist does not belong to your agency")

        # 3. Validate screen ownership
        for s_id in req.screen_ids:
            s_res = await db.execute(
                select(Screen).where(Screen.id == s_id, Screen.organization_id == organization_id)
            )
            screen = s_res.scalar_one_or_none()
            if not screen:
                raise ForbiddenError(f"Screen '{s_id}' does not belong to your agency")

        # 4. Create Campaign
        campaign = Campaign(
            campaign_number=await next_number(db, Campaign, "campaign_number", 2000),
            organization_id=organization_id,
            brand_id=req.brand_id,
            playlist_id=req.playlist_id,
            name=req.name,
            status="DRAFT",
            priority=req.priority,
            start_time=start_time,
            end_time=end_time,
            current_version=1
        )
        db.add(campaign)
        await db.flush()

        # 5. Create screen assignments
        for s_id in req.screen_ids:
            assignment = ScreenAssignment(
                campaign_id=campaign.id,
                screen_id=s_id
            )
            db.add(assignment)

        await db.commit()

        res = await db.execute(
            select(Campaign)
            .where(Campaign.id == campaign.id)
            .options(selectinload(Campaign.assignments))
        )
        return res.scalar_one()

    @staticmethod
    async def publish_campaign(
        db: AsyncSession,
        organization_id: str,
        campaign_id: str
    ) -> Campaign:
        res = await db.execute(
            select(Campaign)
            .where(Campaign.id == campaign_id, Campaign.organization_id == organization_id)
            .options(selectinload(Campaign.assignments))
        )
        campaign = res.scalar_one_or_none()
        if not campaign:
            raise NotFoundError("Campaign not found")

        if ensure_utc(campaign.end_time) <= datetime.now(timezone.utc):
            raise ConflictError("Cannot publish an expired campaign")
        playlist = await db.scalar(select(Playlist).where(
            Playlist.id == campaign.playlist_id, Playlist.organization_id == organization_id
        ).options(selectinload(Playlist.items).selectinload(PlaylistItem.media)))
        if not playlist or not playlist.items or not campaign.assignments:
            raise ConflictError("Publishing requires media and target screens")
        if any(not item.media or item.media.status != "READY"
               or item.media.organization_id != organization_id for item in playlist.items):
            raise ConflictError("Publishing requires READY media owned by your agency")
        for assignment in campaign.assignments:
            await require_owned_reference(db, Screen, assignment.screen_id, organization_id)

        campaign.status = "PUBLISHED"
        campaign.current_version += 1

        # Increment target screens manifest versions so they trigger refresh
        for assignment in campaign.assignments:
            s_res = await db.execute(select(Screen).where(Screen.id == assignment.screen_id))
            screen = s_res.scalar_one_or_none()
            if screen:
                screen.current_manifest_version += 1

        await db.commit()
        return campaign

    @staticmethod
    async def generate_signed_screen_manifest(
        db: AsyncSession,
        screen_id: str
    ) -> Dict[str, Any]:
        s_res = await db.execute(select(Screen).where(Screen.id == screen_id))
        screen = s_res.scalar_one_or_none()
        if not screen:
            raise NotFoundError("Screen not found")

        now = datetime.now(timezone.utc)
        valid_until = now + timedelta(hours=72)

        # Query active campaigns targeting this screen
        query = (
            select(Campaign)
            .join(ScreenAssignment, ScreenAssignment.campaign_id == Campaign.id)
            .where(
                ScreenAssignment.screen_id == screen_id,
                Campaign.organization_id == screen.organization_id,
                Campaign.status == "PUBLISHED",
                Campaign.end_time > now
            )
            .order_by(Campaign.priority.desc(), Campaign.created_at.desc())
        )
        camp_res = await db.execute(query)
        campaigns = camp_res.scalars().all()

        schedule_items = []
        assets_map = {}

        for camp in campaigns:
            if not camp.playlist_id:
                continue
            pl_res = await db.execute(
                select(Playlist)
                .where(Playlist.id == camp.playlist_id, Playlist.organization_id == screen.organization_id)
                .options(selectinload(Playlist.items).selectinload(PlaylistItem.media))
            )
            pl = pl_res.scalar_one_or_none()
            if not pl:
                continue

            playlist_entries = []
            for item in pl.items:
                media = item.media
                if media and media.status == "READY" and media.organization_id == screen.organization_id:
                    assets_map[media.id] = {
                        "id": media.id,
                        "sha256": media.sha256,
                        "filename": media.filename,
                        "size_bytes": media.size_bytes,
                        "download_url": public_media_url(media.storage_key)
                    }
                    playlist_entries.append({
                        "asset_id": media.id,
                        "duration_mode": item.duration_mode,
                        "configured_duration_ms": item.configured_duration_ms
                    })

            schedule_items.append({
                "campaign_id": camp.id,
                "priority": camp.priority,
                "start_time": ensure_utc(camp.start_time).isoformat(),
                "end_time": ensure_utc(camp.end_time).isoformat(),
                "playlist": playlist_entries
            })

        # Manifest JSON payload
        manifest_payload = {
            "manifest_id": f"man_{uuid.uuid4()}",
            "screen_id": screen.id,
            "version": screen.current_manifest_version,
            "valid_from": now.isoformat(),
            "valid_until": valid_until.isoformat(),
            "timezone": "UTC",
            "assets": list(assets_map.values()),
            "schedule": schedule_items,
            "fallback_playlist": [
                {
                    "asset_id": "fallback_standby_logo",
                    "duration_mode": "IMAGE_DEFAULT",
                    "configured_duration_ms": 10000
                }
            ]
        }

        # Sign manifest payload with ED25519
        priv_key, _ = get_server_signing_keys()
        signature = sign_manifest_payload(manifest_payload, priv_key)

        return {
            "signature": signature,
            "payload": manifest_payload
        }
