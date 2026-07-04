"""Import Celery tasks (sprint-3/09 D7) — decoupled; eager-inline in dev/test.

Reuses the workflow engine's Celery app. Each task opens a FRESH session (a
worker process has its own pool); the service re-scopes inside the job's tenant.
"""
from app.database import SessionLocal
from app.workflow_engine.worker import celery_app


@celery_app.task(name="imports.validate")
def import_validate_task(job_id: str) -> None:
    db = SessionLocal()
    try:
        from app.import_engine.service import ImportService

        ImportService(db).run_validate(db, job_id)
    finally:
        db.close()


@celery_app.task(name="imports.commit")
def import_commit_task(job_id: str) -> None:
    db = SessionLocal()
    try:
        from app.import_engine.service import ImportService

        ImportService(db).run_commit(db, job_id)
    finally:
        db.close()
