"""Integration-activity service (sprint-4/12).

``record(...)`` is the generic, failure-isolated WRITE seam every
instrumentation point calls. The read side (``list``/``get``) backs the
Developers → Logs console via a WHITELISTED filter translator - a client can
never reach an arbitrary column.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.activity_log.redaction import redact
from app.activity_log.repository import IntegrationActivityRepository
from app.config import settings
from app.models.integration_activity import (
    ACTIVITY_STATUSES,
    IntegrationActivity,
)
from app.models.integration_log_settings import IntegrationLogSettings
from app.schemas.filters import FilterGroup
from app.services.filter_translator import translate_filter

logger = logging.getLogger("foundryx.activity_log")


# ── Volume guard (AC-DLC-26) ────────────────────────────────────────────────
# A lightweight, cheap, per-PROCESS token counter: at most
# ``integration_activity_max_writes_per_second`` rows are written per 1s window;
# beyond that a write is DROPPED (not blocked) and a counter is logged. This
# bounds the DB blast radius of a burst/error storm without any coordination -
# the write is already off the request critical path (prod BackgroundTask) +
# swallow-isolated, so dropping is graceful degradation, not data-loss on the
# hot path. Trade-off: the cap is per-process (N workers ⇒ N×cap aggregate) and
# best-effort; a Celery/background_jobs-backed async buffer is the true scale
# path (backlog BL - logged in the plan). ``max=0`` disables the guard.
_guard_lock = threading.Lock()
_guard_window_start = 0.0
_guard_window_count = 0
_guard_dropped_total = 0
_guard_dropped_since_log = 0


def _volume_guard_admits() -> bool:
    """Return True if a write is admitted this 1s window; False to drop (over the
    per-process cap). Logs a running dropped-counter every 100 drops so the drop
    is never silent (no silent cap - AC-DLC-26)."""
    cap = settings.integration_activity_max_writes_per_second
    if not cap or cap <= 0:
        return True
    global _guard_window_start, _guard_window_count
    global _guard_dropped_total, _guard_dropped_since_log
    now = time.monotonic()
    with _guard_lock:
        if now - _guard_window_start >= 1.0:
            _guard_window_start = now
            _guard_window_count = 0
        if _guard_window_count >= cap:
            _guard_dropped_total += 1
            _guard_dropped_since_log += 1
            if _guard_dropped_since_log >= 100:
                logger.warning(
                    "integration-activity volume guard dropped %d rows "
                    "(cap=%d/s, total dropped=%d) - a write burst is degrading "
                    "to drop-not-block",
                    _guard_dropped_since_log,
                    cap,
                    _guard_dropped_total,
                )
                _guard_dropped_since_log = 0
            return False
        _guard_window_count += 1
        return True

# Whitelisted filter columns (source/status/time/workspace) - the translator
# never touches anything outside this map.
_FILTER_COLUMNS = {
    "source": IntegrationActivity.source,
    "status": IntegrationActivity.status,
    "workspaceId": IntegrationActivity.workspace_id,
    "workspace_id": IntegrationActivity.workspace_id,
    "createdAt": IntegrationActivity.created_at,
    "created_at": IntegrationActivity.created_at,
}
# Columns a client may sort by (defends the getattr in the repo). Accept both
# the camelCase wire ids (the Resource-shell column ids) and the snake columns.
_SORT_COLUMNS = {
    "created_at",
    "createdAt",
    "latency_ms",
    "latencyMs",
    "status",
    "source",
}
_SORT_ALIAS = {"createdAt": "created_at", "latencyMs": "latency_ms"}


class ActivityLogService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IntegrationActivityRepository(db)

    # ── write seam (failure-isolated) ────────────────────────────────────────

    def record(
        self,
        *,
        tenant_id: Optional[str],
        source: str,
        operation: str,
        status: str,
        trace_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        api_key_id: Optional[str] = None,
        method: Optional[str] = None,
        status_code: Optional[int] = None,
        latency_ms: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        external_ref: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        request: Any = None,
        response: Any = None,
    ) -> Optional[IntegrationActivity]:
        """Write ONE activity row, own commit, swallow-and-log any failure.

        NEVER raises to the caller - a logging failure must not break, slow, or
        500 the observed request. Returns the row on success, ``None`` on either
        a swallowed error or a skip (no attributable tenant)."""
        try:
            # No attributable tenant → skip: no tenant's console could show it,
            # and the table is NOT NULL on tenant_id by design (documented).
            if not tenant_id:
                return None
            # Volume guard (AC-DLC-26) - under a burst beyond the per-process cap,
            # DROP this row (logged counter) rather than block or hammer the DB.
            if not _volume_guard_admits():
                return None
            row = IntegrationActivity(
                tenant_id=tenant_id,
                source=source,
                operation=operation,
                status=status if status in ACTIVITY_STATUSES else "error",
                trace_id=trace_id,
                workspace_id=workspace_id,
                api_key_id=api_key_id,
                method=method,
                status_code=status_code,
                latency_ms=latency_ms,
                error_code=error_code,
                error_message=(redact(error_message) if error_message else None),
                external_ref=external_ref,
                request_summary_json=(redact(request) if request is not None else None),
                response_summary_json=(
                    redact(response) if response is not None else None
                ),
            )
            # An inbound_api row is written post-response but its interaction
            # STARTED before the outbound legs it caused - stamp it at
            # request-start so the trace timeline reads in causal order (else a
            # pure created_at sort inverts inbound vs outbound). Set only when
            # provided; otherwise the column's server_default(now()) applies.
            if occurred_at is not None:
                row.created_at = occurred_at
            self.repo.add(row)
            self.db.commit()
            return row
        except Exception:  # noqa: BLE001 - full isolation, never propagate.
            logger.exception("integration-activity record failed (source=%s)", source)
            try:
                self.db.rollback()
            except Exception:  # noqa: BLE001
                pass
            return None

    # ── reads (console) ───────────────────────────────────────────────────────

    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[List[IntegrationActivity], int]:
        clause = translate_filter(filter_group, _FILTER_COLUMNS)
        sort_col = sort_by if sort_by in _SORT_COLUMNS else "created_at"
        sort_col = _SORT_ALIAS.get(sort_col, sort_col)
        return self.repo.list(
            tenant_id,
            clause=clause,
            search=search,
            sort_by=sort_col,
            sort_desc=(sort_dir != "asc"),
            page=page,
            page_size=page_size,
        )

    def get(self, tenant_id: str, row_id: str) -> Optional[IntegrationActivity]:
        return self.repo.get(tenant_id, row_id)

    def list_by_trace(
        self, tenant_id: str, trace_id: str
    ) -> List[IntegrationActivity]:
        """Ordered legs (oldest→newest) of ONE consumption - inbound API →
        outbound Meta → webhook delivery - for the trace timeline (AC-DLC-17).
        Tenant-scoped."""
        return self.repo.list_by_trace(tenant_id, trace_id)

    def trace_for_external_ref(
        self, tenant_id: str, external_ref: str
    ) -> Optional[str]:
        """Resolve the trace a stored ``external_ref`` (wamid) belongs to, so the
        async webhook leg attaches to the same consumption (AC-DLC-16)."""
        if not external_ref:
            return None
        return self.repo.trace_for_external_ref(tenant_id, external_ref)

    # ── retention settings (AC-DLC-21) ────────────────────────────────────────

    def get_retention(self, tenant_id: str) -> Tuple[int, bool]:
        """Effective retention days for the tenant + whether it's the global
        default (no per-tenant override). Mirrors WorkflowService.get_run_retention."""
        row = (
            self.db.query(IntegrationLogSettings)
            .filter_by(tenant_id=tenant_id)
            .first()
        )
        if row and row.retention_days is not None:
            return row.retention_days, False
        return settings.integration_activity_retention_days, True

    def set_retention(self, tenant_id: str, days: int) -> Tuple[int, bool]:
        """Set a per-tenant retention override (tenant-scoped). Returns the new
        effective value + is_default=False."""
        row = (
            self.db.query(IntegrationLogSettings)
            .filter_by(tenant_id=tenant_id)
            .first()
        )
        if row is None:
            row = IntegrationLogSettings(tenant_id=tenant_id, retention_days=days)
            self.db.add(row)
        else:
            row.retention_days = days
        self.db.commit()
        return days, False
