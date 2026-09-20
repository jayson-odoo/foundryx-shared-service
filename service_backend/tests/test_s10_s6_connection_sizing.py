"""Sprint-5/10 S6 - AC-10-85: per-CONNECTION ``pageSize``/``requestTimeoutSeconds``
(live-replay Finding 1, ``documentation/plans/sprint-5/10-evidence/live-replay/README.md``).

RED before the coder, verified at HEAD (b1593264 boot / advanced during the
replay, unaffected by that concurrent work - see the README's own diff
check): ``AutoCountProvider.fields()`` has exactly the 5 pre-existing fields
(``auth``/``baseUrl``/``appId``/``userId``/``password``) - no ``pageSize``,
no ``requestTimeoutSeconds``. ``HttpApiClient.__init__`` defaults
``timeout_seconds`` to the module constant ``DEFAULT_TIMEOUT_SECONDS = 30.0``
(``http_source/client.py``); the ONE call site that builds it
(``http_source/source.py:237``, ``HttpApiSource.__init__``) never passes an
override at all. ``HttpApiSource._walk_endpoint`` always starts at the
module constant ``DEFAULT_PAGE_SIZE = 1000`` (``http_source/source.py``),
never reading a connection's own setting.

ASSUMED NAMES (the coder must match these - see the brief):

* ``AutoCountProvider.fields()`` gains two entries, in this order after the
  three basic-auth credential fields: ``pageSize`` (``type: "number"``,
  ``default: 1000``, ``min: 50``, ``max: 1000``) and
  ``requestTimeoutSeconds`` (``type: "number"``, ``default: 90``,
  ``max: 100``) - BOTH carrying ``showWhen: {"field": "auth",
  "values": ["none"]}``, the SAME mechanism the existing basic-auth fields
  use in reverse (open connections only, since these are the open REST
  wrapper's own host-latency knobs).
* ``AutoCountProvider.test()`` for ``auth == "none"`` measures the probe's
  own wall-clock duration and reports it in the message, format
  ``"Reached in {seconds} s, {count} locations"`` (the AC's own example
  text), replacing today's ``"Reachable - {n} row(s) returned..."`` string.
* ``modules.autocount.http_source.client.DEFAULT_TIMEOUT_SECONDS`` becomes
  ``90.0`` (was ``30.0``) - the connection-config fallback value, per the
  AC's own text ("the client's DEFAULT_TIMEOUT_SECONDS = 30.0 is fixed...
  both now read from the connection config with THOSE VALUES AS THE
  FALLBACK" - "those values" being 1000/90, not 1000/30).
* ``HttpApiSource.__init__`` reads the resolved connection's
  ``config_json`` for ``pageSize``/``requestTimeoutSeconds`` (wire-shaped
  strings, e.g. ``"250"`` - ``ConnectionUpdateRequest.config`` is
  ``Dict[str, str]``) and passes ``timeout_seconds=<parsed float>`` into
  ``HttpApiClient(base_url, transport=transport, timeout_seconds=...)``,
  and the walk (``_walk_endpoint``/``_walk``) starts at the parsed
  ``pageSize`` instead of the module constant ``DEFAULT_PAGE_SIZE``.
* ``IntegrationService``/``AutoCountProvider.validate_config`` rejects
  ``pageSize`` outside ``50..1000`` and ``requestTimeoutSeconds`` above
  ``100``, naming the offending field in the 422 message (the SAME opt-in
  ``validate_config`` hook ``baseUrl``'s scheme check already uses - see
  ``test_autocount_baseurl_scheme_rejected_at_save_not_only_at_test`` in
  ``test_integrations.py``).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.provider import AutoCountProvider
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

BASE_URL = "https://hapi.sorento.cc.cd/api/db2"


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


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _open_config(base_url: str = BASE_URL, **extra: str) -> Dict[str, Any]:
    return {"baseUrl": base_url, "auth": "none", **extra}


# ── 1. provider.fields() declares pageSize + requestTimeoutSeconds ──────────


def test_provider_fields_declare_page_size_and_timeout_with_show_when():
    fields = AutoCountProvider().fields()
    by_key = {f["key"]: f for f in fields}

    assert "pageSize" in by_key, "AutoCountProvider.fields() has no 'pageSize' entry yet"
    page_size = by_key["pageSize"]
    assert page_size["type"] == "number"
    assert page_size.get("default") == 1000
    assert page_size.get("min") == 50
    assert page_size.get("max") == 1000
    assert page_size.get("showWhen") == {"field": "auth", "values": ["none"]}

    assert "requestTimeoutSeconds" in by_key, (
        "AutoCountProvider.fields() has no 'requestTimeoutSeconds' entry yet"
    )
    timeout = by_key["requestTimeoutSeconds"]
    assert timeout["type"] == "number"
    assert timeout.get("default") == 90
    assert timeout.get("max") == 100
    assert timeout.get("showWhen") == {"field": "auth", "values": ["none"]}


# ── 2. test() reports the MEASURED probe latency + count ────────────────────


def test_test_none_reports_measured_latency_and_location_count():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"Location": "A1"}, {"Location": "A2"}, {"Location": "A3"}])

    result = AutoCountProvider().test(_open_config(), {}, transport=_transport(handler))
    assert result.ok is True
    match = re.search(r"Reached in ([\d.]+)\s*s,\s*(\d+)\s*location", result.message)
    assert match is not None, (
        f"expected a 'Reached in <N> s, <M> locations' message, got: {result.message!r}"
    )
    assert match.group(2) == "3"


# ── 3/4. HttpApiSource builds the client from the CONNECTION's own settings ─


def _open_connection(db, *, page_size: str = None, timeout_seconds: str = None) -> Connection:
    config: Dict[str, Any] = {"baseUrl": BASE_URL, "auth": "none"}
    if page_size is not None:
        config["pageSize"] = page_size
    if timeout_seconds is not None:
        config["requestTimeoutSeconds"] = timeout_seconds
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json=config, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="MOCHA",
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _config(
    db, company, connection_id: str, *, path="/itembypage", lookups: Optional[List[Dict[str, Any]]] = None
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http",
        source_config={
            "connectionId": connection_id, "path": path, "keyFields": ["ItemCode"],
            "watermarkField": None, "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": lookups if lookups is not None else [],
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


def _ok_page(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"TotalCount": len(rows), "Page": 1, "PageSize": len(rows) or 1, "TotalPages": 1, "Data": rows}


def test_http_source_builds_client_with_the_connections_request_timeout(session_factory):
    """The connection carries ``requestTimeoutSeconds: "45"`` - the built
    ``HttpApiClient`` must be constructed with ``timeout_seconds=45``
    (a float), captured via a spy factory (never the wire string ``"45"``
    itself)."""
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.http_source.source import HttpApiSource

    db = session_factory()
    try:
        conn = _open_connection(db, timeout_seconds="45")
        company = _company(db, conn.id)
        config = _config(db, company, conn.id)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_page([{"ItemCode": "A1"}]))

        captured_kwargs: Dict[str, Any] = {}

        def spy_factory(base_url, **kwargs):
            captured_kwargs.update(kwargs)
            return HttpApiClient(base_url, transport=_transport(handler))

        import modules.autocount.http_source.source as source_module

        original = source_module.HttpApiClient
        source_module.HttpApiClient = spy_factory
        try:
            source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT)
            source.fetch_changes(Watermark())
        finally:
            source_module.HttpApiClient = original

        assert captured_kwargs.get("timeout_seconds") == 45.0, (
            f"HttpApiClient was never built with the connection's own "
            f"requestTimeoutSeconds (45); captured kwargs: {captured_kwargs!r}"
        )
    finally:
        db.close()


def test_default_request_timeout_is_now_90_seconds_not_30():
    """Cheap, direct pin of the AC's own stated fallback change."""
    from modules.autocount.http_source.client import DEFAULT_TIMEOUT_SECONDS

    assert DEFAULT_TIMEOUT_SECONDS == 90.0, (
        f"DEFAULT_TIMEOUT_SECONDS is still {DEFAULT_TIMEOUT_SECONDS} - AC-10-85 "
        "moves the fallback from 30s to 90s."
    )


def test_walk_starts_at_the_connections_configured_page_size(session_factory):
    db = session_factory()
    try:
        conn = _open_connection(db, page_size="333")
        company = _company(db, conn.id)
        config = _config(db, company, conn.id)

        calls: List[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=_ok_page([{"ItemCode": "A1"}]))

        import modules.autocount.http_source.source as source_module
        from modules.autocount.http_source.client import HttpApiClient
        from modules.autocount.http_source.source import HttpApiSource

        original = source_module.HttpApiClient
        source_module.HttpApiClient = lambda base_url, **kw: HttpApiClient(
            base_url, transport=_transport(handler)
        )
        try:
            source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT)
            source.fetch_changes(Watermark())
        finally:
            source_module.HttpApiClient = original

        assert calls, "no request was ever made"
        assert calls[0].url.params.get("pageSize") == "333", (
            f"expected the FIRST request to ask for the connection's own "
            f"pageSize (333), got {calls[0].url.params.get('pageSize')!r}"
        )
    finally:
        db.close()


def test_missing_connection_settings_fall_back_to_1000_and_90(session_factory):
    """No ``pageSize``/``requestTimeoutSeconds`` on the connection at all -
    a legacy row, or one never opened up in the wizard - falls back to the
    NEW defaults (1000 / 90), never the old 30s ceiling."""
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.http_source.source import HttpApiSource

    db = session_factory()
    try:
        conn = _open_connection(db)  # no pageSize / requestTimeoutSeconds keys at all
        company = _company(db, conn.id)
        config = _config(db, company, conn.id)

        calls: List[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=_ok_page([{"ItemCode": "A1"}]))

        captured_kwargs: Dict[str, Any] = {}

        def spy_factory(base_url, **kwargs):
            captured_kwargs.update(kwargs)
            return HttpApiClient(base_url, transport=_transport(handler))

        import modules.autocount.http_source.source as source_module

        original = source_module.HttpApiClient
        source_module.HttpApiClient = spy_factory
        try:
            source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT)
            source.fetch_changes(Watermark())
        finally:
            source_module.HttpApiClient = original

        assert calls[0].url.params.get("pageSize") == "1000"
        assert captured_kwargs.get("timeout_seconds") == 90.0, (
            f"missing connection config must fall back to the NEW 90s default, "
            f"captured: {captured_kwargs!r}"
        )
    finally:
        db.close()


# ── 5. halving still starts from the CONFIGURED page size ───────────────────


def test_halving_starts_from_the_configured_page_size_250_125_62(session_factory, monkeypatch):
    """250 -> 125 -> 62 (MAX_PAGE_HALVINGS = 2, floor MIN_PAGE_SIZE = 50) -
    today the walk always starts at the module constant 1000, so this must
    start at the CONNECTION's configured 250 instead."""
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.http_source.source import HttpApiSource

    db = session_factory()
    try:
        conn = _open_connection(db, page_size="250")
        company = _company(db, conn.id)
        config = _config(db, company, conn.id)

        calls: List[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            page_size = request.url.params.get("pageSize")
            if page_size in ("250", "125"):
                return httpx.Response(524, json={})  # Cloudflare-timeout classified
            return httpx.Response(200, json=_ok_page([{"ItemCode": "A1"}]))

        import modules.autocount.http_source.source as source_module

        original = source_module.HttpApiClient
        source_module.HttpApiClient = lambda base_url, **kw: HttpApiClient(
            base_url, transport=_transport(handler)
        )
        try:
            source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT)
            source.fetch_changes(Watermark())
        finally:
            source_module.HttpApiClient = original

        assert source.source_page_size == 62, (
            f"expected the walk to land on 62 after two halvings from a "
            f"configured 250, got {source.source_page_size!r}"
        )
        served_sizes = [c.url.params.get("pageSize") for c in calls]
        assert "250" in served_sizes and "125" in served_sizes and "62" in served_sizes
    finally:
        db.close()


# ── 6. connection save-time validation for the two new fields ───────────────


def _login_headers(client) -> Dict[str, str]:
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


AUTOCOUNT_OPEN_PAYLOAD = {
    "provider": "autocount",
    "name": "Mocha REST sizing",
    "config": {"auth": "none", "baseUrl": BASE_URL},
    "credentials": {},
}


@pytest.mark.parametrize("page_size", ["49", "1001"])
def test_connection_rejects_page_size_out_of_range(client, page_size):
    headers = _login_headers(client)
    payload = {
        **AUTOCOUNT_OPEN_PAYLOAD,
        "config": {**AUTOCOUNT_OPEN_PAYLOAD["config"], "pageSize": page_size},
    }
    res = client.post("/integrations/connections", json=payload, headers=headers)
    assert res.status_code == 422, res.text
    assert "pagesize" in res.json()["detail"].lower()


def test_connection_rejects_request_timeout_over_max(client):
    headers = _login_headers(client)
    payload = {
        **AUTOCOUNT_OPEN_PAYLOAD,
        "config": {**AUTOCOUNT_OPEN_PAYLOAD["config"], "requestTimeoutSeconds": "101"},
    }
    res = client.post("/integrations/connections", json=payload, headers=headers)
    assert res.status_code == 422, res.text
    assert "requesttimeoutseconds" in res.json()["detail"].lower()
