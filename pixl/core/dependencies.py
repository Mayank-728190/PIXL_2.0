from typing import List, Optional, Callable
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool
from pixl.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pixl.core.database import get_db_session
from pixl.core.session import SessionManager
from pixl.core.security import hash_device_token
from pixl.core.exceptions import AuthenticationError, ForbiddenError


async def get_current_session_data(request: Request, db: AsyncSession = Depends(get_db_session)) -> dict:
    """Extract and validate the active session."""
    audience = None
    if request.url.path.startswith("/api/v1/master/"):
        audience = "pixl:audience:master"
    elif request.url.path.startswith("/api/v1/agency/"):
        audience = "pixl:audience:agency"
    if request.url.path.startswith("/api/v1/auth/"):
        panel = request.query_params.get("panel")
        if panel in {"master", "agency", "brand"}:
            audience = f"pixl:audience:{panel}"
    token = SessionManager.extract_session_token(request, audience)
    if not token:
        raise AuthenticationError("Authentication credentials not provided")
    
    session = await run_in_threadpool(SessionManager.get_session, token)
    if not session:
        raise AuthenticationError("Invalid or expired session")
    
    from pixl.modules.auth.models import User
    from pixl.modules.organizations.models import Organization
    user = await db.get(User, session["user_id"])
    if user is None and settings.ENVIRONMENT == "production":
        raise AuthenticationError("Session user no longer exists")
    if user and (user.status != "ACTIVE" or user.role != session["role"]
                 or user.organization_id != session.get("organization_id")):
        raise AuthenticationError("Account permissions changed; please sign in again")
    if session.get("organization_id"):
        org = await db.get(Organization, session["organization_id"])
        if org is None or org.status != "ACTIVE":
            raise ForbiddenError("Organization is not active")
    # Cookie-authenticated writes must originate from an approved portal.
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not request.headers.get("Authorization"):
        origin = request.headers.get("origin")
        if origin not in [*settings.allowed_cors_origins, str(request.base_url).rstrip("/")]:
            if origin or settings.ENVIRONMENT == "production":
                raise ForbiddenError("Invalid or missing request origin")
    return session


def require_role(allowed_roles: List[str], expected_audience: Optional[str] = None) -> Callable:
    """
    Dependency factory enforcing role and audience isolation.
    """
    async def role_checker(
        request: Request,
        session: dict = Depends(get_current_session_data)
    ) -> dict:
        user_role = session.get("role")
        user_audience = session.get("audience")

        # Audience isolation check
        if expected_audience and user_audience != expected_audience:
            raise ForbiddenError(f"Session audience '{user_audience}' not permitted for this endpoint panel")

        # Role check
        if user_role not in allowed_roles:
            raise ForbiddenError(f"Role '{user_role}' does not have permission for this resource")

        return session

    return role_checker


async def require_tenant_context(
    session: dict = Depends(get_current_session_data)
) -> str:
    """
    Ensures that the active request possesses an organization context.
    Fails closed if organization_id is missing or None.
    """
    org_id = session.get("organization_id")
    if not org_id:
        raise ForbiddenError("Missing tenant context: this action requires an active organization")
    return org_id


async def get_authenticated_device(
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Authenticate screen hardware via X-Device-Token header.
    """
    token = request.headers.get("X-Device-Token")
    if not token:
        raise AuthenticationError("Device authentication required: missing X-Device-Token")

    from pixl.modules.screens.models import DeviceCredential
    query = select(DeviceCredential).where(
        DeviceCredential.token_hash == hash_device_token(token),
        DeviceCredential.revoked_at.is_(None)
    )
    result = await db.execute(query)
    credential = result.scalar_one_or_none()

    if not credential:
        raise AuthenticationError("Invalid or revoked device token")
    from pixl.modules.screens.models import Screen
    from pixl.modules.organizations.models import Organization
    screen = await db.get(Screen, credential.screen_id)
    org = await db.get(Organization, screen.organization_id) if screen and screen.organization_id else None
    if not org or org.status != "ACTIVE":
        raise ForbiddenError("Device agency is not active")
    return credential

