from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pixl.core.database import get_db_session
from pixl.core.dependencies import require_role, require_tenant_context, get_authenticated_device
from pixl.modules.campaigns.schemas import (
    CampaignCreateRequest, CampaignResponse, ManifestResponse
)
from pixl.modules.campaigns.service import CampaignService

agency_campaigns_router = APIRouter(prefix="/api/v1/agency/campaigns", tags=["Agency: Campaigns"])
device_manifest_router = APIRouter(prefix="/api/v1/device/manifest", tags=["Device: Manifest"])


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
    credential=Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_db_session)
):
    """Authenticated screen pulls its compiled, ED25519-signed manifest for autonomous offline playback."""
    signed_manifest = await CampaignService.generate_signed_screen_manifest(
        db=db,
        screen_id=credential.screen_id
    )
    return ManifestResponse(**signed_manifest)
