from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class PoPEventItem(BaseModel):
    local_sequence: int = Field(..., ge=1)
    campaign_id: Optional[str] = None
    media_id: str
    media_sha256: Optional[str] = None
    zone_id: str = "zone_main"
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: int = Field(..., ge=0)
    outcome: str = Field(..., pattern="^(COMPLETED|INTERRUPTED|DECODE_FAILED|SKIPPED)$")
    failure_reason: Optional[str] = None
    clock_quality: str = "NTP_SYNCED"


class PoPBatchRequest(BaseModel):
    device_id: str
    epoch: int = Field(default=1, ge=1)
    batch: List[PoPEventItem] = Field(..., min_length=1, max_length=100)


class PoPDisposition(BaseModel):
    local_sequence: int
    status: str  # STORED, DUPLICATE_ACKNOWLEDGED, QUARANTINED


class PoPBatchResponse(BaseModel):
    status: str = "ACK"
    device_id: str
    epoch: int
    last_committed_sequence: int
    dispositions: List[PoPDisposition]

