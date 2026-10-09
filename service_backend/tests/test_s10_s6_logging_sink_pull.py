"""Sprint-5/10 S6 - a `logging`-sink company can still use PULL (live-replay
Finding 0, ``documentation/plans/sprint-5/10-evidence/live-replay/README.md``).

RED before the coder, verified at HEAD: ``CompanyService.set_sink_target``
(``services/company_service.py:1103-1108``) UNCONDITIONALLY clears
``company.sorento_company_code`` the moment ``sink_impl`` switches to
``'logging'`` ("Cleared with the target: a code left behind would silently
anchor a later switch back to Sorento at a company nobody re-chose"). But
``EtlService.set_delivery_mode`` (``services/etl_service.py:2789-2799``)
REQUIRES a non-blank ``company.sorento_company_code`` before ANY entity may
switch to ``deliveryMode: "pull"``, and the public gateway's build route
(``PullGatewayService.build`` -> ``CompanyRepository.
find_by_sorento_company_code``) resolves the target company BY that same
code. Net: **a company on the `logging` sink can never be configured for
pull at all** in this codebase today - not the "banner only, never
blocked" behaviour AC-10-69's third bullet already promises for a
NO-Sorento-connection product task (``CompanyService.contract_gate``
already renders that banner correctly - verified separately, unaffected by
this bug; the block happens one step earlier, before the contract gate is
ever consulted).

The fix this file pins (NOT written here - tester writes red tests only):
``set_sink_target`` must preserve ``sorento_company_code`` across a switch
to ``logging`` (it is the book's public identity, not a push-target
artifact - see the README's Finding 0 for the full reasoning the plan owner
signed off), so the two downstream consumers of that field (``set_delivery_
mode``'s pull gate, the gateway's company resolution) keep working.

ASSUMED NAME: no new name - this is a BEHAVIOUR change to the existing
``CompanyService.set_sink_target`` only.

UAC ambiguity resolved here (see final report): AC-10-69's third bullet
("the company has NO Sorento sink connection... the banner renders with
`version: null`") is ALREADY built and green today (``CompanyService.
contract_gate``, pinned by ``test_s10_s3_product_contract_gate.py``) - the
live-replay's Finding 0 is entirely about the EARLIER blocker (pull mode
itself unreachable), not that banner. This file's main test therefore
drives the REAL end-to-end flow (switch sink -> enable pull -> build
through the gateway -> read the task view's own `contractGate`) so it
fails at the true root cause and also documents/exercises the currently-
correct banner behaviour along the way, rather than duplicating
`test_s10_s3_product_contract_gate.py`."""
from __future__ import annotations

from typing import Any, Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    DELIVERY_MODE_PULL,
    DELIVERY_MODE_PUSH,
    ETL_STATUS_ACTIVE,
    SINK_IMPL_LOGGING,
    SINK_IMPL_SORENTO,
    AcCompany,
    AcEntityConfig,
)
from modules.autocount.services.company_service import CompanyService, SinkTargetValidationError
from modules.autocount.services.etl_service import EtlService


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


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _connection(db, provider: str, config: Dict[str, Any], credentials=None) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider=provider,
        type="erp" if provider != "sorento" else "consumer",
        name=f"{provider} conn", config_json=config,
        credentials_json=encrypt_secret(credentials or {}), is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company_on_sorento_sink(db, *, code: str = "SRT") -> AcCompany:
    """A company already delivering to a real Sorento sink, WITH a code -
    the exact starting state the replay's Setup section describes (SRT
    pointed at a `.invalid` fixture connection, code 'SRT') before the
    session ever touched the sink target."""
    api = _connection(db, "autocount", {"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"})
    sorento = _connection(db, "sorento", {"baseUrl": "https://sorento.example.invalid"}, {"apiKey": "k"})
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id, sorento_company_code=code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _pull_task(db, company) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE, delivery_mode=DELIVERY_MODE_PUSH,
        source_config={
            "connectionId": company.connection_id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [],
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _issue_key(db, *, company_ids):
    from modules.autocount.services.pull_key_service import PullKeyService

    _key, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="S6 logging-sink pull test key", company_ids=company_ids,
    )
    return plaintext


def _stub_empty_transport(monkeypatch) -> None:
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []},
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )


# ── the core defect: the code must survive a switch to `logging` ────────────


def test_switching_to_logging_sink_preserves_sorento_company_code(db):
    """Today ``set_sink_target`` unconditionally clears the code - this is
    THE root cause (Finding 0). A bare, direct pin."""
    company = _company_on_sorento_sink(db, code="SRT")

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id, sink_impl=SINK_IMPL_LOGGING,
    )
    db.refresh(company)

    assert company.sink_impl == SINK_IMPL_LOGGING
    assert company.sorento_company_code == "SRT", (
        "set_sink_target cleared sorento_company_code on a switch to "
        "'logging' - the book's public pull identity must survive a sink "
        "switch (live-replay Finding 0)."
    )


# ── the end-to-end consequence: pull can be enabled and the gateway can build ─


def test_logging_sink_company_can_enable_and_build_a_pull_snapshot(db, monkeypatch):
    """Full real flow: switch to logging (code must survive) -> enable pull
    on the product task -> build through the SAME public-gateway seam a
    real consumer uses (``PullGatewayService.build``, with a stubbed empty
    HTTP transport so no network is touched) -> the resulting snapshot is
    NOT refused. This is the end-to-end fact the brief names: "set_delivery
    _mode(entity='product', 'pull') then succeeds on that company; the
    gateway resolves its companyCode... rather than refusing"."""
    _stub_empty_transport(monkeypatch)

    company = _company_on_sorento_sink(db, code="SRT")
    _pull_task(db, company)

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id, sink_impl=SINK_IMPL_LOGGING,
    )
    db.refresh(company)

    # This call raises `EtlValidationError` ("Set a consumer company code
    # on this company before enabling pull.") at HEAD today, because the
    # switch above already cleared `sorento_company_code` to None - the
    # SAME root cause as the test above, exercised through the actual
    # operator-facing call this AC names.
    view = EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, DELIVERY_MODE_PULL,
    )
    assert view.delivery_mode == DELIVERY_MODE_PULL

    key = _issue_key(db, company_ids=[company.id])
    from modules.autocount.services.pull_gateway_service import PullGatewayService
    from modules.autocount.services.pull_key_service import PullKeyService

    # `PullKeyService.resolve` (not the HTTP-level `resolve_pull_key`,
    # already covered by `test_s10_s4_gateway_auth_and_throttle.py`) is the
    # plaintext -> row lookup; this file tests `PullGatewayService.build`
    # itself.
    key_row = PullKeyService(db).resolve(key)
    assert key_row is not None, "the issued pull key did not resolve"

    resolved_company, snapshot = PullGatewayService(db).build(key_row, "SRT", ENTITY_PRODUCT)
    assert resolved_company.id == company.id
    assert snapshot.status in ("building", "ready"), (
        f"expected the gateway build to proceed (not refuse) for a "
        f"logging-sink company with a preserved code, got status "
        f"{snapshot.status!r}"
    )


def test_logging_sink_company_product_contract_gate_is_null_banner_not_a_block(db):
    """AC-10-69's third bullet, exercised on a company that reached
    `logging` WITH its code preserved (the fixed state): the task view's
    own `contractGate` renders `version: None` (banner-only) rather than
    ever refusing - confirmed independently of the delivery-mode gate
    above, at the same call the Review & Activate screen itself reads."""
    company = _company_on_sorento_sink(db, code="SRT")
    _pull_task(db, company)

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id, sink_impl=SINK_IMPL_LOGGING,
    )
    db.refresh(company)
    assert company.sorento_company_code == "SRT", (
        "precondition for this test: the code must survive the sink "
        "switch (Finding 0) before the contract gate is even reached."
    )

    gate = CompanyService(db).contract_gate(DEFAULT_TENANT_ID, company, ENTITY_PRODUCT)
    assert gate is not None
    assert gate["version"] is None
    assert gate["entity"] == ENTITY_PRODUCT
