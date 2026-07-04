"""Payment webhook Celery worker (sprint-4/07 Cluster F slice 3) — CORE.

Mirrors the omnichannel pattern: the webhook route fast-ACKs + enqueues; this
task owns verify → log → dispatch. Out-of-order events (``RetryableWebhook``)
autoretry with backoff (AC-07-34); under tests Celery is EAGER so the task runs
inline on the request session.

Run alongside uvicorn in prod:
    celery -A app.services.payment_worker worker --loglevel info
"""
from celery import Celery

from app.config import settings

celery_app = Celery(
    "payments",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(
    name="payments.process_webhook",
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=6,
)
def process_payment_webhook(provider: str, connection_id: str, body_b64: str, headers: dict) -> dict:
    import base64

    from app.database import SessionLocal
    from app.services.payment_gateway_service import PaymentGatewayService

    body = base64.b64decode(body_b64.encode())
    db = SessionLocal()
    try:
        return PaymentGatewayService(db).ingest_webhook(provider, connection_id, body, headers)
    finally:
        db.close()
