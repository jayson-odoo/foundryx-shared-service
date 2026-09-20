"""Sprint-5/10 S1 - AC-10-75: bounded retry per page before declaring
failure (the db2 524-timeout finding, 2026-09-19).

RED before the coder: today ``HttpApiSource._walk`` makes ONE attempt per
page (AC-08-23) - a single ``httpx.TimeoutException``/524/5xx fails the
whole run immediately, with no retry and no page-size halving. Every test
below proves REAL behaviour change, not an ImportError.

Assumption flagged for the coder (the plan names the BEHAVIOUR - "retries at
most twice... with a bounded backoff (1s then 4s)" and "on a SECOND timeout
of the SAME page the walk HALVES the page size... and RESTARTS" - but not
WHICH module holds the retry loop or how backoff is invoked). This file:
  - monkeypatches the GLOBAL ``time.sleep`` (``monkeypatch.setattr("time.
    sleep", ...)``) so the backoff never actually sleeps in the suite,
    regardless of which module under ``modules.autocount.http_source`` calls
    it - this works for any ``import time; time.sleep(x)`` caller, which is
    the house style everywhere else in this client (``http_source/client.py``
    already does exactly this for latency timing).
  - reads ONLY the observable contract: how many requests were made, what
    ``pageSize`` they carried, and whether the run ultimately raised
    ``HttpSourceError`` with no state touched - never a private retry
    counter or attribute this file invents a name for.
  - resolves "a SECOND timeout of the SAME page" as EXACTLY two attempts at
    a page (the original request plus one retry) before the halve-and-
    restart fires, rather than the full two-retry/three-attempt budget the
    surrounding sentence describes for the general timeout/5xx retry case -
    the AC's own wording ("On a SECOND timeout...") most directly supports
    this reading. If the coder's mechanics genuinely differ (e.g. three
    attempts before the first halving), say so and this file gets adjusted
    - it is not a signal to silently reshape the test to match the code.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig, AcRowHash
from modules.autocount.repositories import RowHashRepository
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark

from modules.autocount.http_source.source import HttpApiSource
from modules.autocount.http_source.errors import HttpSourceError

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Backoff must never actually sleep in the test suite - patches the
    GLOBAL ``time.sleep`` attribute, which any ``import time; time.sleep()``
    caller resolves through regardless of which file it lives in."""
    monkeypatch.setattr("time.sleep", lambda seconds: None)


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def rig(session_factory):
    db = session_factory()
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    yield db, company, conn
    db.close()


def _config(db, company, connection_id: str) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http",
        source_config={
            "connectionId": connection_id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
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


def _ok_page(rows) -> Dict[str, Any]:
    return {"TotalCount": len(rows), "Page": 1, "PageSize": len(rows) or 1, "TotalPages": 1, "Data": rows}


# ── one retry recovers, no halving ───────────────────────────────────────────


def test_single_timeout_then_success_is_one_retry_no_halving(rig):
    db, company, conn = rig
    config = _config(db, company, conn.id)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("boom", request=request)
        return httpx.Response(200, json=_ok_page([{"ItemCode": "A1", "LastModified": "2026-08-01T09:00:00"}]))

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    result = source.fetch_changes(Watermark())
    assert len(result.records) == 1
    assert len(calls) == 2, "one timeout + one retry = 2 attempts"
    assert calls[1].url.params.get("pageSize") == "1000", "no halving after a SINGLE timeout"


def test_524_is_treated_as_a_timeout_and_retried(rig):
    """AC-10-75: "a Cloudflare 524 is treated as a timeout, not as a 5xx to
    give up on" - a single 524 must recover exactly like a single
    ConnectTimeout, never fail immediately the way a genuine 4xx does."""
    db, company, conn = rig
    config = _config(db, company, conn.id)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(524, text="Cloudflare timeout")
        return httpx.Response(200, json=_ok_page([{"ItemCode": "A1", "LastModified": "2026-08-01T09:00:00"}]))

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    result = source.fetch_changes(Watermark())
    assert len(result.records) == 1
    assert len(calls) == 2


def test_connect_error_then_success_is_one_retry(rig):
    db, company, conn = rig
    config = _config(db, company, conn.id)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=_ok_page([{"ItemCode": "A1", "LastModified": "2026-08-01T09:00:00"}]))

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    result = source.fetch_changes(Watermark())
    assert len(result.records) == 1
    assert len(calls) == 2


# ── a genuine 4xx / bad shape never retries ──────────────────────────────────


def test_4xx_fails_immediately_with_no_retry(rig):
    db, company, conn = rig
    config = _config(db, company, conn.id)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400, text="bad request")

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    with pytest.raises(HttpSourceError):
        source.fetch_changes(Watermark())
    assert len(calls) == 1, "a 4xx must fail immediately - never retried"


# ── two timeouts on the SAME page: halve and restart from page 1 ────────────


def test_second_timeout_on_same_page_halves_page_size_and_restarts(rig):
    db, company, conn = rig
    config = _config(db, company, conn.id)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        page_size = request.url.params.get("pageSize")
        if page_size == "1000":
            raise httpx.ReadTimeout("boom", request=request)
        return httpx.Response(
            200, json=_ok_page([{"ItemCode": "A1", "LastModified": "2026-08-01T09:00:00"}])
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    result = source.fetch_changes(Watermark())
    assert len(result.records) == 1
    page_sizes_requested = [c.url.params.get("pageSize") for c in calls]
    assert page_sizes_requested[0] == "1000"
    assert page_sizes_requested[1] == "1000"
    assert "500" in page_sizes_requested, (
        f"expected a halved 500 pageSize after two 1000-sized timeouts, got {page_sizes_requested}"
    )
    # The FIRST request at the halved size must start over from page 1.
    halved_calls = [c for c in calls if c.url.params.get("pageSize") == "500"]
    assert halved_calls[0].url.params.get("page") == "1"


def test_two_halvings_max_then_the_existing_failure_rule_applies(rig):
    """Persistent timeouts at every size: 1000 -> halve -> 500 -> halve ->
    250, then a THIRD halving must never happen - the run fails outright."""
    db, company, conn = rig
    config = _config(db, company, conn.id)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("boom", request=request)

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    with pytest.raises(HttpSourceError):
        source.fetch_changes(Watermark())
    sizes_seen = {c.url.params.get("pageSize") for c in calls}
    assert sizes_seen == {"1000", "500", "250"}, (
        f"expected exactly two halvings (1000, 500, 250), got {sizes_seen}"
    )


def test_persistent_timeout_exhaustion_touches_no_state(rig):
    db, company, conn = rig
    config = _config(db, company, conn.id)
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, {f"{DB_NAME}:SEED": "x" * 64}, seen_at=None
    )
    before = db.query(AcRowHash).count()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("boom", request=request)

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    with pytest.raises(HttpSourceError):
        source.fetch_changes(Watermark())
    assert db.query(AcRowHash).count() == before


# KILL TEST (for the reviewer): change the coder's "two timeouts trigger a
# halving" counter to reset on ANY successful request rather than being
# scoped to the CURRENT page size - the two-halving-max test would still
# pass, but ``test_second_timeout_on_same_page_halves_page_size_and_restarts``
# is the one that would catch a counter that never reaches 2 at all (e.g. an
# off-by-one that halves on the FIRST timeout instead of the second) via its
# ``page_sizes_requested[1] == "1000"`` assertion.
