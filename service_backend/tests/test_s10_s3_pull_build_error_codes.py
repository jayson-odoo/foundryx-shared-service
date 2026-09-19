"""Sprint-5/10 S3 follow-up - the two unpinned branches of the pull build
job's error-code ladder (AC-10-22 / AC-10-64): ``ENRICH_FAILED`` and
``ROW_LIMIT``. ``SOURCE_PAGE_FAILED`` and ``EMPTY_EXTRACT`` are already
pinned in ``test_s10_s3_snapshot_build_job.py``; this file completes the
set the gateway's error switch (S4) depends on.

Driven at the source-FACTORY seam (``sync.source_factory``, the SAME name
``sync.py`` imports and calls) rather than by actually walking a 200,000+
row extract or scripting the lookup endpoint's own page mechanics - a fake
``EntitySource`` that raises the EXACT ``HttpSourceError`` shape the real
walker would raise isolates ``_run_pull_snapshot``'s error-CLASSIFICATION
logic (``_classify_http_source_error``) from the walker's own internals,
which are already covered elsewhere (``test_s10_http_retry.py`` for
ROW_LIMIT's real trigger, ``http_source/source.py``'s own ``phase="enrich"``
tag for ENRICH_FAILED).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.http_source.errors import HttpSourceError
from modules.autocount.models import ETL_STATUS_ACTIVE, AcCompany, AcEntityConfig, AcFieldMapping

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _product_task(db, company, connection_id) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE, delivery_mode="pull",
        source_config={
            "connectionId": connection_id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [],
        },
        last_preview_at=NOW, result_columns=["ItemCode", "Description"],
    )
    db.add(config)
    db.commit()
    db.add(AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        scope="header", sort_order=0, source_path="ItemCode", canonical_field="code",
        transform="string", is_required=True,
    ))
    db.commit()
    db.refresh(config)
    return config


def _fake_source_raising(exc: HttpSourceError):
    class _FakeSource:
        entity_type = ENTITY_PRODUCT

        def fetch_changes(self, since):
            raise exc

        def close(self):
            pass

    def factory(ctx, **kwargs):
        return _FakeSource()

    return factory


def _build(db, company, monkeypatch, exc: HttpSourceError):
    import modules.autocount.sync as sync_module
    from modules.autocount.services.pull_service import PullService

    monkeypatch.setattr(sync_module, "source_factory", lambda impl: _fake_source_raising(exc))
    return PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )


def test_an_enrich_endpoint_failure_maps_to_enrich_failed(db, monkeypatch):
    from modules.autocount.models import AcPullSnapshotRow

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)

    exc = HttpSourceError(
        "The 'uom' lookup endpoint '/itemuombypage' failed: AutoCount answered HTTP 500 on page 1.",
        code="http_status", page=1, status=500, phase="enrich",
    )
    snapshot = _build(db, company, monkeypatch, exc)
    db.refresh(snapshot)

    assert snapshot.status == "failed"
    assert snapshot.error_code == "ENRICH_FAILED"
    assert snapshot.record_count == 0
    assert (
        db.query(AcPullSnapshotRow)
        .filter(AcPullSnapshotRow.snapshot_id == snapshot.id)
        .count()
        == 0
    )


def test_a_row_cap_breach_maps_to_row_limit(db, monkeypatch):
    from modules.autocount.models import AcPullSnapshotRow

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)

    exc = HttpSourceError(
        "This task's extract exceeded the 200000 row cap.", code="row_limit", page=7,
    )
    snapshot = _build(db, company, monkeypatch, exc)
    db.refresh(snapshot)

    assert snapshot.status == "failed"
    assert snapshot.error_code == "ROW_LIMIT"
    assert snapshot.record_count == 0
    assert (
        db.query(AcPullSnapshotRow)
        .filter(AcPullSnapshotRow.snapshot_id == snapshot.id)
        .count()
        == 0
    )


def test_a_row_cap_breach_on_the_enrich_endpoint_still_maps_to_row_limit(db, monkeypatch):
    """AC-10-22/64's own pin: ``ROW_LIMIT`` is by CODE regardless of phase -
    the row cap is a shared, per-endpoint guard (``_walk_endpoint``), so a
    lookup endpoint hitting it is still ``ROW_LIMIT``, never
    ``ENRICH_FAILED``."""
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)

    exc = HttpSourceError(
        "The 'uom' lookup endpoint '/itemuombypage' failed: This task's "
        "extract exceeded the 200000 row cap.",
        code="row_limit", page=4, phase="enrich",
    )
    snapshot = _build(db, company, monkeypatch, exc)
    db.refresh(snapshot)

    assert snapshot.status == "failed"
    assert snapshot.error_code == "ROW_LIMIT"


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_an_enrich_endpoint_failure_maps_to_enrich_failed dies if
#   ``_classify_http_source_error`` ignores ``exc.phase`` and always answers
#   SOURCE_PAGE_FAILED.
# * test_a_row_cap_breach_on_the_enrich_endpoint_still_maps_to_row_limit dies
#   if the classifier checks ``phase`` BEFORE ``code`` (it would answer
#   ENRICH_FAILED instead of the code-first ROW_LIMIT rule).
