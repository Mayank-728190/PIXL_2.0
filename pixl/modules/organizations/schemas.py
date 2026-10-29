from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class AgencyCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100)
    admin_email: EmailStr
    max_screens: int = Field(default=100, ge=1, le=10000)


class AgencyResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    max_screens: int
    storage_quota_bytes: int
    created_at: datetime

    class Config:
        from_attributes = True


class AgencyProvisionResponse(BaseModel):
    agency: AgencyResponse
    invitation_token: str
    invitation_link: str
    message: str = "Agency provisioned and admin invitation token generated"


class SiteCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    timezone: str = Field(default="UTC", max_length=100)
    address: Optional[str] = None


class SiteResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    timezone: str
    address: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class BrandCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)


class BrandResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

