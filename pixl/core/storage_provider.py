"""Storage boundary; local development remains independent of cloud credentials.

Keys are logical, tenant-scoped names. Providers must never accept client URLs.
Inspection always sees a bounded local snapshot, not a mutable cloud object.
"""
import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import os
import shutil

from pixl.core.exceptions import PixlException, UnprocessableError


class StorageUnavailable(PixlException):
    def __init__(self):
        super().__init__(503, "Media storage temporarily unavailable", "STORAGE_UNAVAILABLE")


class StorageProvider(ABC):
    direct_upload = False

    @abstractmethod
    async def upload_url(self, ticket_id: str, key: str, ttl: int) -> str: ...

    @abstractmethod
    async def size(self, key: str) -> int | None: ...

    @abstractmethod
    def materialize(self, key: str, expected_size: int):
        """Async context manager yielding a local Path, cleaned on exit."""

    @abstractmethod
    async def publish(self, key: str, source: Path, mime: str, lease: str): ...

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """True only when absence is confirmed; safe to repeat."""

    @abstractmethod
    async def reconcile(self, quarantine: str, published: str, keep: set[str],
                        cutoff: datetime) -> bool: ...

    @abstractmethod
    async def download_url(self, key: str, ttl: int) -> str: ...

    def publication_key(self, organization: str, ticket: str, lease: str, ext: str) -> str:
        # Cloud attempts use separate keys so a stale lease cannot overwrite a
        # different worker's publication. Local names retain backwards compatibility.
        suffix = f".{lease}" if self.direct_upload else ""
        return f"published/{organization}/{ticket}{suffix}.{ext}"


class LocalStorage(StorageProvider):
    async def upload_url(self, ticket_id, key, ttl):
        from pixl.core.storage import storage_path, upload_signature
        storage_path(key)
        return f"/api/v1/agency/media/uploads/{ticket_id}?signature={upload_signature(ticket_id)}"

    async def size(self, key):
        from pixl.core.storage import storage_path
        path = storage_path(key)
        return path.stat().st_size if path.is_file() else None

    @asynccontextmanager
    async def materialize(self, key, expected_size):
        from pixl.core.storage import storage_path
        source = storage_path(key)
        if not source.is_file() or source.stat().st_size != expected_size:
            raise UnprocessableError("Uploaded content is missing or has changed")
        yield source

    async def publish(self, key, source, mime, lease):
        from pixl.core.storage import storage_path
        target = storage_path(key)
        # Keep lease-specific staging files visible to crash reconciliation.
        temporary = target.with_name(f"{target.name}.{lease}.part")
        def copy():
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(source, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        await asyncio.to_thread(copy)

    async def delete(self, key):
        from pixl.core.storage import storage_path
        await asyncio.to_thread(storage_path(key).unlink, missing_ok=True)
        return True

    async def reconcile(self, quarantine, published, keep, cutoff):
        from pixl.core.storage import storage_path
        await self.delete(quarantine)
        for key in (published, published + ".part", published.rsplit(".", 1)[0] + ".thumbnail.webp"):
            if key not in keep:
                await self.delete(key)
        def parts():
            published_path = storage_path(published)
            ticket = Path(quarantine).stem
            for parent, pattern in ((published_path.parent, f"{ticket}.*.part*"),
                                    (storage_path(quarantine).parent, "*.part")):
                if parent.exists():
                    for part in parent.glob(pattern):
                        if part.stat().st_mtime < cutoff.timestamp():
                            part.unlink(missing_ok=True)
        await asyncio.to_thread(parts)
        return True

    async def download_url(self, key, ttl):
        from pixl.core.storage import public_media_url
        return public_media_url(key)


def get_storage() -> StorageProvider:
    from pixl.core.config import settings
    from pixl.core.exceptions import ConflictError
    if settings.STORAGE_PROVIDER == "local":
        return LocalStorage()
    if settings.STORAGE_PROVIDER == "stratus":
        from pixl.core.stratus import configured_stratus
        return configured_stratus()
    raise ConflictError("Unsupported storage provider")
