"""Sprint-5/11 S1 - RED tests for the worker-starvation fix, Celery config half
(AC-11-80, AC-11-81, AC-11-82, AC-11-87 groundwork).

Incident (plan sec 2.6, 2026-09-20/21): ``foundryx_ss_worker_workflow`` ran
``-Q workflow`` with no ``-c``, so ONE ForkPoolWorker shared ``jobs.run`` with
every beat tick; a hung ``jobs.run`` starved the platform for 8+ hours. S0's
baseline (``11-evidence/s0-baseline/README.md`` (d)) confirmed today's app has
NO ``task_routes``, prefetch defaults to 4, and no time limits anywhere -
every assertion below is RED against that baseline.

CONTRACT this file pins (the coder implements to this, not the other way
round):
- ``app/workflow_engine/worker.py``: ``celery_app.conf`` routes task name
  ``"jobs.run"`` onto queue ``"jobs"`` (``task_routes``), leaves every OTHER
  task (a tick, ``workflows.run_workflow``, ...) on the ``"workflow"``
  default queue, sets ``worker_prefetch_multiplier = 1``, and declares
  app-level ``task_soft_time_limit = 300`` / ``task_time_limit = 330`` (the
  tick family). ``jobs.run`` stays REGISTERED on this same Celery app (the
  lossless-rollout requirement) - the isolation is queue routing, not a
  second app.
- ``app/jobs/worker.py``: the ``jobs.run`` task itself declares
  ``soft_time_limit=settings.background_job_soft_time_limit_seconds`` and
  ``time_limit=<that + 300>``, and ``acks_late`` stays the Celery default
  (False) - AC-11-81/D17.
- ``app/config.py``: a new ``background_job_soft_time_limit_seconds: int =
  7200`` setting.
"""
from __future__ import annotations

import app.jobs.worker  # noqa: F401 - registers "jobs.run" on celery_app (see
# worker.py's own comment: without this import a worker DISCARDS jobs.run as
# unregistered - the nastiest footgun in this codebase, per the plan itself).
from app.workflow_engine.worker import celery_app


def _resolved_queue(task_name: str) -> str:
    """The queue name Celery would actually publish ``task_name`` onto with
    NO explicit ``apply_async(queue=...)`` override - i.e. what ``task_routes``
    (or the app default) decides. Mirrors how ``JobService.enqueue`` calls
    ``.delay()`` (no queue kwarg) for a job type with no per-type override."""
    return celery_app.amqp.router.route({}, task_name)["queue"].name


# ── AC-11-80: jobs.run gets its own queue, stays registered on this app ─────


def test_jobs_run_routes_to_the_jobs_queue_by_default():
    assert _resolved_queue("jobs.run") == "jobs", (
        "jobs.run must route onto the dedicated 'jobs' queue (AC-11-80) - "
        "S0 confirmed no task_routes exists today, so this resolves to the "
        "app default 'workflow' until the fix lands"
    )


def test_a_tick_task_still_resolves_to_the_workflow_queue():
    """Control: the routing change must be jobs.run-specific. A blanket
    default-queue change would silently move every beat tick too, which is
    exactly the coupling this slice removes."""
    assert _resolved_queue("workflows.run_due") == "workflow"
    assert _resolved_queue("autocount.etl_sweep") == "workflow"


def test_jobs_run_stays_registered_on_the_workflow_celery_app():
    """Lossless rollout: worker_workflow keeps -Q workflow and keeps jobs.run
    registered, so a message already queued there at deploy time still runs.
    (This assertion alone already passes today - jobs.run has always lived
    on this app; it is here as the rollout-safety pin the plan calls for,
    exercised beside the routing change so a future refactor cannot split
    jobs.run onto a second Celery app without this test catching it.)"""
    assert "jobs.run" in celery_app.tasks


# ── AC-11-81: never hold a second message ───────────────────────────────


def test_worker_prefetch_multiplier_is_one():
    assert celery_app.conf.worker_prefetch_multiplier == 1, (
        "S0 confirmed this is unset today (Celery default 4) - the default "
        "prefetch is what let a blocked child hold several beat messages in "
        "its buffer during the incident (plan sec 2.6, claim 2)"
    )


def test_jobs_run_does_not_ack_late():
    """D17: redelivery after a hard kill plus run_job's RUNNING crash-resume
    equals a double push. acks_late must stay OFF (the Celery default) for
    jobs.run - the undispatched sweep is the safe recovery for a lost
    message, not redelivery."""
    assert celery_app.tasks["jobs.run"].acks_late is False


# ── AC-11-82: time limits, per task kind ─────────────────────────────────


def test_the_tick_family_gets_app_level_soft_and_hard_limits():
    assert celery_app.conf.task_soft_time_limit == 300, (
        "S0 confirmed neither limit is set today (grepped worker.py: zero "
        "matches for 'time_limit')"
    )
    assert celery_app.conf.task_time_limit == 330


def test_jobs_run_declares_its_own_generous_bound_from_settings():
    from app.config import settings

    soft = settings.background_job_soft_time_limit_seconds
    assert soft == 7200, (
        "app/config.py must declare background_job_soft_time_limit_seconds "
        "(default 7200s / 2h, per R10 and AC-11-82) - missing today"
    )
    task = celery_app.tasks["jobs.run"]
    assert task.soft_time_limit == soft, (
        "jobs.run's own declared soft_time_limit must come FROM this "
        "setting, not the 300s tick-family app default and not a hardcoded "
        "literal - a legitimate 25+ minute Mocha build must survive it"
    )
    assert task.time_limit == soft + 300, (
        "hard limit = soft + 300s (R10/AC-11-82's own arithmetic: 7200 -> "
        "7500), not a second independent setting"
    )


# ── Review round 1 (B2): workflows.run_workflow / workflows.wake_serialized
# no longer silently inherit the 300s/330s tick-family app default - each
# declares its own generous, settings-driven bound, mirroring jobs.run.


def test_run_workflow_declares_its_own_bound_from_settings():
    from app.config import settings

    soft = settings.workflow_run_soft_time_limit_seconds
    assert soft == 1800, (
        "app/config.py must declare workflow_run_soft_time_limit_seconds "
        "(default 1800s / 30 min, review round 1 B2)"
    )
    task = celery_app.tasks["workflows.run_workflow"]
    assert task.soft_time_limit == soft, (
        "workflows.run_workflow must NOT silently inherit the 300s "
        "tick-family app default - a legitimate multi-node run must survive it"
    )
    assert task.time_limit == soft + 300


def test_wake_serialized_declares_its_own_bound_from_settings():
    from app.config import settings

    soft = settings.workflow_run_soft_time_limit_seconds
    task = celery_app.tasks["workflows.wake_serialized"]
    assert task.soft_time_limit == soft, (
        "workflows.wake_serialized must NOT silently inherit the 300s "
        "tick-family app default - a legitimate multi-run drain must survive it"
    )
    assert task.time_limit == soft + 300


def test_the_tick_family_app_default_is_unchanged_by_the_new_settings():
    """Control: adding per-task bounds to workflows.run_workflow and
    workflows.wake_serialized must not move the app-level default every
    OTHER tick (a tick, jobs.sweep_orphaned, ops.ping, ...) still inherits."""
    assert celery_app.conf.task_soft_time_limit == 300
    assert celery_app.conf.task_time_limit == 330
