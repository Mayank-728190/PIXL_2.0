"""Bounded, idempotent lifecycle maintenance. No playback depends on Beat timing."""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from pixl.core.storage import MIME_EXTENSIONS, storage_path
from pixl.modules.campaigns.models import Campaign, ScreenAssignment
from pixl.modules.media.models import MediaAsset, UploadTicket
from pixl.modules.screens.models import EnrollmentChallenge, Screen


async def maintain_lifecycle(db):
    now = datetime.now(timezone.utc)
    candidates = (await db.scalars(select(Campaign.id).where(
        Campaign.status == "PUBLISHED", Campaign.end_time <= now
    ).order_by(Campaign.end_time).limit(200))).all()
    archived = []
    if candidates:
        archived = (await db.scalars(update(Campaign).execution_options(synchronize_session="fetch").where(
            Campaign.id.in_(candidates), Campaign.status == "PUBLISHED", Campaign.end_time <= now
        ).values(status="ARCHIVED").returning(Campaign.id))).all()
        if archived:
            targets = select(ScreenAssignment.screen_id).where(ScreenAssignment.campaign_id.in_(archived))
            await db.execute(update(Screen).where(Screen.id.in_(targets)).values(
                current_manifest_version=Screen.current_manifest_version + 1))
    challenges = await db.execute(update(EnrollmentChallenge).execution_options(synchronize_session="fetch").where(
        EnrollmentChallenge.status.in_(["PENDING", "CLAIMED"]), EnrollmentChallenge.expires_at <= now
    ).values(status="EXPIRED"))
    # A killed inline request has no queue worker to reclaim its lease.
    await db.execute(update(UploadTicket).execution_options(synchronize_session="fetch").where(
        UploadTicket.status == "PROCESSING", UploadTicket.processing_attempts == 0,
        UploadTicket.lease_expires_at <= now
    ).values(status="UPLOADED", lease_token=None, lease_expires_at=None))
    # One hour of grace protects slow uploads. QUEUED/leased jobs do not expire
    # when the original upload capability expires.
    cutoff = now - timedelta(hours=1)
    expired = await db.execute(update(UploadTicket).execution_options(synchronize_session="fetch").where(
        UploadTicket.status.in_(["PENDING", "UPLOADED", "UPLOADING"]),
        UploadTicket.expires_at <= cutoff, UploadTicket.updated_at <= cutoff
    ).values(status="EXPIRED"))
    await db.commit()

    tickets = (await db.scalars(select(UploadTicket).where(
        UploadTicket.status.in_(["EXPIRED", "FAILED", "FINALIZED"]),
        UploadTicket.quarantine_cleaned_at.is_(None), UploadTicket.updated_at <= cutoff
    ).order_by(UploadTicket.updated_at).limit(100))).all()
    cleaned = 0
    for ticket in tickets:
        keys = [ticket.storage_key]
        published = f"published/{ticket.organization_id}/{ticket.id}.{MIME_EXTENSIONS[ticket.declared_mime]}"
        if not await db.scalar(select(MediaAsset.id).where(MediaAsset.storage_key == published)):
            keys.extend([published, published + ".part",
                         published.rsplit(".", 1)[0] + ".thumbnail.webp"])
        try:
            for key in keys:
                await asyncio.to_thread(storage_path(key).unlink, missing_ok=True)
            # Killed processors can leave lease-specific staging files.
            published_parent = storage_path(published).parent
            if published_parent.exists():
                for part in published_parent.glob(f"{ticket.id}.*.part*"):
                    if part.stat().st_mtime < cutoff.timestamp():
                        await asyncio.to_thread(part.unlink, missing_ok=True)
            # Upload .part files have random names. Only remove old files in the
            # ticket's own quarantine directory, never published media.
            parent = storage_path(ticket.storage_key).parent
            if parent.exists():
                for part in parent.glob("*.part"):
                    if part.stat().st_mtime < cutoff.timestamp():
                        await asyncio.to_thread(part.unlink, missing_ok=True)
            # Keep audit rows while releasing reservations only after deletion.
            ticket.quarantine_cleaned_at = now
            cleaned += 1
        except OSError:
            # Leave the row at the front for a later reconciliation attempt.
            continue
    await db.commit()
    return {"archived_campaigns": len(archived), "expired_challenges": challenges.rowcount,
            "expired_uploads": expired.rowcount, "reconciled_uploads": cleaned}
