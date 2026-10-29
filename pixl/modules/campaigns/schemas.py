from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class CampaignCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    playlist_id: str
    brand_id: Optional[str] = None
    priority: int = Field(default=100, ge=0, le=1000)
    start_time: datetime
    end_time: datetime
    screen_ids: List[str] = Field(..., min_length=1, description="Target screens")


class ScreenAssignmentResponse(BaseModel):
    id: str
    screen_id: str

    class Config:
        from_attributes = True


class CampaignResponse(BaseModel):
    id: str
    organization_id: str
    brand_id: Optional[str]
    playlist_id: Optional[str]
    name: str
    status: str
    priority: int
    start_time: datetime
    end_time: datetime
    current_version: int
    assignments: List[ScreenAssignmentResponse]
    created_at: datetime

    class Config:
        from_attributes = True


class ManifestResponse(BaseModel):
    signature: str
    payload: Dict[str, Any]

