"""Sprint-5/11 S6 - AC-11-10 (politeness back-off, owner ruling R2) and
AC-11-11 (the effective concurrency of a run is recorded).

RED before the coder for the SAME reason as ``test_s11_s6_concurrent_walk.py``
(shares its ``_require_concurrency_wiring`` autouse fixture, imported below).

ASSUMED NAME for AC-11-11 (undecided by the plan; pinned here per the tester
brief): ``HttpApiSource.source_concurrency`` - a public attribute mirroring
the EXISTING ``source_page_size`` (promoted by ``_walk`` immediately after
the main walk, before any lookup runs), carrying the concurrency level the
MAIN walk actually used - the configured N when it legitimately went
concurrent, or ``1`` for every AC-11-02 fallback. ``sync.py`` reads it onto
``metadata_json["sourceConcurrency"]`` exactly as it already reads
``source.source_page_size`` onto ``metadata_json["sourcePageSize"]``.

The exact WORDING of the two new activity notes (AC-11-10's back-off note,
AC-11-11's concurrency-summary note) is not pinned by the plan either - the
assertions below check for the load-bearing FACTS the note must carry (the N
value, a page count, a numeric wall-time-shaped figure, the word "serial"
for a fallback run) rather than an exact sentence, mirroring how existing
notes are asserted elsewhere (e.g. ``"1 duplicate key" in notes[0]...``).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import ETL_STATUS_ACTIVE, AcEntityConfig, AcFieldMapping
from modules.autocount.sources import Watermark

from modules.autocount.http_source.source import HttpApiSource
from modules.autocount.http_source.errors import HttpSourceError

from tests.test_s11_s6_concurrent_walk import (  # noqa: F401 - _require_concurrency_wiring is autouse, collected by import
    _company,
    _config,
    _ctx,
    _envelope,
    _item,
    _open_connection,
    _require_concurrency_wiring,
    _transport,
    db,
)

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
MAIN_PATH = "/itembypage"


def _source(db, *, max_concurrent_pages: str, handler) -> HttpApiSource:
    conn = _open_connection(db, max_concurrent_pages=max_concurrent_pages)
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id, path=MAIN_PATH)
    return HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )


# ══════════════════════════════════════════════════════════════════════════
# AC-11-10 - politeness back-off: a 429 at N>1 aborts the parallel attempt,
# records ONE CallRecord note, sleeps the clamped Retry-After, and restarts
# ONCE serially. A second 429 fails like any other 4xx. At N=1, byte-
# identical to today (immediate failure, no retry, no wait).
# ══════════════════════════════════════════════════════════════════════════


def _sleep_spy(monkeypatch) -> List[float]:
    """Overrides (within THIS test) the conftest-wide no-op ``time.sleep``
    patch for ``test_s11_*`` files with a RECORDING spy - so the clamped
    back-off value itself is observable, not just silently swallowed."""
    calls: List[float] = []

    def spy(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr("time.sleep", spy)
    return calls


def test_429_at_n4_aborts_batch_records_one_note_sleeps_retry_after_and_restarts_serially(
    db, monkeypatch
):
    sleeps = _sleep_spy(monkeypatch)
    TOTAL_PAGES = 5
    attempts_page3 = {"n": 0}
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        page = int(request.url.params.get("page", "1"))
        if page == 3:
            attempts_page3["n"] += 1
            if attempts_page3["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "2"}, json={})
        return httpx.Response(
            200, json=_envelope([_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES)
        )

    source = _source(db, max_concurrent_pages="4", handler=handler)
    result = source.fetch_changes(Watermark())

    assert len(result.records) == TOTAL_PAGES, "the SERIAL restart must still complete the walk"
    assert 2 in sleeps, f"expected a sleep(2) for the clamped Retry-After, got {sleeps}"
    # sprint-5/11 S6 review round 1 (SF-1) - the walk actually finished
    # SERIALLY from the 429 onward; `source_concurrency` must read 1, never
    # the configured N=4 this run never got to use for a single full batch.
    assert source.source_concurrency == 1, (
        f"expected source_concurrency == 1 after a page-3 429 forced a serial "
        f"restart, got {source.source_concurrency!r}"
    )

    activity = source.drain_activity()
    notes = [r for r in activity if r.method == "NOTE"]
    back_off_notes = [n for n in notes if "429" in (n.response or {}).get("message", "")]
    assert len(back_off_notes) == 1, (
        f"expected exactly ONE back-off CallRecord note, got {len(back_off_notes)}: {notes}"
    )
    # The restart re-walks from page 1: SOME request for page 1 must be made
    # again AFTER the 429 was first observed (never resumed mid-batch).
    page_1_requests = [c for c in calls if c.url.params.get("page") == "1"]
    assert len(page_1_requests) >= 2, (
        f"expected page 1 to be re-fetched on the serial restart, got "
        f"{len(page_1_requests)} page-1 request(s) total"
    )


@pytest.mark.parametrize(
    "retry_after, expected_sleep",
    [(None, 5), ("120", 30), ("0", 1), ("-5", 1)],
)
def test_429_retry_after_is_clamped_1_to_30_default_5(db, monkeypatch, retry_after, expected_sleep):
    sleeps = _sleep_spy(monkeypatch)
    TOTAL_PAGES = 3
    hit = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        if page == 2 and hit["n"] == 0:
            hit["n"] += 1
            headers = {"Retry-After": retry_after} if retry_after is not None else {}
            return httpx.Response(429, headers=headers, json={})
        return httpx.Response(
            200, json=_envelope([_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES)
        )

    source = _source(db, max_concurrent_pages="4", handler=handler)
    source.fetch_changes(Watermark())
    assert expected_sleep in sleeps, (
        f"expected a sleep({expected_sleep}) for Retry-After={retry_after!r}, got {sleeps}"
    )


def test_second_429_after_serial_restart_fails_like_an_ordinary_4xx(db, monkeypatch):
    _sleep_spy(monkeypatch)
    TOTAL_PAGES = 5

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        if page == 3:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx.Response(
            200, json=_envelope([_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES)
        )

    source = _source(db, max_concurrent_pages="4", handler=handler)
    with pytest.raises(HttpSourceError) as exc:
        source.fetch_changes(Watermark())
    assert exc.value.code == "http_status", (
        "a SECOND 429 (page 3 fails on the serial restart too) must fail exactly "
        "like any other 4xx - never a second back-off/retry"
    )


def test_429_at_n1_is_byte_identical_to_today_no_sleep_no_retry(db, monkeypatch):
    """CONTROL (mirrors the house pattern of a byte-identical-to-today pin,
    e.g. ``test_s10_s5a_source_reduce_hook.py``): at N=1 a 429 is just
    another 4xx - immediate failure, zero sleep calls, one request."""
    sleeps = _sleep_spy(monkeypatch)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, json={})

    source = _source(db, max_concurrent_pages="1", handler=handler)
    with pytest.raises(HttpSourceError) as exc:
        source.fetch_changes(Watermark())
    assert exc.value.code == "http_status"
    assert len(calls) == 1, "a 429 at N=1 must fail immediately, never retried"
    assert sleeps == [], f"a 429 at N=1 must never sleep, got {sleeps}"


# ══════════════════════════════════════════════════════════════════════════
# AC-11-11 - the effective concurrency of a run is recorded.
# ══════════════════════════════════════════════════════════════════════════


def _assert_has_source_concurrency(source: HttpApiSource) -> int:
    if not hasattr(source, "source_concurrency"):
        pytest.fail(
            "HttpApiSource has no 'source_concurrency' attribute yet (sprint-5/11 "
            "S6, AC-11-11) - ASSUMED NAME mirroring the existing source_page_size; "
            "see this file's module docstring."
        )
    return source.source_concurrency


def test_source_concurrency_is_the_effective_n_on_a_genuine_concurrent_walk(db):
    TOTAL_PAGES = 5  # page 1 + a single full N=4 batch (pages 2..5)

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(
            200, json=_envelope([_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES)
        )

    source = _source(db, max_concurrent_pages="4", handler=handler)
    source.fetch_changes(Watermark())
    assert _assert_has_source_concurrency(source) == 4


@pytest.mark.parametrize(
    "total_pages_header, echo_page",
    [(None, True), (1, True)],
)
def test_source_concurrency_is_one_for_every_fallback_condition(db, total_pages_header, echo_page):
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        body = _envelope(
            [_item(f"P{page}")], page=page, total_pages=total_pages_header, echo_page=echo_page,
        )
        if total_pages_header is None and page > 3:
            body = _envelope([], page=page, total_pages=None, echo_page=echo_page)
        return httpx.Response(200, json=body)

    source = _source(db, max_concurrent_pages="4", handler=handler)
    source.fetch_changes(Watermark())
    assert _assert_has_source_concurrency(source) == 1, (
        "a fallback (no TotalPages / TotalPages==1) walk must record concurrency 1, "
        "never the connection's configured (but never legally used) N"
    )


def test_source_concurrency_is_one_for_a_bare_array_endpoint(db):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"Location": "A1"}])

    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(
        db, company, connection_id=conn.id, path="/location",
        key_fields=("Location",), watermark_field=None,
    )
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    source.fetch_changes(Watermark())
    assert _assert_has_source_concurrency(source) == 1


def test_activity_note_on_concurrent_run_names_n_and_page_count(db):
    TOTAL_PAGES = 5

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(
            200, json=_envelope([_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES)
        )

    source = _source(db, max_concurrent_pages="4", handler=handler)
    source.fetch_changes(Watermark())
    activity = source.drain_activity()
    notes = [r for r in activity if r.method == "NOTE"]
    concurrency_notes = [
        n for n in notes
        if "4" in (n.response or {}).get("message", "")
        and str(TOTAL_PAGES) in (n.response or {}).get("message", "")
    ]
    assert concurrency_notes, (
        f"expected an activity note naming the concurrency (4) and the page "
        f"count ({TOTAL_PAGES}), got notes: {notes}"
    )
    message = concurrency_notes[0].response["message"]
    assert re.search(r"\d", message), f"expected a wall-time figure in the note: {message!r}"


def test_activity_note_on_serial_fallback_names_the_reason(db):
    """A run that CONFIGURED N=4 but fell back to serial (TotalPages==1, an
    AC-11-02 condition) records 1 and names the reason - never silent."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_envelope([_item("A1"), _item("A2")], page=1, total_pages=1, page_size=2)
        )

    source = _source(db, max_concurrent_pages="4", handler=handler)
    source.fetch_changes(Watermark())
    activity = source.drain_activity()
    notes = [r for r in activity if r.method == "NOTE"]
    fallback_notes = [
        n for n in notes if "serial" in (n.response or {}).get("message", "").lower()
    ]
    assert fallback_notes, (
        f"expected an activity note naming the serial fallback and its reason, "
        f"got notes: {notes}"
    )
    assert "1" in fallback_notes[0].response["message"]


# ══════════════════════════════════════════════════════════════════════════
# End to end: metadata_json.sourceConcurrency on the pull snapshot.
# ══════════════════════════════════════════════════════════════════════════


def _product_pull_task(db, company, connection_id) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE, delivery_mode="pull",
        source_config={
            "connectionId": connection_id, "path": MAIN_PATH,
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [],
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


def test_pull_snapshot_metadata_records_source_concurrency_4(db, monkeypatch):
    from modules.autocount.services.pull_service import PullService

    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    _product_pull_task(db, company, conn.id)
    TOTAL_PAGES = 5

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(
            200, json=_envelope([_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES)
        )

    _patch_transport(monkeypatch, _transport(handler))
    snapshot = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )
    db.refresh(snapshot)
    assert snapshot.status == "ready", getattr(snapshot, "error", None)
    metadata = snapshot.metadata_json or {}
    assert metadata.get("sourceConcurrency") == 4, (
        f"expected metadata_json.sourceConcurrency == 4, got {metadata.get('sourceConcurrency')!r} "
        f"(full metadata: {metadata!r})"
    )


def test_pull_snapshot_metadata_records_source_concurrency_1_for_serial_fallback(db, monkeypatch):
    from modules.autocount.services.pull_service import PullService

    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    _product_pull_task(db, company, conn.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_envelope([_item("A1"), _item("A2")], page=1, total_pages=1, page_size=2)
        )

    _patch_transport(monkeypatch, _transport(handler))
    snapshot = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )
    db.refresh(snapshot)
    assert snapshot.status == "ready", getattr(snapshot, "error", None)
    metadata = snapshot.metadata_json or {}
    assert metadata.get("sourceConcurrency") == 1, (
        f"a serial-fallback build (TotalPages==1) must record sourceConcurrency=1, "
        f"even though the connection is configured for 4; got "
        f"{metadata.get('sourceConcurrency')!r}"
    )
