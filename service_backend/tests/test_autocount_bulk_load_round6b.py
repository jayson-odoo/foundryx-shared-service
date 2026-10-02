"""AutoCount bulk document load - round 6b, S5b (sink push concurrency)
(plan sprint-5/03).

RED tests written BEFORE the coder. Design (coordinator's brief, with the
mid-flight ruling folded in): the sink's ``auto_push`` sends its
``SORENTO_MAX_BATCH``-record chunks SEQUENTIALLY today
(``SorentoSink.write_batch``'s ``for start in range(0, len(record_list),
SORENTO_MAX_BATCH): ... body = self._post(chunk, dry_run=False)``). A new
setting, ``autocount_sink_concurrency`` (env ``AUTOCOUNT_SINK_CONCURRENCY``,
default 1, validator 1..4), lets up to N chunks be POSTed with real
overlap. ``write_batch`` keeps TODAY's all-or-nothing contract at EVERY
concurrency level (the coordinator's ruling, folded in): one chunk failing
(a transport error, a 5xx, a timeout) means no further chunks are
submitted, in-flight chunks are awaited (their responses discarded), the
failure propagates exactly like today - no verdict is applied to ANY row
(every row stays STAGED), ``last_run_error`` carries the existing
"push failed before the consumer resolved it" text, and the next run
re-offers everything (idempotent on Sorento's own side). Concurrency 1
must be byte-identical to today (same request order, one at a time).

Grepped clean - no such setting exists, and ``write_batch`` posts one
chunk at a time, always waiting for the PREVIOUS chunk's response before
starting the next.

Driven at the SAME level ``modules/autocount/services/sync_service.py``'s
``auto_push`` is called at directly (not through a full paged run - a
plain ``sql_db`` master with STAGED rows is enough), reusing
``tests/test_autocount_pipeline.py``'s ``sorento_sink``/``transports``/
``_company``/``_sorento_connection``/``_point_at_sorento``/
``_staged_supplier_job`` fixtures - cross-test-file imports are an
established pattern in this suite. ``sinks_sorento.SORENTO_MAX_BATCH`` is
monkeypatched down to 10 so a 6-chunk/3-chunk scenario needs only 60/30
seeded rows, not 6,000/3,000.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, BackgroundJob
from modules.autocount.canonical.masters import ENTITY_SUPPLIER, CanonicalSupplier
from modules.autocount.models import STAGED, AcStagedRecord
from modules.autocount.repositories import StagedRecordRepository
from modules.autocount.services.sync_service import SyncService
from modules.autocount.sync import AUTOCOUNT_SYNC

from tests.test_autocount_pipeline import (
    _company,
    _point_at_sorento,
    _sorento_connection,
    sorento_sink,  # noqa: F401 - re-exported as a fixture for this module
    transports,  # noqa: F401 - re-exported as a fixture for this module
)


def _active_task_staged_supplier_job(db, company, *, refs) -> BackgroundJob:
    """Like ``test_autocount_pipeline``'s ``_staged_supplier_job``, but the
    job is NOT ``needs_review`` - ``auto_push``'s own ``list_pending_for_
    entity`` deliberately EXCLUDES any row belonging to a
    ``needs_review`` job (that gate is for the review-approve path only;
    an ACTIVE db task's own rows are never behind it), so a plain ``done``
    job (as an ACTIVE task's own run would leave behind) is what makes
    those rows visible to ``auto_push`` at all.

    ``created_at`` is EXPLICIT and strictly increasing in ``refs`` order:
    ``list_pending_for_entity`` orders oldest-first and SQLite's
    ``func.now()`` has one-second resolution, so 30 rows inserted in one
    go all tied and the tie-break fell to random UUIDs - chunk membership
    ("ref 15 is in the second chunk") only held by luck (BL-SS-129)."""
    base = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID,
        type=AUTOCOUNT_SYNC,
        status=JOB_DONE,
        payload_json={"companyId": company.id, "entityType": ENTITY_SUPPLIER},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    repo = StagedRecordRepository(db)
    for i, ref in enumerate(refs, start=1):
        record = CanonicalSupplier(
            source_ref=ref, source_doc_no=f"400-{i}", code=f"400-{i}",
            name=f"NAME{i}", email=None, is_active=True,
        )
        repo.add(
            AcStagedRecord(
                tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
                entity_type=ENTITY_SUPPLIER, job_id=job.id, source_ref=ref,
                canonical_json=record.comparable(), status=STAGED,
                created_at=base + timedelta(seconds=i),
            )
        )
    db.commit()
    return job


def _force_setting(obj, name: str, value):
    """Same rationale as the S5 (round 6) helper: a plain
    ``monkeypatch.setattr(obj, name, value, raising=False)`` still raises
    ``ValueError`` for an undeclared Pydantic field regardless of
    ``raising=False`` - write straight into the instance's own ``__dict__``
    instead, with a manual restore (``monkeypatch`` cannot track this)."""
    had = name in obj.__dict__
    previous = obj.__dict__.get(name)
    object.__setattr__(obj, name, value)

    def _restore() -> None:
        if had:
            object.__setattr__(obj, name, previous)
        else:
            obj.__dict__.pop(name, None)

    return _restore


# ── (a) the setting exists, default 1, floor 1 / ceiling 4 ─────────────────


def test_sink_concurrency_setting_exists_with_default_and_bounds(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.delenv("AUTOCOUNT_SINK_CONCURRENCY", raising=False)
    assert Settings().autocount_sink_concurrency == 1

    monkeypatch.setenv("AUTOCOUNT_SINK_CONCURRENCY", "0")
    with pytest.raises(ValidationError):
        Settings()

    monkeypatch.setenv("AUTOCOUNT_SINK_CONCURRENCY", "5")
    with pytest.raises(ValidationError):
        Settings()

    monkeypatch.setenv("AUTOCOUNT_SINK_CONCURRENCY", "4")
    assert Settings().autocount_sink_concurrency == 4
    monkeypatch.setenv("AUTOCOUNT_SINK_CONCURRENCY", "1")
    assert Settings().autocount_sink_concurrency == 1
    monkeypatch.delenv("AUTOCOUNT_SINK_CONCURRENCY", raising=False)


# ── (b) concurrency=3, 6 chunks: real overlap + correct verdicts ───────────


def test_auto_push_sends_up_to_N_chunks_concurrently_with_correct_verdicts(
    session_factory, transports, sorento_sink, monkeypatch,
):
    from app.config import settings as cfg
    from modules.autocount import sinks_sorento as sinks_sorento_module

    monkeypatch.setattr(sinks_sorento_module, "SORENTO_MAX_BATCH", 10, raising=False)
    restore = _force_setting(cfg, "autocount_sink_concurrency", 3)

    db = session_factory()
    company = _company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    refs = tuple(f"AED_VSOFT:{i}" for i in range(60))  # 60 rows / 10 per chunk = 6 chunks
    job = _active_task_staged_supplier_job(db, company, refs=refs)

    lock = threading.Lock()
    state: Dict[str, int] = {"current": 0, "max_concurrent": 0}
    barrier = threading.Barrier(3)

    def responder(request: httpx.Request) -> httpx.Response:
        with lock:
            state["current"] += 1
            state["max_concurrent"] = max(state["max_concurrent"], state["current"])
        try:
            barrier.wait(timeout=1.0)
        except threading.BrokenBarrierError:
            pass
        body = json.loads(request.content)
        recs = [
            {"source_ref": r["source_ref"], "outcome": "created",
             "entity_id": f"id-{r['source_ref']}"}
            for r in body["records"]
        ]
        with lock:
            state["current"] -= 1
        return httpx.Response(200, json={
            "summary": {"total": len(recs), "created": len(recs), "updated": 0,
                        "failed": 0, "retryable": 0},
            "records": recs,
        })

    sorento_sink.responder = responder

    try:
        summary = SyncService(db).auto_push(
            DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id,
        )
    finally:
        restore()

    assert summary.get("error") is None, f"expected a clean push - got {summary!r}"
    assert summary.get("pushed") == 60, f"expected all 60 rows pushed - got {summary!r}"
    assert state["max_concurrent"] >= 3, (
        f"expected up to 3 chunks in flight at once with "
        f"autocount_sink_concurrency=3 - observed max_concurrent="
        f"{state['max_concurrent']} (today's sequential write_batch caps "
        f"this at 1)"
    )

    statuses = {
        r.source_ref: r.status
        for r in StagedRecordRepository(db).list_for_job(
            DEFAULT_TENANT_ID, company.id, job.id
        )
    }
    assert set(statuses.values()) == {"PUSHED"}, (
        f"every one of the 60 rows must be marked pushed - got {statuses}"
    )
    db.close()


# ── (c) a mid-flight failure: all-or-nothing at every concurrency level ────


def test_auto_push_one_failing_chunk_keeps_the_other_chunks_verdicts_at_any_concurrency(
    session_factory, transports, sorento_sink, monkeypatch,
):
    """Re-pointed for fix/push-marks-per-chunk (prod finding: ~5 offers per
    SO because one failing chunk discarded every other chunk's verdicts and
    the next run re-offered the same oldest 5,000). Marks are written and
    committed PER CHUNK: the chunk that failed stays STAGED for the next run,
    every chunk the consumer answered is marked, and the summary accounts for
    requests / requestsFailed / firstFailure - at any concurrency."""
    from app.config import settings as cfg
    from modules.autocount import sinks_sorento as sinks_sorento_module
    from modules.autocount.models import STAGED_PUSHED

    monkeypatch.setattr(sinks_sorento_module, "SORENTO_MAX_BATCH", 10, raising=False)
    monkeypatch.setattr(cfg, "autocount_sink_batch_size", 10)
    restore = _force_setting(cfg, "autocount_sink_concurrency", 3)

    db = session_factory()
    company = _company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    refs = tuple(f"AED_VSOFT:{i}" for i in range(30))  # 3 chunks of 10
    job = _active_task_staged_supplier_job(db, company, refs=refs)

    failing_ref = "AED_VSOFT:15"  # lands in the second chunk
    failing_chunk: Dict[str, set] = {}

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        refs_in_chunk = {r["source_ref"] for r in body["records"]}
        if failing_ref in refs_in_chunk:
            failing_chunk["refs"] = refs_in_chunk
            raise httpx.ConnectError("connection reset", request=request)
        recs = [
            {"source_ref": r["source_ref"], "outcome": "created",
             "entity_id": f"id-{r['source_ref']}"}
            for r in body["records"]
        ]
        return httpx.Response(200, json={
            "summary": {"total": len(recs), "created": len(recs), "updated": 0,
                        "failed": 0, "retryable": 0},
            "records": recs,
        })

    sorento_sink.responder = responder

    try:
        summary = SyncService(db).auto_push(
            DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id,
        )
    finally:
        restore()

    assert summary.get("error") is not None, (
        f"a mid-flight transport failure must still surface as the run error - got "
        f"{summary!r}"
    )
    assert summary.get("requestsFailed") == 1, summary
    assert summary.get("requests", 0) >= 2, summary
    assert "unreachable" in str(summary.get("firstFailure")).lower() or "ConnectError" in str(
        summary.get("firstFailure")
    ), summary

    statuses = {
        r.source_ref: r.status
        for r in StagedRecordRepository(db).list_for_job(
            DEFAULT_TENANT_ID, company.id, job.id
        )
    }
    failed_refs = failing_chunk["refs"]
    assert all(statuses[r] == STAGED for r in failed_refs), (
        f"the failed chunk's rows must stay STAGED for the next run - got {statuses}"
    )
    answered = [r for r in refs if r not in failed_refs and statuses[r] == STAGED_PUSHED]
    assert answered, "chunks the consumer answered must be marked PUSHED"
    assert summary.get("pushed") == len(answered), summary
    assert set(statuses.values()) <= {STAGED, STAGED_PUSHED}
    db.close()
