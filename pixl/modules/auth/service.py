from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from pixl.modules.auth.models import User, UserInvitation, AuditEvent
from pixl.core.database import ensure_utc
from pixl.core.security import verify_password, hash_password, verify_totp_code
from pixl.core.session import SessionManager
from pixl.core.exceptions import AuthenticationError, ForbiddenError, NotFoundError, ConflictError


class AuthService:
    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        email: str,
        password: str,
        totp_code: Optional[str] = None,
        panel_audience: str = "pixl:audience:agency"
    ) -> Tuple[User, str]:
        # 1. Fetch user by email
        result = await db.execute(select(User).where(User.email == email.lower()))
        user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid email or password")

        # 2. Check user status
        if user.status != "ACTIVE":
            raise ForbiddenError(f"Account is {user.status.lower()}. Access denied.")

        # 3. Audience and role validation
        if panel_audience == "pixl:audience:master":
            if user.role != "master_admin":
                raise ForbiddenError("Only Master administrators may authenticate on the Master portal")
            # Master requires MFA
            if user.is_mfa_enabled and user.totp_secret:
                if not totp_code or not verify_totp_code(user.totp_secret, totp_code):
                    raise AuthenticationError("Valid TOTP 2FA code is required for Master login")
        elif panel_audience == "pixl:audience:agency":
            if user.role not in ["agency_admin", "agency_operator"]:
                raise ForbiddenError("Access restricted to Agency members")
        elif panel_audience == "pixl:audience:brand":
            if user.role != "brand_advertiser":
                raise ForbiddenError("Access restricted to Brand Advertisers")

        # Optional MFA check if enabled on user account
        if user.is_mfa_enabled and user.totp_secret and panel_audience != "pixl:audience:master":
            if not totp_code or not verify_totp_code(user.totp_secret, totp_code):
                raise AuthenticationError("Valid TOTP 2FA code is required")

        # 4. Create isolated session
        session_token = SessionManager.create_session(
            user_id=user.id,
            role=user.role,
            audience=panel_audience,
            organization_id=user.organization_id
        )

        # 5. Update last login
        user.last_login_at = datetime.now(timezone.utc)
        await db.commit()

        return user, session_token

    @staticmethod
    async def accept_invitation(
        db: AsyncSession,
        token: str,
        password: str,
        totp_secret: Optional[str] = None
    ) -> User:
        # 1. Locate invitation
        result = await db.execute(select(UserInvitation).where(UserInvitation.token == token))
        invitation = result.scalar_one_or_none()

        if not invitation:
            raise NotFoundError("Invalid or unknown invitation token")

        if invitation.used_at is not None:
            raise ConflictError("Invitation token has already been accepted and used")

        if datetime.now(timezone.utc) > ensure_utc(invitation.expires_at):
            raise ConflictError("Invitation token has expired")

        # 2. Check if user already exists
        user_result = await db.execute(select(User).where(User.email == invitation.email.lower()))
        user = user_result.scalar_one_or_none()

        hashed_pwd = hash_password(password)

        if user:
            # Activate existing user
            user.hashed_password = hashed_pwd
            user.status = "ACTIVE"
            user.role = invitation.role  # Role strictly dictated by invitation
            user.organization_id = invitation.organization_id
            if totp_secret:
                user.totp_secret = totp_secret
                user.is_mfa_enabled = True
        else:
            # Create new user with assigned role from invitation
            user = User(
                email=invitation.email.lower(),
                hashed_password=hashed_pwd,
                role=invitation.role,
                status="ACTIVE",
                organization_id=invitation.organization_id,
                totp_secret=totp_secret,
                is_mfa_enabled=bool(totp_secret)
            )
            db.add(user)

        # 3. Mark invitation as consumed atomically
        invitation.used_at = datetime.now(timezone.utc)

        # 4. Record audit event
        audit = AuditEvent(
            organization_id=invitation.organization_id,
            user_id=user.id,
            action="INVITATION_ACCEPTED",
            resource_type="USER",
            resource_id=user.id,
            details=f"User {user.email} activated with role {user.role}"
        )
        db.add(audit)
        await db.commit()
        return user
