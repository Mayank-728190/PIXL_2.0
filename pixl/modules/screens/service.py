from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pixl.modules.screens.models import Screen, EnrollmentChallenge, DeviceCredential, DeviceCursor
from pixl.modules.organizations.models import Organization
from pixl.core.database import ensure_utc
from pixl.core.security import generate_pin, generate_secure_token, get_server_signing_keys
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
        org_result = await db.execute(select(Organization).where(Organization.id == organization_id))
        if not org_result.scalar_one_or_none():
            raise NotFoundError("Target organization not found")

        screen = Screen(
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
    async def create_enrollment_challenge(
        db: AsyncSession,
        hardware_fingerprint: str,
        model: str,
        app_version: str
    ) -> Tuple[EnrollmentChallenge, str]:
        # Generate 6-character alphanumeric PIN
        pin = generate_pin(6)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

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
        screen_id: str,
        new_name: Optional[str] = None,
        site_id: Optional[str] = None
    ) -> Screen:
        # 1. Fetch screen and ensure it is assigned to this Agency
        screen_result = await db.execute(select(Screen).where(Screen.id == screen_id))
        screen = screen_result.scalar_one_or_none()
        if not screen:
            raise NotFoundError("Assigned screen not found")

        if screen.organization_id != agency_id:
            raise ForbiddenError("Cannot claim a screen that is not assigned to your agency by Master")

        # 2. Fetch challenge by PIN
        challenge_result = await db.execute(
            select(EnrollmentChallenge).where(
                EnrollmentChallenge.pin == pin.upper(),
                EnrollmentChallenge.status == "PENDING"
            )
        )
        challenge = challenge_result.scalar_one_or_none()
        if not challenge:
            raise NotFoundError("Invalid or expired pairing PIN")

        if datetime.now(timezone.utc) > ensure_utc(challenge.expires_at):
            challenge.status = "EXPIRED"
            await db.commit()
            raise ConflictError("Pairing PIN has expired")

        # 3. Bind challenge to screen and mark CLAIMED atomically
        challenge.status = "CLAIMED"
        challenge.screen_id = screen.id
        challenge.organization_id = agency_id

        screen.status = "PAIRING"
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
            )
        )
        challenge = result.scalar_one_or_none()
        if not challenge or not challenge.screen_id:
            raise ForbiddenError("Challenge is not ready for exchange or has already been consumed")

        # 2. Fetch screen
        screen_result = await db.execute(select(Screen).where(Screen.id == challenge.screen_id))
        screen = screen_result.scalar_one_or_none()
        if not screen:
            raise NotFoundError("Associated screen not found")

        # 3. Create device token and credential
        device_token = f"dev_tok_{generate_secure_token(32)}"
        key_id = f"key_{generate_secure_token(16)}"

        # Check existing credential or replace
        cred_result = await db.execute(select(DeviceCredential).where(DeviceCredential.screen_id == screen.id))
        cred = cred_result.scalar_one_or_none()
        if cred:
            cred.key_id = key_id
            cred.public_key_pem = public_key_pem
            cred.token_hash = device_token
            cred.revoked_at = None
        else:
            cred = DeviceCredential(
                screen_id=screen.id,
                key_id=key_id,
                public_key_pem=public_key_pem,
                token_hash=device_token
            )
            db.add(cred)

        # 4. Initialize or reset Device Cursor
        cursor_result = await db.execute(
            select(DeviceCursor).where(DeviceCursor.screen_id == screen.id, DeviceCursor.epoch == 1)
        )
        cursor = cursor_result.scalar_one_or_none()
        if not cursor:
            cursor = DeviceCursor(
                screen_id=screen.id,
                epoch=1,
                last_committed_sequence=0
            )
            db.add(cursor)

        # 5. Mark challenge as EXCHANGED/EXPIRED to prevent replay
        challenge.status = "EXCHANGED"
        screen.status = "READY"

        # Load server public key for offline manifest verification
        _, server_pubkey = get_server_signing_keys()

        await db.commit()

        return screen, device_token, 1, server_pubkey

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
        if storage_free_mb:
            screen.storage_free_bytes = storage_free_mb * 1024 * 1024

        action = None
        if screen.current_manifest_version > manifest_version:
            action = "FETCH_MANIFEST"

        await db.commit()
        return now, screen.current_manifest_version, action
