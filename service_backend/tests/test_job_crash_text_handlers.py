"""Plan 45, AC-45-05 - a handler that catches an error itself and fails the
job (or its run row) stores a fixed sentence that names the exception class,
never the exception's text."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from modules.autocount.models import AcEntityConfig, AcSyncRun, AcWatermark

from tests.test_s10_s3_pull_build_error_codes import NOW, _company, _connection, _product_task

SECRET = "MARKER-CRASH text"


class Marker(RuntimeError):
    pass


def _boom(*_a, **_kw):
    raise Marker(SECRET)


def _row_dict(row) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _assert_clean(job, *rows) -> None:
    """The job names the class and no stored text anywhere holds the marker."""
    assert job.status == "failed"
    assert "Marker" in (job.error or ""), job.error
    parts = [job.error, job.result_json, job.logs_json, job.payload_json, job.cursor_json]
    parts += [_row_dict(r) for r in rows]
    assert "MARKER" not in json.dumps(parts, default=str)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _job(db, job_type, payload, status="running") -> BackgroundJob:
    job = BackgroundJob(tenant_id=DEFAULT_TENANT_ID, type=job_type, status=status, payload_json=payload)
    db.add(job)
    db.commit()
    return job


# ── autocount_source_preview (preview_job.py :287 sample, :390 full) ─────────
def _preview_stub(monkeypatch):
    import modules.autocount.preview_job as preview_job

    class _Etl:
        def __init__(self, db):
            pass

        preview_http = _boom
        preview_task = _boom

    monkeypatch.setattr(preview_job, "EtlService", _Etl)
    return preview_job


@pytest.mark.parametrize("scope", ["sample", "full"])
def test_ac_45_05_preview_job_stores_the_class_name_only(db, monkeypatch, scope):
    preview_job = _preview_stub(monkeypatch)
    job = _job(
        db, "autocount_source_preview",
        {"scope": scope, "companyId": "c1", "entityType": "product", "request": {"connectionId": "x"}},
    )
    preview_job.run_autocount_source_preview(db, job)
    db.refresh(job)
    _assert_clean(job)


# ── autocount_sync (sync.py :453 setup, :715 fetch, :1907 paged fetch) ───────
def _sync_task(db, *, source_impl="autocount_http"):
    conn = _connection(db)
    company = _company(db, conn.id)
    config = _product_task(db, company, conn.id)
    config.delivery_mode = "push"
    config.source_impl = source_impl
    db.commit()
    return company, config


def _run_sync(db, company):
    from modules.autocount.sync import run_autocount_sync

    job = _job(
        db, "autocount_sync",
        {"companyId": company.id, "entityType": "product"}, status="pending",
    )
    run_autocount_sync(db, job)
    db.refresh(job)
    return job


def _sync_rows(db, company):
    return (
        db.query(AcSyncRun).filter(AcSyncRun.company_id == company.id).all()
        + db.query(AcWatermark).filter(AcWatermark.company_id == company.id).all()
        + db.query(AcEntityConfig).filter(AcEntityConfig.company_id == company.id).all()
    )


def test_ac_45_05_sync_setup_fault_stores_the_class_name_only(db, monkeypatch):
    import modules.autocount.sync as sync_module

    company, _ = _sync_task(db)

    def factory(ctx, **kwargs):
        raise Marker(SECRET)

    monkeypatch.setattr(sync_module, "source_factory", lambda impl: factory)
    job = _run_sync(db, company)
    assert db.query(AcSyncRun).filter(AcSyncRun.company_id == company.id).count() == 1
    _assert_clean(job, *_sync_rows(db, company))


def test_ac_45_05_sync_fetch_fault_stores_the_class_name_only(db, monkeypatch):
    import modules.autocount.sync as sync_module

    company, _ = _sync_task(db)

    class _Source:
        entity_type = "product"

        def fetch_changes(self, since):
            raise Marker(SECRET)

        def close(self):
            pass

    monkeypatch.setattr(sync_module, "source_factory", lambda impl: (lambda ctx, **kw: _Source()))
    job = _run_sync(db, company)
    assert db.query(AcSyncRun).filter(AcSyncRun.company_id == company.id).count() == 1
    _assert_clean(job, *_sync_rows(db, company))


def test_ac_45_05_paged_sync_fetch_fault_stores_the_class_name_only(db, monkeypatch):
    import modules.autocount.sync as sync_module

    company, _ = _sync_task(db, source_impl="sql_db")

    class _PagedSource:
        entity_type = "product"
        watermark_column = "LastModified"
        key_columns = ["ItemCode"]
        book = "db1"

        def fetch_page(self, cursor):
            raise Marker(SECRET)

        def close(self):
            pass

        def __getattr__(self, name):
            return None

    monkeypatch.setattr(sync_module, "source_factory", lambda impl: (lambda ctx, **kw: _PagedSource()))
    job = _run_sync(db, company)
    assert db.query(AcSyncRun).filter(AcSyncRun.company_id == company.id).count() == 1
    _assert_clean(job, *_sync_rows(db, company))


# ── autocount_pull_snapshot (sync.py :3056 setup, :3094 fetch) ───────────────
def _build_snapshot(db, monkeypatch, factory):
    import modules.autocount.sync as sync_module
    from modules.autocount.canonical.masters import ENTITY_PRODUCT
    from modules.autocount.models import AcPullSnapshot
    from modules.autocount.services.pull_service import PullService

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)
    monkeypatch.setattr(sync_module, "source_factory", lambda impl: factory)
    snap = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )
    db.refresh(snap)
    job = db.get(BackgroundJob, snap.job_id)
    db.refresh(job)
    runs = db.query(AcSyncRun).filter(AcSyncRun.company_id == company.id).all()
    return job, [snap, *runs]


def test_ac_45_05_pull_snapshot_setup_fault_stores_the_class_name_only(db, monkeypatch):
    def factory(ctx, **kwargs):
        raise Marker(SECRET)

    job, rows = _build_snapshot(db, monkeypatch, factory)
    _assert_clean(job, *rows)


def test_ac_45_05_pull_snapshot_fetch_fault_stores_the_class_name_only(db, monkeypatch):
    class _Source:
        entity_type = "product"

        def fetch_changes(self, since):
            raise Marker(SECRET)

        def close(self):
            pass

    job, rows = _build_snapshot(db, monkeypatch, lambda ctx, **kw: _Source())
    _assert_clean(job, *rows)
