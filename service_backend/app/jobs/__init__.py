"""Centralized background jobs (sprint-4/10).

A generic ``type``-dispatched async job framework: one ``background_jobs`` table,
a handler registry, a service (create/claim/enqueue/progress/finish/resume) and a
Celery worker — mirrors the import-engine job pattern so every future job type
reuses the machinery. Storage migration is the first registered ``type``.
"""
from app.jobs.registry import (
    JobHandlerDef,
    handler_for,
    list_job_handlers,
    register_job_handler,
)
from app.jobs.service import JobService, run_job

__all__ = [
    "JobHandlerDef",
    "JobService",
    "handler_for",
    "list_job_handlers",
    "register_job_handler",
    "run_job",
]
