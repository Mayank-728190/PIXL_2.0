from typing import List
from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pixl.core.database import get_db_session
from pixl.core.dependencies import require_role, require_tenant_context, get_authenticated_device
from pixl.core.exceptions import ForbiddenError, NotFoundError
from pixl.modules.screens.schemas import (
    MasterScreenCreateRequest, ScreenResponse,
    DeviceEnrollChallengeRequest, DeviceEnrollChallengeResponse,
    AgencyScreenClaimRequest, AgencyScreenClaimResponse,
    DeviceEnrollExchangeRequest, DeviceEnrollExchangeResponse,
    ScreenHeartbeatRequest, ScreenHeartbeatResponse
)
from pixl.modules.screens.service import ScreenService
from pixl.modules.screens.models import Screen

master_screens_router = APIRouter(prefix="/api/v1/master/screens", tags=["Master: Screen Fleet Management"])
agency_screens_router = APIRouter(prefix="/api/v1/agency/screens", tags=["Agency: Screen Management"])
device_router = APIRouter(prefix="/api/v1/device", tags=["Device: Hardware Engine"])


# Master endpoints
@master_screens_router.post("", response_model=ScreenResponse)
async def master_provision_screen_endpoint(
    req: MasterScreenCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    session: dict = Depends(require_role(["master_admin"], expected_audience="pixl:audience:master"))
):
    """Master provisions a screen and explicitly assigns it to an Agency."""
    screen = await ScreenService.master_provision_screen(
        db=db,
        name=req.name,
        organization_id=req.organization_id,
        site_id=req.site_id,
        orientation=req.orientation,
        resolution=req.resolution
    )
    return ScreenResponse.model_validate(screen)


@master_screens_router.get("", response_model=List[ScreenResponse])
async def master_list_screens_endpoint(
    db: AsyncSession = Depends(get_db_session),
    session: dict = Depends(require_role(["master_admin"], expected_audience="pixl:audience:master"))
):
    """Master views global fleet across all agencies."""
    result = await db.execute(select(Screen).order_by(Screen.created_at.desc()))
    return [ScreenResponse.model_validate(s) for s in result.scalars().all()]


# Agency endpoints
@agency_screens_router.get("", response_model=List[ScreenResponse])
async def agency_list_screens(
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Agency views ONLY screens assigned to its own organization."""
    result = await db.execute(select(Screen).where(Screen.organization_id == org_id).order_by(Screen.created_at.desc()))
    return [ScreenResponse.model_validate(s) for s in result.scalars().all()]


@agency_screens_router.get("/{screen_id}", response_model=ScreenResponse)
async def agency_get_screen(
    screen_id: str,
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Agency views a single screen; returns 404 if screen belongs to another agency."""
    result = await db.execute(
        select(Screen).where(Screen.id == screen_id, Screen.organization_id == org_id)
    )
    screen = result.scalar_one_or_none()
    if not screen:
        raise NotFoundError("Screen not found within your agency fleet")
    return ScreenResponse.model_validate(screen)


@agency_screens_router.post("/claim", response_model=AgencyScreenClaimResponse)
async def agency_claim_screen_endpoint(
    req: AgencyScreenClaimRequest,
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin"], expected_audience="pixl:audience:agency"))
):
    """Agency finishes pairing an unassigned device PIN against its Master-assigned screen."""
    screen = await ScreenService.agency_claim_screen(
        db=db,
        agency_id=org_id,
        pin=req.pin,
        screen_id=req.screen_id,
        new_name=req.name,
        site_id=req.site_id
    )
    return AgencyScreenClaimResponse(
        status="CLAIMED",
        screen_id=screen.id,
        organization_id=org_id,
        message=f"Screen '{screen.name}' paired successfully"
    )


# Device Hardware endpoints
@device_router.post("/enroll/challenge", response_model=DeviceEnrollChallengeResponse)
async def device_request_challenge(
    req: DeviceEnrollChallengeRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """Device requests a short-lived 6-character pairing PIN to display on screen."""
    challenge, pin = await ScreenService.create_enrollment_challenge(
        db=db,
        hardware_fingerprint=req.hardware_fingerprint,
        model=req.model,
        app_version=req.app_version
    )
    return DeviceEnrollChallengeResponse(
        challenge_id=challenge.id,
        pin=pin,
        expires_at=challenge.expires_at,
        poll_interval_seconds=3
    )


@device_router.post("/enroll/exchange", response_model=DeviceEnrollExchangeResponse)
async def device_exchange_credentials(
    req: DeviceEnrollExchangeRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """Device exchanges claimed challenge for persistent scoped device credentials."""
    screen, token, epoch, server_pubkey = await ScreenService.exchange_device_credentials(
        db=db,
        challenge_id=req.challenge_id,
        public_key_pem=req.public_key_pem
    )
    return DeviceEnrollExchangeResponse(
        device_id=screen.id,
        device_token=token,
        epoch=epoch,
        server_public_key_pem=server_pubkey,
        ws_endpoint="wss://api.pixl.local/ws/v1/device"
    )


@device_router.post("/heartbeat", response_model=ScreenHeartbeatResponse)
async def device_heartbeat_endpoint(
    req: ScreenHeartbeatRequest,
    credential=Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_db_session)
):
    """Authenticated screen sends heartbeat and telemetry."""
    if credential.screen_id != req.device_id:
        raise ForbiddenError("Device token does not match claimed device_id")

    server_time, latest_ver, action = await ScreenService.process_heartbeat(
        db=db,
        screen_id=req.device_id,
        manifest_version=req.manifest_version,
        playback_state=req.playback_state,
        storage_free_mb=req.storage_free_mb
    )
    return ScreenHeartbeatResponse(
        server_time=server_time,
        latest_manifest_version=latest_ver,
        action_required=action
    )

