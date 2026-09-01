"""Trace-id propagation via a ``contextvars.ContextVar`` (sprint-4/12).

The gateway middleware mints a trace id per inbound request and sets it here;
Slice 2's ``WhatsAppCloudAdapter`` reads it so the outbound Meta call lands on
the SAME trace. A ContextVar is task-local, so concurrent requests never bleed
their trace ids into one another.
"""
import contextvars
from typing import Optional

# Default None - most code paths (background jobs, seed, tests) have no trace.
trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "integration_trace_id", default=None
)


def set_trace_id(trace_id: Optional[str]) -> contextvars.Token:
    """Set the current trace id, returning a reset token (the middleware resets
    it after the request so a pooled worker thread never leaks it)."""
    return trace_id_var.set(trace_id)


def get_trace_id() -> Optional[str]:
    return trace_id_var.get()
