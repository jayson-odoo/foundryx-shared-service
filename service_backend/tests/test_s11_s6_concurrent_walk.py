"""Sprint-5/11 S6 - AC-11-02/03/04/06/07/08/09: the bounded-concurrency page
fetch itself (plan section 2.1, D1/D2, files list
``http_source/source.py``/``http_source/client.py``).

RED before the coder, verified at HEAD b4fef31b (S5 merged, S6 not started):
``connection_sizing`` (``http_source/client.py``) still returns a bare
``(page_size, timeout_seconds)`` tuple with no ``max_concurrent_pages`` at
all, and ``HttpApiSource._walk_path``/``_walk_endpoint`` (``http_source/
source.py``) make ONE request at a time, always - there is no
``ThreadPoolExecutor``, no in-flight counter, and no echoed-page
verification distinct from the existing SF-5 guard. Every test in this file
therefore starts with ``_require_concurrency_wiring`` (below), which fails
EXPLICITLY the moment ``connection_sizing(...)`` does not yet read
``maxConcurrentPages`` off the connection config - the correct RED reason
for a file whose FIVE fallback-condition tests (AC-11-02) would otherwise
trivially "pass" today for the wrong reason (a fully serial walk already
satisfies "the walk is serial" by definition, with no feature built at
all). This mirrors the established house pattern of guarding on a symbol/
behaviour rather than a raw ``ImportError``
(``test_s11_s5_progress_stages.py``'s own ``stage_spy`` fixture, and
``test_s10_s5a_source_reduce_hook.py``'s documented "the CONTROL test
already passes today... kept as a regression trip-wire, not a red test").

ASSUMED NAMES the coder must conform to (undecided by the plan; pinned here
per the tester brief so the contract is testable at all - flagged in the
final report as ambiguities the coder should confirm rather than silently
reshape):

* ``modules.autocount.http_source.client.connection_sizing(config)`` returns
  a ``ConnectionSizing`` object (not a tuple) carrying ``.page_size``,
  ``.request_timeout_seconds``, ``.max_concurrent_pages`` (int, default 1
  when the connection carries no value) - pinned directly by AC-11-01 and
  exercised here only as the wiring smoke-check every test starts with.
* ``HttpApiSource`` gains a public attribute ``source_concurrency``
  (mirroring the EXISTING ``source_page_size`` promoted by ``_walk`` after
  the main walk), set to the CONCURRENCY level the main walk actually used
  (the effective N when it went concurrent, or ``1`` for every AC-11-02
  fallback / a genuinely single-connection-configured walk) - read by
  ``sync.py`` onto the pull snapshot's ``metadata_json.sourceConcurrency``
  (pinned in ``test_s11_s6_backoff_and_metadata.py``, not here).
* The per-page worker body a ``ThreadPoolExecutor`` submits for the
  concurrent path is ``HttpApiSource._fetch_page_concurrent`` (a bound
  method) - the ONE new callable AC-11-09's static "never touches the
  database" check can point ``inspect.getsource`` at. If the coder's actual
  concurrent-fetch worker lives under a different name, this specific test
  (``test_concurrent_worker_never_touches_the_database``) needs retargeting,
  never silent deletion.

Thread-safety rules embedded in every fixture below (per the tester brief):
never a real wall-clock sleep over 50ms to force ordering - a
``threading.Barrier(n, timeout=0.5)`` proves genuine simultaneous in-flight
requests deterministically (all N arrive together or the wait times out and
callers proceed unblocked, never hangs the suite), and a deliberate
EXPLICIT reverse completion order (never real randomness - determinism over
"true" shuffling) proves assembly is never by completion order.
"""
from __future__ import annotations

import inspect
import threading
from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark

from modules.autocount.http_source.source import HttpApiSource
from modules.autocount.http_source.errors import HttpSourceError

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"


# ── wiring guard (the file's own RED reason) ─────────────────────────────────


@pytest.fixture(autouse=True)
def _require_concurrency_wiring():
    """Fails EXPLICITLY, before any stub HTTP request is even built, until
    ``connection_sizing`` reads a connection's own ``maxConcurrentPages``
    (AC-11-01). This is the file's shared RED reason - see the module
    docstring."""
    from modules.autocount.http_source.client import connection_sizing

    sizing = connection_sizing({"maxConcurrentPages": "4"})
    if not hasattr(sizing, "max_concurrent_pages"):
        pytest.fail(
            f"connection_sizing(...) returned {sizing!r} - AC-11-01 requires a "
            "ConnectionSizing object (not a bare tuple) carrying "
            ".max_concurrent_pages. The bounded-concurrency walk (S6) cannot "
            "be pinned until this exists."
        )
    if sizing.max_concurrent_pages != 4:
        pytest.fail(
            f"connection_sizing({{'maxConcurrentPages': '4'}}).max_concurrent_pages "
            f"== {sizing.max_concurrent_pages!r}, expected 4 - the connection's "
            "own maxConcurrentPages is not read yet."
        )


# ── fixtures shared with test_s11_s6_parity.py / _backoff_and_metadata.py ───


def _open_connection(
    db, *, max_concurrent_pages: Optional[str] = "4", page_size: Optional[str] = None,
    name: str = "s11-s6 REST",
) -> Connection:
    config: Dict[str, Any] = {"baseUrl": BASE_URL, "auth": "none"}
    if max_concurrent_pages is not None:
        config["maxConcurrentPages"] = max_concurrent_pages
    if page_size is not None:
        config["pageSize"] = page_size
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name=name,
        config_json=config, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str, *, database_name: str = DB_NAME) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=database_name,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _config(
    db, company, *, entity_type=ENTITY_PRODUCT, connection_id: str, path="/itembypage",
    key_fields=("ItemCode",), watermark_field: Optional[str] = "LastModified",
    lookups: Optional[List[Dict[str, Any]]] = None, combine: Optional[Dict[str, Any]] = None,
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl="autocount_http",
        source_config={
            "connectionId": connection_id, "path": path, "keyFields": list(key_fields),
            "watermarkField": watermark_field, "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": lookups or [], "combine": combine,
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _ctx(db, company, config) -> SourceContext:
    return SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _item(code: str, *, last_modified: str = "2026-08-01T09:00:00") -> Dict[str, Any]:
    return {"ItemCode": code, "Description": code, "LastModified": last_modified}


def _envelope(
    rows: List[Dict[str, Any]], *, page: int, total_pages: Optional[int],
    total_count: Optional[int] = None, page_size: int = 1, echo_page: bool = True,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"PageSize": page_size, "Data": rows}
    if echo_page:
        body["Page"] = page
    if total_pages is not None:
        body["TotalPages"] = total_pages
    body["TotalCount"] = total_count if total_count is not None else (total_pages or len(rows))
    return body


class ConcurrencyTracker:
    """Deterministic proof of real overlap (never a wall-clock race): pages
    entering a shared concurrent batch rendezvous on a reusable
    ``threading.Barrier(n)``. Since every test below always queues AT LEAST
    N pages in the batch under test, the first N arrivals are guaranteed to
    reach the barrier together, pinning ``max_in_flight == n`` on purpose. A
    trailing batch smaller than N times out on the barrier (bounded 0.5s,
    never a hang) and every waiter simply proceeds."""

    def __init__(self, n: int, *, barrier_timeout: float = 0.5):
        self.n = max(n, 1)
        self._barrier = (
            threading.Barrier(self.n, timeout=barrier_timeout) if self.n > 1 else None
        )
        self._lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0
        self.request_order: List[int] = []

    def enter(self, page: int) -> Optional[int]:
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self.request_order.append(page)
        idx = None
        if self._barrier is not None:
            try:
                idx = self._barrier.wait()
            except threading.BrokenBarrierError:
                idx = None
        return idx

    def exit(self, page: int) -> None:
        with self._lock:
            self.in_flight -= 1


class _Abandoned(Exception):
    """Local stand-in for ``sync.py``'s own ``_BuildAbandoned`` - the source
    does not know or care about the concrete exception type a heartbeat
    raises, it only propagates it (AC-11-09)."""


# ══════════════════════════════════════════════════════════════════════════
# AC-11-02 - five fallback conditions: concurrency is opt-in per walk, never
# assumed. Every test below asks for maxConcurrentPages=4 but the SERVER's
# own envelope (or, for condition 5, the connection's own N) blocks it - the
# walk must stay byte-for-byte the EXISTING serial loop: requests strictly
# 1, 2, 3, ... with never more than one in flight at a time.
# ══════════════════════════════════════════════════════════════════════════


def _serial_tracking_handler(calls: List[int], tracker: ConcurrencyTracker, build):
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        calls.append(page)
        tracker.enter(page)
        try:
            return build(page)
        finally:
            tracker.exit(page)

    return handler


def test_ac_11_02_bare_array_never_goes_concurrent(db):
    """Condition 1: a bare-array (list) envelope carries no page concept at
    all - ONE request, exactly as today, even with maxConcurrentPages=4."""
    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(
        db, company, connection_id=conn.id, path="/location",
        key_fields=("Location",), watermark_field=None,
    )
    calls: List[int] = []
    tracker = ConcurrencyTracker(1)

    def build(page: int) -> httpx.Response:
        return httpx.Response(200, json=[{"Location": "A1"}, {"Location": "A2"}])

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_serial_tracking_handler(calls, tracker, build)),
    )
    result = source.fetch_changes(Watermark())
    assert len(calls) == 1, f"a bare array must be ONE request, got {calls}"
    assert len(result.records) == 2
    assert tracker.max_in_flight == 1


def test_ac_11_02_absent_total_pages_never_goes_concurrent(db):
    """Condition 2: a paged envelope that never echoes ``TotalPages`` at
    all (not even null) never legalises concurrency - walked serially page
    by page until an empty page ends it."""
    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    calls: List[int] = []
    tracker = ConcurrencyTracker(1)
    LAST_PAGE = 4

    def build(page: int) -> httpx.Response:
        if page > LAST_PAGE:
            return httpx.Response(200, json=_envelope([], page=page, total_pages=None))
        return httpx.Response(
            200, json=_envelope([_item(f"P{page}")], page=page, total_pages=None)
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_serial_tracking_handler(calls, tracker, build)),
    )
    result = source.fetch_changes(Watermark())
    assert calls == list(range(1, LAST_PAGE + 2)), (
        f"expected a strictly serial 1..{LAST_PAGE + 1} walk, got {calls}"
    )
    assert len(result.records) == LAST_PAGE
    assert tracker.max_in_flight == 1


def test_ac_11_02_absent_echoed_page_never_goes_concurrent(db):
    """Condition 3: ``TotalPages`` is echoed (3) but ``Page`` itself is
    never echoed on any page - concurrency needs BOTH, so this stays
    serial even though a total is known."""
    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    calls: List[int] = []
    tracker = ConcurrencyTracker(1)
    TOTAL_PAGES = 3

    def build(page: int) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(
                [_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES, echo_page=False,
            ),
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_serial_tracking_handler(calls, tracker, build)),
    )
    result = source.fetch_changes(Watermark())
    assert calls == [1, 2, 3], f"expected a strictly serial 1,2,3 walk, got {calls}"
    assert len(result.records) == 3
    assert tracker.max_in_flight == 1


def test_ac_11_02_total_pages_of_one_never_goes_concurrent(db):
    """Condition 4: a single-page paged envelope (``TotalPages: 1``) is
    already done after page 1 - nothing to parallelise."""
    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    calls: List[int] = []
    tracker = ConcurrencyTracker(1)

    def build(page: int) -> httpx.Response:
        return httpx.Response(
            200, json=_envelope([_item("A1"), _item("A2")], page=1, total_pages=1, page_size=2)
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_serial_tracking_handler(calls, tracker, build)),
    )
    result = source.fetch_changes(Watermark())
    assert calls == [1]
    assert len(result.records) == 2
    assert tracker.max_in_flight == 1


def test_ac_11_02_max_concurrent_pages_of_one_never_goes_concurrent(db):
    """Condition 5: every server-side condition is satisfied (paged,
    TotalPages=4 echoed, Page echoed and ==1 on page 1) but the
    CONNECTION's own maxConcurrentPages is 1 - byte-identical to today."""
    conn = _open_connection(db, max_concurrent_pages="1")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    calls: List[int] = []
    tracker = ConcurrencyTracker(1)
    TOTAL_PAGES = 4

    def build(page: int) -> httpx.Response:
        return httpx.Response(
            200, json=_envelope([_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES)
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_serial_tracking_handler(calls, tracker, build)),
    )
    result = source.fetch_changes(Watermark())
    assert calls == [1, 2, 3, 4]
    assert len(result.records) == 4
    assert tracker.max_in_flight == 1, (
        "maxConcurrentPages=1 must never let more than one request be in "
        "flight at once"
    )


# ══════════════════════════════════════════════════════════════════════════
# AC-11-03 - at most N requests in flight, total requests == TotalPages,
# page 1 always fetched alone first.
# ══════════════════════════════════════════════════════════════════════════


def test_twelve_pages_at_n4_bounds_in_flight_and_issues_exactly_twelve_requests(db):
    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    N = 4
    TOTAL_PAGES = 12
    tracker = ConcurrencyTracker(N)
    page1_done = threading.Event()
    violations: List[int] = []
    calls: List[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        calls.append(page)
        if page == 1:
            response = httpx.Response(
                200, json=_envelope([_item("P1")], page=1, total_pages=TOTAL_PAGES)
            )
            page1_done.set()
            return response
        if not page1_done.is_set():
            violations.append(page)
        tracker.enter(page)
        try:
            return httpx.Response(
                200, json=_envelope([_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES)
            )
        finally:
            tracker.exit(page)

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    result = source.fetch_changes(Watermark())

    assert not violations, f"page(s) {violations} were requested before page 1 completed"
    assert len(calls) == TOTAL_PAGES, f"expected exactly {TOTAL_PAGES} requests, got {calls}"
    assert tracker.max_in_flight == N, (
        f"expected the in-flight count to reach exactly N={N}, got "
        f"{tracker.max_in_flight} (calls: {calls})"
    )
    assert tracker.max_in_flight <= N
    assert len(result.records) == TOTAL_PAGES


# ══════════════════════════════════════════════════════════════════════════
# AC-11-04 - order is by requested page, never by completion; intra-page
# order preserved; the row de-dup keeps FIRST occurrence by PAGE order
# regardless of which page's HTTP response actually lands first.
# ══════════════════════════════════════════════════════════════════════════


def test_shuffled_completion_order_assembles_ascending_by_requested_page(db):
    """7 pages, N=6 (a single full concurrent batch, pages 2..7 - no
    trailing partial batch to complicate the rendezvous). Page 3 and page 7
    both carry the key ``DUP`` (a duplicate spanning a page boundary); pages
    complete in the EXPLICIT reverse of request order (7, 6, 5, 4, 3, 2) -
    the strongest, fully deterministic proof that assembly is never by
    completion order. Page 4 carries two rows to also pin intra-page order."""
    conn = _open_connection(db, max_concurrent_pages="6")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    N = 6
    TOTAL_PAGES = 7
    tracker = ConcurrencyTracker(N)
    calls: List[int] = []

    release_order = [7, 6, 5, 4, 3, 2]
    events = {p: threading.Event() for p in release_order}

    def rows_for(page: int) -> List[Dict[str, Any]]:
        if page == 3:
            return [_item("DUP", last_modified="2026-08-03T00:00:00")]
        if page == 7:
            return [_item("DUP", last_modified="2026-08-07T00:00:00")]
        if page == 4:
            return [_item("P4-A"), _item("P4-B")]
        return [_item(f"P{page}")]

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        calls.append(page)
        body = _envelope(rows_for(page), page=page, total_pages=TOTAL_PAGES)
        if page == 1:
            return httpx.Response(200, json=body)
        idx = tracker.enter(page)
        if idx == 0:
            for p in release_order:
                events[p].set()
        released = events[page].wait(timeout=2.0)
        assert released, f"page {page}'s release event never fired"
        tracker.exit(page)
        return httpx.Response(200, json=body)

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    result = source.fetch_changes(Watermark())

    assert tracker.max_in_flight == N, (
        f"expected genuine {N}-way overlap while pages complete out of order, "
        f"got {tracker.max_in_flight}"
    )
    codes = [r.raw["ItemCode"] for r in result.records]
    # Ascending by PAGE: P1, then page2..page7 in that order, with page 3's
    # DUP kept (first occurrence by PAGE, not by completion - page 7's DUP
    # actually finished its HTTP response FIRST) and page 4's own two rows
    # in their own sub-order.
    assert codes == ["P1", "P2", "DUP", "P4-A", "P4-B", "P5", "P6"], codes
    dup_records = [r for r in result.records if r.raw["ItemCode"] == "DUP"]
    assert len(dup_records) == 1
    assert dup_records[0].raw["LastModified"] == "2026-08-03T00:00:00", (
        "the de-dup must keep PAGE 3's row (first occurrence by requested "
        "page order), never page 7's - even though page 7 completed first"
    )


# ══════════════════════════════════════════════════════════════════════════
# AC-11-06 - echoed-page verification REPLACES the non-advancing guard in
# the concurrent path: any page whose echoed Page is present and wrong
# fails the WHOLE walk with code "shape", naming the requested page, and no
# page beyond the in-flight set is ever requested.
# ══════════════════════════════════════════════════════════════════════════


def test_echoed_page_mismatch_in_concurrent_batch_fails_shape_bounded_calls(db):
    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    N = 4
    TOTAL_PAGES = 9  # strictly more than 1 + N, so a SECOND batch would be
    # required if the walk were allowed to continue past the failure.
    calls: List[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        calls.append(page)
        if page == 1:
            return httpx.Response(
                200, json=_envelope([_item("P1")], page=1, total_pages=TOTAL_PAGES)
            )
        # Every page beyond 1 echoes the WRONG Page (always "1") - a server
        # that ignores the page parameter while still answering per-page
        # data, distinct from the row-count-only page-drift case.
        body = _envelope([_item(f"P{page}")], page=1, total_pages=TOTAL_PAGES)
        return httpx.Response(200, json=body)

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    with pytest.raises(HttpSourceError) as exc:
        source.fetch_changes(Watermark())
    assert exc.value.code == "shape", (
        f"expected code='shape' for an echoed-page mismatch, got {exc.value.code!r}"
    )
    assert exc.value.page in range(2, N + 2), (
        f"expected the failure to name one of the in-flight batch's requested "
        f"pages (2..{N + 1}), got {exc.value.page!r}"
    )
    assert len(calls) <= 1 + N, (
        f"no page beyond the in-flight set may ever be requested once the "
        f"mismatch is observed; got {calls}"
    )


# ══════════════════════════════════════════════════════════════════════════
# AC-11-07 - every existing guard survives concurrency: fail-before-state,
# same codes, the row-cap pre-flight AND the exact post-assembly check.
# ══════════════════════════════════════════════════════════════════════════


def test_4xx_on_page_5_of_12_at_n4_fails_http_status_writes_nothing(db):
    from modules.autocount.models import AcRowHash
    from modules.autocount.repositories import RowHashRepository

    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, {f"{DB_NAME}:SEED": "x" * 64}, seen_at=None
    )
    before_hashes = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    before_count = db.query(AcRowHash).count()

    N = 4
    TOTAL_PAGES = 12
    calls: List[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        calls.append(page)
        if page == 5:
            return httpx.Response(400, text="bad request")
        return httpx.Response(
            200, json=_envelope([_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES)
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    with pytest.raises(HttpSourceError) as exc:
        source.fetch_changes(Watermark())
    assert exc.value.code == "http_status"
    assert exc.value.page == 5
    assert db.query(AcRowHash).count() == before_count
    assert RowHashRepository(db).all_hashes(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT
    ) == before_hashes
    assert max(calls) <= 1 + N, (
        f"no page beyond the in-flight set may be requested after the "
        f"failure is observed (the second batch, pages 6..9, must never "
        f"start); got {calls}"
    )


def test_row_cap_preflight_fails_before_page_2_is_requested(db):
    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    calls: List[int] = []
    # TotalPages(300) x echoed PageSize(1000) = 300,000, way over a 2,000 cap.
    TOTAL_PAGES = 300

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        calls.append(page)
        return httpx.Response(
            200,
            json=_envelope(
                [_item("P1")], page=1, total_pages=TOTAL_PAGES, page_size=1000,
            ),
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
        row_limit=2000,
    )
    with pytest.raises(HttpSourceError) as exc:
        source.fetch_changes(Watermark())
    assert exc.value.code == "row_limit"
    assert calls == [1], (
        f"the row-cap PRE-FLIGHT projection must fail after page 1 alone, "
        f"before page 2 is ever requested; got {calls}"
    )


def test_row_cap_exact_post_assembly_check_still_fires_when_concurrent(db):
    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    TOTAL_PAGES = 3  # 3 x 1000 = 3,000 clears a naive pre-flight of 2,500,
    # but each page ACTUALLY returns 1,000 rows -> 3,000 scanned > 2,500.

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        rows = [_item(f"P{page}-{i}") for i in range(1000)]
        return httpx.Response(
            200, json=_envelope(rows, page=page, total_pages=TOTAL_PAGES, page_size=1000)
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
        row_limit=2500,
    )
    with pytest.raises(HttpSourceError) as exc:
        source.fetch_changes(Watermark())
    assert exc.value.code == "row_limit"


# ══════════════════════════════════════════════════════════════════════════
# AC-11-08 - AC-10-75 preserved exactly: a page timing out twice at N=4
# aborts the in-flight set, DISCARDS every partial, halves the page size,
# and restarts from a SERIAL page 1 before going concurrent again.
# ══════════════════════════════════════════════════════════════════════════


def test_halving_at_n4_discards_partials_and_restarts_serial_then_concurrent(db):
    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    TOTAL_PAGES = 5
    calls: List[httpx.Request] = []
    page3_attempts_at_1000 = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        page = int(request.url.params.get("page", "1"))
        page_size = request.url.params.get("pageSize")
        if page == 3 and page_size == "1000":
            page3_attempts_at_1000["n"] += 1
            return httpx.Response(524, json={})  # Cloudflare-timeout classified
        return httpx.Response(
            200,
            json=_envelope(
                [_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES,
                page_size=int(page_size),
            ),
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    result = source.fetch_changes(Watermark())

    assert page3_attempts_at_1000["n"] == 2, (
        "page 3 must be attempted exactly twice at the ORIGINAL page size "
        "before the halving fires (AC-10-75's own retry budget)"
    )
    assert source.source_page_size == 500, (
        f"expected the walk to land on 500 after ONE halving from 1000, got "
        f"{source.source_page_size!r}"
    )
    page1_calls = [c for c in calls if c.url.params.get("page") == "1"]
    assert len(page1_calls) == 2, (
        "page 1 must be re-fetched exactly once more on the restart (once "
        "for the original attempt, once for the halved-size restart)"
    )
    assert page1_calls[0].url.params.get("pageSize") == "1000"
    assert page1_calls[1].url.params.get("pageSize") == "500"
    # No accumulation across the restart: exactly one record per page, from
    # the FINAL successful walk only.
    assert len(result.records) == TOTAL_PAGES
    codes = sorted(r.raw["ItemCode"] for r in result.records)
    assert codes == [f"P{p}" for p in range(1, TOTAL_PAGES + 1)]


def test_halving_at_n4_respects_max_page_halvings(db):
    """Persistent timeouts at every size, even under concurrency: exactly
    MAX_PAGE_HALVINGS (2) halvings, then the existing failure rule applies -
    never a third halving, never an infinite restart loop."""
    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        page = int(request.url.params.get("page", "1"))
        if page == 1:
            return httpx.Response(524, json={})
        return httpx.Response(200, json=_envelope([_item(f"P{page}")], page=page, total_pages=5))

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    with pytest.raises(HttpSourceError):
        source.fetch_changes(Watermark())
    sizes_seen = {c.url.params.get("pageSize") for c in calls if c.url.params.get("page") == "1"}
    assert sizes_seen == {"1000", "500", "250"}, (
        f"expected exactly two halvings (1000, 500, 250), got {sizes_seen}"
    )


# ══════════════════════════════════════════════════════════════════════════
# AC-11-09 - worker threads never touch the database: the heartbeat fires
# from the DRAINING (calling) thread only, and the concurrent worker body's
# own source references no Session / self._ctx.db / RowHashRepository.
# ══════════════════════════════════════════════════════════════════════════


def test_heartbeat_abandonment_at_n4_stops_the_walk_no_new_page_submitted(db):
    conn = _open_connection(db, max_concurrent_pages="4")
    company = _company(db, conn.id)
    config = _config(db, company, connection_id=conn.id)
    N = 4
    TOTAL_PAGES = 9  # more than 1 + N, so a second batch would be needed if
    # the abandonment were not honoured.
    calls: List[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        calls.append(page)
        return httpx.Response(
            200, json=_envelope([_item(f"P{page}")], page=page, total_pages=TOTAL_PAGES)
        )

    heartbeat_calls = {"n": 0}

    def heartbeat(stage: str, page: int, total: Optional[int]) -> None:
        heartbeat_calls["n"] += 1
        if heartbeat_calls["n"] == 3:
            raise _Abandoned("this build was abandoned")

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
        heartbeat=heartbeat,
    )
    with pytest.raises(_Abandoned):
        source.fetch_changes(Watermark())
    assert len(calls) <= 1 + N, (
        f"no page beyond the in-flight batch active when the abandonment "
        f"fired may ever be requested; got {calls}"
    )


def test_concurrent_worker_never_touches_the_database():
    """Static check (AC-11-09's own named review hard-gate, ALSO pinned
    here): the concurrent per-page worker body must reference no
    ``Session``/``self._ctx.db``/``RowHashRepository`` - a stray DB call
    inside a worker thread would corrupt a non-thread-safe SQLAlchemy
    session in ways an ordinary test would rarely catch.

    ASSUMED NAME (see module docstring): ``HttpApiSource._fetch_page_concurrent``.
    """
    worker = getattr(HttpApiSource, "_fetch_page_concurrent", None)
    if worker is None:
        pytest.fail(
            "HttpApiSource._fetch_page_concurrent does not exist yet "
            "(sprint-5/11 S6, AC-11-09) - this is an ASSUMED NAME for the "
            "per-page worker body a ThreadPoolExecutor submits; if the "
            "coder used a different name, retarget this test at it rather "
            "than deleting the check."
        )
    src = inspect.getsource(worker)
    for forbidden in ("Session", "self._ctx.db", "RowHashRepository", "self._ctx.company_service"):
        assert forbidden not in src, (
            f"the concurrent worker body references {forbidden!r} - worker "
            f"threads must do HTTP + JSON parse ONLY, never touch the "
            f"database\n{src}"
        )
