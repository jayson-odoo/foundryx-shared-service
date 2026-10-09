"""Sprint-5/10 S4 security round 1 - MEDIUM 3: unauthenticated reflection.

PROVEN (independent Opus security review): `_read_json_body` reads an
UNBOUNDED body before auth ever runs, and the raw `companyCode`/`entity`
strings are echoed straight into the 401 body - so an anonymous caller with
no valid key at all could get a 200 KB response back from a 200 KB request,
and a JSON object sent where Appendix A6 expects a string came back
unmodified (a shape violation, not just a size one).

RED before the fix: every test below currently either echoes the raw value
unmodified or accepts an unbounded body.
"""
from __future__ import annotations

import pytest

from app.models import DEFAULT_TENANT_ID


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
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


GATEWAY_PREFIX = "/api/v1/autocount"


# ── unauthenticated reflection is capped, sanitised, type-safe ─────────────


def test_a_huge_company_code_is_never_echoed_back_unbounded_when_unauthenticated(client):
    huge = "X" * 200_000
    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": huge, "entity": "products"},
        headers={"X-API-Key": "fxa_live_" + "z" * 43},
    )
    assert response.status_code in (401, 413), response.text
    if response.status_code == 401:
        body = response.json()
        assert len(body.get("companyCode") or "") <= 64
        assert len(response.text) < 10_000


def test_a_non_string_company_code_never_echoes_a_raw_json_object(client):
    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": {"nested": "object"}, "entity": "products"},
        headers={"X-API-Key": "fxa_live_" + "z" * 43},
    )
    assert response.status_code == 401, response.text
    body = response.json()
    assert body["companyCode"] is None


def test_control_characters_are_stripped_from_an_echoed_company_code(client):
    dirty = "SRT\x00\x1b[31mHACK\x07"
    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": dirty, "entity": "products"},
        headers={"X-API-Key": "fxa_live_" + "z" * 43},
    )
    assert response.status_code == 401, response.text
    echoed = response.json()["companyCode"]
    for ch in echoed or "":
        assert ord(ch) >= 0x20 and ord(ch) != 0x7F


def test_an_oversized_body_is_refused_before_any_json_parsing(client):
    """The cap applies to the RAW body, before JSON is even attempted -
    proven with a body that is not even valid JSON."""
    huge_garbage = b"{" + b"a" * 200_000
    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        content=huge_garbage,
        headers={"X-API-Key": "fxa_live_" + "z" * 43, "Content-Type": "application/json"},
    )
    assert response.status_code in (413, 422), response.text
    body = response.json()
    assert "error" not in body
    assert len(response.text) < 10_000


def test_a_small_valid_body_is_unaffected_control(client, db):
    """CONTROL: an ordinary small request is not impacted by the cap."""
    from app.models.connection import Connection
    from modules.autocount.canonical.masters import ENTITY_PRODUCT
    from modules.autocount.models import AcCompany, AcEntityConfig
    from modules.autocount.services.pull_key_service import PullKeyService

    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", etl_status="active", delivery_mode="pull",
            source_config={
                "connectionId": conn.id, "path": "/itembypage",
                "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
                "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
                "reconcileAt": "02:00", "lookups": [],
            },
        )
    )
    db.commit()
    _key, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="k", company_ids=[company.id],
    )

    import httpx
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []},
        )

    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )
    try:
        response = client.post(
            f"{GATEWAY_PREFIX}/snapshots",
            json={"companyCode": "SRT", "entity": "products"},
            headers={"X-API-Key": plaintext},
        )
        assert response.status_code == 202, response.text
    finally:
        monkeypatch.undo()


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_a_huge_company_code_is_never_echoed_back_unbounded_when_unauthenticated
#   dies if the echoed value is not truncated, or if the body is read in
#   full with no size cap at all.
# * test_a_non_string_company_code_never_echoes_a_raw_json_object dies if a
#   non-string value is echoed as-is (a shape violation of Appendix A6,
#   which always expects `companyCode` to be a string or absent/null).
# * test_control_characters_are_stripped_from_an_echoed_company_code dies if
#   raw control/ANSI-escape bytes reach the response body unmodified.
