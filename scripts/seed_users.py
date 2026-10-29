"""
PIXL 2.0 - Database Seeding Script (scripts/seed_users.py)
==========================================================
Bootstraps initial Master Admin and Agency Admin accounts
for local development and first-time operations.
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pyotp
from sqlalchemy import select

# Import all SQLAlchemy models to register metadata
import pixl.modules.organizations.models  # noqa
import pixl.modules.screens.models  # noqa
import pixl.modules.media.models  # noqa
import pixl.modules.playlists.models  # noqa
import pixl.modules.campaigns.models  # noqa
import pixl.modules.ingestion.models  # noqa

from pixl.core.database import AsyncSessionFactory, engine, Base
from pixl.core.security import hash_password
from pixl.modules.auth.models import User
from pixl.modules.organizations.models import Organization


MASTER_EMAIL = "master@pixl.io"
MASTER_PASSWORD = "MasterPassword123!"
MASTER_TOTP_SECRET = "JBSWY3DPEHPK3PXP"

AGENCY_EMAIL = "admin@demoagency.com"
AGENCY_PASSWORD = "AgencyPassword123!"
AGENCY_NAME = "Demo Signage Agency"
AGENCY_SLUG = "demo-agency"


async def seed_users(verbose: bool = True):
    # Ensure database schema exists
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionFactory() as session:
        # 1. Seed Master Admin
        existing_master = (
            await session.execute(select(User).where(User.email == MASTER_EMAIL))
        ).scalar_one_or_none()

        if not existing_master:
            master = User(
                email=MASTER_EMAIL,
                hashed_password=hash_password(MASTER_PASSWORD),
                role="master_admin",
                status="ACTIVE",
                totp_secret=MASTER_TOTP_SECRET,
                is_mfa_enabled=True,
            )
            session.add(master)
            if verbose:
                print(f"[Seed] Created Master Administrator: {MASTER_EMAIL}")
        else:
            if verbose:
                print(f"[Seed] Master Administrator already exists: {MASTER_EMAIL}")

        # 2. Seed Default Agency
        existing_org = (
            await session.execute(select(Organization).where(Organization.slug == AGENCY_SLUG))
        ).scalar_one_or_none()

        if not existing_org:
            org = Organization(
                name=AGENCY_NAME,
                slug=AGENCY_SLUG,
                status="ACTIVE",
                max_screens=50
            )
            session.add(org)
            await session.flush()
            org_id = org.id
            if verbose:
                print(f"[Seed] Created Agency: {AGENCY_NAME} ({AGENCY_SLUG})")
        else:
            org_id = existing_org.id
            if verbose:
                print(f"[Seed] Agency already exists: {AGENCY_NAME}")

        # 3. Seed Agency Admin
        existing_agency_user = (
            await session.execute(select(User).where(User.email == AGENCY_EMAIL))
        ).scalar_one_or_none()

        if not existing_agency_user:
            agency_user = User(
                organization_id=org_id,
                email=AGENCY_EMAIL,
                hashed_password=hash_password(AGENCY_PASSWORD),
                role="agency_admin",
                status="ACTIVE",
                totp_secret=None,
                is_mfa_enabled=False,
            )
            session.add(agency_user)
            if verbose:
                print(f"[Seed] Created Agency Admin: {AGENCY_EMAIL}")
        else:
            if verbose:
                print(f"[Seed] Agency Admin already exists: {AGENCY_EMAIL}")

        await session.commit()

    if verbose:
        totp = pyotp.TOTP(MASTER_TOTP_SECRET)
        current_code = totp.now()
        print("\n" + "=" * 68)
        print("                 PIXL 2.0 LOGIN CREDENTIALS                 ")
        print("=" * 68)
        print(" 1. MASTER SUPER-ADMIN (Portal: http://localhost:8000/master)")
        print(f"    - Email:              {MASTER_EMAIL}")
        print(f"    - Password:           {MASTER_PASSWORD}")
        print(f"    - Authenticator Code: {current_code} (Valid for ~30 seconds)")
        print(f"    - Base32 Secret:      {MASTER_TOTP_SECRET} (for Authenticator App)")
        print()
        print(" 2. AGENCY ADMIN (Portal: http://localhost:8000/agency)")
        print(f"    - Email:              {AGENCY_EMAIL}")
        print(f"    - Password:           {AGENCY_PASSWORD}")
        print("    - Authenticator Code: (Leave empty - MFA not required)")
        print("=" * 68 + "\n")


if __name__ == "__main__":
    asyncio.run(seed_users(verbose=True))
