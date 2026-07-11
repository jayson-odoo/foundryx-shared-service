"""Generic, failure-isolated integration-activity log seam (sprint-4/12).

Mirrors the ``app/jobs/`` package shape. ``ActivityLogService.record(...)`` is
the ONE write seam every instrumentation point (gateway middleware, outbound
Meta, embed session) calls — it redacts, writes one ``integration_activity``
row on its own commit, and swallows any exception so logging can NEVER break,
slow, or 500 the request it observes.
"""
from app.activity_log.context import get_trace_id, set_trace_id, trace_id_var
from app.activity_log.redaction import redact
from app.activity_log.service import ActivityLogService

__all__ = [
    "ActivityLogService",
    "redact",
    "trace_id_var",
    "get_trace_id",
    "set_trace_id",
]
