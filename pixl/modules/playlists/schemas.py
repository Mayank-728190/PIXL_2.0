from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class PlaylistItemCreate(BaseModel):
    media_id: str
    sort_order: int = Field(..., ge=0)
    duration_mode: str = Field(default="FULL_CLIP", pattern="^(FULL_CLIP|CUSTOM_DURATION|IMAGE_DEFAULT)$")
    configured_duration_ms: int = Field(default=10000, ge=1000, le=3600000)


class PlaylistItemResponse(BaseModel):
    id: str
    media_id: str
    sort_order: int
    duration_mode: str
    configured_duration_ms: int

    class Config:
        from_attributes = True


class PlaylistCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    is_reusable: bool = True
    items: List[PlaylistItemCreate] = Field(default_factory=list)


class PlaylistResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    is_reusable: bool
    items: List[PlaylistItemResponse]
    created_at: datetime

    class Config:
        from_attributes = True
