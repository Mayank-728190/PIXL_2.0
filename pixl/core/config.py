from typing import List, Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    PORTAL_PANEL: Literal["all", "master", "agency", "none"] = "all"

    # Security
    SECRET_KEY: str = "pixl_default_insecure_secret_key_needs_override_32_bytes_min"
    SESSION_COOKIE_NAME: str = "__Host-PIXL-Session"
    SESSION_BACKEND: Literal["memory", "redis"] = "memory"
    ALLOW_LEGACY_TV: bool = False
    SESSION_COOKIE_SECURE: bool = False
    SESSION_MAX_AGE_SECONDS: int = 1209600  # 14 days

    # Domains & Origins
    MASTER_ORIGIN: str = "http://master.pixl.local:3000"
    AGENCY_ORIGIN: str = "http://agency.pixl.local:3000"
    ADVERTISER_ORIGIN: str = "http://advertiser.pixl.local:3000"

    @property
    def allowed_cors_origins(self) -> List[str]:
        configured = [self.MASTER_ORIGIN, self.AGENCY_ORIGIN, self.ADVERTISER_ORIGIN]
        if self.ENVIRONMENT == "production":
            return configured
        return configured + [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./pixl2_dev.db"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_TIMEOUT_SECONDS: int = 30

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Cryptography
    MANIFEST_SIGNING_PRIVATE_KEY_B64: str = ""
    MANIFEST_SIGNING_PUBLIC_KEY_B64: str = ""

    # Storage
    STORAGE_PROVIDER: str = "local"  # local or stratus; unknown providers fail closed.
    LOCAL_STORAGE_PATH: str = "local_storage"
    MEDIA_PUBLIC_BASE_URL: str = ""  # Empty uses same-origin URLs.
    MEDIA_PROCESSING_MODE: Literal["inline", "worker"] = "inline"
    MAX_UPLOAD_BYTES: int = Field(default=262144000, gt=0, le=262144000)
    FFPROBE_BINARY: str = "ffprobe"
    FFMPEG_BINARY: str = "ffmpeg"
    MEDIA_TEMP_PATH: str = ""  # Worker-only scratch; empty uses the OS temporary directory.
    STRATUS_PROJECT_ID: str = ""
    STRATUS_ORGANIZATION_ID: str = ""
    STRATUS_BUCKET: str = ""
    STRATUS_NAMESPACE: str = "pixl-staging"
    STRATUS_CLIENT_ID: SecretStr = Field(default=SecretStr(""), repr=False)
    STRATUS_CLIENT_SECRET: SecretStr = Field(default=SecretStr(""), repr=False)
    STRATUS_REFRESH_TOKEN: SecretStr = Field(default=SecretStr(""), repr=False)
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_QUARANTINE: str = "pixl-quarantine-dev"
    R2_BUCKET_PUBLISHED: str = "pixl-published-dev"
    R2_PUBLIC_URL_PREFIX: str = "https://media.pixl.local"

    # Device & Fleet
    ENROLLMENT_PIN_TTL_SECONDS: int = 900  # 15 minutes
    ENROLLMENT_MAX_ATTEMPTS: int = 5
    DEVICE_HEARTBEAT_INTERVAL_SECONDS: int = Field(default=60, ge=10, le=3600)
    DEVICE_CONTENT_CHECK_INTERVAL_SECONDS: int = Field(default=60, ge=10, le=3600)
    DEVICE_OFFLINE_THRESHOLD_SECONDS: int = Field(default=180, ge=10, le=86400)

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"


    def validate_production(self):
        """Fail closed before serving requests, without exposing config values."""
        if self.ENVIRONMENT != "production":
            return
        from urllib.parse import urlsplit
        if self.DEBUG:
            raise RuntimeError("Production requires DEBUG=false")
        if self.SESSION_BACKEND != "redis":
            raise RuntimeError("Production requires SESSION_BACKEND=redis")
        if self.ALLOW_LEGACY_TV:
            raise RuntimeError("Production forbids ALLOW_LEGACY_TV")
        if self.SECRET_KEY.startswith(("pixl_default_", "pixl_dev_")) or len(self.SECRET_KEY) < 32:
            raise RuntimeError("Production requires a strong random SECRET_KEY")
        if not self.DATABASE_URL.startswith("postgresql+asyncpg://"):
            raise RuntimeError("Production requires PostgreSQL with asyncpg")
        for name in ("MASTER_ORIGIN", "AGENCY_ORIGIN", "ADVERTISER_ORIGIN", "MEDIA_PUBLIC_BASE_URL"):
            try:
                parsed = urlsplit(getattr(self, name))
                _ = parsed.port  # Validate port syntax/range, not just the scheme.
                valid = (parsed.scheme == "https" and parsed.hostname and
                         not parsed.username and not parsed.password and
                         parsed.path in ("", "/") and not parsed.query and not parsed.fragment)
                if not valid:
                    raise ValueError()
            except ValueError:
                raise RuntimeError(f"Production requires a valid HTTPS origin for {name}") from None
        if self.STORAGE_PROVIDER not in {"local", "stratus"}:
            raise RuntimeError("Unsupported storage provider")
        if self.STORAGE_PROVIDER == "stratus":
            self.validate_stratus()
        if self.MEDIA_PROCESSING_MODE != "worker":
            raise RuntimeError("Production requires MEDIA_PROCESSING_MODE=worker and worker/Beat services")

    def validate_stratus(self):
        """India Development only. Never include credential values in errors."""
        import re
        if not (re.fullmatch(r"[0-9]+", self.STRATUS_PROJECT_ID)
                and re.fullmatch(r"[0-9]+", self.STRATUS_ORGANIZATION_ID)
                and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", self.STRATUS_BUCKET)
                and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", self.STRATUS_NAMESPACE)):
            raise RuntimeError("Stratus requires valid project, organization, bucket and namespace settings")
        if not all(value.get_secret_value() for value in (
                self.STRATUS_CLIENT_ID, self.STRATUS_CLIENT_SECRET, self.STRATUS_REFRESH_TOKEN)):
            raise RuntimeError("Stratus requires dedicated application OAuth credentials")
        if self.MEDIA_PROCESSING_MODE != "worker":
            raise RuntimeError("Stratus requires worker processing; inline HTTP inspection is disabled")


settings = Settings()

