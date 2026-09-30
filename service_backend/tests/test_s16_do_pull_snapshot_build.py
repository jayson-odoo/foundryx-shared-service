"""Sprint-5/16 - the `delivery_orders` snapshot build job (AC-16-20..33): the
`autocount_pull_snapshot` handler's DO branch. Contract of record:
`documentation/plans/sprint-5/16-autocount-do-pull-snapshot-contract.md`.

RED before the coder: `delivery_orders` is an unknown gateway entity (422
`UNKNOWN_ENTITY`) and `PullService.request_build` has no `scope` parameter.

ASSUMED NAMES the coder must conform to:

* The build job is the EXISTING `autocount_pull_snapshot` job type
  (`modules.autocount.sync.AUTOCOUNT_PULL_SNAPSHOT`, handler
  `_run_pull_snapshot`), payload `{companyId, entityType, snapshotId,
  fromDay, toDay, docNo}`; the DO body lives in
  `modules.autocount.doc_feed.snapshot`.
* `PullService.request_build(tenant_id, company_id, entity_type, *,
  requested_via, requested_by=None, now=None, scope=None)` where `scope` is
  `{"fromDay": "YYYY-MM-DD", "toDay": "YYYY-MM-DD", "docNo": str | None}`
  (already normalised; used by the abandonment tests that drive the build
  through the service seam so a callback can flip the snapshot mid-build).
* Vendor reads go through `modules.autocount.doc_feed.runner.resolve_vendor`
  -> `HttpApiClient` built from THAT module's own import; the tests patch
  `modules.autocount.doc_feed.runner.HttpApiClient` (`VendorStub.install`).
  Only `/deliveryorderbydocdate` is routed: any other path (contract probe,
  lookups, `byLastModified`) asserts and lands in `stub.unrouted`.
* Under eager jobs the build runs inline in the POST; the tests read the
  terminal state straight from the DB (`stored_snapshot` / `stored_rows`).
* Row `source_ref` column = `{book}:DO:{DocKey}`; failed code for any vendor
  day failure = `SOURCE_PAGE_FAILED`; `metadata_json` carries `fromDay`,
  `toDay`, `docNo`, `book`, `daysRead`, `fetchedCount`, `lineCount`,
  `excludedRows`, `excludedCount`, `sourcePageSize` (null).
* The `missing_doc_key` excluded-row message is the contract's example text.

Kill tests:
* AC-16-21: replace `dedupe_latest` with "first wins" and
  `test_ac_16_21_*` fails (the day-2 copy of 55120 is the newer one).
* AC-16-28: swallow a day failure and continue (a partial snapshot) and every
  `test_ac_16_28_*` case fails (the middle day fails, two days succeed).
* AC-16-32: reuse `run_poll` for the read and `test_ac_16_32_*` fails (it
  writes run / ledger rows and moves the cursor).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from app.models.integration_activity import IntegrationActivity
from modules.autocount.models import (
    RUN_FAILED,
    RUN_SUCCESS,
    AcDocFeed,
    AcDocFeedBackfill,
    AcDocFeedIssue,
    AcDocFeedLedger,
    AcDocFeedRun,
    AcDocFingerprint,
    AcPullSnapshot,
    AcPullSnapshotRow,
    AcRowHash,
    AcStagedRecord,
    AcSyncRun,
    AcWatermark,
)

from .s14_doc_feed_helpers import BOOK, JsonRoute, load_fixture
from .s16_do_pull_helpers import (  # noqa: F401 - s16_isolation is an autouse fixture
    ENTITY_DO,
    build_env,
    day_ago,
    defer_jobs,
    do_rec,
    fixture_records,
    get_header,
    iso,
    post_build,
    s16_isolation,
    stored_rows,
    stored_snapshot,
    tiny_rec,
)

MISSING_KEY_MESSAGE = "DocKey is missing or not an integer; the record cannot be identified."


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _build(client, env, **scope) -> str:
    response = post_build(client, env.key, **scope)
    assert response.status_code == 202, response.text
    return response.json()["snapshotId"]


def _payloads(db, snapshot_id: str) -> List[Dict[str, Any]]:
    return [row.payload_json for row in stored_rows(db, snapshot_id)]


def _spy_beat_progress(monkeypatch, on_call=None) -> List[tuple]:
    """Wraps the REAL `JobService.beat_progress` (per-page / per-day liveness +
    progress in ONE UPDATE) and records `(stage, done, total)`."""
    from app.jobs.service import JobService

    calls: List[tuple] = []
    real = JobService.beat_progress

    def spy(self, job_id, *, done=None, total=None, stage=None, now=None):
        result = real(self, job_id, done=done, total=total, stage=stage)
        calls.append((stage, done, total))
        if on_call is not None:
            on_call(len(calls), stage, done, total)
        return result

    monkeypatch.setattr(JobService, "beat_progress", spy)
    return calls


# ── AC-16-20: the vendor reads ───────────────────────────────────────────────


def test_ac_16_20_reads_the_by_doc_date_door_once_per_day_inclusive_and_nothing_else(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch)
    days = [day_ago(4), day_ago(3), day_ago(2)]

    snapshot_id = _build(client, env, fromDay=iso(days[0]), toDay=iso(days[-1]))

    assert stored_snapshot(db, snapshot_id).status == "ready"
    assert env.stub.paths == ["/deliveryorderbydocdate"] * 3
    assert sorted(env.stub.days) == days
    assert env.stub.unrouted == [], "no contract probe, lookup or byLastModified read"
    assert all(r.method == "GET" for r in env.stub.requests)


def test_ac_16_20_reads_through_the_feed_connections_base_url(client, db, monkeypatch):
    env = build_env(db, monkeypatch)

    _build(client, env, fromDay=iso(day_ago(1)))

    (request,) = env.stub.requests
    assert str(request.url).startswith(
        "https://hapi.sorento.cc.cd/api/db1/deliveryorderbydocdate?DocDate="
    )
    assert request.url.params["DocDate"] == day_ago(1).strftime("%Y%m%d")


def test_ac_16_20_a_company_with_a_wired_sink_never_has_its_sink_or_contract_touched(
    client, db, monkeypatch,
):
    from modules.autocount.sinks_sorento import SorentoSink

    probes: List[str] = []

    def no_probe(self, *a, **k):
        probes.append("contract")
        raise AssertionError("the DO snapshot must never probe the CRM contract")

    monkeypatch.setattr(SorentoSink, "fetch_contract_detail", no_probe)
    env = build_env(db, monkeypatch, wired_sink=True)

    snapshot_id = _build(client, env, fromDay=iso(day_ago(1)))

    assert stored_snapshot(db, snapshot_id).status == "ready"
    assert probes == []
    assert env.stub.unrouted == []


def test_ac_16_20_the_job_payload_scope_alone_drives_a_direct_handler_call(db, monkeypatch):
    """Direct `_run_pull_snapshot` call with a hand-built job: proves the
    payload keys `{fromDay, toDay, docNo}` are what the handler reads."""
    from app.jobs.service import JobService
    from modules.autocount.services.pull_service import SnapshotService
    from modules.autocount.sync import AUTOCOUNT_PULL_SNAPSHOT, _run_pull_snapshot

    day = day_ago(2)
    recs = fixture_records()
    env = build_env(db, monkeypatch, day_fn=lambda d: recs if d == day else [])
    snap = SnapshotService(db).create_building(
        DEFAULT_TENANT_ID, env.company.id, ENTITY_DO,
        company_code="SRT", requested_via="gateway",
    )
    jobs = JobService(db)
    job = jobs.create(
        type=AUTOCOUNT_PULL_SNAPSHOT, tenant_id=DEFAULT_TENANT_ID,
        payload={
            "companyId": env.company.id, "entityType": ENTITY_DO, "snapshotId": snap.id,
            "fromDay": iso(day), "toDay": iso(day), "docNo": None,
        },
    )
    assert jobs.claim(job.id)
    job = jobs.get(DEFAULT_TENANT_ID, job.id)

    _run_pull_snapshot(db, job)

    after = stored_snapshot(db, snap.id)
    assert after.status == "ready"
    assert after.record_count == 2
    assert env.stub.days == [day]


# ── AC-16-21: dedupe and order ───────────────────────────────────────────────


def test_ac_16_21_one_row_per_dockey_greatest_last_modified_wins_ordered_by_docdate_then_dockey(
    client, db, monkeypatch,
):
    d1, d2 = day_ago(2), day_ago(1)
    a_old = do_rec(55120, "DO-A", "2026-09-28T00:00:00", "2026-09-28T09:00:00.000", Ref="old")
    a_new = do_rec(55120, "DO-A", "2026-09-29T00:00:00", "2026-09-29T09:00:00.000", Ref="new")
    b = do_rec(55121, "DO-B", "2026-09-27T00:00:00", "2026-09-27T08:00:00.000")
    c_keep = do_rec(55122, "DO-C", "2026-09-28T00:00:00", "2026-09-28T12:00:00.000", Ref="keep")
    c_stale = do_rec(55122, "DO-C", "2026-09-28T00:00:00", "2026-09-28T08:00:00.000", Ref="stale")
    e = do_rec(55119, "DO-E", "2026-09-28T00:00:00", "2026-09-28T07:00:00.000")
    answers = {d1: [a_old, c_keep, e], d2: [a_new, b, c_stale]}
    env = build_env(db, monkeypatch, day_fn=lambda d: answers.get(d, []))

    snapshot_id = _build(client, env, fromDay=iso(d1), toDay=iso(d2))

    rows = stored_rows(db, snapshot_id)
    # DocDate asc, then DocKey asc: 55121 (09-27), 55119 + 55122 (09-28), 55120 (09-29)
    assert [r.payload_json["DocKey"] for r in rows] == [55121, 55119, 55122, 55120]
    assert [r.row_index for r in rows] == [0, 1, 2, 3]
    by_key = {r.payload_json["DocKey"]: r.payload_json for r in rows}
    assert by_key[55120]["Ref"] == "new", "the greatest LastModified copy wins across days"
    assert by_key[55122]["Ref"] == "keep", "the greatest LastModified copy wins over a stale duplicate"
    snap = stored_snapshot(db, snapshot_id)
    assert snap.record_count == 4
    assert snap.metadata_json["fetchedCount"] == 6


# ── AC-16-22: rows are the raw vendor dicts ──────────────────────────────────


def test_ac_16_22_payload_is_the_raw_vendor_dict_verbatim_and_source_ref_is_book_do_dockey(
    client, db, monkeypatch,
):
    day = day_ago(1)
    recs = fixture_records()
    recs[0]["UnknownVendorKey"] = {"nested": [1, 2.5, None, "x"], "flag": True}
    expected = json.loads(json.dumps(recs))
    env = build_env(db, monkeypatch, day_fn=lambda d: recs if d == day else [])

    snapshot_id = _build(client, env, fromDay=iso(day))

    rows = stored_rows(db, snapshot_id)
    assert [r.source_ref for r in rows] == ["db1:DO:55120", "db1:DO:55121"]
    assert BOOK == "db1"
    assert [r.row_index for r in rows] == [0, 1]
    for row, want in zip(rows, expected):
        assert row.payload_json == want
        # byte-for-byte: no number re-typed (250.0 must not become 250), no key dropped
        assert json.dumps(row.payload_json, sort_keys=True) == json.dumps(want, sort_keys=True)
        assert row.company_id == env.company.id
        assert row.tenant_id == DEFAULT_TENANT_ID
    assert rows[0].payload_json["Details"] == expected[0]["Details"]
    assert rows[0].payload_json["UnknownVendorKey"] == {"nested": [1, 2.5, None, "x"], "flag": True}


# ── AC-16-23: the docNo filter ───────────────────────────────────────────────


def test_ac_16_23_doc_no_filter_is_trimmed_and_case_insensitive_and_drops_silently(
    client, db, monkeypatch,
):
    day = day_ago(1)
    hit_exact = do_rec(1, "DO-2609/0201", "2026-09-28T00:00:00", "2026-09-28T10:00:00.000")
    hit_padded = do_rec(2, " do-2609/0201 ", "2026-09-28T00:00:00", "2026-09-28T10:00:00.000")
    miss = do_rec(3, "DO-2609/0202", "2026-09-28T00:00:00", "2026-09-28T10:00:00.000")
    no_docno = do_rec(4, None, "2026-09-28T00:00:00", "2026-09-28T10:00:00.000")
    env = build_env(
        db, monkeypatch,
        day_fn=lambda d: [miss, hit_padded, no_docno, hit_exact] if d == day else [],
    )

    snapshot_id = _build(client, env, fromDay=iso(day), docNo="do-2609/0201")

    snap = stored_snapshot(db, snapshot_id)
    assert snap.status == "ready"
    assert [p["DocKey"] for p in _payloads(db, snapshot_id)] == [1, 2]
    assert snap.record_count == 2
    assert snap.metadata_json["fetchedCount"] == 4
    assert snap.metadata_json["excludedCount"] == 0
    assert snap.metadata_json["excludedRows"] == [], "non-matching records are dropped, never excluded"
    assert snap.metadata_json["docNo"] == "do-2609/0201" or snap.metadata_json["docNo"] == "DO-2609/0201"


def test_ac_16_23_a_doc_no_that_matches_nothing_is_a_ready_zero_row_snapshot(client, db, monkeypatch):
    day = day_ago(1)
    env = build_env(db, monkeypatch, day_fn=lambda d: fixture_records() if d == day else [])

    snapshot_id = _build(client, env, fromDay=iso(day), docNo="NO-SUCH-DO")

    snap = stored_snapshot(db, snapshot_id)
    assert snap.status == "ready"
    assert snap.record_count == 0
    assert snap.error_code is None
    assert stored_rows(db, snapshot_id) == []
    assert snap.metadata_json["fetchedCount"] == 2


def test_ac_16_23_doc_no_alone_reads_the_31_day_default_range(client, db, monkeypatch):
    target = do_rec(9, "DO-2609/0201", "2026-09-28T00:00:00", "2026-09-28T10:00:00.000")
    env = build_env(db, monkeypatch, day_fn=lambda d: [target] if d == day_ago(10) else [])

    snapshot_id = _build(client, env, docNo="DO-2609/0201")

    assert sorted(env.stub.days) == [day_ago(n) for n in range(30, -1, -1)]
    assert [p["DocKey"] for p in _payloads(db, snapshot_id)] == [9]
    assert stored_snapshot(db, snapshot_id).metadata_json["daysRead"] == 31


# ── AC-16-24: excluded rows ──────────────────────────────────────────────────


def test_ac_16_24_a_record_without_an_integer_dockey_is_an_excluded_row_never_stored(
    client, db, monkeypatch,
):
    day = day_ago(1)
    good = do_rec(55120, "DO-OK", "2026-09-28T00:00:00", "2026-09-28T10:00:00.000")
    no_key = {"DocNo": "DO-2609/0199", "Details": []}
    text_key = {"DocKey": "abc", "Details": []}
    bool_key = {"DocKey": True, "DocNo": "DO-BOOL", "Details": []}
    env = build_env(
        db, monkeypatch, day_fn=lambda d: [no_key, good, text_key, bool_key] if d == day else [],
    )

    snapshot_id = _build(client, env, fromDay=iso(day))

    snap = stored_snapshot(db, snapshot_id)
    assert snap.status == "ready"
    assert [p["DocKey"] for p in _payloads(db, snapshot_id)] == [55120]
    assert snap.record_count == 1
    assert snap.metadata_json["excludedCount"] == 3
    assert snap.metadata_json["excludedRows"] == [
        {"source_ref": None, "code": "DO-2609/0199", "reason": "missing_doc_key", "message": MISSING_KEY_MESSAGE},
        {"source_ref": None, "code": None, "reason": "missing_doc_key", "message": MISSING_KEY_MESSAGE},
        {"source_ref": None, "code": "DO-BOOL", "reason": "missing_doc_key", "message": MISSING_KEY_MESSAGE},
    ]


# ── AC-16-25 / 26: metadata, complete, hash, timestamps ─────────────────────


def test_ac_16_25_metadata_carries_the_scope_book_and_counts(client, db, monkeypatch):
    day = day_ago(1)
    recs = fixture_records()  # 2 + 1 Details
    env = build_env(db, monkeypatch, day_fn=lambda d: recs + [{"DocNo": "X"}] if d == day else [])

    snapshot_id = _build(client, env, fromDay=iso(day_ago(2)), toDay=iso(day))

    metadata = stored_snapshot(db, snapshot_id).metadata_json
    assert metadata["fromDay"] == iso(day_ago(2))
    assert metadata["toDay"] == iso(day)
    assert metadata["docNo"] is None
    assert metadata["book"] == "db1"
    assert metadata["daysRead"] == 2
    assert metadata["fetchedCount"] == 3
    assert metadata["lineCount"] == 3
    assert metadata["excludedCount"] == 1
    assert len(metadata["excludedRows"]) == 1
    assert "sourcePageSize" in metadata and metadata["sourcePageSize"] is None


def test_ac_16_26_complete_true_hash_over_stored_payloads_and_a_24h_ttl(client, db, monkeypatch):
    from modules.autocount.services.pull_service import compute_content_hash

    day = day_ago(1)
    recs = fixture_records()
    env = build_env(db, monkeypatch, day_fn=lambda d: list(reversed(recs)) if d == day else [])
    before = datetime.now(timezone.utc)

    snapshot_id = _build(client, env, fromDay=iso(day))

    after = datetime.now(timezone.utc)
    snap = stored_snapshot(db, snapshot_id)
    assert snap.status == "ready"
    assert snap.complete is True
    assert snap.content_hash == compute_content_hash(_payloads(db, snapshot_id))
    assert snap.content_hash == compute_content_hash(recs), "hash follows row_index order (DocDate asc)"
    assert before - timedelta(seconds=1) <= snap.extracted_at <= after + timedelta(seconds=1)
    assert snap.expires_at - snap.extracted_at == timedelta(hours=24)
    header = get_header(client, env.key, snapshot_id).json()
    assert header["complete"] is True
    assert header["contentHash"] == snap.content_hash


# ── AC-16-27: zero rows are a normal ready snapshot ──────────────────────────


@pytest.mark.parametrize("via_doc_no", [False, True], ids=["empty-range", "doc-no-miss"])
def test_ac_16_27_a_zero_row_result_is_ready_even_after_a_previous_ready_snapshot_with_rows(
    client, db, monkeypatch, via_doc_no,
):
    from modules.autocount.services.pull_service import SnapshotService

    day = day_ago(1)
    env = build_env(
        db, monkeypatch,
        day_fn=lambda d: fixture_records() if (via_doc_no and d == day) else [],
    )
    service = SnapshotService(db)
    now = datetime.now(timezone.utc)
    earlier = service.create_building(
        DEFAULT_TENANT_ID, env.company.id, ENTITY_DO, company_code="SRT", requested_via="gateway",
    )
    service.stamp_ready(
        DEFAULT_TENANT_ID, earlier, record_count=5, complete=True, content_hash="b" * 64,
        metadata={"excludedCount": 0, "excludedRows": []},
        extracted_at=now - timedelta(hours=2), expires_at=now + timedelta(hours=22),
    )
    scope: Dict[str, Any] = {"fromDay": iso(day)}
    if via_doc_no:
        scope["docNo"] = "NO-SUCH-DO"

    snapshot_id = _build(client, env, **scope)

    snap = stored_snapshot(db, snapshot_id)
    assert snap.id != earlier.id
    assert snap.status == "ready", snap.error
    assert snap.error_code is None
    assert snap.record_count == 0
    assert snap.complete is True
    assert stored_rows(db, snapshot_id) == []


# ── AC-16-28: any vendor day failing fails the whole build ──────────────────

_FAILURES = {
    "http-500-after-retries": lambda: JsonRoute({"message": "down"}, status_code=500),
    "http-404": lambda: JsonRoute({"message": "gone"}, status_code=404),
    "not-json": lambda: httpx.Response(200, text="<html>not json</html>"),
    "wrong-shape": lambda: httpx.Response(200, json="oops"),
    "paged-envelope": lambda: load_fixture("do-vendor-day-paged-envelope.json"),
    "transport-error": lambda: httpx.ConnectError("boom"),
}


@pytest.mark.parametrize("failure", sorted(_FAILURES))
def test_ac_16_28_a_failing_middle_day_fails_the_whole_build_and_leaves_the_feed_untouched(
    client, db, monkeypatch, failure,
):
    d1, d2, d3 = day_ago(3), day_ago(2), day_ago(1)
    recs = fixture_records()

    def day_fn(day: date):
        if day == d2:
            return _FAILURES[failure]()
        return recs

    env = build_env(
        db, monkeypatch, day_fn=day_fn,
        feed_columns={
            "cursor_day": date(2026, 9, 1), "last_error": "an older error",
            "last_error_code": "OLD_CODE",
            "last_poll_at": datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
            "last_poll_ok_at": datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
        },
    )
    db.refresh(env.feed)
    feed_before = (
        env.feed.cursor_day, env.feed.last_poll_at, env.feed.last_poll_ok_at,
        env.feed.last_error, env.feed.last_error_code, env.feed.mode, env.feed.next_poll_at,
    )

    snapshot_id = _build(client, env, fromDay=iso(d1), toDay=iso(d3))

    snap = stored_snapshot(db, snapshot_id)
    assert snap.status == "failed"
    assert snap.error_code == "SOURCE_PAGE_FAILED"
    assert stored_rows(db, snapshot_id) == [], "nothing partial is ever stored"
    job = db.get(BackgroundJob, snap.job_id)
    assert job.status == "failed"
    feed = db.get(AcDocFeed, env.feed.id)
    db.refresh(feed)
    assert (
        feed.cursor_day, feed.last_poll_at, feed.last_poll_ok_at, feed.last_error,
        feed.last_error_code, feed.mode, feed.next_poll_at,
    ) == feed_before
    header = get_header(client, env.key, snapshot_id).json()
    assert header["status"] == "failed"
    assert header["error"]["code"] == "SOURCE_PAGE_FAILED"


# ── AC-16-29: the 10,000 document cap ────────────────────────────────────────


def test_ac_16_29_over_10000_documents_fails_row_limit_with_no_rows(client, db, monkeypatch):
    day = day_ago(1)
    many = [tiny_rec(i) for i in range(1, 10_002)]
    env = build_env(db, monkeypatch, day_fn=lambda d: many if d == day else [])

    snapshot_id = _build(client, env, fromDay=iso(day))

    snap = stored_snapshot(db, snapshot_id)
    assert snap.status == "failed"
    assert snap.error_code == "ROW_LIMIT"
    assert stored_rows(db, snapshot_id) == []
    assert db.get(BackgroundJob, snap.job_id).status == "failed"


def test_ac_16_29_control_exactly_10000_documents_is_still_ready(client, db, monkeypatch):
    day = day_ago(1)
    many = [tiny_rec(i) for i in range(1, 10_001)]
    env = build_env(db, monkeypatch, day_fn=lambda d: many if d == day else [])

    snapshot_id = _build(client, env, fromDay=iso(day))

    snap = stored_snapshot(db, snapshot_id)
    assert snap.status == "ready", snap.error
    assert snap.record_count == 10_000
    assert db.query(AcPullSnapshotRow).filter(AcPullSnapshotRow.snapshot_id == snapshot_id).count() == 10_000


# ── AC-16-30: progress ───────────────────────────────────────────────────────


def test_ac_16_30_beats_progress_per_day_read_and_every_200_stored_rows(client, db, monkeypatch):
    day = day_ago(1)
    rows = [tiny_rec(i) for i in range(1, 251)]
    env = build_env(db, monkeypatch, day_fn=lambda d: rows if d == day else [])
    calls = _spy_beat_progress(monkeypatch)

    snapshot_id = _build(client, env, fromDay=iso(day_ago(2)), toDay=iso(day))

    assert stored_snapshot(db, snapshot_id).status == "ready"
    source = [(done, total) for stage, done, total in calls if stage == "source"]
    for days_read in (1, 2):
        assert (days_read, 2) in source, calls
    assert all(total == 2 for _done, total in source)
    assert ("storing", 200, 250) in calls, calls


# ── AC-16-31: abandonment ────────────────────────────────────────────────────


def _flip_to_abandoned(db, company_id: str) -> None:
    snap = (
        db.query(AcPullSnapshot)
        .filter(
            AcPullSnapshot.tenant_id == DEFAULT_TENANT_ID,
            AcPullSnapshot.company_id == company_id,
            AcPullSnapshot.entity_type == ENTITY_DO,
            AcPullSnapshot.status == "building",
        )
        .one()
    )
    snap.status = "failed"
    snap.error = "The worker stopped before this build finished."
    snap.error_code = "BUILD_ABANDONED"
    db.commit()


def _request_scoped_build(db, company_id: str, from_day: date, to_day: date) -> AcPullSnapshot:
    from modules.autocount.services.pull_service import PullService

    return PullService(db).request_build(
        DEFAULT_TENANT_ID, company_id, ENTITY_DO, requested_via="gateway",
        scope={"fromDay": iso(from_day), "toDay": iso(to_day), "docNo": None},
    )


def test_ac_16_31_abandoned_mid_range_stops_reading_and_never_restamps(db, monkeypatch):
    env = build_env(db, monkeypatch, day_fn=lambda _d: [])
    _spy_beat_progress(
        monkeypatch,
        on_call=lambda n, *_a: _flip_to_abandoned(db, env.company.id) if n == 1 else None,
    )

    snapshot = _request_scoped_build(db, env.company.id, day_ago(3), day_ago(1))

    db.expire_all()
    snap = db.get(AcPullSnapshot, snapshot.id)
    assert snap.status == "failed"
    assert snap.error_code == "BUILD_ABANDONED"
    assert snap.error == "The worker stopped before this build finished.", "never re-stamped"
    assert len(env.stub.requests) < 3, "the remaining days must not be read once abandoned"
    assert stored_rows(db, snap.id) == []
    job = db.get(BackgroundJob, snap.job_id)
    assert job.status == "failed"
    run = db.query(AcSyncRun).filter(AcSyncRun.job_id == job.id).one()
    assert run.outcome == RUN_FAILED


def test_ac_16_31_abandoned_while_storing_inserts_no_further_rows(db, monkeypatch):
    day = day_ago(1)
    rows = [tiny_rec(i) for i in range(1, 251)]
    env = build_env(db, monkeypatch, day_fn=lambda d: rows if d == day else [])
    _spy_beat_progress(
        monkeypatch,
        on_call=lambda n, stage, *_a: _flip_to_abandoned(db, env.company.id) if stage == "storing" else None,
    )

    snapshot = _request_scoped_build(db, env.company.id, day, day)

    db.expire_all()
    snap = db.get(AcPullSnapshot, snapshot.id)
    assert snap.status == "failed"
    assert snap.error_code == "BUILD_ABANDONED"
    stored = db.query(AcPullSnapshotRow).filter(AcPullSnapshotRow.snapshot_id == snap.id).count()
    assert stored <= 200, "no row may be inserted after the abandonment was noticed"
    assert db.get(BackgroundJob, snap.job_id).status == "failed"


def test_ac_16_31_the_orphan_hook_stamps_build_abandoned_on_a_do_snapshot(client, db, monkeypatch):
    from modules.autocount.bootstrap import on_job_orphaned

    env = build_env(db, monkeypatch)
    defer_jobs(monkeypatch)
    snapshot_id = _build(client, env, fromDay=iso(day_ago(1)))
    snap = stored_snapshot(db, snapshot_id)
    assert snap.status == "building"
    job = db.get(BackgroundJob, snap.job_id)

    on_job_orphaned(db, job)
    db.commit()

    after = stored_snapshot(db, snapshot_id)
    assert after.status == "failed"
    assert after.error_code == "BUILD_ABANDONED"


# ── AC-16-32: no feed side effects ───────────────────────────────────────────

_FEED_SIDE_EFFECT_TABLES = (
    AcDocFeedLedger, AcDocFeedIssue, AcDocFeedRun, AcDocFeedBackfill, AcStagedRecord,
    AcRowHash, AcWatermark, AcDocFingerprint,
)


def _counts(db) -> Dict[str, int]:
    db.expire_all()
    return {model.__tablename__: db.query(model).count() for model in _FEED_SIDE_EFFECT_TABLES}


def test_ac_16_32_a_build_writes_no_feed_ledger_issue_run_staged_hash_or_watermark_rows(
    client, db, monkeypatch,
):
    day = day_ago(1)
    env = build_env(
        db, monkeypatch, day_fn=lambda d: fixture_records() if d == day else [],
        feed_columns={"cursor_day": date(2026, 9, 1), "last_error": None},
    )
    db.refresh(env.feed)
    feed_before = (env.feed.cursor_day, env.feed.last_poll_at, env.feed.last_poll_ok_at)
    before = _counts(db)

    snapshot_id = _build(client, env, fromDay=iso(day))

    assert stored_snapshot(db, snapshot_id).status == "ready"
    assert _counts(db) == before
    feed = db.get(AcDocFeed, env.feed.id)
    db.refresh(feed)
    assert (feed.cursor_day, feed.last_poll_at, feed.last_poll_ok_at) == feed_before


def test_ac_16_32_exactly_one_snapshot_mode_sync_run_row_is_written(client, db, monkeypatch):
    day = day_ago(1)
    env = build_env(db, monkeypatch, day_fn=lambda d: fixture_records() if d == day else [])

    snapshot_id = _build(client, env, fromDay=iso(day))

    snap = stored_snapshot(db, snapshot_id)
    runs = db.query(AcSyncRun).filter(AcSyncRun.company_id == env.company.id).all()
    assert len(runs) == 1
    run = runs[0]
    assert run.mode == "snapshot"
    assert run.entity_type == ENTITY_DO
    assert run.job_id == snap.job_id
    assert run.outcome == RUN_SUCCESS
    assert run.added_count == 2


# ── AC-16-33: activity ───────────────────────────────────────────────────────


def test_ac_16_33_each_vendor_call_is_recorded_in_integration_activity_without_record_bodies(
    client, db, monkeypatch,
):
    day = day_ago(1)
    env = build_env(db, monkeypatch, day_fn=lambda d: fixture_records() if d == day else [])

    _build(client, env, fromDay=iso(day_ago(2)), toDay=iso(day))

    db.expire_all()
    rows = (
        db.query(IntegrationActivity)
        .filter(
            IntegrationActivity.tenant_id == DEFAULT_TENANT_ID,
            IntegrationActivity.operation.like("GET /deliveryorderbydocdate%"),
        )
        .all()
    )
    assert len(rows) == 2
    assert {r.status_code for r in rows} == {200}
    blob = json.dumps(
        [[r.operation, r.error_message, r.request_summary_json, r.response_summary_json] for r in rows],
        default=str,
    )
    for secret in ("Anon Trading Sdn Bhd", "Beta Hardware Sdn Bhd", "0123456789", "DO-2609/0201"):
        assert secret not in blob, f"{secret!r} (a record body value) leaked into integration_activity"
