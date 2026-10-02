"""Sprint-5/10 S3 review round 1 - MUST-FIX 2 (AC-10-24): ``complete`` is
never a guess.

Coordinator finding: before this round, ``_run_pull_snapshot`` computed
``complete = result.reported_total is None or rows_scanned ==
result.reported_total`` - so a PAGED endpoint that simply omitted or nulled
``TotalCount`` (``reported_total is None``) read as unconditionally
``complete = True``, exactly like a genuinely bare-array endpoint. That is
the worst failure mode this plan names (Sorento zeroes every stock pair
absent from a fed set) landing on an UNVERIFIED page, not just a verified-
false one. The fix threads the main path's own envelope shape
(``FetchResult.envelope_kind``) through so ``complete`` is ``True`` only for
a genuinely bare array, or a paged walk whose scanned-row count actually
matches an ECHOED total.

RED before the fix (proven by reasoning): before ``envelope_kind`` existed,
every test below that constructs a paged body with NO/null ``TotalCount``
would have produced ``complete = True`` (the old ``reported_total is None``
branch), the exact opposite of what is asserted here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import ETL_STATUS_ACTIVE, AcCompany, AcEntityConfig, AcFieldMapping

DB_NAME = "AED_SORENTO"
BASE_URL = "https://hapi.sorento.cc.cd/api/db1"

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    ``test_s10_s3_delivery_mode.py``'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20)."""
    real_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    async def guarded_async_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return await real_async_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """The halving test times a page out twice - backoff must never
    actually sleep in the suite (mirrors ``test_s10_http_retry.py``)."""
    monkeypatch.setattr("time.sleep", lambda seconds: None)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=DB_NAME,
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _product_task(db, company, connection_id) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE, delivery_mode="pull",
        source_config={
            "connectionId": connection_id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [],
        },
        last_preview_at=NOW, result_columns=["ItemCode", "Description"],
    )
    db.add(config)
    db.commit()
    db.add(AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        scope="header", sort_order=0, source_path="ItemCode", canonical_field="code",
        transform="string", is_required=True,
    ))
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


def _single_page_transport(body: Any) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _build(db, company, *, now=NOW):
    from modules.autocount.services.pull_service import PullService

    return PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=now,
    )


# ── a paged body that OMITS TotalCount entirely is UNVERIFIED, never true ──


def test_paged_body_with_no_total_count_key_is_incomplete(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)
    body = {
        # No "TotalCount" key at all.
        "Page": 1, "PageSize": 1000, "TotalPages": 1,
        "Data": [{"ItemCode": "A1", "Description": "A1"}],
    }
    _patch_transport(monkeypatch, _single_page_transport(body))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready", "a completeness gap alone never fails the build"
    assert snapshot.complete is False
    assert snapshot.record_count == 1


# ── a paged body with an EXPLICIT null TotalCount is equally UNVERIFIED ────


def test_paged_body_with_null_total_count_is_incomplete(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)
    body = {
        "TotalCount": None, "Page": 1, "PageSize": 1000, "TotalPages": 1,
        "Data": [{"ItemCode": "A1", "Description": "A1"}],
    }
    _patch_transport(monkeypatch, _single_page_transport(body))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.complete is False


# ── a genuine mismatch (control, mirrors the pre-round test) ───────────────


def test_paged_body_with_mismatched_total_count_is_incomplete(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)
    body = {
        "TotalCount": 1000, "Page": 1, "PageSize": 1000, "TotalPages": 1,
        "Data": [{"ItemCode": "A1", "Description": "A1"}],
    }
    _patch_transport(monkeypatch, _single_page_transport(body))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.complete is False
    assert snapshot.record_count == 1


# ── a genuinely bare-array endpoint has no total to compare, always true ───


def test_bare_array_endpoint_is_unconditionally_complete(db, monkeypatch):
    """A lookup-shaped bare JSON array as the MAIN path (never happens live
    today, but the classification is endpoint-shape-driven, not
    entity-driven) - there is no total to fall short of BY DESIGN, so
    ``complete`` must be ``True`` regardless of how few rows came back."""
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)
    body: List[Dict[str, Any]] = [{"ItemCode": "A1", "Description": "A1"}]
    _patch_transport(monkeypatch, _single_page_transport(body))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready"
    assert snapshot.complete is True
    assert snapshot.record_count == 1


# ── a halving restart reports ONLY the final walk's own counts ─────────────


def test_halving_restart_completeness_uses_only_the_final_walk(db, monkeypatch):
    """Page 1 at the default page size succeeds (3 rows, ``TotalCount: 6``,
    implying a second page); page 2 times out on BOTH attempts, so the walk
    halves the page size and restarts from page 1 ENTIRELY - ``_walk_path``
    builds a fresh ``scanned = []`` on every call, so the timed-out
    attempt's 3 rows/``TotalCount: 6`` must never blend into the final
    result. At the halved size, ONE page answers everything (2 rows,
    ``TotalCount: 2``). If the discarded attempt's counts leaked in, this
    would read ``record_count == 5`` and (2 != 6 mismatch, unrelated
    accounting) certainly not the clean ``complete = True`` a correct,
    single coherent walk produces."""
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)

    def handler(request: httpx.Request) -> httpx.Response:
        page_size = request.url.params.get("pageSize")
        page = request.url.params.get("page")
        if page_size == "1000":
            if page == "1":
                return httpx.Response(
                    200,
                    json={
                        "TotalCount": 6, "Page": 1, "PageSize": 1000, "TotalPages": 2,
                        "Data": [
                            {"ItemCode": "A", "Description": "A"},
                            {"ItemCode": "B", "Description": "B"},
                            {"ItemCode": "C", "Description": "C"},
                        ],
                    },
                )
            # Page 2 at the default size times out on BOTH attempts.
            raise httpx.ReadTimeout("boom", request=request)
        # The halved size (500) answers everything in ONE page.
        return httpx.Response(
            200,
            json={
                "TotalCount": 2, "Page": 1, "PageSize": 500, "TotalPages": 1,
                "Data": [
                    {"ItemCode": "X", "Description": "X"},
                    {"ItemCode": "Y", "Description": "Y"},
                ],
            },
        )

    _patch_transport(monkeypatch, httpx.Client(transport=httpx.MockTransport(handler)))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready"
    assert snapshot.record_count == 2, "only the FINAL walk's rows - never blended with the discarded attempt"
    assert snapshot.complete is True, (
        "the final walk's own scanned count (2) matches its own echoed "
        "total (2) - a blended accounting (5 scanned vs a stale/foreign "
        "total) would have produced complete=False instead"
    )


# ── kill tests ──────────────────────────────────────────────────────────────
#
# * test_paged_body_with_no_total_count_key_is_incomplete and its null-total
#   twin die if the completeness check reverts to
#   ``reported_total is None or rows_scanned == reported_total`` (the
#   pre-round formula) - both would flip to True.
# * test_bare_array_endpoint_is_unconditionally_complete dies if
#   ``envelope_kind`` is dropped or hardcoded to ``ENVELOPE_PAGED`` - the
#   completeness check would then fall through to the reported-total branch,
#   which is None for a bare array, ALSO True under the old formula but for
#   the WRONG reason (this is the one case old and new code agree on the
#   answer, so it alone would not have caught a regression - paired with the
#   no-total-count test above specifically to close that gap).
# * test_halving_restart_completeness_uses_only_the_final_walk dies if a
#   restart's rows/total ever accumulate across ``_walk_endpoint``'s retry
#   loop instead of each attempt starting a fresh ``scanned``.
