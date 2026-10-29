from typing import List, Optional, Callable
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pixl.core.database import get_db_session
from pixl.core.session import SessionManager
from pixl.core.exceptions import AuthenticationError, ForbiddenError


async def get_current_session_data(request: Request) -> dict:
    """Extract and validate the active session."""
    token = SessionManager.extract_session_token(request)
    if not token:
        raise AuthenticationError("Authentication credentials not provided")
    
    session = SessionManager.get_session(token)
    if not session:
        raise AuthenticationError("Invalid or expired session")
    
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
        DeviceCredential.token_hash == token,
        DeviceCredential.revoked_at.is_(None)
    )
    result = await db.execute(query)
    credential = result.scalar_one_or_none()

    if not credential:
        raise AuthenticationError("Invalid or revoked device token")

    return credential
