"""Sprint-5/10 S4 - error-ladder completeness + audit: AC-10-31 (410 leg),
AC-10-64 (exact failed-status code set), AC-10-34 (one audit row per call,
no payload, no plaintext key).

RED before the coder: none of this exists yet.

ASSUMED NAMES (additional to the other S4 files):

* `GET /snapshots/{id}` on an EXPIRED (but once-ready) snapshot -> 410
  `SNAPSHOT_EXPIRED`, full flat body - `companyCode`/`entity` are derivable
  from the FOUND (if expired) snapshot row itself, unlike `UNKNOWN_SNAPSHOT`
  (nothing to derive from at all - see the ambiguity note in
  `test_s10_s4_gateway_auth_and_throttle.py`).
* `modules.autocount.sync._classify_http_source_error` (already landed,
  read verbatim: `row_limit` code -> `ROW_LIMIT`; `phase == "enrich"` ->
  `ENRICH_FAILED`; else -> `SOURCE_PAGE_FAILED`) UNION the literal
  `"EMPTY_EXTRACT"` string (AC-10-46, already landed in `_run_pull_snapshot`)
  is EXACTLY AC-10-64's set - pinned here as a set-equality assertion rather
  than an invented named constant, since none exists on this branch. NO
  reachable path may ever produce `"MAPPING_FAILED"` as a snapshot-level
  `error_code` (that string exists ONLY as an `excludedRows[].reason`,
  AC-10-62).
* `modules.autocount.models.AcPullAudit` (table `ac_pull_audit`, AC-10-27's
  columns). ONE row per gateway call: build, header read, rows read - each
  carrying `key_id, company_id, entity_type, snapshot_id, action, page,
  record_count, status_code`. Nothing on the row is a payload field or the
  plaintext key.
* THIS FILE'S OWN CHOICE for the "no resolvable key" case (AC-10-31's "state
  which, once, and test it"): a request whose key cannot be resolved AT ALL
  (missing/malformed/unknown - no tenant to attribute the row to, and every
  other table in this module requires `tenant_id NOT NULL`) writes NO audit
  row. A key that DOES resolve (tenant known) but then fails for any other
  reason (wrong company scope, disabled service, cooldown, ...) DOES write
  one, with that tenant.

Kill-test notes are per section below.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany

GATEWAY_PREFIX = "/api/v1/autocount"
# Anchored on the REAL wall clock (coordinator fix, 2026-09-20): the gateway's
# `SNAPSHOT_EXPIRED` check compares `expires_at` against `datetime.now(utc)`
# at REQUEST time - there is no `now=` seam to inject on an unauthenticated
# GET, unlike `PullService.request_build`'s own `now` parameter. A fixed
# calendar constant here would make `test_410_snapshot_expired_full_body`
# pass only before its own hardcoded clock-time on one specific day, and
# would make every OTHER "not yet expired" fixture in this file a ticking
# time bomb once real time passed its hardcoded window.
NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    `test_s10_s3_delivery_mode.py`'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20)."""
    import httpx

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


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(db, *, sorento_company_code="SRT", database_name="AED_SORENTO") -> AcCompany:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=database_name,
        company_name="Sorento", name="Sorento", is_active=True,
        sorento_company_code=sorento_company_code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _issue_key(db, *, company_ids):
    from modules.autocount.services.pull_key_service import PullKeyService

    key, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="audit test key", company_ids=company_ids,
    )
    return key, plaintext


def _ready_snapshot(db, company, *, extracted_at, expires_at):
    from modules.autocount.services.pull_service import SnapshotService

    service = SnapshotService(db)
    snap = service.create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="gateway",
    )
    service.insert_row(
        DEFAULT_TENANT_ID, snap, 0, company_id=company.id,
        source_ref="AED_SORENTO:A1", payload={"code": "A1"},
    )
    return service.stamp_ready(
        DEFAULT_TENANT_ID, snap, record_count=1, complete=True, content_hash="a" * 64,
        metadata={"excludedCount": 0, "excludedRows": []},
        extracted_at=extracted_at, expires_at=expires_at,
    )


# ── AC-10-31: 410 SNAPSHOT_EXPIRED, full flat body ───────────────────────────


def test_410_snapshot_expired_full_body(client, db):
    company = _company(db)
    key, plaintext = _issue_key(db, company_ids=[company.id])
    snap = _ready_snapshot(
        db, company, extracted_at=NOW - timedelta(hours=48), expires_at=NOW - timedelta(hours=1),
    )

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": plaintext})
    assert response.status_code == 410, response.text
    body = response.json()
    assert body["code"] == "SNAPSHOT_EXPIRED"
    assert body["companyCode"] == "SRT"
    assert body["entity"] == "products"


def test_a_not_yet_expired_snapshot_is_readable_control(client, db):
    company = _company(db)
    key, plaintext = _issue_key(db, company_ids=[company.id])
    snap = _ready_snapshot(
        db, company, extracted_at=NOW, expires_at=NOW + timedelta(hours=23),
    )

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": plaintext})
    assert response.status_code == 200, response.text


# ── AC-10-64: the exact failed-status code set ───────────────────────────────


def test_the_pinned_failed_code_set_is_exhaustive_and_excludes_mapping_failed():
    import inspect

    from modules.autocount import sync as sync_module
    from modules.autocount.http_source.errors import HttpSourceError

    # review round 2 (coordinator-authorized change, item 1): the set is now
    # a NAMED constant (``sync.PULL_SNAPSHOT_FAILED_CODES``) that also
    # includes ``BUILD_ABANDONED`` (AC-10-88 - a genuine fifth code, an
    # orphan-reclaimed build, never folded onto ``SOURCE_PAGE_FAILED``) - so
    # this test asserts against THAT constant rather than a hand-typed set
    # that would otherwise need updating by hand every time the ladder
    # grows.
    # review round 4 (SF-3) - a SIXTH code, ``COMBINE_RULE_FAILED``: a
    # ``combine`` drop rule that raises at runtime during a pull build
    # (AC-10-79) is a genuine extraction failure, never folded onto
    # ``SOURCE_PAGE_FAILED`` either, for the same "an operator debugging the
    # failure needs to land on the actual cause" reasoning as
    # ``BUILD_ABANDONED``.
    reachable = {
        sync_module._classify_http_source_error(HttpSourceError("boom", code="row_limit")),
        sync_module._classify_http_source_error(HttpSourceError("boom", phase="enrich")),
        sync_module._classify_http_source_error(HttpSourceError("boom")),
        "EMPTY_EXTRACT",
        "BUILD_ABANDONED",
        "COMBINE_RULE_FAILED",
    }
    assert reachable == set(sync_module.PULL_SNAPSHOT_FAILED_CODES)
    assert "MAPPING_FAILED" not in reachable
    # `MAPPING_FAILED` must never appear anywhere in the module as a
    # snapshot-level error code literal (a lightweight source-grep control -
    # it legitimately DOES appear as an `excludedRows[].reason`, so this
    # checks the SYNC module's error-code-producing function only).
    source = inspect.getsource(sync_module._classify_http_source_error)
    assert "MAPPING_FAILED" not in source


# ── AC-10-34: one audit row per call, no payload, no plaintext ──────────────


def test_a_successful_build_writes_one_audit_row_with_no_payload(client, db, monkeypatch):
    import httpx
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.models import AcEntityConfig, AcFieldMapping, AcPullAudit

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []},
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )
    company = _company(db)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", etl_status="active", delivery_mode="pull",
            source_config={
                "connectionId": company.connection_id, "path": "/itembypage",
                "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
                "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
                "reconcileAt": "02:00", "lookups": [],
            },
        )
    )
    db.commit()
    key, plaintext = _issue_key(db, company_ids=[company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": plaintext},
    )
    assert response.status_code == 202, response.text

    rows = db.query(AcPullAudit).filter(AcPullAudit.tenant_id == DEFAULT_TENANT_ID).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.key_id == key.id
    assert row.company_id == company.id
    assert row.entity_type == ENTITY_PRODUCT
    assert row.status_code == 202
    for forbidden in ("payload", "payload_json", "raw_json"):
        assert not hasattr(row, forbidden)


def test_a_read_within_the_keys_own_tenant_but_wrong_company_still_writes_one_audit_row(
    client, db,
):
    """The key resolves (tenant known) but the target snapshot is outside
    its company scope - still attributable, so still audited (contrast with
    the no-resolvable-key case below, which is not)."""
    from modules.autocount.models import AcPullAudit

    company = _company(db)
    other_company = _company(db, sorento_company_code="MCH", database_name="MOCHA")
    snap = _ready_snapshot(db, other_company, extracted_at=NOW, expires_at=NOW + timedelta(hours=1))
    key, plaintext = _issue_key(db, company_ids=[company.id])

    before = db.query(AcPullAudit).count()
    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": plaintext})
    assert response.status_code == 404, response.text

    after = db.query(AcPullAudit).filter(AcPullAudit.tenant_id == DEFAULT_TENANT_ID).count()
    assert after == before + 1


def test_a_request_with_no_resolvable_key_writes_no_audit_row_this_files_own_choice(client, db):
    from modules.autocount.models import AcPullAudit

    before = db.query(AcPullAudit).count()
    response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/does-not-exist",
        headers={"X-API-Key": "fxa_live_" + "q" * 43},
    )
    assert response.status_code == 401, response.text

    after = db.query(AcPullAudit).count()
    assert after == before


def test_multiple_calls_write_multiple_distinct_audit_rows_control(client, db, monkeypatch):
    """CONTROL: proves the audit write genuinely happens per call (not once
    globally, and not skipped for every call) by making TWO calls and
    checking the count grew by exactly two."""
    from modules.autocount.models import AcPullAudit

    company = _company(db)
    snap = _ready_snapshot(db, company, extracted_at=NOW, expires_at=NOW + timedelta(hours=1))
    key, plaintext = _issue_key(db, company_ids=[company.id])

    before = db.query(AcPullAudit).count()
    client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": plaintext})
    client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}/rows", headers={"X-API-Key": plaintext})
    after = db.query(AcPullAudit).count()
    assert after == before + 2


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_the_pinned_failed_code_set_is_exhaustive_and_excludes_mapping_failed
#   dies if a future addition to `_classify_http_source_error` introduces a
#   fifth code, or if `MAPPING_FAILED` is ever emitted from that function -
#   a set-EQUALITY check, not a subset check, so an extra code fails too.
# * test_a_request_with_no_resolvable_key_writes_no_audit_row_this_files_own_choice
#   is paired with test_multiple_calls_write_multiple_distinct_audit_rows_control
#   so an implementation that writes ZERO audit rows for EVERY call (a
#   silently broken audit path) cannot pass both - the control demands
#   exactly +2 for two successful calls.
