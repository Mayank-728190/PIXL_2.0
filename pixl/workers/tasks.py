import time
from pixl.workers.celery_app import celery_app


@celery_app.task(name="tasks.process_media_asset")
def process_media_asset(media_id: str):
    """
    Background worker task: executes ffprobe, calculates exact content SHA-256,
    generates WebP thumbnails, and moves asset from quarantine to published bucket.
    """
    time.sleep(1)  # Simulate processing duration
    return {"media_id": media_id, "status": "READY"}


@celery_app.task(name="tasks.compile_scheduled_manifests")
def compile_scheduled_manifests():
    """
    Periodic task to pre-compile upcoming day manifests.
    """
    return {"compiled_count": 0}


@celery_app.task(name="tasks.aggregate_hourly_pop")
def aggregate_hourly_pop():
    """
    Periodic task: generates hourly aggregates from raw playback_events table.
    """
    return {"aggregated_count": 0}

