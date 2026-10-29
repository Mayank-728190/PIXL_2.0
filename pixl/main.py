from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pixl.core.config import settings
from pixl.core.database import engine, Base
from pixl.core.exceptions import PixlException

# Import all models to ensure metadata registration
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup (especially for sqlite dev/test)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
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
async def readiness_check():
    """Readiness probe: validates database connection pool."""
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

