"""Sprint-5/10 S1 review round 1 (Opus reviewer) - NITS.

1. The timeout counter (AC-10-75) must count TIMEOUTS of the SAME page
   only - a 5xx followed by ONE timeout must not halve (only a SECOND
   consecutive timeout does).
2. Seeded preset lookups are ``copy.deepcopy``'d - the stored ``on``/
   ``fields`` lists must never alias the module-level preset's own objects.
3. A drift assert that ``USER_AGENT``'s version equals ``manifest.json``'s.
4. AC-10-07 where the source price is the STRING ``"0"`` (not the float).
5. A preview-count test that includes a MISSED row (the pre-existing one
   only ever has a matching row).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.mapping import MappingEngine, MappingRow, flat_profile
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.presets import PRODUCT_HTTP_PRESET
from modules.autocount.services.company_service import CompanyService
from modules.autocount.services.etl_service import EtlService
from modules.autocount.sources import SourceContext, Watermark

from modules.autocount.http_source.client import USER_AGENT
from modules.autocount.http_source.source import HttpApiSource

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"


# ── nit 1: a 5xx then ONE timeout must not halve ─────────────────────────────


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
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


def _ok_page(rows) -> Dict[str, Any]:
    return {"TotalCount": len(rows), "Page": 1, "PageSize": len(rows) or 1, "TotalPages": 1, "Data": rows}


def test_a_5xx_then_one_timeout_never_halves(rig):
    db, company, conn = rig
    config = _config(db, company, conn.id)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(500, text="boom")
        if len(calls) == 2:
            raise httpx.ReadTimeout("boom", request=request)
        return httpx.Response(200, json=_ok_page([{"ItemCode": "A1", "LastModified": "2026-08-01T09:00:00"}]))

    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )
    source = HttpApiSource(ctx, entity_type=ENTITY_PRODUCT, transport=_transport(handler))
    result = source.fetch_changes(Watermark())
    assert len(result.records) == 1
    assert len(calls) == 3, "a 500, then one timeout, then success - no halving involved"
    page_sizes = {c.url.params.get("pageSize") for c in calls}
    assert page_sizes == {"1000"}, f"a single timeout after an unrelated 5xx must never halve: {page_sizes}"


# ── nit 2: seeded preset lookups are deep-copied, never aliased ─────────────


def _http_raw(**overrides: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": "autocount_http",
        "connectionId": None,
        "path": "/itembypage",
        "keyFields": ["ItemCode"],
        "watermarkField": "LastModified",
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }
    raw.update(overrides)
    return raw


def test_seeded_lookups_never_alias_the_module_level_preset(rig, monkeypatch):
    """A JSON column round-trip (commit + refresh) always deserializes into
    FRESH Python objects regardless of whether the write used a shallow or
    a deep copy - masking the aliasing bug the moment either happens. This
    pins it at the ONLY place it is actually observable: the in-memory
    object ``_update_http_task`` itself builds, BEFORE that round trip
    (``commit``/``refresh`` monkeypatched to no-ops so the session's
    identity map keeps returning the SAME un-reloaded instance)."""
    db, company, conn = rig
    monkeypatch.setattr(db, "commit", lambda: None)
    monkeypatch.setattr(db, "refresh", lambda instance: None)

    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id)
    )
    config = EtlService(db).configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    seeded_lookups = config.source_config.get("lookups")
    assert seeded_lookups, "the first save must have seeded the preset's ItemUOM lookup"
    seeded_on = seeded_lookups[0]["on"]
    preset_on = PRODUCT_HTTP_PRESET.lookups[0]["on"]
    assert seeded_on == preset_on
    assert seeded_on is not preset_on, "the seeded 'on' list must not be the SAME object as the preset's"

    # Mutating the SEEDED copy must never touch the module-level preset.
    seeded_on.append({"local": "X", "remote": "Y"})
    assert PRODUCT_HTTP_PRESET.lookups[0]["on"] == preset_on, (
        "mutating one tenant's seeded lookup corrupted the shared module-level preset"
    )
    assert len(PRODUCT_HTTP_PRESET.lookups[0]["on"]) == 2


# ── nit 3: USER_AGENT version drift vs manifest.json ─────────────────────────


def test_user_agent_version_matches_manifest_json():
    manifest_path = Path(__file__).resolve().parents[1] / "modules" / "autocount" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    expected = f"Foundryx-AutoCount-ESB/{manifest['version']}"
    assert USER_AGENT == expected, (
        f"USER_AGENT ({USER_AGENT!r}) has drifted from manifest.json's version "
        f"({manifest['version']!r}) - bump USER_AGENT alongside it"
    )


# ── nit 4: AC-10-07, source price is the STRING "0" ──────────────────────────


def _engine() -> MappingEngine:
    rows = [
        MappingRow(
            source_path=f.source_path,
            canonical_field=f.canonical_field,
            transform=f.transform,
            formula=f.formula,
            is_required=f.required,
            is_enabled=f.enabled,
        )
        for f in PRODUCT_HTTP_PRESET.rows
    ]
    profile = flat_profile(ENTITY_PRODUCT, list(PRODUCT_HTTP_PRESET.key_fields))
    return MappingEngine(rows, entity_type=ENTITY_PRODUCT, profile=profile, database_name="AED_SORENTO")


def _raw(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "ItemCode": "SRT-01", "Description": "WIDGET", "Desc2": None,
        "ItemGroup": "GRP1", "ItemBrand": "BR1", "BaseUOM": "UNIT",
        "IsActive": "T", "Discontinued": "F", "BaseUOMPrice": 10.0,
    }
    base.update(overrides)
    return base


def test_list_price_source_is_the_string_zero():
    mapped = _engine().map_document(_raw(BaseUOMPrice="0"))
    assert mapped.ok, mapped.errors
    payload = mapped.record.sink_payload()
    assert payload.get("list_price") == "0.0", payload


# ── nit 5: preview per-lookup counts including a MISSED row ──────────────────


@pytest.fixture
def headers(client):
    response = client.post(
        "/auth/login", json={"email": "demo@example.com", "password": "demo1234"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _multi_transport(pages_by_path: Dict[str, Any]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        match = next((p for p in pages_by_path if request.url.path.endswith(p)), None)
        if match is None:
            return httpx.Response(404, text=f"no fixture for {request.url.path}")
        return httpx.Response(200, json=pages_by_path[match])

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_preview_counts_a_row_that_misses_the_lookup(client, headers, db):
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    app.dependency_overrides[get_http_transport] = lambda: _multi_transport({
        "/itembypage": {
            "TotalCount": 2, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [
                {"ItemCode": "SRT-01", "BaseUOM": "UNIT"},
                {"ItemCode": "SRT-02", "BaseUOM": "EA"},
            ],
        },
        "/itemuombypage": {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            # Only SRT-01 has a matching ItemUOM row - SRT-02 misses.
            "Data": [{"ItemCode": "SRT-01", "UOM": "UNIT", "Price": 5.0}],
        },
    })
    try:
        response = client.post(
            "/autocount/http/preview",
            json={
                "connectionId": conn.id, "path": "/itembypage",
                "lookups": [{
                    "path": "/itemuombypage", "as": "uom",
                    "on": [
                        {"local": "ItemCode", "remote": "ItemCode"},
                        {"local": "BaseUOM", "remote": "UOM", "match": "casefold_trim"},
                    ],
                    "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
                }],
            },
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    assert response.status_code == 200, response.text
    body = response.json()
    lookup_counts = body["lookups"][0]
    assert lookup_counts["matched"] == 1, lookup_counts
    assert lookup_counts["missed"] == 1, lookup_counts
    rows_by_code = {r["ItemCode"]: r for r in body["rows"]}
    assert rows_by_code["SRT-01"].get("BaseUOMPrice") == 5.0
    assert "BaseUOMPrice" not in rows_by_code["SRT-02"]
