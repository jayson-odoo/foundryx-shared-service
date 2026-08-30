"""Observability - every AutoCount interaction lands in the Developer Logs
console under the ``autocount`` source (AC-13-42, AC-13-46).

Two rules, both non-negotiable:

1. **Masked, always.** Payloads go through ``mask_payload`` BEFORE they reach
   the write seam (which redacts again - belt and braces, since the two use
   different key lists). AppId, Password, Token and JWTToken must never appear
   in plaintext in a log, an activity row, an error message, or an API response.
2. **Never raises.** ``ActivityLogService.record`` is already swallow-isolated;
   this wrapper adds its own guard so an observability failure can never break,
   slow or fail a sync (AC-13-43).

    !!  CALL-SITE CONSTRAINT - read before adding a call.  !!

``ActivityLogService.record`` **commits the session you hand it** (and
``rollback``s it if the activity write fails). That is the shared house
behaviour, not something this module chose. The consequence is sharp: calling
this in the MIDDLE of uncommitted work will either commit that work early or
throw it away.

So every call must sit at a transaction boundary - right after a ``commit()``,
or before any pending change exists. Every call site in this module currently
does; keep it that way. If a future slice needs to log mid-transaction, give it
its own session (``Session(bind=db.get_bind())``, the pattern the workflow
event drain uses) rather than moving the boundary.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy.orm import Session

from app.activity_log.service import ActivityLogService
from app.integrations.masking import mask_payload
from app.models.integration_activity import (
    ACTIVITY_ERROR,
    ACTIVITY_SUCCESS,
    SOURCE_AUTOCOUNT,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from .client import AutoCountClient

logger = logging.getLogger("foundryx.autocount")

__all__ = [
    "record_activity",
    "record_client_calls",
    "trace_id_for_job",
    "ACTIVITY_SUCCESS",
    "ACTIVITY_ERROR",
]


def trace_id_for_job(job_id: str) -> str:
    """The trace every leg of ONE sync run shares.

    Derived from the job id rather than minted at random so an operator holding
    a job id (from the Runs tab, a job row, or a support ticket) can find its
    calls in the Developer Logs console without a lookup table.
    """
    return f"acsync-{job_id}"


def record_activity(
    db: Session,
    *,
    tenant_id: str,
    operation: str,
    status: str,
    external_ref: Optional[str] = None,
    trace_id: Optional[str] = None,
    method: Optional[str] = None,
    status_code: Optional[int] = None,
    latency_ms: Optional[int] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    request: Any = None,
    response: Any = None,
) -> None:
    """Write ONE masked activity row. Never raises."""
    try:
        ActivityLogService(db).record(
            tenant_id=tenant_id,
            source=SOURCE_AUTOCOUNT,
            operation=operation,
            status=status,
            trace_id=trace_id,
            external_ref=external_ref,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
            error_code=error_code,
            # Even an error MESSAGE can carry a credential (a vendor echo of the
            # request); mask it like a payload.
            error_message=(
                str(mask_payload(error_message)) if error_message else None
            ),
            request=(mask_payload(request) if request is not None else None),
            response=(mask_payload(response) if response is not None else None),
        )
    except Exception:  # noqa: BLE001 - observability NEVER breaks the caller
        logger.exception("failed to record autocount activity for %s", operation)


def record_client_calls(
    db: Session,
    client: Any,
    *,
    tenant_id: str,
    trace_id: Optional[str] = None,
    external_ref: Optional[str] = None,
) -> int:
    """Drain a client's OR a source's buffered calls into activity rows.
    Never raises.

    Accepts an ``AutoCountClient`` (``drain_calls``) or any ``EntitySource``
    exposing the optional duck-typed ``drain_activity`` (plan 22 §2.1) - both
    yield ``CallRecord``-shaped objects. An object with neither records nothing.

    ONE row per real request/response, carrying the ACTUAL masked payloads plus
    ``status_code``, ``latency_ms`` and the run's ``trace_id`` - which is what
    the Developer Logs console is built to render, and what a customer's mapping
    failure cannot be diagnosed without.

        !!  CALL THIS AT A TRANSACTION BOUNDARY.  !!

    ``record_activity`` commits (see the module docstring), so a call placed in
    the middle of uncommitted work will commit or discard it. Every call site
    sits immediately after a ``commit()``.

    ``client.drain_calls()`` clears the buffer, so calling this twice cannot
    duplicate a row. Returns the number of rows attempted.
    """
    try:
        drain = getattr(client, "drain_activity", None) or getattr(
            client, "drain_calls", None
        )
        calls = drain() if drain is not None else []
    except Exception:  # noqa: BLE001
        logger.exception("failed to drain autocount client calls")
        return 0

    for call in calls:
        record_activity(
            db,
            tenant_id=tenant_id,
            operation=f"{call.method} {call.path}",
            status=ACTIVITY_SUCCESS if call.ok else ACTIVITY_ERROR,
            trace_id=trace_id,
            external_ref=external_ref,
            method=call.method,
            status_code=call.status_code,
            latency_ms=call.latency_ms,
            error_message=call.error_message,
            # Already masked AND bounded by the client; ``record_activity``
            # masks again (belt and braces - the two use different key lists).
            request=call.request,
            response=call.response,
        )
    return len(calls)
