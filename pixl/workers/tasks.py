"""Real scheduled work; the database, not broker delivery, owns job state."""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Register the complete schema in a standalone worker process.
import pixl.core.identifiers  # noqa: F401
import pixl.modules.auth.models  # noqa: F401
import pixl.modules.ingestion.models  # noqa: F401
import pixl.modules.playlists.models  # noqa: F401
from pixl.core.config import settings
from pixl.modules.media.models import UploadTicket
from pixl.modules.media.service import MediaService
from pixl.workers.celery_app import celery_app
from pixl.workers.maintenance import maintain_lifecycle


async def with_database(operation):
    # Celery calls asyncio.run per task. A fresh unpooled engine prevents asyncpg
    # connections being reused across closed event loops or forked processes.
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await operation(db)
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.process_media_asset", ignore_result=True)
def process_media_asset(ticket_id: str):
    return asyncio.run(with_database(lambda db: MediaService.process_queued_upload(db, ticket_id)))


@celery_app.task(name="tasks.dispatch_media_jobs", ignore_result=True)
def dispatch_media_jobs():
    async def outstanding(db):
        return list((await db.scalars(select(UploadTicket.id).where(
            MediaService.runnable_jobs(datetime.now(timezone.utc))
        ).order_by(UploadTicket.updated_at).limit(100))).all())

    ids = asyncio.run(with_database(outstanding))
    for ticket_id in ids:
        process_media_asset.apply_async(args=[ticket_id], expires=60)
    return {"dispatched": len(ids)}


@celery_app.task(name="tasks.maintain_lifecycle", ignore_result=True)
def maintenance():
    return asyncio.run(with_database(maintain_lifecycle))
