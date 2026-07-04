"""Celery worker (plan 05 decision 8): Redis broker, exponential-backoff retries.

Run alongside uvicorn:
    celery -A modules.omnichannel.worker worker --loglevel info

The webhook endpoint fast-ACKs and enqueues `process_inbound_webhook`; this
task owns parse → resolve → persist → broadcast. DB down → autoretry with
backoff (≈5s/10s/.../10m, spec §3.3); the payload stays safe in Redis until
the task succeeds or exhausts retries.
"""
from celery import Celery

from app.config import settings

celery_app = Celery(
    "omnichannel",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(
    name="omnichannel.process_inbound_webhook",
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=6,
)
def process_inbound_webhook(channel_id: str, payload: dict) -> dict:
    # Import inside the task so the Celery worker process loads the app stack
    # (and its DB engine) lazily, not at module import.
    from app.database import SessionLocal
    from modules.omnichannel.services.inbound_service import InboundService

    db = SessionLocal()
    try:
        return InboundService(db).process_payload(channel_id, payload)
    finally:
        db.close()
