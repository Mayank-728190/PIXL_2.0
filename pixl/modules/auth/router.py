from fastapi import APIRouter, Depends, Response, Request
from starlette.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from pixl.core.database import get_db_session
from pixl.core.session import SessionManager
from pixl.core.rate_limit import authentication_rate_limit
from pixl.core.dependencies import get_current_session_data
from pixl.modules.auth.schemas import LoginRequest, LoginResponse, InvitationAcceptRequest, UserResponse
from pixl.modules.auth.service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & Session"])


@router.post("/master/login", response_model=LoginResponse, dependencies=[Depends(authentication_rate_limit)])
async def login_master(
    req: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session)
):
    """Authenticate Master Super-Administrator with MFA."""
    user, session_token = await AuthService.authenticate_user(
        db=db,
        email=req.email,
        password=req.password,
        totp_code=req.totp_code,
        panel_audience="pixl:audience:master"
    )
    SessionManager.attach_session_cookie(response, session_token, "pixl:audience:master")
    return LoginResponse(
        user=UserResponse.model_validate(user),
        audience="pixl:audience:master",
        session_token=session_token,
        message="Master login authenticated"
    )


@router.post("/agency/login", response_model=LoginResponse, dependencies=[Depends(authentication_rate_limit)])
async def login_agency(
    req: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session)
):
    """Authenticate Agency Administrator or Operator."""
    user, session_token = await AuthService.authenticate_user(
        db=db,
        email=req.email,
        password=req.password,
        totp_code=req.totp_code,
        panel_audience="pixl:audience:agency"
    )
    SessionManager.attach_session_cookie(response, session_token, "pixl:audience:agency")
    return LoginResponse(
        user=UserResponse.model_validate(user),
        audience="pixl:audience:agency",
        session_token=session_token,
        message="Agency login authenticated"
    )


@router.post("/brand/login", response_model=LoginResponse, dependencies=[Depends(authentication_rate_limit)])
async def login_brand(
    req: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session)
):
    """Authenticate Brand / Advertiser."""
    user, session_token = await AuthService.authenticate_user(
        db=db,
        email=req.email,
        password=req.password,
        totp_code=req.totp_code,
        panel_audience="pixl:audience:brand"
    )
    SessionManager.attach_session_cookie(response, session_token, "pixl:audience:brand")
    return LoginResponse(
        user=UserResponse.model_validate(user),
        audience="pixl:audience:brand",
        session_token=session_token,
        message="Brand login authenticated"
    )


@router.post("/invitation/accept", response_model=UserResponse, dependencies=[Depends(authentication_rate_limit)])
async def accept_invitation(
    req: InvitationAcceptRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """Redeem expiring invitation token to set password and activate account."""
    user = await AuthService.accept_invitation(
        db=db,
        token=req.invitation_token,
        password=req.password
    )
    return UserResponse.model_validate(user)


@router.post("/logout")
async def logout(
    response: Response,
    request: Request,
    session: dict = Depends(get_current_session_data)
):
    """Revoke session and clear HttpOnly cookie."""
    token = session.get("session_token")
    if token:
        await run_in_threadpool(SessionManager.revoke_session, token)
    SessionManager.clear_session_cookie(response, session.get("audience", ""))
    return {"status": "SUCCESS", "message": "Logged out successfully"}


@router.get("/me")
async def get_me(session: dict = Depends(get_current_session_data)):
    """Return active session context."""
    return {
        "user_id": session.get("user_id"),
        "role": session.get("role"),
        "audience": session.get("audience"),
        "organization_id": session.get("organization_id"),
        "expires_at": session.get("expires_at"),
    }

