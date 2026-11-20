"""Plan 45, AC-45-05 - every handler path that stores a crash stores the fixed
sentence naming the exception class, never the exception's text."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone


from app.models.background_job import BackgroundJob
from modules.autocount.models import AcDocFeed, AcDocFeedBackfill, AcDocFeedRun

from .s14_doc_feed_helpers import wired_company

EXPECTED = "Job crashed (RuntimeError)."


def _boom(*_a, **_kw):
    raise RuntimeError("MARKER-CRASH text")


def _feed(db, company, ac_conn) -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=company.tenant_id, company_id=company.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push",
    )
    db.add(row)
    db.commit()
    return row


def _job(db, tenant_id, job_type, payload, status="running"):
    job = BackgroundJob(tenant_id=tenant_id, type=job_type, status=status, payload_json=payload)
    db.add(job)
    db.commit()
    return job


def _assert_class_only(db, job_id, tenant_id):
    db.expire_all()
    job = db.get(BackgroundJob, job_id)
    assert job.status == "failed"
    assert job.error == EXPECTED
    parts = [job.error, job.result_json, job.logs_json, job.payload_json, job.cursor_json]
    for run in db.query(AcDocFeedRun).filter(AcDocFeedRun.tenant_id == tenant_id).all():
        parts.append({c.name: getattr(run, c.name) for c in run.__table__.columns})
    assert "MARKER" not in json.dumps(parts, default=str)


def test_ac_45_05_doc_feed_run_job_stores_the_class_name_only(session_factory, monkeypatch):
    from modules.autocount.doc_feed import jobs

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = _job(db, co.tenant_id, "autocount_doc_feed_run", {"feedId": feed.id, "kind": "poll"})
    monkeypatch.setattr(jobs, "run_poll", _boom)

    jobs.run_doc_feed_job(db, job)

    _assert_class_only(db, job.id, co.tenant_id)


def test_ac_45_05_doc_feed_backfill_job_stores_the_class_name_only(session_factory, monkeypatch):
    from modules.autocount.doc_feed import jobs

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = _job(db, co.tenant_id, "autocount_doc_feed_backfill", {"backfillId": "x"})
    backfill = AcDocFeedBackfill(
        tenant_id=co.tenant_id, company_id=co.id, feed_id=feed.id, feed="delivery_orders",
        book="db1", dry_run=False, from_day=date(2026, 1, 1), to_day=date(2026, 1, 3),
        next_day=date(2026, 1, 1), status="running", job_id=job.id,
        started_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
    )
    db.add(backfill)
    db.commit()
    job.payload_json = {"backfillId": backfill.id}
    db.commit()
    monkeypatch.setattr(jobs, "run_backfill", _boom)

    jobs.run_doc_feed_backfill_job(db, job)

    _assert_class_only(db, job.id, co.tenant_id)


def test_ac_45_05_doc_feed_service_eager_transport_path_stores_the_class_name_only(session_factory):
    from modules.autocount.services.doc_feed_service import DocFeedService

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = _job(
        db, co.tenant_id, "autocount_doc_feed_run", {"feedId": feed.id, "kind": "poll"},
        status="pending",
    )

    DocFeedService(db)._run_eager_with_transport(_boom, job, transport=object())

    _assert_class_only(db, job.id, co.tenant_id)


def test_ac_45_05_preview_eager_transport_path_stores_the_class_name_only(session_factory, monkeypatch):
    from modules.autocount.services import preview_job_service as svc

    db = session_factory()
    co, _ac_conn, _crm = wired_company(db)
    job = _job(db, co.tenant_id, "autocount_source_preview", {"companyId": co.id}, status="pending")
    monkeypatch.setattr(svc, "run_autocount_source_preview", _boom)

    svc.PreviewJobService(db)._run_eager_with_transport(job, transport=object())

    _assert_class_only(db, job.id, co.tenant_id)
