"""AutoCount bulk document load - round 3 (plan sprint-5/03), at HEAD 59cc070.

RED tests written BEFORE the coder, from the coordinator's re-review of
59cc070 ("review round 2 - preview paging, abort safety, reconcile
continuation, composite tie ordering"):

* T1 (R2-B1) - round 2's F5 fix (an internal ``skip``/``OFFSET`` retry loop
  inside ONE ``fetch_page`` call, growing a bound ``:skip`` parameter) is
  REPLACED by composite ``(watermark, key)`` seek ordering: ``ORDER BY
  t.<wm>, t.<key>`` with a SEEK predicate (``(t.<wm> > :mark) OR (t.<wm> =
  :mark AND t.<key> > :last_key)``), never ``OFFSET``/``FETCH``/a growing
  bind. ``key`` = the task's first key column, quoted the same way the
  watermark already is.
* T2 (R2-S1) - ``EtlService._extract_and_map``'s preview path now calls
  ``SqlDbSource.fetch_page`` (round 2's F1 fix), but ``fetch_page.records``
  is CHANGE-ONLY by design (D2) - after a real run has already hashed the
  page, a preview immediately after reads the SAME page as all-unchanged
  and hands the sink an EMPTY records list, so the dry-run summary reports
  ``total: 0`` for a task that plainly has 6 rows.
* T3 (R2-S2) - ``sync._run_paged_sql_db`` tracks a MONOTONIC top-level
  position (``top_mark``, via ``_advance_mark_and_ties``) separately from
  the pass's own in-progress position (``pass_mark``) - correctly used for
  ``cursor_json[CURSOR_MARK]``/``tieRefs`` at the tail of the function, but
  ``watermark_row.last_modified_at`` (and therefore
  ``run.watermark_advanced_to``, assigned from it one line later) is set
  from ``decode_mark(pass_mark)`` instead of ``top_mark`` - a TRUNCATED
  reconcile (which always restarts its OWN pass position from scratch,
  ascending) can regress the public ``last_modified_at`` below whatever a
  previous successful run already advanced it to.
* Nit - ``scheduler._sweep_one`` only ever enqueues ``mode in
  {"incremental", "reconcile"}`` by construction of its own ternary; this
  is a regression guard, not necessarily red.

ASSUMPTIONS this file makes about the not-yet-built composite-ordering
signature (T1), named so the coder can match them:

* ``build_paged_wrap(query, quoted_watermark, quoted_date_column, mark, *,
  dialect, page_size, quoted_key=None, last_key=None)`` - ``quoted_key``
  given (composite ordering) replaces the current ``skip`` parameter
  entirely; omitted/``None`` keeps today's watermark-only behaviour (kept
  for any caller that has no key to seek on, though ``fetch_page`` always
  has one - a document/master task's ``key_columns`` is never empty,
  construction-time-guarded already).
* ``PageCursor``/``PageResult`` gain a ``last_key: Any = None`` field
  REPLACING ``tie_refs`` (the whole point of switching to a seek: no more
  ref-set exclusion, no more ``tieRefs`` in ``cursor_json`` - just the
  ``(mark, key)`` pair). Existing tests asserting ``tie_refs``/``tieRefs``
  are updated below (the only allowed edit to existing tests, per the
  brief) to assert ``last_key``/``lastKey`` instead - named in the report.

Reuses ``tests/test_autocount_bulk_load.py``'s fixture plumbing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import (
    RUN_MODE_INCREMENTAL,
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
    AcStagedRecord,
)
from modules.autocount.sql_source.runtime import RUNTIME

from tests.test_autocount_bulk_load import (
    Consumer,
    _config_row,
    _insert_rows,
    _make_rig,
    _run,
    _run_row,
    _rows,
    _watermark_row,
)


@pytest.fixture
def consumer(monkeypatch) -> Consumer:
    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    rec = Consumer()

    def fake(config, credentials, *, entity_type, company_code=None, transport=None):
        return real(
            config, credentials, entity_type=entity_type,
            company_code=company_code, transport=rec.transport,
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", fake)
    return rec


@pytest.fixture(autouse=True)
def _clean_runtime():
    yield
    RUNTIME.dispose_all()


# ── T1(a) - build_paged_wrap: composite ordering, SEEK not OFFSET ─────────


@pytest.mark.parametrize("dialect", ["mssql", "postgresql", "mysql", "sqlite"])
def test_build_paged_wrap_first_page_orders_by_watermark_then_key(dialect):
    from modules.autocount.sql_source.source import build_paged_wrap

    quoted_wm = '"last_modified"'
    quoted_key = '"acc_no"'
    sql = build_paged_wrap(
        "SELECT acc_no, last_modified FROM debtor", quoted_wm, None, None,
        dialect=dialect, page_size=500, quoted_key=quoted_key, last_key=None,
    )
    assert sql.rstrip().endswith(f"ORDER BY t.{quoted_wm}, t.{quoted_key}"), sql
    assert ":mark" not in sql
    assert ":last_key" not in sql
    for forbidden in ("OFFSET", "FETCH", ":skip"):
        assert forbidden not in sql, f"{forbidden!r} must never appear - got:\n{sql}"


@pytest.mark.parametrize(
    "dialect,page_prefix",
    [
        ("mssql", "SELECT TOP (:page_size) * FROM ("),
        ("postgresql", "SELECT * FROM ("),
        ("mysql", "SELECT * FROM ("),
    ],
)
def test_build_paged_wrap_later_page_is_a_seek_predicate(dialect, page_prefix):
    from modules.autocount.sql_source.source import build_paged_wrap

    quoted_wm = '"last_modified"'
    quoted_key = '"acc_no"'
    sql = build_paged_wrap(
        "SELECT acc_no, last_modified FROM debtor", quoted_wm, None, "2026-01-01",
        dialect=dialect, page_size=500, quoted_key=quoted_key, last_key="300-A001",
    )
    assert sql.startswith(page_prefix)
    assert (
        f"WHERE (t.{quoted_wm} > :mark) OR "
        f"(t.{quoted_wm} = :mark AND t.{quoted_key} > :last_key)"
    ) in sql, sql
    assert sql.rstrip().endswith(f"ORDER BY t.{quoted_wm}, t.{quoted_key}"), sql
    for forbidden in ("OFFSET", "FETCH", ":skip"):
        assert forbidden not in sql, f"{forbidden!r} must never appear - got:\n{sql}"
    assert "300-A001" not in sql, "last_key must ride as a bind, never spliced"


def test_build_paged_wrap_seek_predicate_ands_with_the_from_date_floor():
    from modules.autocount.sql_source.source import build_paged_wrap

    quoted_wm = '"LastModified"'
    quoted_date = '"DocDate"'
    quoted_key = '"DocKey"'
    sql = build_paged_wrap(
        "SELECT DocKey, DocDate, LastModified FROM SO", quoted_wm, quoted_date, "2026-01-01",
        dialect="mssql", page_size=2000, quoted_key=quoted_key, last_key="D0001",
    )
    assert f"t.{quoted_date} >= :from_date AND (" in sql, sql
    assert f"(t.{quoted_wm} > :mark) OR (t.{quoted_wm} = :mark AND t.{quoted_key} > :last_key)" in sql
    for forbidden in ("OFFSET", "FETCH", ":skip"):
        assert forbidden not in sql


# ── T1(b)/(c) - behavioural: bounded statement count, resume, cursor shape ─


def _tied_rows(n: int, mark: str) -> List[tuple]:
    return [(f"300-B{i:04d}", f"Company {i}", f"c{i}@x.com", mark) for i in range(n)]


def test_a_tie_group_of_3x_page_size_is_staged_once_each_with_ceil_n_statements(
    session_factory, monkeypatch, consumer,
):
    """T1(b). No chase: the WHOLE pass (however many pages a 3x-page-size
    tie group needs) must cost exactly ``ceil(n/page_size)`` real SELECT
    statements against the source - never more (the round-2 internal
    ``skip`` retry loop cost several statements per logical page)."""
    from app.config import settings as cfg

    page_size = 3
    n = 3 * page_size
    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _tied_rows(n, "2026-09-01 00:00:00")
    _insert_rows(engine, rows)
    monkeypatch.setattr(cfg, "autocount_page_size", page_size, raising=False)

    statements = {"n": 0}

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if "debtor" in statement.lower():
            statements["n"] += 1

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute)
    db = session_factory()
    try:
        job = _run(db, company_id, RUN_MODE_MANUAL)
    finally:
        sa.event.remove(engine, "before_cursor_execute", before_cursor_execute)
    assert job.status == JOB_DONE

    import math

    assert statements["n"] == math.ceil(n / page_size), (
        f"expected exactly ceil({n}/{page_size})={math.ceil(n / page_size)} "
        f"statements for the whole pass - executed {statements['n']}"
    )

    staged = (
        db.query(AcStagedRecord)
        .filter(AcStagedRecord.tenant_id == DEFAULT_TENANT_ID, AcStagedRecord.job_id == job.id)
        .all()
    )
    assert len(staged) == n, f"every one of the {n} tied rows must stage exactly once"
    assert len({r.source_ref for r in staged}) == n, "no duplicate source_ref in this job"

    watermark = _watermark_row(db, company_id)
    pass_state = (watermark.cursor_json or {}).get("pass") or {}
    assert "lastKey" in pass_state, f"cursor_json.pass must carry lastKey - got {pass_state}"
    assert "tieRefs" not in pass_state, (
        f"cursor_json.pass must NOT carry a tieRefs list any more (composite "
        f"ordering makes it unnecessary) - got {pass_state}"
    )


def test_a_pass_interrupted_mid_tie_group_resumes_without_duplicates_or_gaps(
    session_factory, monkeypatch, consumer,
):
    """T1(c). Budget cuts the pass mid tie group; the continuation tick
    resumes from ``(mark, lastKey)`` and finishes with every row staged
    exactly once - no duplicates, no gaps."""
    from app.config import settings as cfg

    page_size = 2
    n = 3 * page_size + 1
    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _tied_rows(n, "2026-09-01 00:00:00")
    _insert_rows(engine, rows)
    expected_refs = {f"{__import__('tests.test_autocount_bulk_load', fromlist=['DB_NAME']).DB_NAME}:{r[0]}" for r in rows}

    monkeypatch.setattr(cfg, "autocount_page_size", page_size, raising=False)
    monkeypatch.setattr(cfg, "autocount_run_time_budget_seconds", 0, raising=False)

    db = session_factory()
    seen_refs: set[str] = set()
    for _ in range(20):
        job = _run(db, company_id, RUN_MODE_INCREMENTAL)
        staged = (
            db.query(AcStagedRecord)
            .filter(AcStagedRecord.tenant_id == DEFAULT_TENANT_ID, AcStagedRecord.job_id == job.id)
            .all()
        )
        job_refs = {r.source_ref for r in staged}
        assert not (job_refs & seen_refs), (
            f"a resumed pass must never re-stage a ref already staged by an "
            f"earlier tick in the SAME pass - duplicated: {job_refs & seen_refs}"
        )
        seen_refs |= job_refs
        watermark = _watermark_row(db, company_id)
        pass_state = (watermark.cursor_json or {}).get("pass") or {}
        if pass_state.get("complete"):
            break
    else:
        pytest.fail("the tie group never completed within the tick budget")

    assert seen_refs == expected_refs, (
        f"no row may be skipped either - got {sorted(seen_refs)}, expected "
        f"{sorted(expected_refs)}"
    )


# ── T2 (R2-S1) - preview must report the page's real count, not 0 ─────────


def test_preview_after_a_real_run_reports_the_pages_row_count_not_zero(
    session_factory, monkeypatch, consumer,
):
    from modules.autocount.services.etl_service import EtlService

    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(6)
    _insert_rows(engine, rows)

    db = session_factory()
    job = _run(db, company_id, RUN_MODE_MANUAL)
    assert job.status == JOB_DONE

    _view, payload = EtlService(db).preview_task(DEFAULT_TENANT_ID, company_id, ENTITY_CUSTOMER)
    assert payload.get("previewable") is True, payload
    assert payload["summary"]["total"] == 6, (
        f"preview right after a real run (source unchanged) must report the "
        f"PAGE's row count (6), not the change-only-staging count (0) - got "
        f"{payload['summary']}"
    )

    # The run loop's own change-only staging must be UNAFFECTED by the fix -
    # a real run immediately after still stages nothing (nothing changed).
    job2 = _run(db, company_id, RUN_MODE_MANUAL)
    assert job2.status == JOB_DONE
    staged2 = (
        db.query(AcStagedRecord)
        .filter(AcStagedRecord.tenant_id == DEFAULT_TENANT_ID, AcStagedRecord.job_id == job2.id)
        .all()
    )
    assert staged2 == [], "a real run must still stage 0 when nothing changed"


# ── T3 (R2-S2) - a truncated reconcile must not regress the watermark ─────


def test_a_truncated_reconcile_never_regresses_last_modified_at(
    session_factory, monkeypatch, consumer,
):
    from app.config import settings as cfg

    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(6)
    _insert_rows(engine, rows)

    db = session_factory()
    seed = _run(db, company_id, RUN_MODE_MANUAL)
    seed_run = _run_row(db, company_id, seed.id)
    assert seed.status == JOB_DONE

    before_last_modified_at = _watermark_row(db, company_id).last_modified_at
    before_advanced_to = seed_run.watermark_advanced_to
    assert before_last_modified_at is not None
    assert before_advanced_to is not None

    # A reconcile ALWAYS restarts from scratch, ascending - the first page
    # of THIS pass necessarily lands far below the existing high-water mark.
    monkeypatch.setattr(cfg, "autocount_page_size", 1, raising=False)
    monkeypatch.setattr(cfg, "autocount_run_time_budget_seconds", 0, raising=False)

    job = _run(db, company_id, RUN_MODE_RECONCILE)
    run = _run_row(db, company_id, job.id)
    assert run.truncated is True

    after = _watermark_row(db, company_id)
    assert after.last_modified_at >= before_last_modified_at, (
        f"a truncated reconcile must never REGRESS the public "
        f"last_modified_at - before={before_last_modified_at} "
        f"after={after.last_modified_at}"
    )
    assert run.watermark_advanced_to is None or run.watermark_advanced_to >= before_advanced_to, (
        f"run.watermark_advanced_to must be monotone too - before="
        f"{before_advanced_to} after={run.watermark_advanced_to}"
    )

    # The PASS's own (allowed to be "behind") position is tracked separately.
    pass_state = (after.cursor_json or {}).get("pass") or {}
    assert pass_state.get("mark") == rows[0][3], (
        f"cursor_json.pass.mark must hold the PAGE position this pass has "
        f"actually reached - got {pass_state.get('mark')!r}"
    )


# ── nit - the scheduler never enqueues literal mode='manual' ──────────────


def test_a_continued_manual_pass_is_swept_as_incremental_or_reconcile_never_manual(
    session_factory, monkeypatch, consumer,
):
    from app.config import settings as cfg
    from modules.autocount.scheduler import _sweep_one

    company_id, sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(4))
    monkeypatch.setattr(cfg, "autocount_page_size", 1, raising=False)
    monkeypatch.setattr(cfg, "autocount_run_time_budget_seconds", 0, raising=False)

    db = session_factory()
    manual_job = _run(db, company_id, RUN_MODE_MANUAL)  # opens an incomplete MANUAL pass
    manual_run = _run_row(db, company_id, manual_job.id)
    assert manual_run.truncated is True
    pass_state = (_watermark_row(db, company_id).cursor_json or {}).get("pass") or {}
    assert pass_state.get("kind") == RUN_MODE_MANUAL

    before_ids = {
        row.id
        for row in db.query(__import__(
            "modules.autocount.models", fromlist=["AcSyncRun"]
        ).AcSyncRun.id).filter_by(tenant_id=DEFAULT_TENANT_ID, company_id=company_id)
    }
    now = datetime.now(timezone.utc)
    config = _config_row(db, company_id)
    config.next_incremental_at = now
    db.commit()
    outcome = _sweep_one(db, config, now=now)
    assert outcome == "fired"

    from modules.autocount.models import AcSyncRun

    new_run = next(
        r for r in db.query(AcSyncRun).filter(
            AcSyncRun.tenant_id == DEFAULT_TENANT_ID, AcSyncRun.company_id == company_id
        )
        if r.id not in before_ids
    )
    assert new_run.mode in (RUN_MODE_INCREMENTAL, RUN_MODE_RECONCILE), (
        f"a scheduler-driven tick must never record mode='manual' even when "
        f"continuing an open manual pass - got {new_run.mode!r}"
    )
