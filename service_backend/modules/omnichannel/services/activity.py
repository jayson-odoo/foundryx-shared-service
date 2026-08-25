"""Outbound-Meta activity recorders (sprint-4/12 Slice 2, AC-DLC-14/15).

The WhatsApp adapter is DB-agnostic - it reports each Graph call as a
``GraphCall`` to an optional recorder. This module owns the recorders: they
persist an ``outbound_meta`` row to the core ``integration_activity`` table via
the generic ``ActivityLogService`` seam, attributing the tenant + reading the
inbound trace id off the request contextvar (so an inbound gateway send and its
resulting outbound Meta call share ONE trace - AC-DLC-15).

Fully failure-isolated on two levels: (1) each record runs on a FRESH session
bound to the same engine, so a logging commit/rollback never touches the send's
own transaction (the send may hold uncommitted writes, e.g. a re-keyed voice
blob); (2) any exception is swallowed + logged - a logging failure can NEVER
break, slow, or fail a send.
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.activity_log.context import get_trace_id
from app.activity_log.service import ActivityLogService
from app.models.integration_activity import (
    SOURCE_EMBED_SESSION,
    SOURCE_OUTBOUND_META,
)

from ..adapters.whatsapp_cloud import GraphCall, GraphRecorder

logger = logging.getLogger(__name__)


def build_meta_recorder(
    db: Session,
    tenant_id: str,
    workspace_id: Optional[str] = None,
) -> GraphRecorder:
    """Return a recorder that logs one ``outbound_meta`` activity row per Graph
    call for ``tenant_id`` (optionally attributed to ``workspace_id``)."""
    bind = db.get_bind()

    def _record(call: GraphCall) -> None:
        try:
            fresh = Session(bind=bind)
            try:
                ActivityLogService(fresh).record(
                    tenant_id=tenant_id,
                    source=SOURCE_OUTBOUND_META,
                    operation=call.operation,
                    status=call.status,
                    trace_id=get_trace_id(),
                    workspace_id=workspace_id,
                    status_code=call.status_code,
                    latency_ms=call.latency_ms,
                    error_code=call.error_code,
                    error_message=call.error_message,
                    external_ref=call.external_ref,
                )
            finally:
                fresh.close()
        except Exception:  # noqa: BLE001 - logging must never break a send.
            logger.exception("outbound-meta activity record failed (%s)", call.operation)

    return _record


def record_embed_session(
    db: Session,
    *,
    tenant_id: Optional[str],
    workspace_id: Optional[str],
    status: str,
    status_code: Optional[int],
    parent_origin: Optional[str],
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Log ONE ``embed_session`` activity row for a ``POST /embed/session``
    exchange (AC-DLC-20) - ``success`` on a minted token, ``error`` with the typed
    ``EmbedError`` code on a failed verification. Fully failure-isolated (fresh
    session + swallow-and-log) so a logging failure can NEVER break the embed
    exchange - a security path.

    The raw assertion and ``embedSecret`` are NEVER passed here; only the parent
    origin (a URL, not a secret - redaction preserves it) is captured. When the
    failure is so early there's no resolvable tenant (malformed assertion before
    the connection lookup), ``tenant_id`` is None and ``record()`` skips."""
    if not tenant_id:
        # Unattributable (e.g. malformed assertion before iss resolution) - record
        # everything we CAN attribute, skip the rest (mirrors the inbound-401 case).
        return
    bind = db.get_bind()
    try:
        fresh = Session(bind=bind)
        try:
            ActivityLogService(fresh).record(
                tenant_id=tenant_id,
                source=SOURCE_EMBED_SESSION,
                operation="embed:session",
                status=status,
                workspace_id=workspace_id,
                status_code=status_code,
                error_code=error_code,
                error_message=error_message,
                request={"parentOrigin": parent_origin} if parent_origin else None,
            )
        finally:
            fresh.close()
    except Exception:  # noqa: BLE001 - logging must never break the embed exchange.
        logger.exception("embed-session activity record failed")
