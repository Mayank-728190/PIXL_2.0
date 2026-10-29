from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_serializer


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
    expected_sha256: Optional[str] = Field(default=None, pattern="^[a-fA-F0-9]{64}$")


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

    @field_serializer("thumbnail_url")
    def current_thumbnail_url(self, value):
        if value is None:
            return None
        from pixl.core.storage import public_media_url
        key = self.storage_key.rsplit(".", 1)[0] + ".thumbnail.webp"
        return public_media_url(key)

    class Config:
        from_attributes = True

