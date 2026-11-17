"""Lane AUTOCOUNT-INDEX-JOB: the SPO / SO write-back indexes are filled by a background job, not a migration.

Prod 17 Nov: the 0047 / 0048 migrations backfilled ``ac_spo_po_link`` / ``ac_so_row_index`` from every staged
shipping / sales order inside ``alembic upgrade`` at backend start; that ran past the 240 s health budget and
the deploy aborted. The migrations now create the tables only; ``autocount_index_build`` fills them per company
in batches (resumable, idempotent), and until a company's index is complete every lookup that reads it takes
the old full staged read instead - never an answer from a half-built index.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcIndexBuild, AcSoRowIndex, AcSpoPoLink
from tests.test_autocount_write_back_operations import (  # noqa: F401
    OpHarness,
    db,
    h,
)
from tests.test_autocount_write_back_primitives import DBNAME, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401
from tests.write_back_live_books import live_books_open  # noqa: F401

pytestmark = pytest.mark.usefixtures("live_books_open")

SPO_INDEX = "spo_po_link"
SO_INDEX = "so_row_index"


def _wipe_indexes(h) -> None:
    """The book as it was when 0047 / 0048 ran: documents staged, index tables empty, nothing built."""
    h.db.query(AcSpoPoLink).filter_by(company_id=h.company.id).delete()
    h.db.query(AcSoRowIndex).filter_by(company_id=h.company.id).delete()
    h.db.query(AcIndexBuild).filter_by(company_id=h.company.id).delete()
    h.db.commit()


def _spo_rows(h):
    h.db.expire_all()
    return sorted((r.spo_source_ref, r.spo_doc_no, r.spo_dtl_key, r.po_dtl_key, Decimal(r.qty))
                  for r in h.db.query(AcSpoPoLink).filter_by(company_id=h.company.id))


def _so_rows(h):
    h.db.expire_all()
    return sorted((r.so_source_ref, r.so_doc_no, r.so_dtl_key, r.location, r.ambiguous, r.so_doc_key)
                  for r in h.db.query(AcSoRowIndex).filter_by(company_id=h.company.id))


def _book(h, spos: int = 3, sos: int = 3):
    """SO 7002 + PO 7001 (row 0 linked to the SO, rows 1..2 free); SPO 7100 points at PO row 1; noise SPOs / SOs."""
    h.delete_on()
    so = h.seed_doc("SO", 7002, [_line("ITEM-A", 10, 5.0, "BR4")])
    so_dtl = so["Details"][0]["DtlKey"]
    link = dict(FromDocType="SO", FromDocNo="", FromDocDtlKey=so_dtl, FromSODtlKey=so_dtl)
    po = h.seed_doc("PO", 7001, [_line("ITEM-A", 4, 5.0, "BR4", **link), _line("ITEM-A", 3, 5.0, "BR4"),
                                 _line("ITEM-A", 2, 5.0, "BR4")])
    keys = [r["DtlKey"] for r in po["Details"]]
    h.seed_doc("SPO", 7100, [_line("ITEM-A", 2, 5.0, "BR4", FromDocType="PO", FromDocNo="PO-7001",
                                   FromDocDtlKey=keys[1])])
    for n in range(spos):
        h.seed_doc("SPO", 7200 + n, [_line("ITEM-A", 1, 5.0, "BR4", FromDocType="PO", FromDocNo="PO-1",
                                           FromDocDtlKey=700000 + n)])
    for n in range(sos):
        h.seed_doc("SO", 7300 + n, [_line("ITEM-B", 1, 5.0, f"L{n}")])
    return so_dtl, keys


def _build(h, **kw):
    from modules.autocount.write_back.index_build import build_indexes

    return build_indexes(h.db, DEFAULT_TENANT_ID, **kw)


# ---- not built yet: the lookups take the old full read --------------------------------------------------------

def test_an_unbuilt_spo_index_falls_back_to_the_staged_read_for_row_on_spo(h):
    _so_dtl, keys = _book(h)
    _wipe_indexes(h)  # SPO 7100 staged before the index existed: no row in ac_spo_po_link
    res = h.run("unlink_row", dict(doc_key=7001, dtl_key=keys[1]), key="unbuilt-on-spo")
    assert (res.outcome, res.error_code) == ("refused", "ROW_ON_SPO")  # the fallback still sees SPO 7100
    assert h.vendor.writes() == []


def test_an_unbuilt_spo_index_falls_back_for_the_frame_lookup_and_the_linked_qty(h):
    from modules.autocount.write_back.operations import OperationService  # noqa: F401 - import side effects

    _so_dtl, keys = _book(h)
    _wipe_indexes(h)
    svc = h.ops()
    assert svc.prims._spo_ref(DEFAULT_TENANT_ID, h.company.id, keys[1]) == "SPO-7100"
    fresh = {"DocKey": 9999, "Details": []}  # another SPO: every staged SPO row on PO row 1 counts
    assert svc._spo_linked_qty(h.company, fresh, keys[1], own_dtl=0) == Decimal(2)


def test_an_unbuilt_so_index_falls_back_for_the_so_number_and_location(h):
    so_dtl, keys = _book(h)
    _wipe_indexes(h)
    svc = h.ops()
    found = svc.prims._so_row(DEFAULT_TENANT_ID, h.company.id, so_dtl)
    assert found == ("SO-7002", "BR4", False)
    res = h.run("unlink_row", dict(doc_key=7001, dtl_key=keys[0]), key="unbuilt-so")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert h.operation(res).snapshot_json["oldLink"]["FromDocNo"] == "SO-7002"


def test_an_unbuilt_so_index_falls_back_for_the_restage_line_mapping(h):
    from modules.autocount.write_back.doc_mapping import _so_dtl_lookup

    so_dtl, _keys = _book(h)
    _wipe_indexes(h)
    assert _so_dtl_lookup(h.db, DEFAULT_TENANT_ID, h.company, [so_dtl]) == {so_dtl: (7002, "SO-7002")}


def test_a_partly_built_index_is_never_read(h):
    """The job has done some batches (cursor set, ``built_at`` empty): still the full read."""
    from modules.autocount.write_back.link_index import index_ready

    _so_dtl, keys = _book(h)
    _wipe_indexes(h)
    h.db.add(AcIndexBuild(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, index_name=SPO_INDEX,
                          cursor_ref=f"{DBNAME}:7000", docs_done=1))
    h.db.commit()
    assert index_ready(h.db, DEFAULT_TENANT_ID, h.company.id, SPO_INDEX) is False
    assert h.ops().prims._spo_ref(DEFAULT_TENANT_ID, h.company.id, keys[1]) == "SPO-7100"


# ---- the job ----------------------------------------------------------------------------------------------------

def test_the_job_builds_the_same_rows_as_the_runtime_writer_and_marks_the_company_built(h):
    from modules.autocount.write_back.link_index import index_ready

    _book(h, spos=7, sos=5)
    expected_spo, expected_so = _spo_rows(h), _so_rows(h)  # written by the staging writes (refresh_links)
    assert expected_spo and expected_so
    _wipe_indexes(h)
    _build(h, batch_size=3)
    assert _spo_rows(h) == expected_spo
    assert _so_rows(h) == expected_so
    assert index_ready(h.db, DEFAULT_TENANT_ID, h.company.id, SPO_INDEX)
    assert index_ready(h.db, DEFAULT_TENANT_ID, h.company.id, SO_INDEX)


def test_the_job_is_idempotent(h):
    _book(h, spos=4, sos=4)
    _wipe_indexes(h)
    _build(h, batch_size=2)
    first = (_spo_rows(h), _so_rows(h))
    h.db.query(AcIndexBuild).filter_by(company_id=h.company.id).delete()  # force a second full pass
    h.db.commit()
    _build(h, batch_size=5)
    assert (_spo_rows(h), _so_rows(h)) == first  # no duplicates, same rows


def test_the_job_resumes_from_its_cursor_after_a_crash(h, monkeypatch):
    from modules.autocount.write_back import index_build

    _book(h, spos=8, sos=0)
    expected = _spo_rows(h)
    _wipe_indexes(h)
    real = index_build._rebuild_batch
    calls = {"n": 0}

    def crash_on_third(db, tenant_id, company_id, index_name, refs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("worker killed")
        return real(db, tenant_id, company_id, index_name, refs)

    monkeypatch.setattr(index_build, "_rebuild_batch", crash_on_third)
    with pytest.raises(RuntimeError):
        _build(h, batch_size=2)
    h.db.rollback()
    state = h.db.query(AcIndexBuild).filter_by(company_id=h.company.id, index_name=SPO_INDEX).one()
    assert state.built_at is None and state.cursor_ref is not None and state.docs_done == 4
    seen = []

    def record(db, tenant_id, company_id, index_name, refs):
        seen.extend(refs)
        return real(db, tenant_id, company_id, index_name, refs)

    monkeypatch.setattr(index_build, "_rebuild_batch", record)
    _build(h, batch_size=2)
    spo_seen = [r for r in seen if r > state.cursor_ref]
    assert spo_seen and min(spo_seen) > state.cursor_ref  # resumed after the cursor, not from the start
    assert not [r for r in seen if r <= state.cursor_ref and r.startswith(f"{DBNAME}:7")
                and r in {e[0] for e in expected}]  # no SPO before the cursor was redone
    assert _spo_rows(h) == expected


def test_after_the_build_the_lookups_read_the_index(h):
    """Built: the guard answers from ``ac_spo_po_link`` (an index row the staged copies do not hold wins)."""
    _so_dtl, keys = _book(h)
    _wipe_indexes(h)
    _build(h)
    h.db.query(AcSpoPoLink).filter_by(company_id=h.company.id).delete()  # the index now says "no SPO"
    h.db.commit()
    assert h.ops().prims._spo_ref(DEFAULT_TENANT_ID, h.company.id, keys[1]) is None


def test_the_handler_runs_through_background_jobs(h):
    from app.jobs.service import JobService
    from app.models.background_job import JOB_DONE
    from modules.autocount.write_back.index_build import INDEX_BUILD_JOB_TYPE
    from modules.autocount.write_back.link_index import index_ready

    _book(h)
    _wipe_indexes(h)
    job = JobService(h.db).create_and_enqueue(type=INDEX_BUILD_JOB_TYPE, tenant_id=DEFAULT_TENANT_ID)
    h.db.expire_all()
    assert job.status == JOB_DONE, (job.status, job.error)
    assert index_ready(h.db, DEFAULT_TENANT_ID, h.company.id, SPO_INDEX)
    assert (job.result_json or {}).get("docs", 0) > 0


def test_the_sweep_enqueues_one_build_per_tenant_that_needs_it(h, monkeypatch):
    from app.jobs.service import JobService
    from app.models.background_job import BackgroundJob
    from modules.autocount.write_back import index_build

    _book(h)
    _wipe_indexes(h)
    queued = []
    monkeypatch.setattr(JobService, "enqueue", lambda self, job_id: queued.append(job_id))
    assert index_build.enqueue_index_builds(h.db) == 1
    assert index_build.enqueue_index_builds(h.db) == 0  # one already pending: never a second
    job = h.db.query(BackgroundJob).filter_by(type=index_build.INDEX_BUILD_JOB_TYPE).one()
    assert queued == [job.id]
    h.db.delete(job)
    h.db.commit()
    _build(h)
    assert index_build.enqueue_index_builds(h.db) == 0  # built: nothing to do
