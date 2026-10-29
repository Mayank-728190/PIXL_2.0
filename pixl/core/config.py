from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Security
    SECRET_KEY: str = "pixl_default_insecure_secret_key_needs_override_32_bytes_min"
    SESSION_COOKIE_NAME: str = "__Host-PIXL-Session"
    SESSION_COOKIE_SECURE: bool = False
    SESSION_MAX_AGE_SECONDS: int = 1209600  # 14 days

    # Domains & Origins
    MASTER_ORIGIN: str = "http://master.pixl.local:3000"
    AGENCY_ORIGIN: str = "http://agency.pixl.local:3000"
    ADVERTISER_ORIGIN: str = "http://advertiser.pixl.local:3000"

    @property
    def allowed_cors_origins(self) -> List[str]:
        return [
            self.MASTER_ORIGIN,
            self.AGENCY_ORIGIN,
            self.ADVERTISER_ORIGIN,
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
    STORAGE_PROVIDER: str = "local"  # "local" or "r2"
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_QUARANTINE: str = "pixl-quarantine-dev"
    R2_BUCKET_PUBLISHED: str = "pixl-published-dev"
    R2_PUBLIC_URL_PREFIX: str = "https://media.pixl.local"

    # Device & Fleet
    ENROLLMENT_PIN_TTL_SECONDS: int = 900  # 15 minutes
    ENROLLMENT_MAX_ATTEMPTS: int = 5
    DEVICE_HEARTBEAT_INTERVAL_SECONDS: int = 60
    DEVICE_OFFLINE_THRESHOLD_SECONDS: int = 180

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"


settings = Settings()

