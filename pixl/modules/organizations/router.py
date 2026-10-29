from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pixl.core.database import get_db_session
from pixl.core.config import settings
from pixl.core.dependencies import require_role, require_tenant_context
from pixl.modules.organizations.schemas import (
    AgencyCreateRequest, AgencyResponse, AgencyProvisionResponse,
    SiteCreateRequest, SiteResponse,
    BrandCreateRequest, BrandResponse
)
from pixl.modules.organizations.service import OrganizationService
from pixl.modules.organizations.models import Site, Brand

master_router = APIRouter(prefix="/api/v1/master/agencies", tags=["Master: Agency Provisioning"])
agency_router = APIRouter(prefix="/api/v1/agency", tags=["Agency: Organization & Sites"])


# Master endpoints
@master_router.post("", response_model=AgencyProvisionResponse)
async def provision_agency(
    req: AgencyCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    session: dict = Depends(require_role(["master_admin"], expected_audience="pixl:audience:master"))
):
    """Master provisions a new Agency organization and issues expiring admin invitation."""
    org, token = await OrganizationService.create_agency(
        db=db,
        name=req.name,
        slug=req.slug,
        admin_email=req.admin_email,
        max_screens=req.max_screens,
        creator_user_id=session.get("user_id")
    )
    invitation_link = settings.AGENCY_ORIGIN.rstrip("/") + f"/accept-invitation?token={token}"
    return AgencyProvisionResponse(
        agency=AgencyResponse.model_validate(org),
        invitation_token=token,
        invitation_link=invitation_link
    )


@master_router.get("", response_model=List[AgencyResponse])
async def list_all_agencies(
    db: AsyncSession = Depends(get_db_session),
    session: dict = Depends(require_role(["master_admin"], expected_audience="pixl:audience:master"))
):
    """Master views all registered agency organizations globally."""
    agencies = await OrganizationService.list_agencies(db)
    return [AgencyResponse.model_validate(a) for a in agencies]


@master_router.post("/{agency_id}/suspend", response_model=AgencyResponse)
async def suspend_agency_endpoint(
    agency_id: str,
    db: AsyncSession = Depends(get_db_session),
    session: dict = Depends(require_role(["master_admin"], expected_audience="pixl:audience:master"))
):
    """Master suspends an agency and terminates all active sessions."""
    org = await OrganizationService.suspend_agency(db, agency_id, actor_id=session.get("user_id"))
    return AgencyResponse.model_validate(org)


# Agency endpoints
@agency_router.post("/sites", response_model=SiteResponse)
async def create_agency_site(
    req: SiteCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Agency creates a physical Site for grouping screens."""
    site = await OrganizationService.create_site(
        db=db,
        organization_id=org_id,
        name=req.name,
        timezone_str=req.timezone,
        address=req.address
    )
    return SiteResponse.model_validate(site)


@agency_router.get("/sites", response_model=List[SiteResponse])
async def list_agency_sites(
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Agency views only its own physical sites."""
    result = await db.execute(select(Site).where(Site.organization_id == org_id))
    return [SiteResponse.model_validate(s) for s in result.scalars().all()]


@agency_router.post("/brands", response_model=BrandResponse)
async def create_agency_brand(
    req: BrandCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin"], expected_audience="pixl:audience:agency"))
):
    """Agency creates an Advertiser Brand account."""
    brand = await OrganizationService.create_brand(db=db, organization_id=org_id, name=req.name)
    return BrandResponse.model_validate(brand)


@agency_router.get("/brands", response_model=List[BrandResponse])
async def list_agency_brands(
    db: AsyncSession = Depends(get_db_session),
    org_id: str = Depends(require_tenant_context),
    session: dict = Depends(require_role(["agency_admin", "agency_operator"], expected_audience="pixl:audience:agency"))
):
    """Agency views only its own registered brands."""
    result = await db.execute(select(Brand).where(Brand.organization_id == org_id))
    return [BrandResponse.model_validate(b) for b in result.scalars().all()]

