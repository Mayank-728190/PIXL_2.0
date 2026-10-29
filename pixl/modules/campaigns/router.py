from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pixl.modules.campaigns.models import Campaign
from pixl.modules.screens.models import Screen
from sqlalchemy.ext.asyncio import AsyncSession

from pixl.core.database import get_db_session
from pixl.core.dependencies import require_role, require_tenant_context, get_authenticated_device
from pixl.modules.campaigns.schemas import (
    CampaignCreateRequest, CampaignResponse, ManifestResponse
)
from pixl.modules.campaigns.service import CampaignService

agency_campaigns_router = APIRouter(prefix="/api/v1/agency/campaigns", tags=["Agency: Campaigns"])
device_manifest_router = APIRouter(prefix="/api/v1/device/manifest", tags=["Device: Manifest"])


@agency_campaigns_router.get("", response_model=list[CampaignResponse])
async def list_campaigns_endpoint(
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency")),
):
    campaigns = (await db.execute(select(Campaign).where(Campaign.organization_id == org_id)
                 .options(selectinload(Campaign.assignments)).order_by(Campaign.created_at.desc()))).scalars().all()
    return [CampaignResponse.model_validate(campaign) for campaign in campaigns]


@agency_campaigns_router.post("", response_model=CampaignResponse)
async def create_campaign_endpoint(
    req: CampaignCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Agency creates campaign targeting its own screens and playlist."""
    campaign = await CampaignService.create_campaign(
        db=db,
        organization_id=org_id,
        req=req
    )
    return CampaignResponse.model_validate(campaign)


@agency_campaigns_router.post("/{campaign_id}/publish", response_model=CampaignResponse)
async def publish_campaign_endpoint(
    campaign_id: str,
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Agency publishes campaign, invalidating target screens' manifest versions."""
    campaign = await CampaignService.publish_campaign(
        db=db,
        organization_id=org_id,
        campaign_id=campaign_id
    )
    return CampaignResponse.model_validate(campaign)


@device_manifest_router.get("", response_model=ManifestResponse)
async def get_device_manifest(
    request: Request,
    response: Response,
    credential=Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_db_session)
):
    """Authenticated screen pulls its compiled, ED25519-signed manifest for autonomous offline playback."""
    screen = await db.get(Screen, credential.screen_id)
    # Include an hourly authorization window so unchanged checks still renew
    # offline authorization instead of retaining an expired manifest forever.
    from datetime import datetime, timezone
    window = int(datetime.now(timezone.utc).timestamp()) // 3600
    etag = f'"{screen.id}:{screen.current_manifest_version}:{window}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, no-cache"})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache"
    signed_manifest = await CampaignService.generate_signed_screen_manifest(
        db=db,
        screen_id=credential.screen_id
    )
    return ManifestResponse(**signed_manifest)

