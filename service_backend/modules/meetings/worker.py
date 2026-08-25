"""The ``bots`` Celery worker (S2 plan §5, AC-S2-14).

A THIRD Celery app beside ``workflow`` and ``omni``, on the same Redis, with its
own queue. The separation is not tidiness: a bot task blocks for the length of a
meeting and needs a Docker socket, so it must never land on the app server's
workers, and the app server's tasks must never land here.

    celery -A modules.meetings.worker worker -Q bots -c 2 --loglevel info

Boot is checked LOUDLY. A worker consuming the wrong queue, or one that cannot
reach Docker, looks exactly like a healthy idle worker from the outside - and the
symptom is meetings that are never joined, discovered hours later.
"""
from __future__ import annotations

import logging

from celery import Celery
from celery.signals import worker_init

from app.config import settings

logger = logging.getLogger("foundryx.meetings")

BOTS_QUEUE = "bots"

celery_app = Celery(
    "meetings",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    # A failed run is recorded on the meeting, not raised at the worker.
    task_eager_propagates=False,
    broker_connection_retry_on_startup=True,
    # Dedicated queue — this worker consumes ONLY this, and the workflow/omni
    # workers never see a bot run. Both other apps share the same broker, so
    # without per-app queues the tasks cross over and get discarded unregistered.
    task_default_queue=BOTS_QUEUE,
    # One bot per worker slot for the whole meeting: prefetching a second job a
    # slot cannot start for an hour would hide it from an idle sibling worker.
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)


class WorkerBootError(RuntimeError):
    """The worker cannot do its job. Raised at boot so it dies visibly rather
    than sitting there looking healthy while no meeting is ever joined."""


def check_worker_boot(queues, *, client_factory=None) -> None:
    """AC-S2-14: exactly the ``bots`` queue, and a reachable Docker daemon."""
    names = sorted(set(queues or ()))
    if names != [BOTS_QUEUE]:
        raise WorkerBootError(
            f"The bots worker must consume only the '{BOTS_QUEUE}' queue "
            f"(got {names or 'none'}). Start it with -Q {BOTS_QUEUE}."
        )
    if client_factory is None:
        from .services.bot_runner import docker_client as client_factory
    try:
        client_factory().info()
    except Exception as exc:  # noqa: BLE001 — any reason is the same problem
        raise WorkerBootError(
            f"The bots worker cannot reach Docker: {exc}. "
            "Check DOCKER_HOST and that the socket is mounted."
        ) from exc


@worker_init.connect
def _check_boot(sender=None, **_kwargs) -> None:
    """Run the boot check for a real ``celery worker`` process only.

    ``worker_init`` fires once per worker; ``sender.app.amqp.queues`` is already
    narrowed to whatever ``-Q`` selected by this point."""
    app = getattr(sender, "app", None)
    queues = list(getattr(app.amqp, "queues", {}).keys()) if app else []
    check_worker_boot(queues)
    logger.info("meetings bots worker ready: queue=%s, docker reachable", BOTS_QUEUE)


@celery_app.task(name="meetings.bot_run")
def run_bot_job(job_id: str) -> None:
    """Run ONE ``meetings.bot_run`` background job on a fresh session.

    A worker process has its own engine, and the job blocks for the meeting, so
    the session is opened and closed around this one job rather than shared."""
    from app.database import SessionLocal
    from app.jobs.service import run_job

    db = SessionLocal()
    try:
        run_job(db, job_id)
    finally:
        db.close()


# The worker boots NO FastAPI lifespan, so the handlers only exist here if their
# module is imported. Without this the job is claimed and then fails with "no
# handler for type" - the loudest possible version of a silent stall, but still
# a wasted meeting.
import modules.meetings.jobs  # noqa: E402,F401
