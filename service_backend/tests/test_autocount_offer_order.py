"""Offer order (lane feat/line-fingerprint-sweep, contract B).

Prod finding: ``list_pending_for_entity`` orders ``last_offered_at NULLS
FIRST, created_at, id`` - a freshly staged LIVE change waits behind the
never-offered initial backlog (~80k rows), so the CRM sees yesterday's bulk
load before today's delivery.

Contract: ``last_offered_at NULLS FIRST``, then ``source_last_modified DESC
NULLS LAST``, then ``created_at, id`` (newest AutoCount change first).

- a fresh row staged from an incremental after an 80-row never-offered
  backlog is in the FIRST chunk;
- re-offered rows still go after never-offered ones;
- deletes unchanged (a delete row is offered like any other row; no
  ``source_last_modified`` = NULLS LAST, then created_at/id).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, BackgroundJob
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_SUPPLIER, CanonicalSupplier
from modules.autocount.models import (
    STAGED,
    STAGED_OP_DELETE,
    STAGED_OP_UPSERT,
    AcCompany,
    AcStagedRecord,
)
from modules.autocount.repositories.autocount_repository import StagedRecordRepository
from modules.autocount.sync import AUTOCOUNT_SYNC

BASE = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
SOURCE_BASE = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)


def _company(db, database: str = "AED_OFFER") -> AcCompany:
    api = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="AutoCount",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name=database,
        company_name=f"{database} Co", name=database, is_active=True, sink_impl="sorento",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _job(db, company: AcCompany) -> BackgroundJob:
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_DONE,
        payload_json={"companyId": company.id, "entityType": ENTITY_SUPPLIER},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _stage(
    db, company: AcCompany, job: BackgroundJob, refs: Sequence[str], *,
    start: int = 0,
    source_last_modified: Optional[Sequence[Optional[datetime]]] = None,
    last_offered_at: Optional[datetime] = None,
    op: str = STAGED_OP_UPSERT,
) -> List[AcStagedRecord]:
    """STAGED rows with strictly increasing ``created_at`` (the order given),
    an optional per-row ``source_last_modified`` and an optional shared
    ``last_offered_at``."""
    repo = StagedRecordRepository(db)
    rows = []
    for i, ref in enumerate(refs):
        record = CanonicalSupplier(
            source_ref=ref, source_doc_no=ref, code=ref, name=f"N {ref}", email=None, is_active=True,
        )
        row = AcStagedRecord(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SUPPLIER,
            job_id=job.id, source_ref=ref, canonical_json=record.comparable(),
            status=STAGED, op=op, created_at=BASE + timedelta(seconds=start + i),
            source_last_modified=(
                source_last_modified[i] if source_last_modified is not None else None
            ),
            last_offered_at=last_offered_at,
        )
        repo.add(row)
        rows.append(row)
    db.commit()
    return rows


def _pending(db, company: AcCompany, *, limit: int) -> List[str]:
    rows = StagedRecordRepository(db).list_pending_for_entity(
        DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_type=AUTOCOUNT_SYNC, limit=limit,
    )
    return [row.source_ref for row in rows]


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_a_fresh_incremental_row_is_offered_ahead_of_the_never_offered_backlog(db):
    """80 never-offered backlog rows (older source stamps, older created_at)
    then ONE row staged by a later incremental run with today's
    ``source_last_modified``: the fresh row is in the first chunk - in fact
    first - and the backlog follows newest-source-first."""
    company = _company(db)
    job = _job(db, company)
    backlog = [f"B{i:03d}" for i in range(80)]
    _stage(
        db, company, job, backlog,
        source_last_modified=[SOURCE_BASE + timedelta(minutes=i) for i in range(80)],
    )
    fresh_job = _job(db, company)
    _stage(
        db, company, fresh_job, ["FRESH"], start=1000,
        source_last_modified=[datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)],
    )

    first_chunk = _pending(db, company, limit=50)
    assert "FRESH" in first_chunk, "the live change waits behind the backlog"
    assert first_chunk[0] == "FRESH"
    # Backlog itself: newest AutoCount change first.
    assert first_chunk[1:4] == ["B079", "B078", "B077"], first_chunk[1:4]
    assert len(first_chunk) == 50


def test_re_offered_rows_still_go_after_never_offered_ones(db):
    """A row already offered once (``last_offered_at`` set) sorts after every
    never-offered row, even when its source stamp is the newest of all - the
    starvation guard keeps precedence over recency."""
    company = _company(db)
    job = _job(db, company)
    _stage(
        db, company, job, ["OFFERED-NEWEST"],
        source_last_modified=[datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)],
        last_offered_at=BASE + timedelta(hours=1),
    )
    _stage(
        db, company, job, ["NEVER-OLD", "NEVER-NEWER"], start=10,
        source_last_modified=[SOURCE_BASE, SOURCE_BASE + timedelta(days=1)],
    )

    order = _pending(db, company, limit=10)
    assert order == ["NEVER-NEWER", "NEVER-OLD", "OFFERED-NEWEST"], order


def test_among_re_offered_rows_the_earliest_offer_then_newest_source_wins(db):
    company = _company(db)
    job = _job(db, company)
    _stage(
        db, company, job, ["R-EARLY-OLDSRC"],
        source_last_modified=[SOURCE_BASE], last_offered_at=BASE + timedelta(hours=1),
    )
    _stage(
        db, company, job, ["R-LATE-NEWSRC"], start=1,
        source_last_modified=[SOURCE_BASE + timedelta(days=5)], last_offered_at=BASE + timedelta(hours=2),
    )
    _stage(
        db, company, job, ["R-EARLY-NEWSRC"], start=2,
        source_last_modified=[SOURCE_BASE + timedelta(days=3)], last_offered_at=BASE + timedelta(hours=1),
    )

    order = _pending(db, company, limit=10)
    assert order == ["R-EARLY-NEWSRC", "R-EARLY-OLDSRC", "R-LATE-NEWSRC"], order


def test_rows_without_a_source_stamp_sort_last_then_oldest_created_first(db):
    """``source_last_modified DESC NULLS LAST``: a row with no stamp (a master
    without a watermark column, or a delete) goes after every stamped row and
    falls back to ``created_at, id`` - the pre-existing order, unchanged."""
    company = _company(db)
    job = _job(db, company)
    _stage(db, company, job, ["NULL-OLDER", "NULL-NEWER"])  # no source stamps
    _stage(
        db, company, job, ["STAMPED"], start=50,
        source_last_modified=[SOURCE_BASE],
    )

    order = _pending(db, company, limit=10)
    assert order == ["STAMPED", "NULL-OLDER", "NULL-NEWER"], order


def test_deletes_are_offered_by_the_same_rule_unchanged(db):
    """Deletes are not special-cased: a delete row is listed with everything
    else under the same ordering, and a stamped delete takes its place by
    recency exactly like an upsert."""
    company = _company(db)
    job = _job(db, company)
    _stage(
        db, company, job, ["UP-OLD"],
        source_last_modified=[SOURCE_BASE],
    )
    _stage(
        db, company, job, ["DEL-NEW"], start=1, op=STAGED_OP_DELETE,
        source_last_modified=[SOURCE_BASE + timedelta(days=2)],
    )
    _stage(db, company, job, ["DEL-NOSTAMP"], start=2, op=STAGED_OP_DELETE)

    rows = StagedRecordRepository(db).list_pending_for_entity(
        DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_type=AUTOCOUNT_SYNC, limit=10,
    )
    assert [r.source_ref for r in rows] == ["DEL-NEW", "UP-OLD", "DEL-NOSTAMP"], [r.source_ref for r in rows]
    assert {r.source_ref: r.op for r in rows} == {
        "DEL-NEW": STAGED_OP_DELETE, "UP-OLD": STAGED_OP_UPSERT, "DEL-NOSTAMP": STAGED_OP_DELETE,
    }


def test_a_tie_on_source_stamp_falls_back_to_created_at_then_id(db):
    company = _company(db)
    job = _job(db, company)
    stamp = SOURCE_BASE + timedelta(days=1)
    _stage(db, company, job, ["T-FIRST", "T-SECOND", "T-THIRD"], source_last_modified=[stamp] * 3)

    order = _pending(db, company, limit=10)
    assert order == ["T-FIRST", "T-SECOND", "T-THIRD"], order


def test_the_limit_still_caps_the_chunk_and_scoping_is_per_company(db):
    company = _company(db)
    other = _company(db, database="AED_OTHER")
    job = _job(db, company)
    other_job = _job(db, other)
    _stage(db, company, job, [f"C{i}" for i in range(5)],
           source_last_modified=[SOURCE_BASE + timedelta(minutes=i) for i in range(5)])
    _stage(db, other, other_job, ["OTHER-NEWEST"],
           source_last_modified=[datetime(2026, 9, 7, tzinfo=timezone.utc)])

    order = _pending(db, company, limit=3)
    assert order == ["C4", "C3", "C2"], order
    assert "OTHER-NEWEST" not in _pending(db, company, limit=100)
