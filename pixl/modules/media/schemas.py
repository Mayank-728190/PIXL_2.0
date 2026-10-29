from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class UploadTicketRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    size_bytes: int = Field(..., gt=0, le=262144000, description="Max 250MB")
    declared_mime: str = Field(..., pattern="^(video/mp4|video/webm|image/jpeg|image/png|image/webp)$")


class UploadTicketResponse(BaseModel):
    ticket_id: str
    storage_key: str
    presigned_upload_url: str
    expires_at: datetime


class FinalizeUploadRequest(BaseModel):
    ticket_id: str
    brand_id: Optional[str] = None
    expected_sha256: Optional[str] = None


class MediaAssetResponse(BaseModel):
    id: str
    organization_id: str
    brand_id: Optional[str]
    filename: str
    storage_key: str
    sha256: str
    mime_type: str
    size_bytes: int
    duration_ms: int
    width: int
    height: int
    status: str
    thumbnail_url: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
