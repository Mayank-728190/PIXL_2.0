"""Bootstrap a master account after migrations. Never prints credentials."""
import asyncio
import getpass
import os

from sqlalchemy import select
import pyotp

# Register mapper relationships, without starting the application.
from pixl.main import app  # noqa: F401
from pixl.core.database import AsyncSessionFactory, engine
from pixl.core.security import hash_password
from pixl.modules.auth.models import User, AuditEvent


async def create_master(email, password, totp_secret):
    from pydantic import TypeAdapter, EmailStr
    email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    if len(password) < 12:
        raise ValueError("Master password must contain at least 12 characters")
    pyotp.TOTP(totp_secret).now()  # Reject malformed base32 secrets.
    if len(totp_secret) < 32:
        raise ValueError("Use a randomly generated TOTP secret of at least 32 base32 characters")
    async with AsyncSessionFactory() as db:
        if await db.scalar(select(User).where(User.email == email)):
            raise ValueError("Account already exists; refusing to overwrite it")
        user = User(email=email, hashed_password=hash_password(password), role="master_admin",
                    status="ACTIVE", totp_secret=totp_secret, is_mfa_enabled=True)
        db.add(user)
        await db.flush()
        db.add(AuditEvent(user_id=user.id, action="MASTER_BOOTSTRAPPED", resource_type="USER", resource_id=user.id))
        await db.commit()


def main():
    email = os.environ.get("MASTER_BOOTSTRAP_EMAIL") or input("Master email: ")
    password = os.environ.get("MASTER_BOOTSTRAP_PASSWORD") or getpass.getpass("Master password: ")
    totp_secret = os.environ.get("MASTER_BOOTSTRAP_TOTP_SECRET") or getpass.getpass("TOTP secret from your password manager: ")
    async def run():
        try:
            await create_master(email, password, totp_secret)
        finally:
            await engine.dispose()
    asyncio.run(run())
    print("Master account created. Sign in with your password and authenticator code.")


if __name__ == "__main__":
    main()
