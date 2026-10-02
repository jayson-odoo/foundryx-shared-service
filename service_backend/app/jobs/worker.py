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

Prod hotfix (PR #80 part 2, 2026-09-21): since `worker_jobs` (PR #76)
consumes ONLY the `jobs` queue, no `workflows.run_workflow`/
`wake_serialized` task EVER executes in this process to warm
`_ensure_module_nodes()` as a side effect the way it does on the shared
`workflow` worker. A handler that registers only inside a module's
`register_engine_entities()` (reachable exclusively through
`boot_module_hooks()`) - e.g. omnichannel's contacts-export/broadcast-send/
report-export/respond.io-migration job handlers - was PERMANENTLY unknown
here, not a race: `UnknownJobType` on every single dispatch. `sql_db`/
`autocount_http`/the meetings handlers dodge this because they register at
their OWN module's import time and that module is explicitly imported at
the bottom of `app/workflow_engine/worker.py` - but a NEW module's handler
living only in `register_engine_entities()` would hit the exact same gap
again. Boot every module's hooks once per process, right here, before ANY
job type is dispatched - the single structural fix, not a fifth explicit
import to hand-maintain.
"""
import logging

from app.config import settings
from app.workflow_engine.worker import _ensure_module_nodes, celery_app

logger = logging.getLogger("foundryx.jobs")


@celery_app.task(
    name="jobs.run",
    soft_time_limit=settings.background_job_soft_time_limit_seconds,
    time_limit=settings.background_job_soft_time_limit_seconds + 300,
)
def run_job_task(job_id: str) -> None:
    # Failure-isolated (D8, same discipline as `boot_module_hooks` itself):
    # a broken module's hook must never take this job down with it - the job
    # still runs with whatever core + already-booted handlers exist, and the
    # broken module surfaces in `ERRORED_MODULES` the way `load_modules`
    # already reports it on the API side.
    try:
        _ensure_module_nodes()
    except Exception:
        logger.exception("Module hook boot failed before jobs.run; continuing with core-only handlers.")

    from app.database import SessionLocal
    from app.jobs.service import run_job

    db = SessionLocal()
    try:
        run_job(db, job_id)
    finally:
        db.close()
