"""Observability — every AutoCount interaction lands in the Developer Logs
console under the ``autocount`` source (AC-13-42, AC-13-46).

Two rules, both non-negotiable:

1. **Masked, always.** Payloads go through ``mask_payload`` BEFORE they reach
   the write seam (which redacts again — belt and braces, since the two use
   different key lists). AppId, Password, Token and JWTToken must never appear
   in plaintext in a log, an activity row, an error message, or an API response.
2. **Never raises.** ``ActivityLogService.record`` is already swallow-isolated;
   this wrapper adds its own guard so an observability failure can never break,
   slow or fail a sync (AC-13-43).

    !!  CALL-SITE CONSTRAINT — read before adding a call.  !!

``ActivityLogService.record`` **commits the session you hand it** (and
``rollback``s it if the activity write fails). That is the shared house
behaviour, not something this module chose. The consequence is sharp: calling
this in the MIDDLE of uncommitted work will either commit that work early or
throw it away.

So every call must sit at a transaction boundary — right after a ``commit()``,
or before any pending change exists. Every call site in this module currently
does; keep it that way. If a future slice needs to log mid-transaction, give it
its own session (``Session(bind=db.get_bind())``, the pattern the workflow
event drain uses) rather than moving the boundary.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.activity_log.service import ActivityLogService
from app.integrations.masking import mask_payload
from app.models.integration_activity import (
    ACTIVITY_ERROR,
    ACTIVITY_SUCCESS,
    SOURCE_AUTOCOUNT,
)

logger = logging.getLogger("foundryx.autocount")

__all__ = ["record_activity", "ACTIVITY_SUCCESS", "ACTIVITY_ERROR"]


def record_activity(
    db: Session,
    *,
    tenant_id: str,
    operation: str,
    status: str,
    external_ref: Optional[str] = None,
    trace_id: Optional[str] = None,
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
    except Exception:  # noqa: BLE001 — observability NEVER breaks the caller
        logger.exception("failed to record autocount activity for %s", operation)
