"""Auto-push marks and commits per CHUNK, never all-or-nothing (prod finding).

Sorento's api_call_log over 6h of the sales_order task: ~657 requests x 200 =
~131k offers for 23k distinct SOs (~5 offers per document), ~14s per
request, none near the 60s cut. Our side: ``auto_push`` selects up to 5,000
STAGED rows oldest-first, hands ALL of them to one ``write_batch`` (which
chunks at 200 and returns verdicts only after every chunk succeeded), and
marks + commits after that. Any batch-level fault on any chunk returns with
NO marks and NO commit - the next run re-offers the same oldest 5,000 and
Sorento answers ``updated`` again.

Contract:
(1) pushed/quarantined marks are written and COMMITTED per chunk: a fault
    on chunk N keeps chunks 1..N-1 PUSHED, only N.. stay STAGED;
(2) the summary carries ``requests``, ``requestsFailed``, ``firstFailure``
    (status + snippet, ``describe_consumer_failure`` style) and the run
    item exposes them;
(3) a permanently-``retryable`` head must not starve fresh rows.

Rig: the pipeline's company + recording Sorento sink, staged rows inserted
with EXPLICIT increasing ``created_at`` so the oldest-first selection (and
therefore chunk membership) is deterministic; ``autocount_sink_batch_size``
pinned to 3, concurrency left at 1.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Sequence, Set

import httpx
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, BackgroundJob
from modules.autocount.canonical.masters import ENTITY_SUPPLIER, CanonicalSupplier
from modules.autocount.models import STAGED, STAGED_OP_DELETE, STAGED_PUSHED, AcStagedRecord
from modules.autocount.repositories import StagedRecordRepository
from modules.autocount.services.sync_service import SyncService
from modules.autocount.sync import AUTOCOUNT_SYNC
from tests.test_autocount_pipeline import (  # noqa: F401 - fixtures re-exported
    _company,
    _point_at_sorento,
    _sorento_connection,
    sorento_sink,
    transports,
)

BASE = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _batch_of_three(monkeypatch):
    monkeypatch.setattr(settings, "autocount_sink_batch_size", 3)
    monkeypatch.setattr(settings, "autocount_sink_concurrency", 1)


def _done_job(db, company) -> BackgroundJob:
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_DONE,
        payload_json={"companyId": company.id, "entityType": ENTITY_SUPPLIER},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _stage(db, company, job, refs: Sequence[str], *, op: str = "upsert", start: int = 0) -> None:
    """STAGED rows with strictly increasing created_at (oldest first = the
    order given), so chunk membership under oldest-first selection is fixed."""
    repo = StagedRecordRepository(db)
    for i, ref in enumerate(refs):
        record = CanonicalSupplier(
            source_ref=ref, source_doc_no=ref, code=ref, name=f"N {ref}", email=None, is_active=True,
        )
        repo.add(
            AcStagedRecord(
                tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SUPPLIER,
                job_id=job.id, source_ref=ref, canonical_json=record.comparable(),
                status=STAGED, op=op, created_at=BASE + timedelta(seconds=start + i),
            )
        )
    db.commit()


def _statuses(session_factory, company_id: str, *, rollback: object = None) -> Dict[str, str]:
    """Read back what is actually COMMITTED. The conftest engine is
    ``sqlite://`` on a StaticPool - every session shares ONE connection, so a
    "fresh" session sees uncommitted rows too. Pass the run's session as
    ``rollback`` to discard its uncommitted state first; only marks that were
    committed per chunk survive."""
    if rollback is not None:
        rollback.rollback()
    s = session_factory()
    try:
        rows = (
            s.query(AcStagedRecord)
            .filter(AcStagedRecord.tenant_id == DEFAULT_TENANT_ID, AcStagedRecord.company_id == company_id)
            .all()
        )
        return {r.source_ref: r.status for r in rows}
    finally:
        s.close()


def _ok(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if request.url.path.endswith("/deletions"):
        refs = body["source_refs"]
        return httpx.Response(200, json={
            "summary": {"total": len(refs), "deleted": len(refs), "deactivated": 0,
                        "not_found": 0, "failed": 0, "retryable": 0},
            "records": [{"source_ref": r, "outcome": "deleted"} for r in refs],
        })
    recs = [
        {"source_ref": r["source_ref"], "outcome": "created", "entity_id": f"id-{r['source_ref']}"}
        for r in body["records"]
    ]
    return httpx.Response(200, json={
        "summary": {"total": len(recs), "created": len(recs), "updated": 0, "failed": 0, "retryable": 0},
        "records": recs,
    })


def _offered(requests: List[httpx.Request]) -> List[Set[str]]:
    out: List[Set[str]] = []
    for r in requests:
        body = json.loads(r.content)
        if r.url.path.endswith("/deletions"):
            out.append(set(body["source_refs"]))
        else:
            out.append({rec["source_ref"] for rec in body["records"]})
    return out


def _rig(db, transports):
    company = _company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    return company


def _count_commits(db) -> List[int]:
    """Session-level ``after_commit`` counter on the run's own session (a
    heartbeat's connection-level commit does not register here)."""
    import sqlalchemy as sa

    commits: List[int] = []
    sa.event.listen(db, "after_commit", lambda session: commits.append(1))
    return commits


REFS = [f"AED_VSOFT:{i}" for i in range(7)]  # chunks: 0-2 / 3-5 / 6


# ── (a) chunk 2 answers 500 ─────────────────────────────────────────────────


def test_a_500_on_chunk_two_keeps_chunk_one_pushed_and_committed(session_factory, transports, sorento_sink):
    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    _stage(db, company, job, REFS)

    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 2:
            return httpx.Response(500, json={"message": "Internal server error"})
        return _ok(request)

    sorento_sink.responder = responder
    commits = _count_commits(db)
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)

    # B2: chunk 1's marks must survive a ROLLBACK of the run's session - i.e.
    # they were committed when chunk 1 resolved, not left for a final commit.
    assert len(commits) >= 1, "no Session commit happened while chunk 1 resolved"
    statuses = _statuses(session_factory, company.id, rollback=db)
    assert [statuses[r] for r in REFS[:3]] == [STAGED_PUSHED] * 3, statuses
    assert [statuses[r] for r in REFS[3:]] == [STAGED] * 4, statuses
    assert summary["pushed"] == 3
    assert summary["requests"] == 2
    assert summary["requestsFailed"] == 1
    assert "HTTP 500" in str(summary["firstFailure"])
    assert summary["error"], "the batch-level fault must still surface as the run error"

    # The next run re-offers ONLY the four rows the fault left behind.
    sorento_sink.requests.clear()
    sorento_sink.responder = _ok
    second = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)
    offered = _offered(sorento_sink.requests)
    assert set().union(*offered) == set(REFS[3:]), offered
    assert second["pushed"] == 4
    assert second["requests"] == 2 and second["requestsFailed"] == 0
    assert set(_statuses(session_factory, company.id).values()) == {STAGED_PUSHED}
    db.close()


# ── (b) a transport timeout on chunk 3 ──────────────────────────────────────


def test_a_timeout_on_chunk_three_keeps_the_first_two_chunks_pushed(session_factory, transports, sorento_sink):
    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    _stage(db, company, job, REFS)

    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 3:
            raise httpx.ReadTimeout("read timed out", request=request)
        return _ok(request)

    sorento_sink.responder = responder
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)

    statuses = _statuses(session_factory, company.id)
    assert [statuses[r] for r in REFS[:6]] == [STAGED_PUSHED] * 6, statuses
    assert statuses[REFS[6]] == STAGED
    assert summary["pushed"] == 6
    assert summary["requests"] == 3
    assert summary["requestsFailed"] == 1
    first_failure = str(summary["firstFailure"])
    assert "ReadTimeout" in first_failure or "unreachable" in first_failure.lower()
    db.close()


# ── (c) delete path parity ──────────────────────────────────────────────────


def test_a_500_on_the_second_deletions_chunk_keeps_the_first_chunk_handled(session_factory, transports, sorento_sink):
    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    _stage(db, company, job, REFS, op=STAGED_OP_DELETE)

    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/deletions")
        calls["n"] += 1
        if calls["n"] == 2:
            return httpx.Response(500, json={"message": "Internal server error"})
        return _ok(request)

    sorento_sink.responder = responder
    commits = _count_commits(db)
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)

    assert len(commits) >= 1, "no Session commit happened while deletions chunk 1 resolved"
    statuses = _statuses(session_factory, company.id, rollback=db)
    assert [statuses[r] for r in REFS[:3]] == [STAGED_PUSHED] * 3, statuses
    assert [statuses[r] for r in REFS[3:]] == [STAGED] * 4, statuses
    assert summary["deletedHandled"] == 3
    assert summary["requests"] == 2
    assert summary["requestsFailed"] == 1
    assert "HTTP 500" in str(summary["firstFailure"])
    db.close()


# ── (d) a permanently-retryable head must not starve fresh rows ─────────────


def test_a_retryable_head_does_not_starve_fresh_rows_within_two_runs(
    session_factory, transports, sorento_sink, monkeypatch
):
    """6 rows the consumer always answers ``retryable`` were staged first; 3
    fresh rows after them; the offer cap is 5. Oldest-first alone re-offers
    the same 5 retryable rows forever. Within two runs the 3 fresh rows must
    have been offered (the exact skip rule - retry_count / last_offered_at -
    is the coder's; only starvation is pinned here)."""
    from modules.autocount.repositories import autocount_repository as repo_module

    original = repo_module.StagedRecordRepository.list_pending_for_entity

    def capped(self, tenant_id, company_id, entity_type, *, job_type, limit=5000):
        return original(self, tenant_id, company_id, entity_type, job_type=job_type, limit=5)

    monkeypatch.setattr(repo_module.StagedRecordRepository, "list_pending_for_entity", capped)

    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    stuck = [f"AED_VSOFT:S{i}" for i in range(6)]
    fresh = [f"AED_VSOFT:F{i}" for i in range(3)]
    _stage(db, company, job, stuck, start=0)
    _stage(db, company, job, fresh, start=100)

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        recs = []
        for r in body["records"]:
            ref = r["source_ref"]
            if ref in stuck:
                recs.append({"source_ref": ref, "outcome": "retryable",
                             "errors": {"supplier_ref": "not synced yet"}})
            else:
                recs.append({"source_ref": ref, "outcome": "created", "entity_id": f"id-{ref}"})
        retryable = sum(1 for r in recs if r["outcome"] == "retryable")
        return httpx.Response(200, json={
            "summary": {"total": len(recs), "created": len(recs) - retryable, "updated": 0,
                        "failed": 0, "retryable": retryable},
            "records": recs,
        })

    sorento_sink.responder = responder
    offered_all: Set[str] = set()
    for _ in range(2):
        sorento_sink.requests.clear()
        SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)
        offered_all |= set().union(*(_offered(sorento_sink.requests) or [set()]))

    assert set(fresh) <= offered_all, (
        f"fresh rows starved behind a retryable head: offered={sorted(offered_all)}"
    )
    statuses = _statuses(session_factory, company.id)
    assert all(statuses[r] == STAGED_PUSHED for r in fresh), statuses
    assert all(statuses[r] == STAGED for r in stuck), statuses
    db.close()


# ── (2) the run item exposes the request accounting ─────────────────────────


def test_the_run_item_exposes_requests_requests_failed_and_first_failure():
    from modules.autocount.schemas import SyncRunItem

    fields = set(SyncRunItem.model_fields)
    assert {"requests", "requestsFailed", "firstFailure"} <= fields, sorted(fields)


# ═══════════════════════════════════════════════════════════════════════════
#  Transient 5xx retry (root cause: Sorento's nginx answers 502 on ~1 in 25
#  requests; every failed prod run carries "Sorento returned HTTP 502 ... nginx")
# ═══════════════════════════════════════════════════════════════════════════

NGINX_502 = "<html><head><title>502 Bad Gateway</title></head><body><center><h1>502 Bad Gateway</h1></center><hr><center>nginx</center></body></html>"


@pytest.fixture
def no_sleep(monkeypatch) -> List[float]:
    slept: List[float] = []
    monkeypatch.setattr("modules.autocount.sinks_sorento.time.sleep", slept.append)
    return slept


def _sequenced(script: Dict[int, object]):
    """A responder keyed by POST number: an int is an HTTP status (5xx/4xx
    with an nginx-style body), ``"ok"`` (or an unlisted call) answers created."""
    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        step = script.get(calls["n"], "ok")
        if isinstance(step, int):
            return httpx.Response(step, text=NGINX_502.replace("502 Bad Gateway", f"{step} Gateway"))
        return _ok(request)

    return responder, calls


def test_retry_attempts_setting_defaults_to_3(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("AUTOCOUNT_SINK_RETRY_ATTEMPTS", raising=False)
    assert Settings().autocount_sink_retry_attempts == 3


# ── (f) a 502 then 200 on retry is a delivered chunk ────────────────────────


def test_a_502_answered_200_on_retry_marks_the_chunk_pushed(session_factory, transports, sorento_sink, no_sleep):
    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    _stage(db, company, job, REFS)

    # POST 1 = chunk 1 ok; POST 2 = chunk 2 -> 502; POST 3 = chunk 2 retry ok; POST 4 = chunk 3 ok.
    responder, calls = _sequenced({2: 502})
    sorento_sink.responder = responder
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)

    assert set(_statuses(session_factory, company.id).values()) == {STAGED_PUSHED}
    assert summary["pushed"] == 7
    assert summary["requestsFailed"] == 0
    assert summary.get("error") is None, summary
    assert summary["requests"] >= 3, summary
    assert calls["n"] == 4, "one retry: four POSTs for three chunks"
    # Every chunk was offered exactly once per attempt - the retried chunk
    # carried the SAME rows both times.
    offered = _offered(sorento_sink.requests)
    assert offered[1] == offered[2] == set(REFS[3:6])
    db.close()


# ── (g) the attempt cap fails ONLY that chunk; later chunks still go out ────


def test_a_502_at_the_attempt_cap_fails_only_that_chunk_and_the_push_continues(
    session_factory, transports, sorento_sink, no_sleep, monkeypatch
):
    monkeypatch.setattr(settings, "autocount_sink_retry_attempts", 3, raising=False)
    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    _stage(db, company, job, REFS)

    # chunk 1 ok (POST 1); chunk 2 -> 502 x3 (POSTs 2-4); chunk 3 ok (POST 5).
    responder, calls = _sequenced({2: 502, 3: 502, 4: 502})
    sorento_sink.responder = responder
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)

    statuses = _statuses(session_factory, company.id)
    assert [statuses[r] for r in REFS[:3]] == [STAGED_PUSHED] * 3, statuses
    assert [statuses[r] for r in REFS[3:6]] == [STAGED] * 3, statuses
    assert statuses[REFS[6]] == STAGED_PUSHED, "a later chunk is still attempted after a transient failure"
    assert summary["pushed"] == 4
    assert summary["requestsFailed"] == 1
    assert "HTTP 502" in str(summary["firstFailure"])
    assert summary["error"], "the failed chunk still surfaces as the run error"
    assert calls["n"] == 5, "3 attempts on chunk 2 + chunk 1 + chunk 3"
    db.close()


def test_a_4xx_still_ends_the_push_without_retry(session_factory, transports, sorento_sink, no_sleep):
    """A 4xx is not transient: one attempt, that chunk fails, and the push
    ends there (chunk 3 is not attempted) - the pre-fix posture for anything
    that is not a 5xx blip."""
    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    _stage(db, company, job, REFS)

    responder, calls = _sequenced({2: 400})
    sorento_sink.responder = responder
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)

    statuses = _statuses(session_factory, company.id)
    assert [statuses[r] for r in REFS[:3]] == [STAGED_PUSHED] * 3, statuses
    assert [statuses[r] for r in REFS[3:]] == [STAGED] * 4, statuses
    assert calls["n"] == 2, "no retry on a 4xx and no further chunk"
    assert summary["requestsFailed"] == 1
    assert "HTTP 400" in str(summary["firstFailure"])
    assert no_sleep == []
    db.close()


# ── (h) retry only 502/503/504; a 500 is one attempt; backoff bounded ───────


@pytest.mark.parametrize("status", [502, 503, 504])
def test_transient_statuses_are_retried(session_factory, transports, sorento_sink, no_sleep, status):
    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    _stage(db, company, job, REFS[:3])  # one chunk

    responder, calls = _sequenced({1: status})
    sorento_sink.responder = responder
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)

    assert calls["n"] == 2, f"HTTP {status} must be retried once"
    assert summary["pushed"] == 3 and summary["requestsFailed"] == 0
    db.close()


def test_a_500_is_not_retried(session_factory, transports, sorento_sink, no_sleep):
    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    _stage(db, company, job, REFS)

    responder, calls = _sequenced({2: 500})
    sorento_sink.responder = responder
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)

    statuses = _statuses(session_factory, company.id)
    assert [statuses[r] for r in REFS[:3]] == [STAGED_PUSHED] * 3
    assert [statuses[r] for r in REFS[3:6]] == [STAGED] * 3
    assert summary["requestsFailed"] == 1
    assert "HTTP 500" in str(summary["firstFailure"])
    # Chunk 2 was attempted exactly once: POSTs = chunk 1 + chunk 2 (+ chunk 3
    # if the loop continues past a non-transient chunk fault - either way no
    # second attempt on chunk 2).
    assert offered_count(sorento_sink.requests, set(REFS[3:6])) == 1
    assert no_sleep == []
    db.close()


def offered_count(requests: List[httpx.Request], refs: Set[str]) -> int:
    return sum(1 for chunk in _offered(requests) if chunk == refs)


def test_backoff_is_bounded_across_the_attempt_cap(session_factory, transports, sorento_sink, no_sleep, monkeypatch):
    monkeypatch.setattr(settings, "autocount_sink_retry_attempts", 3, raising=False)
    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    _stage(db, company, job, REFS[:3])

    responder, calls = _sequenced({1: 502, 2: 502, 3: 502})
    sorento_sink.responder = responder
    SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)

    assert calls["n"] == 3
    assert no_sleep, "a retry must back off, never hammer nginx immediately"
    assert sum(no_sleep) <= 10.0, f"backoff for three attempts must stay bounded: {no_sleep}"
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  Review round 2 (76510bb3): B1, B2 (above), S1, S3, S4, S5
# ═══════════════════════════════════════════════════════════════════════════

import sqlalchemy as sa  # noqa: E402

from modules.autocount.models import STAGED_FAILED, AcSyncRun  # noqa: E402
from tests.test_autocount_bulk_load import (  # noqa: E402,F401 - fixtures re-exported
    RUN_MODE_MANUAL,
    _clean_runtime,
    _insert_rows,
    _make_rig,
    _rows,
    _run,
    _run_row,
    consumer,
)


def _sequenced_upsert(consumer, script: Dict[int, int]):
    """Override the bulk-load Consumer's ``_upsert`` by POST number: an int
    answers that HTTP status with an nginx-style body, else the normal
    created verdicts."""
    original = consumer._upsert
    calls = {"n": 0}

    def upsert(body):
        calls["n"] += 1
        status = script.get(calls["n"])
        if status is not None:
            return httpx.Response(status, text=NGINX_502.replace("502 Bad Gateway", f"{status} Gateway"))
        return original(body)

    consumer._upsert = upsert
    return calls


# ── B1: the paged run persists the accounting on the run row ────────────────


def test_a_paged_run_persists_error_requests_requests_failed_and_first_failure_on_the_run_row(
    session_factory, monkeypatch, consumer, no_sleep
):
    monkeypatch.setattr(settings, "autocount_page_size", 100, raising=False)
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 600, raising=False)
    monkeypatch.setattr(settings, "autocount_sink_retry_attempts", 3, raising=False)

    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(7))
    # chunk 1 ok (POST 1); chunk 2 -> 502 x3 (POSTs 2-4, exhausted); chunk 3 ok (POST 5).
    calls = _sequenced_upsert(consumer, {2: 502, 3: 502, 4: 502})

    db = session_factory()
    job = _run(db, company_id, RUN_MODE_MANUAL)
    db.close()

    fresh = session_factory()
    try:
        run = fresh.query(AcSyncRun).filter(AcSyncRun.job_id == job.id).one()
        assert run.error, "a failed chunk must leave a non-null run error"
        # ``requests`` counts CHUNKS this run offered (retries of one chunk are
        # not separate chunks); ``requests_failed`` the chunks that never resolved.
        assert run.requests == 3, run.requests
        assert run.requests_failed == 1
        assert run.first_failure, "first_failure must be persisted on the run row"
        assert "HTTP 502" in str(run.first_failure)
        assert run.pushed_count == 4
        statuses = {
            r.source_ref: r.status
            for r in fresh.query(AcStagedRecord).filter(AcStagedRecord.company_id == company_id)
        }
        assert sorted(statuses.values()) == sorted([STAGED_PUSHED] * 4 + [STAGED] * 3)
    finally:
        fresh.close()
    assert calls["n"] == 5


# ── S1: a truncated pass keeps BOTH the budget note and the push failure ────


def test_a_truncated_pass_with_a_failed_push_chunk_keeps_both_texts_on_the_run_error(
    session_factory, monkeypatch, consumer, no_sleep
):
    monkeypatch.setattr(settings, "autocount_page_size", 5, raising=False)
    # Budget 0 cuts the run after its FIRST page (the loop checks the page's
    # own completeness before the budget) - page 1 carries 5 of the 7 rows.
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 0, raising=False)

    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(7))
    # page 1 = 5 rows -> chunks of 3 / 2; chunk 2 answers a plain 500.
    _sequenced_upsert(consumer, {2: 500})

    db = session_factory()
    job = _run(db, company_id, RUN_MODE_MANUAL)
    run = _run_row(db, company_id, job.id)

    assert run.truncated is True
    assert run.error, "the run error must not be wiped"
    assert "Budget reached" in run.error, run.error
    assert "HTTP 500" in run.error, run.error
    assert run.requests_failed == 1
    db.close()


# ── S3: a commit that fails inside apply_chunk must not poison the session ──


def test_a_commit_failure_on_chunk_two_stops_the_push_and_leaves_the_session_usable(
    session_factory, transports, sorento_sink
):
    """A real flush failure inside the per-chunk commit (here a NOT NULL
    violation on a chunk-2 row) rolls SQLAlchemy's transaction back and, if
    nobody calls ``rollback()``, every later statement raises
    ``PendingRollbackError`` - the run row could never be written. The push
    must stop at that chunk, account the failure, keep chunk 1's committed
    marks, and hand back a usable session."""
    from sqlalchemy.exc import PendingRollbackError

    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    _stage(db, company, job, REFS)
    chunk2_row = (
        db.query(AcStagedRecord)
        .filter(AcStagedRecord.company_id == company.id, AcStagedRecord.source_ref == REFS[3])
        .one()
    )
    chunk2_id = chunk2_row.id
    db.expire_all()

    sorento_sink.responder = _ok
    real_commit = db.commit
    state = {"commits": 0}

    def sabotaged_commit():
        state["commits"] += 1
        target = db.get(AcStagedRecord, chunk2_id)
        if target.status == STAGED_PUSHED and not state.get("poisoned"):
            # Chunk 2's own per-chunk commit (its rows were just marked in
            # session): poison the flush with an invalid value on one of them.
            state["poisoned"] = True
            target.status = None  # NOT NULL column -> IntegrityError inside commit
        return real_commit()

    db.commit = sabotaged_commit  # instance attribute, this session only
    posts_before = len(sorento_sink.requests)
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)
    db.commit = real_commit

    assert len(sorento_sink.requests) - posts_before == 2, "the push must stop at the failing chunk"
    assert summary["error"], summary
    assert summary["firstFailure"], summary
    # The session is usable without the caller having to know a commit failed.
    try:
        db.query(AcStagedRecord).filter(AcStagedRecord.company_id == company.id).count()
    except PendingRollbackError as exc:  # pragma: no cover - the failure we are guarding
        pytest.fail(f"session poisoned after a failed per-chunk commit: {exc}")
    statuses = _statuses(session_factory, company.id, rollback=db)
    assert [statuses[r] for r in REFS[:3]] == [STAGED_PUSHED] * 3, statuses
    assert [statuses[r] for r in REFS[3:]] == [STAGED] * 4, statuses
    db.close()


# ── S4: one STAGED row per source_ref ───────────────────────────────────────


def test_re_extracting_an_unresolved_document_updates_its_staged_row_in_place(
    session_factory, monkeypatch, consumer
):
    """Doc X is staged and the consumer answers ``retryable`` (unresolved);
    X changes at source and is extracted again by the next run. There must
    be ONE STAGED row for X, carrying the NEWER payload - never a second
    insert that would be offered twice (and pushed twice) later."""
    monkeypatch.setattr(settings, "autocount_page_size", 100, raising=False)
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 600, raising=False)

    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(1))  # 300-B0000, "Company 0"
    ref = f"AED_BULK:300-B0000"

    original = consumer._upsert

    def retryable_upsert(body):
        recs = [
            {"source_ref": r["source_ref"], "outcome": "retryable", "errors": {"x": "not yet"}}
            for r in body["records"]
        ]
        return httpx.Response(200, json={
            "summary": {"total": len(recs), "created": 0, "updated": 0, "failed": 0, "retryable": len(recs)},
            "records": recs,
        })

    consumer._upsert = retryable_upsert

    db = session_factory()
    job1 = _run(db, company_id, RUN_MODE_MANUAL)
    assert job1.status == JOB_DONE, job1.error
    rows_after_first = (
        db.query(AcStagedRecord)
        .filter(AcStagedRecord.company_id == company_id, AcStagedRecord.source_ref == ref)
        .all()
    )
    assert len(rows_after_first) == 1 and rows_after_first[0].status == STAGED

    # The document changes at source and is picked up by the next run.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE debtor SET company_name = 'Company 0 RENAMED', "
            "last_modified = '2026-08-01 05:00:00' WHERE acc_no = '300-B0000'"
        )
    job2 = _run(db, company_id, RUN_MODE_MANUAL)
    assert job2.status == JOB_DONE, job2.error
    db.expire_all()

    staged_for_ref = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.source_ref == ref,
            AcStagedRecord.status == STAGED,
        )
        .all()
    )
    assert len(staged_for_ref) == 1, (
        f"expected ONE STAGED row for {ref}, got {len(staged_for_ref)} (a second insert "
        f"means the document is offered twice)"
    )
    assert (staged_for_ref[0].canonical_json or {}).get("name") == "Company 0 RENAMED"
    consumer._upsert = original
    db.close()


def test_two_staged_rows_for_one_ref_are_both_marked_after_a_successful_chunk(
    session_factory, transports, sorento_sink
):
    """Defence in depth: if duplicates exist anyway (legacy data), a
    successful push must mark EVERY staged row of that ref - a ref-to-row
    dict that keeps only the last one leaves a ghost STAGED row to be
    re-offered forever."""
    db = session_factory()
    company = _rig(db, transports)
    job = _done_job(db, company)
    _stage(db, company, job, ["AED_VSOFT:dup", "AED_VSOFT:other"])
    _stage(db, company, job, ["AED_VSOFT:dup"], start=50)  # the duplicate, staged later

    sorento_sink.responder = _ok
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, job_id=job.id)

    rows = (
        db.query(AcStagedRecord)
        .filter(AcStagedRecord.company_id == company.id, AcStagedRecord.source_ref == "AED_VSOFT:dup")
        .all()
    )
    assert len(rows) == 2
    assert {r.status for r in rows} == {STAGED_PUSHED}, [r.status for r in rows]
    assert summary["pushed"] == 3
    db.close()


# ── S5: the 429 wait is capped ──────────────────────────────────────────────


def _sink_with(responder, **kwargs):
    from modules.autocount.sinks_sorento import SorentoSink

    return SorentoSink(
        base_url="http://x", api_key="k", entity_type="supplier",
        transport=httpx.MockTransport(responder), **kwargs,
    )


def _supplier_records(n: int):
    return [
        CanonicalSupplier(source_ref=f"AED:{i}", source_doc_no=f"C{i}", code=f"C{i}", name="N", is_active=True)
        for i in range(n)
    ]


def test_a_huge_retry_after_is_capped_at_sixty_seconds(no_sleep):
    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "3600"}, json={"code": "rate_limited"})
        return _ok(request)

    sink = _sink_with(responder, batch_size=3)
    results = sink.write_batch(_supplier_records(3), request_id="t")

    assert len(results) == 3 and all(r.delivered for r in results)
    assert no_sleep, "a 429 must still wait before retrying"
    assert max(no_sleep) <= 60.0, f"Retry-After must be capped at 60s, slept {no_sleep}"


def test_a_transient_retry_does_not_re_enter_an_uncapped_429_wait(no_sleep, monkeypatch):
    """502 -> backoff -> 429 (Retry-After 3600) -> 200: the total wait for
    the chunk stays within one capped 429 wait plus the bounded backoff."""
    monkeypatch.setattr(settings, "autocount_sink_retry_attempts", 3, raising=False)
    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(502, text=NGINX_502)
        if calls["n"] == 2:
            return httpx.Response(429, headers={"Retry-After": "3600"}, json={"code": "rate_limited"})
        return _ok(request)

    sink = _sink_with(responder, batch_size=3)
    results = sink.write_batch(_supplier_records(3), request_id="t")

    assert len(results) == 3 and all(r.delivered for r in results)
    assert calls["n"] == 3
    assert sum(no_sleep) <= 65.0, f"total wait must stay bounded: {no_sleep}"
