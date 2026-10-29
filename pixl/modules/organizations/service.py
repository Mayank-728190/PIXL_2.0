from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from pixl.modules.organizations.models import Organization, Site, Brand
from pixl.modules.auth.models import User, UserInvitation, AuditEvent
from pixl.core.security import generate_secure_token
from pixl.core.session import SessionManager
from pixl.core.exceptions import ConflictError, NotFoundError


class OrganizationService:
    @staticmethod
    async def create_agency(
        db: AsyncSession,
        name: str,
        slug: str,
        admin_email: str,
        max_screens: int = 100,
        creator_user_id: Optional[str] = None
    ) -> Tuple[Organization, str]:
        # 1. Check slug uniqueness
        existing_org = await db.execute(select(Organization).where(Organization.slug == slug.lower()))
        if existing_org.scalar_one_or_none():
            raise ConflictError(f"Agency slug '{slug}' is already registered")

        # 2. Check if admin email already active
        existing_user = await db.execute(select(User).where(User.email == admin_email.lower()))
        if existing_user.scalar_one_or_none():
            raise ConflictError(f"User with email '{admin_email}' already exists")

        # 3. Create agency organization
        org = Organization(
            name=name,
            slug=slug.lower(),
            max_screens=max_screens,
            status="ACTIVE"
        )
        db.add(org)
        await db.flush()

        # 4. Generate expiring invitation for Agency Administrator (24 hour TTL)
        token = generate_secure_token(32)
        invitation = UserInvitation(
            organization_id=org.id,
            email=admin_email.lower(),
            role="agency_admin",
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
        )
        db.add(invitation)

        # 5. Record audit log
        audit = AuditEvent(
            organization_id=org.id,
            user_id=creator_user_id,
            action="AGENCY_PROVISIONED",
            resource_type="ORGANIZATION",
            resource_id=org.id,
            details=f"Agency '{name}' provisioned with admin '{admin_email}'"
        )
        db.add(audit)

        await db.commit()
        return org, token

    @staticmethod
    async def suspend_agency(db: AsyncSession, org_id: str, actor_id: Optional[str] = None) -> Organization:
        org_result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = org_result.scalar_one_or_none()
        if not org:
            raise NotFoundError("Agency not found")

        org.status = "SUSPENDED"

        # Revoke all sessions of users in this agency
        user_results = await db.execute(select(User).where(User.organization_id == org_id))
        users = user_results.scalars().all()
        for u in users:
            await run_in_threadpool(SessionManager.revoke_all_user_sessions, u.id)

        audit = AuditEvent(
            organization_id=org_id,
            user_id=actor_id,
            action="AGENCY_SUSPENDED",
            resource_type="ORGANIZATION",
            resource_id=org_id,
            details=f"Agency {org.name} suspended and all active user sessions revoked"
        )
        db.add(audit)
        await db.commit()
        return org

    @staticmethod
    async def invite_admin(db: AsyncSession, org_id: str, email: str, actor_id: str) -> str:
        org = await db.get(Organization, org_id)
        if not org:
            raise NotFoundError("Agency not found")
        if org.status != "ACTIVE":
            raise ConflictError("Only active agencies can receive admin invitations")
        email = email.lower()
        if await db.scalar(select(User.id).where(User.email == email)):
            raise ConflictError("An account already uses this email; use a new administrator identity")
        now = datetime.now(timezone.utc)
        pending = await db.execute(select(UserInvitation).where(
            UserInvitation.email == email, UserInvitation.used_at.is_(None),
            UserInvitation.expires_at > now
        ))
        if pending.scalars().first():
            raise ConflictError("An unexpired invitation already exists for this email")
        token = generate_secure_token(32)
        db.add(UserInvitation(organization_id=org_id, email=email, role="agency_admin",
                              token=token, expires_at=now + timedelta(hours=24)))
        db.add(AuditEvent(organization_id=org_id, user_id=actor_id,
                          action="ADMIN_INVITED", resource_type="ORGANIZATION", resource_id=org_id,
                          details="Master issued an administrator invitation"))
        await db.commit()
        return token

    @staticmethod
    async def delete_admin(db: AsyncSession, org_id: str, user_id: str, actor_id: str) -> None:
        user = await db.get(User, user_id)
        if not user or user.organization_id != org_id or user.role != "agency_admin":
            raise NotFoundError("Agency administrator not found")
        if user.status == "DELETED":
            return
        user.status = "DELETED"
        # Expire outstanding invitations too, so they cannot restore this identity.
        invitations = await db.execute(select(UserInvitation).where(
            UserInvitation.organization_id == org_id,
            UserInvitation.email == user.email,
            UserInvitation.used_at.is_(None)
        ))
        for invitation in invitations.scalars():
            invitation.expires_at = datetime.now(timezone.utc)
        db.add(AuditEvent(
            organization_id=org_id, user_id=actor_id,
            action="ADMIN_ACCESS_DELETED", resource_type="USER", resource_id=user_id,
            details="Admin access revoked; business records retained"
        ))
        # Persist the disabled status first: authorization rejects even if the
        # session store is temporarily unavailable during revocation.
        await db.commit()
        await run_in_threadpool(SessionManager.revoke_all_user_sessions, user_id)

    @staticmethod
    async def list_agencies(db: AsyncSession) -> List[Organization]:
        result = await db.execute(select(Organization).order_by(Organization.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def create_site(
        db: AsyncSession,
        organization_id: str,
        name: str,
        timezone_str: str = "UTC",
        address: Optional[str] = None
    ) -> Site:
        site = Site(
            organization_id=organization_id,
            name=name,
            timezone=timezone_str,
            address=address
        )
        db.add(site)
        await db.commit()
        return site

    @staticmethod
    async def create_brand(
        db: AsyncSession,
        organization_id: str,
        name: str
    ) -> Brand:
        brand = Brand(
            organization_id=organization_id,
            name=name,
            status="ACTIVE"
        )
        db.add(brand)
        await db.commit()
        return brand
