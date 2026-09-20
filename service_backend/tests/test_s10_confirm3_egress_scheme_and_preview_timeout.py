"""Sprint-5/10 review round "confirm-3" - two findings the Opus merge-gate
review of range ``7660251a..17dc2c61`` closed:

B1  The AutoCount open-REST egress guard
    (``modules.autocount.http_client.assert_autocount_base_url_deliverable``)
    delegates to the house guard's https-only ``assert_deliverable``, even
    though ``provider.py``'s own save-time message and Test-time message
    used to say "must start with http:// or https://" - a genuinely public
    plain-http AutoCount wrapper 422s at both save and every request, which
    the provider's own copy contradicted. OWNER RULING (2026-09-20,
    overriding this round's own initial http-allowed draft): stay
    https-ONLY outside the one development loopback carve-out - a bare
    ``localhost``/``127.0.0.0/8`` host is allowed http in
    ``ENVIRONMENT=development`` only; a metadata address
    (``169.254.169.254``) is refused everywhere regardless of scheme or
    environment. The fix instead corrects the CONTRADICTION the other way:
    ``provider.py``'s two operator-facing messages now say "must start with
    https://" - the wizard never advertises a scheme that 422s. See
    BL-SS-241 (new, High) for the ops consequence: an existing ``http://``
    AutoCount connection outside the dev carve-out now fails every walk.
S1  ``http_source/preview.py``'s ``run_http_preview`` built its
    ``HttpApiClient`` with NO ``timeout_seconds`` at all, silently falling
    back to the bare module default (``DEFAULT_TIMEOUT_SECONDS``) - a
    preview against a connection with its own, larger
    ``requestTimeoutSeconds`` (AC-10-85) timed out at the smaller default
    even though a REAL run against the same connection would have used the
    connection's own value. Both ``EtlService.preview_http`` and
    ``EtlService.preview_http_columns`` (the Source tab's Test button and
    the lookup editor's column probe) now read the connection's own sizing
    via the SAME ``http_source.client.connection_sizing`` helper
    ``HttpApiSource.__init__`` uses for a real run.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

PUBLIC_HTTP_URL = "http://autocount.acme.com:8080/api"
PUBLIC_HTTPS_URL = "https://hapi.sorento.cc.cd/api/db2"
PRIVATE_RANGE_HTTP_URL = "http://192.168.1.50:5000/api"
METADATA_HTTP_URL = "http://169.254.169.254/latest/meta-data"
LOCAL_HTTP_URL = "http://localhost:8011/api"


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


def _production(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")


def _development(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "development")


def _login_headers(client) -> Dict[str, str]:
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


AUTOCOUNT_OPEN_PAYLOAD = {
    "provider": "autocount",
    "name": "confirm-3 egress scheme",
    "config": {"auth": "none", "baseUrl": PUBLIC_HTTPS_URL},
    "credentials": {},
}


def _save_connection(client, base_url: str):
    headers = _login_headers(client)
    payload = {
        **AUTOCOUNT_OPEN_PAYLOAD,
        "config": {**AUTOCOUNT_OPEN_PAYLOAD["config"], "baseUrl": base_url},
    }
    return client.post("/integrations/connections", json=payload, headers=headers)


# ── B1: https-only outside the development loopback carve-out ──────────────


def test_a_public_http_base_url_is_refused_at_save(client, monkeypatch):
    """Owner ruling: a genuinely PUBLIC host (``getaddrinfo`` stubbed to a
    public IP by the ``N1`` fixture) on plain ``http://`` is refused at
    save, 422 naming ``baseUrl``, the message pointing at ``https://``."""
    _production(monkeypatch)
    res = _save_connection(client, PUBLIC_HTTP_URL)
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert "baseurl" in detail.lower()
    assert "https" in detail.lower()


def test_provider_validate_config_message_no_longer_advertises_http():
    """Pins the EXACT wording change (owner ruling): the old text ("must
    start with http:// or https://") technically contained the substring
    "https" too, so the save-route test above cannot by itself prove the
    message changed - this checks the provider's own hook directly against
    an obviously-bad scheme, where old vs new text differs."""
    from modules.autocount.provider import AutoCountProvider

    message = AutoCountProvider().validate_config(
        {"auth": "none", "baseUrl": "ftp://autocount.acme.com/api"}
    )
    assert message == "The base URL must start with https://.", (
        f"expected the https-only message, got: {message!r}"
    )
    assert "or http" not in (message or "").lower()


def test_provider_test_message_no_longer_advertises_http():
    from modules.autocount.provider import AutoCountProvider

    result = AutoCountProvider().test(
        {"auth": "none", "baseUrl": "ftp://autocount.acme.com/api"}, {}
    )
    assert result.ok is False
    assert result.message == "The base URL must start with https://.", (
        f"expected the https-only message, got: {result.message!r}"
    )
    assert "or http" not in result.message.lower()


def test_a_public_https_base_url_still_saves_control(client, monkeypatch):
    """CONTROL - https on a public host is unaffected by this ruling."""
    _production(monkeypatch)
    res = _save_connection(client, PUBLIC_HTTPS_URL)
    assert res.status_code in (200, 201), res.text


def test_a_private_range_http_base_url_is_refused_outside_development(client, monkeypatch):
    _production(monkeypatch)
    res = _save_connection(client, PRIVATE_RANGE_HTTP_URL)
    assert res.status_code == 422, res.text
    assert "baseurl" in res.json()["detail"].lower()


@pytest.mark.parametrize("environment", ["production", "development"])
def test_a_metadata_http_base_url_is_refused_in_every_environment(client, monkeypatch, environment):
    monkeypatch.setattr(settings, "environment", environment)
    res = _save_connection(client, METADATA_HTTP_URL)
    assert res.status_code == 422, res.text
    assert "baseurl" in res.json()["detail"].lower()


def test_a_local_http_wrapper_is_refused_in_production(client, monkeypatch):
    _production(monkeypatch)
    res = _save_connection(client, LOCAL_HTTP_URL)
    assert res.status_code == 422, res.text
    assert "baseurl" in res.json()["detail"].lower()


def test_a_local_http_wrapper_is_accepted_only_in_development(client, monkeypatch):
    _development(monkeypatch)
    res = _save_connection(client, LOCAL_HTTP_URL)
    assert res.status_code in (200, 201), res.text


def _ctx(db, company, config) -> SourceContext:
    return SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )


def _walk_connection(db, base_url: str, *, calls: List[httpx.Request]) -> None:
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.http_source.source import HttpApiSource
    import modules.autocount.http_source.source as source_module

    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="confirm-3 walk",
        config_json={"baseUrl": base_url, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)

    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name="MOCHA",
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http",
        source_config={
            "connectionId": conn.id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": None, "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [],
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"TotalCount": 1, "Page": 1, "PageSize": 1, "TotalPages": 1,
                  "Data": [{"ItemCode": "A1"}]},
        )

    original = source_module.HttpApiClient
    source_module.HttpApiClient = lambda base_url, **kw: HttpApiClient(
        base_url, transport=httpx.Client(transport=httpx.MockTransport(handler))
    )
    try:
        source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT)
        source.fetch_changes(Watermark())
    finally:
        source_module.HttpApiClient = original


def test_a_public_http_base_url_is_refused_before_any_request_on_a_walk(db, monkeypatch):
    """Owner ruling - a walk against a PUBLIC http:// baseUrl is refused
    with a named failure, and the transport is never touched at all (the
    SAME shape as the existing private-target walk refusal in
    test_s10_s6_security_fixes.py)."""
    from modules.autocount.http_source.errors import HttpSourceError

    _production(monkeypatch)
    calls: List[httpx.Request] = []
    with pytest.raises(HttpSourceError) as excinfo:
        _walk_connection(db, PUBLIC_HTTP_URL, calls=calls)
    assert calls == [], "a refused http:// base URL still reached the transport"
    assert "baseurl" in str(excinfo.value).lower()
    assert "https" in str(excinfo.value).lower()


def test_a_public_https_base_url_still_walks_control(db, monkeypatch):
    """CONTROL for the walk path - https on a public host is unaffected."""
    _production(monkeypatch)
    calls: List[httpx.Request] = []
    _walk_connection(db, PUBLIC_HTTPS_URL, calls=calls)
    assert calls, "a public https:// base URL never reached the transport"


# ── S1: preview honours the connection's own requestTimeoutSeconds ─────────


def _open_page(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"TotalCount": len(rows), "Page": 1, "PageSize": len(rows) or 1, "TotalPages": 1, "Data": rows}


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_run_http_preview_builds_its_client_with_the_given_timeout(monkeypatch):
    from modules.autocount.http_source.client import HttpApiClient
    import modules.autocount.http_source.preview as preview_module

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_open_page([{"ItemCode": "A1"}]))

    captured: Dict[str, Any] = {}

    class _SpyClient:
        def __init__(self, base_url, *, transport: Optional[httpx.Client] = None, timeout_seconds=None):
            captured["timeout_seconds"] = timeout_seconds
            self._real = HttpApiClient(base_url, transport=transport, timeout_seconds=timeout_seconds)

        def get(self, *args, **kwargs):
            return self._real.get(*args, **kwargs)

        def close(self):
            self._real.close()

    monkeypatch.setattr(preview_module, "HttpApiClient", _SpyClient)

    preview_module.run_http_preview(
        "https://hapi.sorento.cc.cd/api/db2", "/itembypage",
        transport=_transport(handler), timeout_seconds=33.0,
    )

    assert captured.get("timeout_seconds") == 33.0, (
        f"run_http_preview did not pass its own timeout_seconds through to "
        f"HttpApiClient; captured: {captured!r}"
    )


def test_run_http_preview_defaults_to_90_seconds_when_no_timeout_is_given(monkeypatch):
    from modules.autocount.http_source.client import DEFAULT_TIMEOUT_SECONDS, HttpApiClient
    import modules.autocount.http_source.preview as preview_module

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_open_page([{"ItemCode": "A1"}]))

    captured: Dict[str, Any] = {}

    class _SpyClient:
        def __init__(self, base_url, *, transport: Optional[httpx.Client] = None, timeout_seconds=None):
            captured["timeout_seconds"] = timeout_seconds
            self._real = HttpApiClient(base_url, transport=transport, timeout_seconds=timeout_seconds)

        def get(self, *args, **kwargs):
            return self._real.get(*args, **kwargs)

        def close(self):
            self._real.close()

    monkeypatch.setattr(preview_module, "HttpApiClient", _SpyClient)

    preview_module.run_http_preview(
        "https://hapi.sorento.cc.cd/api/db2", "/itembypage", transport=_transport(handler),
    )

    assert captured.get("timeout_seconds") == DEFAULT_TIMEOUT_SECONDS == 90.0


def _open_connection(db, *, timeout_seconds: str) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="confirm-3 preview timeout",
        config_json={"baseUrl": PUBLIC_HTTPS_URL, "auth": "none", "requestTimeoutSeconds": timeout_seconds},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def test_preview_http_passes_the_connections_own_timeout_through(db, monkeypatch):
    from modules.autocount.services.etl_service import EtlService
    import modules.autocount.services.etl_service as etl_service_module

    conn = _open_connection(db, timeout_seconds="33")

    captured: Dict[str, Any] = {}
    real_run_http_preview = etl_service_module.run_http_preview

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        return real_run_http_preview(*args, **kwargs)

    monkeypatch.setattr(etl_service_module, "run_http_preview", _spy)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_open_page([{"ItemCode": "A1"}]))

    EtlService(db).preview_http(
        DEFAULT_TENANT_ID, conn.id, "/itembypage", transport=_transport(handler),
    )

    assert captured.get("timeout_seconds") == 33.0, (
        f"EtlService.preview_http did not pass the connection's own "
        f"requestTimeoutSeconds through to run_http_preview; captured: "
        f"{captured!r}"
    )


def test_preview_http_columns_passes_the_connections_own_timeout_through(db, monkeypatch):
    from modules.autocount.services.etl_service import EtlService
    import modules.autocount.services.etl_service as etl_service_module

    conn = _open_connection(db, timeout_seconds="33")

    captured: Dict[str, Any] = {}
    real_run_http_preview = etl_service_module.run_http_preview

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        return real_run_http_preview(*args, **kwargs)

    monkeypatch.setattr(etl_service_module, "run_http_preview", _spy)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_open_page([{"ItemCode": "A1"}]))

    EtlService(db).preview_http_columns(
        DEFAULT_TENANT_ID, conn.id, "/itembypage", transport=_transport(handler),
    )

    assert captured.get("timeout_seconds") == 33.0, (
        f"EtlService.preview_http_columns did not pass the connection's own "
        f"requestTimeoutSeconds through to run_http_preview; captured: "
        f"{captured!r}"
    )


def test_preview_http_falls_back_to_90_when_the_connection_has_no_timeout(db, monkeypatch):
    from modules.autocount.http_source.client import DEFAULT_TIMEOUT_SECONDS
    from modules.autocount.services.etl_service import EtlService
    import modules.autocount.services.etl_service as etl_service_module

    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="confirm-3 preview default",
        config_json={"baseUrl": PUBLIC_HTTPS_URL, "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)

    captured: Dict[str, Any] = {}
    real_run_http_preview = etl_service_module.run_http_preview

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        return real_run_http_preview(*args, **kwargs)

    monkeypatch.setattr(etl_service_module, "run_http_preview", _spy)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_open_page([{"ItemCode": "A1"}]))

    EtlService(db).preview_http(
        DEFAULT_TENANT_ID, conn.id, "/itembypage", transport=_transport(handler),
    )

    assert captured.get("timeout_seconds") == DEFAULT_TIMEOUT_SECONDS == 90.0
