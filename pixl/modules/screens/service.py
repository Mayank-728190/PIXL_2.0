from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload

from pixl.modules.screens.models import Screen, EnrollmentChallenge, DeviceCredential, DeviceCursor
from pixl.modules.organizations.models import Organization, Site
from pixl.core.tenancy import require_owned_reference
from pixl.modules.campaigns.models import Campaign, ScreenAssignment
from pixl.modules.playlists.models import Playlist, PlaylistItem
from pixl.modules.media.models import MediaAsset
from pixl.core.config import settings
from pixl.core.identifiers import next_number
from pixl.core.database import ensure_utc
from pixl.core.security import generate_pin, generate_secure_token, get_server_signing_keys, hash_device_token
from pixl.core.exceptions import ConflictError, NotFoundError, ForbiddenError


class ScreenService:
    @staticmethod
    async def master_provision_screen(
        db: AsyncSession,
        name: str,
        organization_id: str,
        site_id: Optional[str] = None,
        orientation: str = "LANDSCAPE",
        resolution: str = "1920x1080"
    ) -> Screen:
        # Verify organization exists
        org = await db.scalar(select(Organization).where(
            Organization.id == organization_id).with_for_update())
        if not org or org.status != "ACTIVE":
            raise NotFoundError("Active target organization not found")
        count = await db.scalar(select(func.count()).select_from(Screen).where(
            Screen.organization_id == organization_id))
        if count >= org.max_screens:
            raise ConflictError("Agency screen limit reached")

        await require_owned_reference(db, Site, site_id, organization_id)
        screen = Screen(
            screen_number=await next_number(db, Screen, "screen_number", 1000),
            name=name,
            organization_id=organization_id,
            site_id=site_id,
            orientation=orientation,
            resolution=resolution,
            status="UNREGISTERED"
        )
        db.add(screen)
        await db.commit()
        return screen

    @staticmethod
    async def assign_screen(db: AsyncSession, screen_id: str, organization_id: str,
                            site_id: Optional[str] = None) -> Screen:
        from sqlalchemy import delete, update
        from pixl.modules.auth.models import AuditEvent
        org = await db.scalar(select(Organization).where(
            Organization.id == organization_id).with_for_update())
        if not org or org.status != "ACTIVE":
            raise NotFoundError("Active target agency not found")
        count = await db.scalar(select(func.count()).select_from(Screen).where(
            Screen.organization_id == organization_id, Screen.id != screen_id))
        if count >= org.max_screens:
            raise ConflictError("Agency screen limit reached")
        await require_owned_reference(db, Site, site_id, organization_id)
        screen = await db.scalar(select(Screen).where(Screen.id == screen_id).with_for_update())
        if not screen:
            raise NotFoundError("Screen not found")
        if screen.organization_id != organization_id:
            await db.execute(delete(ScreenAssignment).where(ScreenAssignment.screen_id == screen.id))
            await db.execute(update(DeviceCredential).where(DeviceCredential.screen_id == screen.id)
                             .values(revoked_at=datetime.now(timezone.utc)))
            if screen.organization_id:
                screen.pairing_code = None
                screen.status = "UNREGISTERED"
                await db.execute(update(EnrollmentChallenge).where(
                    EnrollmentChallenge.screen_id == screen.id).values(status="EXPIRED"))
            screen.organization_id = organization_id
            await db.execute(update(Screen).where(Screen.id == screen.id).values(
                current_manifest_version=Screen.current_manifest_version + 1))
            db.add(AuditEvent(organization_id=organization_id, action="SCREEN_ASSIGNED",
                              resource_type="SCREEN", resource_id=screen.id))
        screen.site_id = site_id
        await db.commit()
        return screen

    @staticmethod
    async def create_enrollment_challenge(
        db: AsyncSession,
        hardware_fingerprint: str,
        model: str,
        app_version: str
    ) -> Tuple[EnrollmentChallenge, str]:
        # Generate 6-character alphanumeric PIN
        pin = generate_pin(6)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.ENROLLMENT_PIN_TTL_SECONDS)

        challenge = EnrollmentChallenge(
            pin=pin,
            hw_fingerprint=hardware_fingerprint,
            status="PENDING",
            expires_at=expires_at
        )
        db.add(challenge)
        await db.commit()
        return challenge, pin

    @staticmethod
    async def agency_claim_screen(
        db: AsyncSession,
        agency_id: str,
        pin: str,
        screen_id: Optional[str] = None,
        new_name: Optional[str] = None,
        site_id: Optional[str] = None
    ) -> Screen:
        clean_pin = pin.strip().upper()

        # 1. Fetch challenge by PIN
        challenge_result = await db.execute(
            select(EnrollmentChallenge).where(
                EnrollmentChallenge.pin == clean_pin,
                EnrollmentChallenge.status == "PENDING"
            ).with_for_update()
        )
        challenge = challenge_result.scalar_one_or_none()
        if not challenge:
            raise NotFoundError("Invalid or expired pairing PIN")

        if datetime.now(timezone.utc) > ensure_utc(challenge.expires_at):
            challenge.status = "EXPIRED"
            await db.commit()
            raise ConflictError("Pairing PIN has expired")

        if challenge.screen_id and screen_id and challenge.screen_id != screen_id:
            raise ForbiddenError("Pairing challenge belongs to a different screen")

        # 2. Determine target screen
        target_screen_id = screen_id or challenge.screen_id
        if not target_screen_id:
            raise NotFoundError("No screen associated with this challenge")

        screen_result = await db.execute(select(Screen).where(Screen.id == target_screen_id))
        screen = screen_result.scalar_one_or_none()
        if not screen:
            raise NotFoundError("Assigned screen not found")

        if screen.organization_id and screen.organization_id != agency_id:
            raise ForbiddenError("Cannot claim a screen that is not assigned to your agency by Master")

        await require_owned_reference(db, Site, site_id, agency_id)

        if not screen.organization_id and (settings.ENVIRONMENT == "production" or not settings.ALLOW_LEGACY_TV):
            raise ForbiddenError("Only Master may assign an unassigned screen to an agency")

        # Compare-and-set also protects SQLite, where FOR UPDATE is ignored.
        from sqlalchemy import update
        claimed = await db.execute(update(EnrollmentChallenge).where(
            EnrollmentChallenge.id == challenge.id, EnrollmentChallenge.status == "PENDING"
        ).values(status="CLAIMED"))
        if claimed.rowcount != 1:
            raise ConflictError("Pairing challenge has already been claimed")
        challenge.screen_id = screen.id
        challenge.organization_id = agency_id

        screen.organization_id = agency_id
        screen.status = "PAIRED"
        screen.pairing_code = clean_pin
        if new_name:
            screen.name = new_name
        if site_id:
            screen.site_id = site_id

        await db.commit()
        return screen

    @staticmethod
    async def exchange_device_credentials(
        db: AsyncSession,
        challenge_id: str,
        public_key_pem: str
    ) -> Tuple[Screen, str, int, str]:
        # 1. Find challenge
        result = await db.execute(
            select(EnrollmentChallenge).where(
                EnrollmentChallenge.id == challenge_id,
                EnrollmentChallenge.status == "CLAIMED"
            ).with_for_update()
        )
        challenge = result.scalar_one_or_none()
        if not challenge or not challenge.screen_id:
            raise ForbiddenError("Challenge is not ready for exchange or has already been consumed")

        if datetime.now(timezone.utc) > ensure_utc(challenge.expires_at):
            challenge.status = "EXPIRED"
            await db.commit()
            raise ConflictError("Pairing challenge has expired")

        # 2. Fetch screen
        screen_result = await db.execute(select(Screen).where(Screen.id == challenge.screen_id))
        screen = screen_result.scalar_one_or_none()
        if not screen:
            raise NotFoundError("Associated screen not found")

        from sqlalchemy import update
        consumed = await db.execute(update(EnrollmentChallenge).where(
            EnrollmentChallenge.id == challenge.id, EnrollmentChallenge.status == "CLAIMED"
        ).values(status="EXCHANGING"))
        if consumed.rowcount != 1:
            raise ConflictError("Pairing challenge is already being exchanged")

        # 3. Create device token and credential
        device_token = f"dev_tok_{generate_secure_token(32)}"
        key_id = f"key_{generate_secure_token(16)}"

        # Check existing credential or replace
        cred_result = await db.execute(select(DeviceCredential).where(DeviceCredential.screen_id == screen.id))
        cred = cred_result.scalar_one_or_none()
        if cred:
            cred.key_id = key_id
            cred.public_key_pem = public_key_pem
            cred.token_hash = hash_device_token(device_token)
            cred.revoked_at = None
        else:
            cred = DeviceCredential(
                screen_id=screen.id,
                key_id=key_id,
                public_key_pem=public_key_pem,
                token_hash=hash_device_token(device_token)
            )
            db.add(cred)

        # Each credential exchange creates a new sequence epoch; old receipts
        # cannot be replayed under a replacement credential.
        previous_epoch = await db.scalar(select(func.max(DeviceCursor.epoch)).where(
            DeviceCursor.screen_id == screen.id))
        epoch = (previous_epoch or 0) + 1
        db.add(DeviceCursor(screen_id=screen.id, epoch=epoch, last_committed_sequence=0))

        # 5. Mark challenge as EXCHANGED/EXPIRED to prevent replay
        challenge.status = "EXCHANGED"
        screen.status = "READY"

        # Load server public key for offline manifest verification
        _, server_pubkey = get_server_signing_keys()

        await db.commit()

        return screen, device_token, epoch, server_pubkey

    @staticmethod
    async def process_heartbeat(
        db: AsyncSession,
        screen_id: str,
        manifest_version: int,
        playback_state: str,
        storage_free_mb: Optional[int] = None
    ) -> Tuple[datetime, int, Optional[str]]:
        result = await db.execute(select(Screen).where(Screen.id == screen_id))
        screen = result.scalar_one_or_none()
        if not screen:
            raise NotFoundError("Screen not found")

        now = datetime.now(timezone.utc)
        screen.last_heartbeat_at = now
        screen.status = "PLAYING" if playback_state == "PLAYING" else playback_state
        if storage_free_mb is not None:
            screen.storage_free_bytes = storage_free_mb * 1024 * 1024

        action = None
        if screen.current_manifest_version > manifest_version:
            action = "FETCH_MANIFEST"

        await db.commit()
        return now, screen.current_manifest_version, action

    @staticmethod
    async def play_ad_on_screen(
        db: AsyncSession,
        screen_id: str,
        organization_id: Optional[str],
        media_ids: List[str],
        duration_seconds: int = 10,
        name: Optional[str] = "Live Ad Broadcast",
        priority: int = 200,
        duration_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Allows an admin to instantly trigger and publish an ad (or set of ads) to a screen.
        High priority (default 200) preempts standard background playlists (priority 100).
        """
        query = select(Screen)
        if screen_id.isdigit():
            query = query.where(Screen.screen_number == int(screen_id))
        else:
            query = query.where(Screen.id == screen_id)

        if organization_id:
            query = query.where(Screen.organization_id == organization_id)

        res = await db.execute(query)
        screen = res.scalar_one_or_none()
        if not screen:
            raise NotFoundError("Screen not found or not accessible within your organization")

        if not screen.organization_id:
            raise ConflictError("A screen must be assigned to an agency before broadcasting")
        if screen.screen_number is None:
            screen.screen_number = await next_number(db, Screen, "screen_number", 1000)

        if not media_ids:
            raise ConflictError("At least one media_id must be provided to play an ad")

        # Fetch and validate all media assets
        media_assets = []
        for mid in media_ids:
            m_query = select(MediaAsset)
            if str(mid).isdigit():
                m_query = m_query.where(MediaAsset.media_number == int(mid))
            else:
                m_query = m_query.where(MediaAsset.id == str(mid))

            m_query = m_query.where(MediaAsset.organization_id == screen.organization_id)

            m_res = await db.execute(m_query)
            m_asset = m_res.scalar_one_or_none()
            if not m_asset:
                raise NotFoundError(f"Media asset '{mid}' not found or not accessible")
            if m_asset.status != "READY":
                raise ConflictError("Only READY media can be broadcast")
            media_assets.append(m_asset)

        # 1. Create a dedicated playlist for this ad broadcast
        p_num = await next_number(db, Playlist, "playlist_number", 3000)
        playlist = Playlist(
            playlist_number=p_num,
            organization_id=screen.organization_id or organization_id,
            name=f"Ad: {name or 'Broadcast'}",
            is_reusable=False
        )
        db.add(playlist)
        await db.flush()

        # Add media items to playlist
        for idx, m_asset in enumerate(media_assets):
            p_item = PlaylistItem(
                playlist_id=playlist.id,
                media_id=m_asset.id,
                sort_order=idx,
                duration_mode="CUSTOM_DURATION",
                configured_duration_ms=max(1, duration_seconds) * 1000
            )
            db.add(p_item)
        await db.flush()

        # 2. Create the ad campaign
        now = datetime.now(timezone.utc)
        c_num = await next_number(db, Campaign, "campaign_number", 2000)
        campaign = Campaign(
            campaign_number=c_num,
            organization_id=screen.organization_id or organization_id,
            name=name or "Live Ad Broadcast",
            playlist_id=playlist.id,
            priority=priority,
            status="PUBLISHED",
            start_time=now,
            end_time=now + timedelta(hours=duration_hours),
            current_version=1
        )
        db.add(campaign)
        await db.flush()

        # 3. Assign campaign to screen
        assignment = ScreenAssignment(
            campaign_id=campaign.id,
            screen_id=screen.id
        )
        db.add(assignment)

        # 4. Invalidate screen manifest version so player downloads the new ad
        await db.execute(update(Screen).where(Screen.id == screen.id).values(
            current_manifest_version=Screen.current_manifest_version + 1))
        await db.commit()

        return {
            "screen_id": screen.id,
            "screen_number": screen.screen_number,
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "priority": campaign.priority,
            "status": "PLAYING",
            "manifest_version": screen.current_manifest_version,
            "media_count": len(media_assets),
            "media_items": [
                {
                    "id": m.media_number or 5000,
                    "uuid": m.id,
                    "filename": m.filename,
                    "type": "video" if "video" in (m.mime_type or "") else "image"
                }
                for m in media_assets
            ],
            "message": "Ad broadcast published. Screen will display the ad on its next sync cycle."
        }

    @staticmethod
    async def get_current_playback(
        db: AsyncSession,
        screen_id: str,
        organization_id: Optional[str]
    ) -> Dict[str, Any]:
        """Returns the current playback state and active campaign for a screen."""
        query = select(Screen)
        if screen_id.isdigit():
            query = query.where(Screen.screen_number == int(screen_id))
        else:
            query = query.where(Screen.id == screen_id)

        if organization_id:
            query = query.where(Screen.organization_id == organization_id)

        res = await db.execute(query)
        screen = res.scalar_one_or_none()
        if not screen:
            raise NotFoundError("Screen not found or not accessible within your organization")

        now = datetime.now(timezone.utc)
        is_online = False
        if screen.last_heartbeat_at and (now - ensure_utc(screen.last_heartbeat_at)).total_seconds() <= settings.DEVICE_OFFLINE_THRESHOLD_SECONDS:
            is_online = True
        elif screen.last_sync_at and (now - ensure_utc(screen.last_sync_at)).total_seconds() <= settings.DEVICE_OFFLINE_THRESHOLD_SECONDS:
            is_online = True

        # Find active published campaign
        camp_res = await db.execute(
            select(Campaign)
            .join(ScreenAssignment, ScreenAssignment.campaign_id == Campaign.id)
            .where(
                ScreenAssignment.screen_id == screen.id,
                Campaign.status == "PUBLISHED",
                Campaign.organization_id == screen.organization_id,
                Campaign.start_time <= now,
                Campaign.end_time > now
            )
            .order_by(Campaign.priority.desc(), Campaign.created_at.desc(), Campaign.id.asc())
        )
        campaign = camp_res.scalars().first()

        campaign_info = None
        if campaign and campaign.playlist_id:
            pl_res = await db.execute(
                select(Playlist)
                .where(Playlist.id == campaign.playlist_id)
                .options(selectinload(Playlist.items).selectinload(PlaylistItem.media))
            )
            pl = pl_res.scalar_one_or_none()
            if pl:
                campaign_info = {
                    "campaign_id": campaign.id,
                    "campaign_number": campaign.campaign_number,
                    "name": campaign.name,
                    "priority": campaign.priority,
                    "start_time": campaign.start_time,
                    "end_time": campaign.end_time,
                    "playlist_name": pl.name,
                    "media_items": [
                        {
                            "media_id": item.media.media_number if item.media else None,
                            "filename": item.media.filename if item.media else "unknown",
                            "type": "video" if item.media and "video" in (item.media.mime_type or "") else "image",
                            "duration_seconds": item.configured_duration_ms // 1000
                        }
                        for item in pl.items
                    ]
                }

        return {
            "screen_id": screen.id,
            "screen_number": screen.screen_number,
            "screen_name": screen.name,
            "status": screen.status,
            "is_online": is_online,
            "manifest_version": screen.current_manifest_version,
            "last_sync_at": screen.last_sync_at,
            "current_campaign": campaign_info
        }

    @staticmethod
    async def stop_ad_on_screen(
        db: AsyncSession,
        screen_id: str,
        organization_id: Optional[str]
    ) -> Dict[str, Any]:
        """Stops the current high-priority ad campaign on a screen, reverting to standard content."""
        query = select(Screen)
        if screen_id.isdigit():
            query = query.where(Screen.screen_number == int(screen_id))
        else:
            query = query.where(Screen.id == screen_id)

        if organization_id:
            query = query.where(Screen.organization_id == organization_id)

        res = await db.execute(query)
        screen = res.scalar_one_or_none()
        if not screen:
            raise NotFoundError("Screen not found")

        now = datetime.now(timezone.utc)
        camp_res = await db.execute(
            select(Campaign)
            .join(ScreenAssignment, ScreenAssignment.campaign_id == Campaign.id)
            .where(
                ScreenAssignment.screen_id == screen.id,
                Campaign.status == "PUBLISHED",
                Campaign.organization_id == screen.organization_id,
                Campaign.start_time <= now,
                Campaign.end_time > now
            )
            .order_by(Campaign.priority.desc(), Campaign.created_at.desc(), Campaign.id.asc())
        )
        campaign = camp_res.scalars().first()
        if campaign:
            # Stop only this screen; other assignments remain active.
            from sqlalchemy import delete
            await db.execute(delete(ScreenAssignment).where(
                ScreenAssignment.campaign_id == campaign.id,
                ScreenAssignment.screen_id == screen.id,
            ))
            await db.execute(update(Screen).where(Screen.id == screen.id).values(
                current_manifest_version=Screen.current_manifest_version + 1))
            await db.commit()
            return {"status": "STOPPED", "campaign_id": campaign.id, "message": "Ad playback stopped."}

        return {"status": "NO_ACTIVE_AD", "message": "No active ad was scheduled."}

