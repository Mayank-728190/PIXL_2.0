from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pixl.core.config import settings
from pixl.core.database import engine, Base, get_db_session
from pixl.core.exceptions import PixlException

# Import all models to ensure metadata registration
import pixl.core.identifiers  # noqa
import pixl.modules.auth.models  # noqa
import pixl.modules.organizations.models  # noqa
import pixl.modules.screens.models  # noqa
import pixl.modules.media.models  # noqa
import pixl.modules.playlists.models  # noqa
import pixl.modules.campaigns.models  # noqa
import pixl.modules.ingestion.models  # noqa

# Import routers
from pixl.modules.auth.router import router as auth_router
from pixl.modules.organizations.router import master_router as org_master_router, agency_router as org_agency_router
from pixl.modules.screens.router import (
    master_screens_router,
    agency_screens_router,
    device_router
)
from pixl.modules.media.router import router as media_router
from pixl.modules.playlists.router import router as playlists_router
from pixl.modules.campaigns.router import (
    agency_campaigns_router,
    device_manifest_router
)
from pixl.modules.ingestion.router import router as ingestion_router
from pixl.modules.tv.router import tv_router, media_file_router
from pixl.modules.simulator.router import simulator_router
from pixl.portals.router import router as portal_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENVIRONMENT == "production":
        if settings.SESSION_BACKEND != "redis":
            raise RuntimeError("Production requires SESSION_BACKEND=redis")
        if settings.SECRET_KEY.startswith(("pixl_default_", "pixl_dev_")) or len(settings.SECRET_KEY) < 32:
            raise RuntimeError("Production requires a strong SECRET_KEY")
        from pixl.core.security import get_server_signing_keys
        get_server_signing_keys()
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title="PIXL 2.0 Signage Core API",
    version="2.0.0",
    description="Enterprise Multi-Tenant Digital Signage Backend & Device Engine",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
)

# CORS Middleware (Strict explicit origins, never wildcard * with credentials)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Global Exception Handler
@app.exception_handler(PixlException)
async def pixl_exception_handler(request: Request, exc: PixlException):
    content = {
        "error": {
            "code": exc.code,
            "message": exc.detail,
        }
    }
    if exc.extra:
        content["error"]["details"] = exc.extra
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=exc.headers
    )


# Operational Healthcheck Endpoints
@app.get("/health", tags=["Operational Observability"])
@app.get("/healthz", tags=["Operational Observability"])
@app.get("/api/v1/health/live", tags=["Operational Observability"])
async def liveness_check():
    """Liveness probe: returns 200 if process is running."""
    return {"status": "UP", "version": "2.0.0"}


@app.get("/api/v1/health/ready", tags=["Operational Observability"])
async def readiness_check(db: AsyncSession = Depends(get_db_session)):
    """Readiness probe: checks the database rather than just process liveness."""
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        await db.rollback()
        return JSONResponse(
            status_code=503,
            content={"status": "NOT_READY", "database": "UNAVAILABLE"},
        )
    if settings.SESSION_BACKEND == "redis":
        import redis
        from starlette.concurrency import run_in_threadpool
        from pixl.core.session_store import cache
        try:
            await run_in_threadpool(lambda: cache().ping())
        except redis.RedisError:
            return JSONResponse(status_code=503, content={"status": "NOT_READY", "sessions": "UNAVAILABLE"})
    return {"status": "READY", "database": "CONNECTED"}


# Register API Routers
app.include_router(auth_router)
app.include_router(org_master_router)
app.include_router(org_agency_router)
app.include_router(master_screens_router)
app.include_router(agency_screens_router)
app.include_router(device_router)
app.include_router(media_router)
app.include_router(playlists_router)
app.include_router(agency_campaigns_router)
app.include_router(device_manifest_router)
app.include_router(ingestion_router)
app.include_router(tv_router)
app.include_router(media_file_router)
app.include_router(simulator_router)
app.include_router(portal_router)

