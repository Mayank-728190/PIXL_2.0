from celery import Celery
from pixl.core.config import settings

celery_app = Celery(
    "pixl_workers",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["pixl.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_default_queue="pixl",
    task_track_started=True,
    task_soft_time_limit=240,
    task_time_limit=300,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    result_expires=3600,
    beat_schedule={
        "dispatch-durable-media-jobs": {
            "task": "tasks.dispatch_media_jobs", "schedule": 10.0, "options": {"expires": 30},
        },
        "maintain-lifecycle": {
            "task": "tasks.maintain_lifecycle", "schedule": 300.0, "options": {"expires": 240},
        },
    },
)
