"""AutoCount bulk document load - round 6, S5 (performance) (plan sprint-5/03).

RED tests written BEFORE the coder. Design (from the coordinator's brief):

``fetch_page`` fetches a page's CHANGED headers' lines with up to N
concurrent read-only connections, ``N = settings.autocount_line_fetch_workers``
(env ``AUTOCOUNT_LINE_FETCH_WORKERS``, default 4, validator 1..8 - the
source engine pool is ``pool_size=2, max_overflow=3`` = 5 total, so 4
workers plus the header page's own connection fits). Each worker opens its
OWN ``open_readonly`` connection from the source engine (never shares the
header page's connection across threads). Results must be byte-identical
to today's sequential path and attached to the RIGHT header (by DocKey,
never by finish order). One failing line query still fails the WHOLE page
exactly like today (``SqlQueryError`` propagates, nothing staged, the
top-level cursor untouched). ``MAX_DOCUMENT_LINES_PER_HEADER`` is still
enforced PER HEADER. ``workers=1`` must behave exactly like today
(sequential, one connection).

Grepped clean - no such setting exists anywhere yet, and ``_read_lines``
is called sequentially, once per changed header, off the ONE connection
``fetch_page`` already holds open for the header page read - never a
second connection. (a) is red on the missing setting; (b) is red because
only ONE connection is ever used regardless of any worker count.

The in-memory SQLite ``StaticPool`` rig every other file in this suite
uses is single-connection by construction (StaticPool hands back the SAME
connection every time) - real concurrent connections need a FILE-based
SQLite engine (``tmp_path``, ``check_same_thread=False``, ``QueuePool``),
built here rather than imported (per the brief).

Reuses ``tests/test_autocount_document_mapping.py``'s ``HEADER_QUERY``/
``LINE_QUERY``/``_company``/``_sql_connection``/``_document_config`` (the
schema/config shape), and ``tests/test_autocount_bulk_load_round4.py``'s
``_seed_row`` mapping-row pattern - cross-test-file imports are an
established pattern in this suite.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import QueuePool

from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.documents import ENTITY_SALES_ORDER
from modules.autocount.mapping import SCOPE_HEADER, SCOPE_LINE
from modules.autocount.models import (
    RUN_FAILED,
    RUN_SUCCESS,
    STAGED,
    AcStagedRecord,
    AcSyncRun,
    AcWatermark,
)
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sql_source.source import CURSOR_MARK
from modules.autocount.sync import AUTOCOUNT_SYNC

from tests.test_autocount_bulk_load_round4 import _seed_row
from tests.test_autocount_document_mapping import (
    HEADER_QUERY,
    LINE_QUERY,
    _company,
    _document_config,
    _sql_connection,
)


# ── shared rig: a REAL, file-based multi-connection SQLite engine ─────────


def _file_engine(
    tmp_path, header_rows: List[tuple], lines_by_doc: Dict[str, List[tuple]], *, name: str
) -> sa.engine.Engine:
    """A file-based SQLite engine with a real pool (``QueuePool``) - unlike
    the ``StaticPool`` in-memory rig every other file in this suite uses,
    this hands out GENUINELY DIFFERENT connections, so a worker-pool
    implementation can be proven to actually use more than one."""
    db_path = tmp_path / f"{name}.db"
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=0,
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE so_header (doc_key TEXT PRIMARY KEY, doc_no TEXT, "
            "status TEXT, cancelled TEXT, doc_date TEXT, last_modified TEXT)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE so_line (dtl_key TEXT PRIMARY KEY, doc_key TEXT, "
            "item_code TEXT, qty_ordered TEXT, qty_delivered TEXT, seq INTEGER)"
        )
        for row in header_rows:
            conn.exec_driver_sql("INSERT INTO so_header VALUES (?, ?, ?, ?, ?, ?)", row)
        for doc_key, lines in lines_by_doc.items():
            for dtl_key, item_code, qty, delivered, seq in lines:
                conn.exec_driver_sql(
                    "INSERT INTO so_line VALUES (?, ?, ?, ?, ?, ?)",
                    (dtl_key, doc_key, item_code, qty, delivered, seq),
                )
    return engine


def _seed_document_mapping(db, company) -> None:
    _seed_row(
        db, company, scope=SCOPE_HEADER, source_path="doc_no",
        canonical_field="so_number", transform="string", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_HEADER, source_path="status",
        canonical_field="status", transform="string", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_LINE, source_path="dtl_key",
        canonical_field="source_ref", transform="string", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_LINE, source_path="item_code",
        canonical_field="product_ref", transform="ref_product", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_LINE, source_path="qty_ordered",
        canonical_field="qty_ordered", transform="decimal", required=True,
    )


def _twelve_headers(prefix: str) -> Tuple[List[tuple], Dict[str, List[tuple]]]:
    header_rows = []
    lines_by_doc: Dict[str, List[tuple]] = {}
    for i in range(12):
        doc_key = f"{prefix}D{i:03d}"
        header_rows.append(
            (doc_key, f"SO-{i:03d}", "open", "F", f"2026-08-{(i % 28) + 1:02d}",
             f"2026-08-{(i % 28) + 1:02d} 09:00:00")
        )
        lines_by_doc[doc_key] = [
            (f"{doc_key}-1", "ITEM-A", "10", "0", 1),
            (f"{doc_key}-2", "ITEM-B", "5", "0", 2),
        ]
    return header_rows, lines_by_doc


def _force_setting(obj, name: str, value):
    """Set an attribute on the LIVE ``settings`` singleton that may not be a
    declared Pydantic field yet (the whole point of a RED test) - a plain
    ``monkeypatch.setattr(obj, name, value, raising=False)`` still goes
    through Pydantic's own ``__setattr__`` and raises ``ValueError`` for an
    undeclared field regardless of ``raising=False`` (that guards
    ``AttributeError`` only), so this writes straight into the instance's
    own ``__dict__`` instead - once the field is declared for real this
    becomes an ordinary attribute write. Returns a restore callable so the
    test can put the process-wide singleton back exactly as it found it
    (``monkeypatch`` cannot track a ``__dict__``-level write for auto-
    revert)."""
    had = name in obj.__dict__
    previous = obj.__dict__.get(name)
    object.__setattr__(obj, name, value)

    def _restore() -> None:
        if had:
            object.__setattr__(obj, name, previous)
        else:
            obj.__dict__.pop(name, None)

    return _restore


def _run_manual(db, company_id: str) -> AcSyncRun:
    job = JobService(db).create_and_enqueue(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company_id, "entityType": ENTITY_SALES_ORDER, "mode": "manual"},
    )
    return db.query(AcSyncRun).filter(AcSyncRun.job_id == job.id).one()


def _staged_rows(db, company_id: str) -> List[AcStagedRecord]:
    return (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.entity_type == ENTITY_SALES_ORDER,
        )
        .all()
    )


# ── (a) the setting exists, default 4, floor 1 / ceiling 8 ─────────────────


def test_line_fetch_workers_setting_exists_with_default_and_bounds(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.delenv("AUTOCOUNT_LINE_FETCH_WORKERS", raising=False)
    assert Settings().autocount_line_fetch_workers == 4

    monkeypatch.setenv("AUTOCOUNT_LINE_FETCH_WORKERS", "0")
    with pytest.raises(ValidationError):
        Settings()

    monkeypatch.setenv("AUTOCOUNT_LINE_FETCH_WORKERS", "9")
    with pytest.raises(ValidationError):
        Settings()

    monkeypatch.setenv("AUTOCOUNT_LINE_FETCH_WORKERS", "8")
    assert Settings().autocount_line_fetch_workers == 8
    monkeypatch.setenv("AUTOCOUNT_LINE_FETCH_WORKERS", "1")
    assert Settings().autocount_line_fetch_workers == 1
    monkeypatch.delenv("AUTOCOUNT_LINE_FETCH_WORKERS", raising=False)


# ── (b) 12 headers x 2 lines, workers=4: correct assignment + >=2 connections


def test_line_fetch_uses_multiple_connections_and_assigns_lines_by_dockey(
    session_factory, tmp_path, monkeypatch,
):
    from app.config import settings as cfg

    header_rows, lines_by_doc = _twelve_headers("B")
    engine = _file_engine(tmp_path, header_rows, lines_by_doc, name="s5b")

    db = session_factory()
    conn = _sql_connection(db, engine, database="AED_S5B", name="src")
    company = _company(db, conn.id, database="AED_S5B", name="S5B Co")
    _document_config(db, company, conn.id)
    _seed_document_mapping(db, company)

    monkeypatch.setattr(cfg, "autocount_page_size", 20, raising=False)
    restore_workers = _force_setting(cfg, "autocount_line_fetch_workers", 4)

    line_statements = {"n": 0}
    connection_ids: set = set()

    def before_cursor_execute(dbapi_conn, cursor, statement, parameters, context, executemany):
        if "so_line" in statement.lower():
            line_statements["n"] += 1
            connection_ids.add(id(dbapi_conn))

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        run = _run_manual(db, company.id)
    finally:
        sa.event.remove(engine, "before_cursor_execute", before_cursor_execute)
        restore_workers()

    assert run.outcome == RUN_SUCCESS, f"outcome={run.outcome!r} error={run.error!r}"

    staged = _staged_rows(db, company.id)
    assert len(staged) == 12, f"expected 12 staged headers, got {len(staged)}"

    for record in staged:
        doc_key = record.raw_json["doc_key"]
        lines = record.raw_json.get("_lines") or []
        assert len(lines) == 2, f"{doc_key}: expected 2 lines, got {len(lines)}"
        assert all(line["dtl_key"].startswith(doc_key) for line in lines), (
            f"{doc_key}: a line was assigned to the WRONG header - got "
            f"dtl_keys {[l['dtl_key'] for l in lines]}"
        )
        canon_lines = record.canonical_json.get("lines") or []
        assert len(canon_lines) == 2, (
            f"{doc_key}: canonical_json['lines'] has {len(canon_lines)}, expected 2"
        )

    assert line_statements["n"] == 12, (
        f"expected exactly 12 line statements (one per header) - got "
        f"{line_statements['n']}"
    )
    assert len(connection_ids) >= 2, (
        f"expected line fetches to use at least 2 distinct connections with "
        f"autocount_line_fetch_workers=4 - all {line_statements['n']} line "
        f"statements ran on {len(connection_ids)} connection(s)"
    )
    db.close()
    RUNTIME.dispose_all()


# ── (c) one failing line query fails the WHOLE page, cursor untouched ──────


def test_a_failing_line_query_fails_the_whole_page_cursor_unchanged(
    session_factory, tmp_path, monkeypatch,
):
    from app.config import settings as cfg
    from modules.autocount.sql_source.errors import SqlQueryError
    from modules.autocount.sql_source.source import SqlDbSource

    header_rows, lines_by_doc = _twelve_headers("C")
    engine = _file_engine(tmp_path, header_rows, lines_by_doc, name="s5c")

    db = session_factory()
    conn = _sql_connection(db, engine, database="AED_S5C", name="src")
    company = _company(db, conn.id, database="AED_S5C", name="S5C Co")
    _document_config(db, company, conn.id)
    _seed_document_mapping(db, company)

    monkeypatch.setattr(cfg, "autocount_page_size", 20, raising=False)
    restore_workers = _force_setting(cfg, "autocount_line_fetch_workers", 4)

    real_read_lines = SqlDbSource._read_lines
    failing_doc_key = "C" + "D005"

    def flaky_read_lines(self, conn2, doc_key_value):
        if doc_key_value == failing_doc_key:
            raise SqlQueryError(f"line query failed for {doc_key_value}")
        return real_read_lines(self, conn2, doc_key_value)

    monkeypatch.setattr(SqlDbSource, "_read_lines", flaky_read_lines)

    try:
        run = _run_manual(db, company.id)
    finally:
        restore_workers()

    assert run.outcome == RUN_FAILED, (
        f"one failing line query must fail the WHOLE page - got "
        f"outcome={run.outcome!r} error={run.error!r}"
    )
    assert _staged_rows(db, company.id) == [], "a failed page must stage nothing"

    watermark = (
        db.query(AcWatermark)
        .filter(
            AcWatermark.tenant_id == DEFAULT_TENANT_ID,
            AcWatermark.company_id == company.id,
            AcWatermark.entity_type == ENTITY_SALES_ORDER,
        )
        .first()
    )
    assert watermark is None or (watermark.cursor_json or {}).get(CURSOR_MARK) is None, (
        "a failed page must leave the top-level cursor untouched"
    )
    db.close()
    RUNTIME.dispose_all()


# ── (d) workers=1 gives byte-identical payloads to workers=4 ───────────────


def test_workers_one_matches_workers_four_byte_for_byte(session_factory, tmp_path, monkeypatch):
    from app.config import settings as cfg

    header_rows, lines_by_doc = _twelve_headers("D")

    def _normalize(value, database_name: str):
        """Strip the run's OWN ``database_name`` out of every ref - two
        different companies (``ac_company.database_name`` is unique per
        tenant, so the two runs cannot literally share one) mint refs that
        embed it (AC-14-10) - a placeholder makes the comparison about the
        LINE DATA, not which company happened to fetch it."""
        if isinstance(value, str):
            return value.replace(database_name, "DB")
        if isinstance(value, list):
            return [_normalize(v, database_name) for v in value]
        if isinstance(value, dict):
            return {k: _normalize(v, database_name) for k, v in value.items()}
        return value

    def _run_with(workers: int, name: str):
        database_name = f"AED_{name.upper()}"
        engine = _file_engine(tmp_path, header_rows, lines_by_doc, name=name)
        db = session_factory()
        conn = _sql_connection(db, engine, database=database_name, name="src")
        company = _company(db, conn.id, database=database_name, name=name)
        _document_config(db, company, conn.id)
        _seed_document_mapping(db, company)
        monkeypatch.setattr(cfg, "autocount_page_size", 20, raising=False)
        restore_workers = _force_setting(cfg, "autocount_line_fetch_workers", workers)
        try:
            run = _run_manual(db, company.id)
        finally:
            restore_workers()
        assert run.outcome == RUN_SUCCESS, f"workers={workers}: outcome={run.outcome!r} error={run.error!r}"
        payload = {
            r.raw_json["doc_key"]: _normalize(
                sorted((r.canonical_json.get("lines") or []), key=lambda l: l.get("source_ref")),
                database_name,
            )
            for r in _staged_rows(db, company.id)
        }
        db.close()
        return payload

    payload_1 = _run_with(1, "s5d1")
    payload_4 = _run_with(4, "s5d4")

    assert set(payload_1) == set(payload_4) == {f"DD{i:03d}" for i in range(12)}
    for doc_key in payload_1:
        assert payload_1[doc_key] == payload_4[doc_key], (
            f"{doc_key}: workers=1 and workers=4 produced DIFFERENT line "
            f"payloads - workers=1={payload_1[doc_key]!r}, "
            f"workers=4={payload_4[doc_key]!r}"
        )
    RUNTIME.dispose_all()
