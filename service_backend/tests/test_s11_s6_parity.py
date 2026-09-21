"""Sprint-5/11 S6 - AC-11-05: serial-versus-concurrent parity is mandatory,
pinned by a test. The ONE risk that matters (plan section 5): "a concurrent
walk silently changes a data set" - Sorento zeroes stock pairs absent from a
fed set, so byte-identical output at N=1 and N=4 is not a nice-to-have, it
is the whole safety case for shipping this slice at all.

RED before the coder for the SAME reason as ``test_s11_s6_concurrent_walk.py``
(shares its ``_require_concurrency_wiring`` autouse fixture, imported below -
``connection_sizing`` does not read ``maxConcurrentPages`` yet, so every test
here fails at fixture setup with an explicit, named reason before a single
HTTP stub is even built).

Fixture reused across every test in this file: an 8-page product walk (>=7
pages per the brief), a duplicate key (``DUP``) spanning the page 3/page 7
boundary, a watermark column (``LastModified``), and one lookup endpoint
(``/itemuombypage``) merging ``BaseUOMPrice`` - run at N=1 (default,
byte-identical to today) and N=4 via TWO separate companies sharing the
SAME ``database_name`` (so ``source_ref``/row-hash keys are byte-identical
between the two runs, making the comparison a straight ``==``) against the
SAME served data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import ETL_STATUS_ACTIVE, AcEntityConfig, AcFieldMapping
from modules.autocount.sources import Watermark

from modules.autocount.http_source.source import HttpApiSource

# House-style cross-file fixture reuse (see e.g. ``test_s10_s6_lookup_sizing.py``
# importing from ``test_s10_s6_connection_sizing.py``).
from tests.test_s11_s6_concurrent_walk import (  # noqa: F401 - _require_concurrency_wiring is autouse, collected by import
    DB_NAME,
    _company,
    _config,
    _ctx,
    _envelope,
    _open_connection,
    _require_concurrency_wiring,
    _transport,
    db,
)
from tests.test_s10_s5a_source_reduce_hook import SIMPLE_COMBINE

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)

MAIN_PATH = "/itembypage"
LOOKUP_PATH = "/itemuombypage"

# page -> [(ItemCode, LastModified)]
PAGE_ROWS: Dict[int, List[Dict[str, Any]]] = {
    1: [{"code": "P1", "last_modified": "2026-08-01T00:00:00"}],
    2: [{"code": "P2", "last_modified": "2026-08-02T00:00:00"}],
    3: [{"code": "DUP", "last_modified": "2026-08-03T00:00:00"}],
    4: [{"code": "P4", "last_modified": "2026-08-04T00:00:00"}],
    5: [{"code": "P5", "last_modified": "2026-08-05T00:00:00"}],
    6: [{"code": "P6", "last_modified": "2026-08-06T00:00:00"}],
    7: [{"code": "DUP", "last_modified": "2026-08-07T00:00:00"}],
    8: [{"code": "P8", "last_modified": "2026-08-08T00:00:00"}],
}
TOTAL_PAGES = 8
DISTINCT_CODES = ["P1", "P2", "DUP", "P4", "P5", "P6", "P8"]
LOOKUP = {
    "path": LOOKUP_PATH, "as": "uom",
    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
    "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
}


def _main_page_body(page: int, *, description_suffix: str = "") -> Dict[str, Any]:
    rows = [
        {
            "ItemCode": r["code"], "Description": r["code"] + description_suffix,
            "LastModified": r["last_modified"],
        }
        for r in PAGE_ROWS[page]
    ]
    return _envelope(rows, page=page, total_pages=TOTAL_PAGES)


def _lookup_body() -> List[Dict[str, Any]]:
    return [{"ItemCode": code, "Price": 9.5} for code in DISTINCT_CODES]


def _fixture_handler(*, description_suffix: str = ""):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(LOOKUP_PATH):
            return httpx.Response(200, json=_lookup_body())
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(
            200, json=_main_page_body(page, description_suffix=description_suffix)
        )

    return handler


def _pair(db, *, max_concurrent_pages_n: str = "4"):
    """Two companies sharing ONE ``database_name`` (byte-identical
    ``source_ref``/row-hash keys), one on an N=1 connection, one on an
    N={max_concurrent_pages_n} connection."""
    conn_n1 = _open_connection(db, max_concurrent_pages="1", name="s11-s6 parity N1")
    conn_n4 = _open_connection(
        db, max_concurrent_pages=max_concurrent_pages_n, name="s11-s6 parity N4"
    )
    company_n1 = _company(db, conn_n1.id, database_name=DB_NAME)
    company_n4 = _company(db, conn_n4.id, database_name=DB_NAME)
    return conn_n1, conn_n4, company_n1, company_n4


def _make_source(db, company, conn, *, transport, combine=None) -> HttpApiSource:
    config = _config(
        db, company, connection_id=conn.id, path=MAIN_PATH,
        lookups=[LOOKUP] if combine is None else None, combine=combine,
    )
    return HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=transport,
    )


# ══════════════════════════════════════════════════════════════════════════
# fetch_changes() itself: every FetchResult field + the persisted hash map.
# ══════════════════════════════════════════════════════════════════════════


def test_fetch_changes_byte_identical_at_n1_and_n4(db):
    conn_n1, conn_n4, company_n1, company_n4 = _pair(db)

    source_n1 = _make_source(db, company_n1, conn_n1, transport=_transport(_fixture_handler()))
    result_n1 = source_n1.fetch_changes(Watermark())

    source_n4 = _make_source(db, company_n4, conn_n4, transport=_transport(_fixture_handler()))
    result_n4 = source_n4.fetch_changes(Watermark())

    raws_n1 = [r.raw for r in result_n1.records]
    raws_n4 = [r.raw for r in result_n4.records]
    assert raws_n1 == raws_n4, "records (order and content) differ between N=1 and N=4"
    assert len(raws_n1) == len(DISTINCT_CODES), "the DUP key must collapse to one row"

    assert result_n1.rows_scanned == result_n4.rows_scanned
    assert result_n1.reported_total == result_n4.reported_total
    assert result_n1.added_count == result_n4.added_count
    assert result_n1.updated_count == result_n4.updated_count
    assert result_n1.delete_refs == result_n4.delete_refs
    assert result_n1.current_refs == result_n4.current_refs
    assert result_n1.cursor == result_n4.cursor
    assert result_n1.envelope_kind == result_n4.envelope_kind
    assert result_n1.lookup_verification == result_n4.lookup_verification
    assert result_n1.combine_metadata == result_n4.combine_metadata

    from modules.autocount.repositories import RowHashRepository

    hashes_n1 = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company_n1.id, ENTITY_PRODUCT)
    hashes_n4 = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company_n4.id, ENTITY_PRODUCT)
    assert hashes_n1 == hashes_n4, "the persisted ac_row_hash map differs between N=1 and N=4"
    assert f"{DB_NAME}:DUP" in hashes_n1

    # The DUP key must resolve to PAGE 3's row (first occurrence by
    # requested page order), identically at both N.
    dup_n1 = next(r.raw for r in result_n1.records if r.raw["ItemCode"] == "DUP")
    dup_n4 = next(r.raw for r in result_n4.records if r.raw["ItemCode"] == "DUP")
    assert dup_n1["LastModified"] == "2026-08-03T00:00:00"
    assert dup_n4["LastModified"] == "2026-08-03T00:00:00"


# ══════════════════════════════════════════════════════════════════════════
# End to end: _run_pull_snapshot at N=1 vs N=4 -> the SAME content_hash and
# record_count.
# ══════════════════════════════════════════════════════════════════════════


def _product_pull_task(db, company, connection_id, *, combine=None) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE, delivery_mode="pull",
        source_config={
            "connectionId": connection_id, "path": MAIN_PATH,
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [LOOKUP] if combine is None else [],
            "combine": combine,
        },
        last_preview_at=NOW, result_columns=["ItemCode", "Description"],
    )
    db.add(config)
    db.commit()
    db.add(
        AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            scope="header", sort_order=0, source_path="ItemCode", canonical_field="code",
            transform="string", is_required=True, formula=None,
        )
    )
    db.add(
        AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            scope="header", sort_order=1, source_path="Description", canonical_field="name",
            transform="string", is_required=False, formula=None,
        )
    )
    db.commit()
    db.refresh(config)
    return config


def _patch_transport(monkeypatch, transport: httpx.Client) -> None:
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=transport),
    )


def _build(db, company, *, now=NOW):
    from modules.autocount.services.pull_service import PullService

    return PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=now,
    )


def test_pull_snapshot_content_hash_and_record_count_identical_at_n1_and_n4(db, monkeypatch):
    conn_n1, conn_n4, company_n1, company_n4 = _pair(db)
    _product_pull_task(db, company_n1, conn_n1.id)
    _product_pull_task(db, company_n4, conn_n4.id)

    _patch_transport(monkeypatch, _transport(_fixture_handler()))
    snapshot_n1 = _build(db, company_n1)
    db.refresh(snapshot_n1)
    assert snapshot_n1.status == "ready", getattr(snapshot_n1, "error", None)

    _patch_transport(monkeypatch, _transport(_fixture_handler()))
    snapshot_n4 = _build(db, company_n4)
    db.refresh(snapshot_n4)
    assert snapshot_n4.status == "ready", getattr(snapshot_n4, "error", None)

    assert snapshot_n1.record_count == snapshot_n4.record_count == len(DISTINCT_CODES)
    assert snapshot_n1.content_hash == snapshot_n4.content_hash, (
        "content_hash differs between an N=1 build and an N=4 build of the "
        "SAME fixture data - the one risk this whole slice exists to prevent"
    )


def test_mutation_control_hash_changes_at_both_n(db, monkeypatch):
    """The parity assertion above must not pass for the wrong reason (e.g.
    a hash function that ignores its input): mutating ONE cell of the
    fixture (page 4's Description) must move ``content_hash`` relative to
    the ORIGINAL fixture, at BOTH N=1 and N=4."""
    conn_n1, conn_n4, company_n1, company_n4 = _pair(db)
    _product_pull_task(db, company_n1, conn_n1.id)
    _product_pull_task(db, company_n4, conn_n4.id)

    _patch_transport(monkeypatch, _transport(_fixture_handler()))
    original_n1 = _build(db, company_n1, now=NOW)
    db.refresh(original_n1)
    original_n4 = _build(db, company_n4, now=NOW)
    db.refresh(original_n4)
    assert original_n1.status == "ready" and original_n4.status == "ready"

    _patch_transport(
        monkeypatch, _transport(_fixture_handler(description_suffix="-MUTATED"))
    )
    later = NOW + timedelta(minutes=5)
    mutated_n1 = _build(db, company_n1, now=later)
    db.refresh(mutated_n1)
    mutated_n4 = _build(db, company_n4, now=later)
    db.refresh(mutated_n4)
    assert mutated_n1.status == "ready" and mutated_n4.status == "ready"

    assert mutated_n1.content_hash != original_n1.content_hash, (
        "N=1: mutating one cell did not move content_hash"
    )
    assert mutated_n4.content_hash != original_n4.content_hash, (
        "N=4: mutating one cell did not move content_hash"
    )
    assert mutated_n1.content_hash == mutated_n4.content_hash, (
        "the MUTATED fixture must still hash identically at N=1 and N=4"
    )


# ══════════════════════════════════════════════════════════════════════════
# A combine-carrying task, separately (D per the brief: "if the existing
# fixtures make that cheap" - SIMPLE_COMBINE, reused byte-for-byte from
# test_s10_s5a_source_reduce_hook.py, makes it cheap).
# ══════════════════════════════════════════════════════════════════════════


def _combine_page_body(page: int, rows: List[Dict[str, Any]], *, total_pages: int) -> Dict[str, Any]:
    return _envelope(rows, page=page, total_pages=total_pages)


def test_combine_carrying_task_parity_at_n1_and_n4(db):
    """4 pages of raw {g, v} rows, grouped+summed by SIMPLE_COMBINE
    (``groupBy: ["g"]``, ``sum(v) -> total``) - the combine step runs
    AFTER lookups and BEFORE de-dup/hashing (AC-10-80), so its own output
    must be exactly as order-independent of N as the plain walk."""
    conn_n1 = _open_connection(db, max_concurrent_pages="1", name="s11-s6 combine N1")
    conn_n4 = _open_connection(db, max_concurrent_pages="4", name="s11-s6 combine N4")
    company_n1 = _company(db, conn_n1.id, database_name=DB_NAME)
    company_n4 = _company(db, conn_n4.id, database_name=DB_NAME)

    total_pages = 4
    rows_by_page = {
        1: [{"g": "A", "v": 1}],
        2: [{"g": "B", "v": 2}],
        3: [{"g": "A", "v": 3}],
        4: [{"g": "B", "v": 4}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(
            200, json=_combine_page_body(page, rows_by_page[page], total_pages=total_pages)
        )

    def make(company, conn):
        config = _config(
            db, company, connection_id=conn.id, path="/rows", key_fields=("g",),
            watermark_field=None, combine=SIMPLE_COMBINE,
        )
        return HttpApiSource(
            _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
        )

    result_n1 = make(company_n1, conn_n1).fetch_changes(Watermark())
    result_n4 = make(company_n4, conn_n4).fetch_changes(Watermark())

    raws_n1 = [r.raw for r in result_n1.records]
    raws_n4 = [r.raw for r in result_n4.records]
    assert raws_n1 == raws_n4
    assert raws_n1 == [{"g": "A", "total": 4}, {"g": "B", "total": 6}], raws_n1
    assert result_n1.combine_metadata == result_n4.combine_metadata
