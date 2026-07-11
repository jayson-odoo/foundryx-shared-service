"""Background-job Celery task (sprint-4/10) — decoupled; eager-inline in dev/test.

Reuses the workflow engine's Celery app. The task opens a FRESH session (a
worker process has its own pool); the service re-scopes inside the job's tenant.

    celery -A app.workflow_engine.worker worker --loglevel info
"""
from app.workflow_engine.worker import celery_app


@celery_app.task(name="jobs.run")
def run_job_task(job_id: str) -> None:
    from app.database import SessionLocal
    from app.jobs.service import run_job

    db = SessionLocal()
    try:
        run_job(db, job_id)
    finally:
        db.close()
