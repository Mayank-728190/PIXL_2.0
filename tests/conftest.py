import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
import pyotp

from pixl.core.database import Base, get_db_session
from pixl.core.security import hash_password
from pixl.core.session import SessionManager
from pixl.main import app
from pixl.modules.auth.models import User

# In-memory SQLite for isolated, fast test execution
import os
import tempfile
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.pool import NullPool

_test_directory = tempfile.TemporaryDirectory(prefix="pixl-tests-")
TEST_DB_FILE = (Path(_test_directory.name) / "test_pixl.db").as_posix()
TEST_DATABASE_URL = os.environ.get("PIXL_TEST_DATABASE_URL", f"sqlite+aiosqlite:///{TEST_DB_FILE}")
from sqlalchemy.engine import make_url
_test_url = make_url(TEST_DATABASE_URL)
if not TEST_DATABASE_URL.startswith("sqlite") and not (_test_url.database or "").endswith("_test"):
    raise RuntimeError("Destructive database tests require a dedicated database name ending in _test")
_test_sqlite = TEST_DATABASE_URL.startswith("sqlite")

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False} if _test_sqlite else {},
    hide_parameters=True,
    pool_pre_ping=True,
    poolclass=NullPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db(tmp_path, monkeypatch):
    from pixl.core.config import settings
    monkeypatch.setattr(settings, "LOCAL_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "SESSION_BACKEND", "memory")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    from pixl.core.session import _session_store
    _session_store.clear()
    monkeypatch.setattr(settings, "ALLOW_LEGACY_TV", True)
    from pixl.core.rate_limit import _attempts
    _attempts.clear()
    async with test_engine.begin() as conn:
        if _test_sqlite:
            await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()
    if _test_sqlite and os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except Exception:
            pass


async def override_get_db_session():
    async with TestingSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db_session] = override_get_db_session


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def master_admin_user():
    """Seeds a master administrator with TOTP MFA secret."""
    totp_secret = "JBSWY3DPEHPK3PXP"  # Standard base32 test secret
    user = User(
        email="master@pixl.io",
        hashed_password=hash_password("MasterPassword123!"),
        role="master_admin",
        status="ACTIVE",
        totp_secret=totp_secret,
        is_mfa_enabled=True,
    )
    async with TestingSessionLocal() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user, totp_secret


@pytest_asyncio.fixture
async def master_auth_headers(master_admin_user):
    user, _ = master_admin_user
    session_token = SessionManager.create_session(
        user_id=user.id,
        role="master_admin",
        audience="pixl:audience:master"
    )
    return {
        "Cookie": f"__Host-PIXL-Master-Session={session_token}",
        "Authorization": f"Bearer {session_token}"
    }
