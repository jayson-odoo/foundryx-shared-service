"""Volume guard (sprint-4/12 Slice 3, AC-DLC-26).

Under a burst beyond the per-process cap the writer DROPS the row (returns None,
no DB write) rather than blocking or hammering the DB — best-effort graceful
degradation. Proven deterministically with a tiny cap.
"""
import app.activity_log.service as svc_mod
from app.activity_log.service import ActivityLogService
from app.config import settings
from app.models.integration_activity import (
    IntegrationActivity,
    SOURCE_INBOUND_API,
)
from tests.conftest import DEFAULT_TENANT_ID


def _reset_guard():
    svc_mod._guard_window_start = 0.0
    svc_mod._guard_window_count = 0
    svc_mod._guard_dropped_total = 0
    svc_mod._guard_dropped_since_log = 0


def test_volume_guard_drops_over_cap(session_factory):
    db = session_factory()
    svc = ActivityLogService(db)
    original = settings.integration_activity_max_writes_per_second
    settings.integration_activity_max_writes_per_second = 2
    _reset_guard()
    try:
        results = [
            svc.record(
                tenant_id=DEFAULT_TENANT_ID,
                source=SOURCE_INBOUND_API,
                operation=f"POST /m{i}",
                status="success",
            )
            for i in range(5)
        ]
        # First two admitted (a row), the rest dropped (None) within the 1s window.
        admitted = [r for r in results if r is not None]
        dropped = [r for r in results if r is None]
        assert len(admitted) == 2
        assert len(dropped) == 3
        # Only the admitted rows are persisted.
        assert db.query(IntegrationActivity).count() == 2
    finally:
        settings.integration_activity_max_writes_per_second = original
        _reset_guard()
        db.close()


def test_volume_guard_disabled_when_cap_zero(session_factory):
    db = session_factory()
    svc = ActivityLogService(db)
    original = settings.integration_activity_max_writes_per_second
    settings.integration_activity_max_writes_per_second = 0  # disabled
    _reset_guard()
    try:
        for i in range(4):
            assert (
                svc.record(
                    tenant_id=DEFAULT_TENANT_ID,
                    source=SOURCE_INBOUND_API,
                    operation=f"POST /n{i}",
                    status="success",
                )
                is not None
            )
        assert db.query(IntegrationActivity).count() == 4
    finally:
        settings.integration_activity_max_writes_per_second = original
        _reset_guard()
        db.close()
