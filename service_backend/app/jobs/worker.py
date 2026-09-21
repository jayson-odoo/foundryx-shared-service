"""Background-job Celery task (sprint-4/10) - decoupled; eager-inline in dev/test.

Reuses the workflow engine's Celery app. The task opens a FRESH session (a
worker process has its own pool); the service re-scopes inside the job's tenant.

    celery -A app.workflow_engine.worker worker -Q jobs -c 2 --loglevel info

sprint-5/11 S1 (the worker-starvation fix, plan sec 2.6): `task_routes` (in
`app.workflow_engine.worker`) sends this task onto the dedicated `jobs`
queue, consumed by the compose `worker_jobs` service - never the shared
`workflow` queue every beat tick lives on. Its own declared soft/hard time
limit (AC-11-82) is generous and settings-driven (a 25+ minute Mocha build
must survive it); `run_job` handles `SoftTimeLimitExceeded` cooperatively
(app/jobs/service.py) so a wedged job fails cleanly instead of holding this
worker's slot forever.
"""
from app.config import settings
from app.workflow_engine.worker import celery_app


@celery_app.task(
    name="jobs.run",
    soft_time_limit=settings.background_job_soft_time_limit_seconds,
    time_limit=settings.background_job_soft_time_limit_seconds + 300,
)
def run_job_task(job_id: str) -> None:
    from app.database import SessionLocal
    from app.jobs.service import run_job

    db = SessionLocal()
    try:
        run_job(db, job_id)
    finally:
        db.close()
