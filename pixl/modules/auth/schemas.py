from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=1024)
    totp_code: Optional[str] = Field(None, max_length=6, description="Required for accounts with MFA enabled (e.g. Master)")


class InvitationAcceptRequest(BaseModel):
    invitation_token: str = Field(..., min_length=1, max_length=256)
    password: str = Field(..., min_length=12, max_length=128)
    totp_code: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    organization_id: Optional[str]
    email: str
    role: str
    status: str
    is_mfa_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    user: UserResponse
    audience: str
    session_token: str
    message: str = "Authenticated successfully"

