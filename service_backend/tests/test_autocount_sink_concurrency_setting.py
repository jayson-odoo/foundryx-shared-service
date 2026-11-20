"""Per-connection Sorento push concurrency (feat/sink-concurrency-ui).

The operator runs 2 during a backlog drain and sets it back to 1 afterwards
from Settings > Integrations > the Sorento connection - no deploy.

Contract:
* ``SorentoProvider.fields()`` gains a select ``sinkConcurrency``
  (``SINK_CONCURRENCY_KEY``), options "1".."4" labelled "1 (sequential)",
  "2", "3", "4", NO stored default: unset means the platform default
  ``settings.autocount_sink_concurrency``. The field carries the platform
  default as ``effectiveValue`` so the form's read mode / edit prefill can
  show what the connection actually runs at (the frontend's
  ``storedOrEffective`` falls back to it).
* ``SorentoSink`` (built through ``sorento_sink_from_connection``) resolves
  concurrency = connection config if present and valid, else settings;
  clamped to 1..4 and to ``len(chunks)``. An invalid stored value ("0",
  "9", "abc", None) falls back to settings and logs ONE warning per sink
  instance, never raises. ``write_batch`` and ``delete_batch`` both honour
  it; ``dry_run`` is unchanged.
* There is NO provider-level config validation hook on the connection PATCH
  today (``IntegrationProvider`` exposes ``fields``/``test`` only), so an
  out-of-range value is pinned at the sink-side fallback here.
* Tenant scoping: ``sink_for_company`` reads the tenant's own connection
  row; a connection owned by another tenant is never used.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.masters import CanonicalSupplier
from modules.autocount.sinks_sorento import sorento_sink_from_connection

SINK_CONCURRENCY_KEY = "sinkConcurrency"


def _suppliers(n: int) -> List[CanonicalSupplier]:
    return [
        CanonicalSupplier(source_ref=f"AED:{i}", source_doc_no=f"C{i}", code=f"C{i}", name="N", is_active=True)
        for i in range(n)
    ]


def _ok(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if request.url.path.endswith("/deletions"):
        refs = body["source_refs"]
        return httpx.Response(200, json={
            "summary": {"total": len(refs), "deleted": len(refs), "deactivated": 0,
                        "not_found": 0, "failed": 0, "retryable": 0},
            "records": [{"source_ref": r, "outcome": "deleted"} for r in refs],
        })
    recs = [
        {"source_ref": r["source_ref"], "outcome": "created", "entity_id": f"id-{r['source_ref']}"}
        for r in body["records"]
    ]
    return httpx.Response(200, json={
        "summary": {"total": len(recs), "created": len(recs), "updated": 0, "failed": 0, "retryable": 0},
        "records": recs,
    })


@pytest.fixture
def executor_spy(monkeypatch) -> List[Optional[int]]:
    """Record every ``ThreadPoolExecutor(max_workers=...)`` the sink opens;
    a sequential push opens none."""
    import modules.autocount.sinks_sorento as sink_module

    real = sink_module.ThreadPoolExecutor
    seen: List[Optional[int]] = []

    class Spy(real):  # type: ignore[misc,valid-type]
        def __init__(self, max_workers=None, *args, **kwargs):
            seen.append(max_workers)
            super().__init__(max_workers, *args, **kwargs)

    monkeypatch.setattr(sink_module, "ThreadPoolExecutor", Spy)
    return seen


@pytest.fixture
def platform_default(monkeypatch) -> int:
    monkeypatch.setattr(settings, "autocount_sink_concurrency", 1)
    monkeypatch.setattr(settings, "autocount_sink_batch_size", 2)
    return 1


def _sink(config: Dict[str, Any]):
    return sorento_sink_from_connection(
        {"baseUrl": "http://sorento.test", **config}, {"apiKey": "k"},
        entity_type="supplier", company_code="C1", transport=httpx.MockTransport(_ok),
    )


# ── the provider field ──────────────────────────────────────────────────────


def test_provider_exposes_the_sink_concurrency_select_without_a_stored_default():
    from modules.autocount import sorento_provider

    assert getattr(sorento_provider, "SINK_CONCURRENCY_KEY", None) == SINK_CONCURRENCY_KEY
    fields = {f["key"]: f for f in sorento_provider.SorentoProvider().fields()}
    field = fields.get(SINK_CONCURRENCY_KEY)
    assert field is not None, sorted(fields)
    assert field["type"] == "select"
    assert field.get("secret") is not True
    assert [o["value"] for o in field["options"]] == ["1", "2", "3", "4"]
    assert [o["label"] for o in field["options"]] == ["1 (sequential)", "2", "3", "4"]
    assert "defaultValue" not in field, "unset must mean the platform default, not a stored value"


def test_provider_field_carries_the_platform_default_as_the_effective_value(monkeypatch):
    """Read mode / edit prefill show what the connection RUNS at when nothing
    is stored - the platform setting, read at request time."""
    from modules.autocount import sorento_provider

    monkeypatch.setattr(settings, "autocount_sink_concurrency", 3)
    field = {f["key"]: f for f in sorento_provider.SorentoProvider().fields()}[SINK_CONCURRENCY_KEY]
    assert field.get("effectiveValue") == "3"
    monkeypatch.setattr(settings, "autocount_sink_concurrency", 1)
    field = {f["key"]: f for f in sorento_provider.SorentoProvider().fields()}[SINK_CONCURRENCY_KEY]
    assert field.get("effectiveValue") == "1"


# ── the sink resolves connection value, else settings ───────────────────────


def test_a_stored_2_runs_two_workers_on_write_batch(platform_default, executor_spy):
    sink = _sink({SINK_CONCURRENCY_KEY: "2"})
    results = sink.write_batch(_suppliers(8), request_id="t")  # 4 chunks of 2
    assert len(results) == 8 and all(r.delivered for r in results)
    assert executor_spy == [2], executor_spy


def test_a_stored_2_runs_two_workers_on_delete_batch(platform_default, executor_spy):
    sink = _sink({SINK_CONCURRENCY_KEY: "2"})
    result = sink.delete_batch([f"AED:{i}" for i in range(8)])  # 4 chunks of 2
    assert result["summary"]["deleted"] == 8
    assert executor_spy == [2], executor_spy


def test_dry_run_is_unchanged_by_the_connection_setting(platform_default, executor_spy):
    sink = _sink({SINK_CONCURRENCY_KEY: "4"})
    result = sink.dry_run(_suppliers(8))
    assert result.summary["total"] == 8
    assert executor_spy == [], "dry_run must stay sequential"


def test_unset_falls_back_to_the_platform_setting(monkeypatch, executor_spy):
    monkeypatch.setattr(settings, "autocount_sink_batch_size", 2)
    monkeypatch.setattr(settings, "autocount_sink_concurrency", 3)
    sink = _sink({})
    sink.write_batch(_suppliers(8), request_id="t")
    assert executor_spy == [3], executor_spy


def test_the_platform_setting_is_read_at_call_time_not_construction(monkeypatch, executor_spy):
    monkeypatch.setattr(settings, "autocount_sink_batch_size", 2)
    monkeypatch.setattr(settings, "autocount_sink_concurrency", 1)
    sink = _sink({})
    monkeypatch.setattr(settings, "autocount_sink_concurrency", 2)
    sink.write_batch(_suppliers(8), request_id="t")
    assert executor_spy == [2], executor_spy


@pytest.mark.parametrize("bad", ["0", "9", "abc", None, ""], ids=["zero", "nine", "abc", "none", "blank"])
def test_an_invalid_stored_value_falls_back_to_settings_and_warns_once(
    monkeypatch, executor_spy, caplog, bad
):
    monkeypatch.setattr(settings, "autocount_sink_batch_size", 2)
    monkeypatch.setattr(settings, "autocount_sink_concurrency", 3)
    with caplog.at_level(logging.WARNING, logger="foundryx.autocount"):
        sink = _sink({SINK_CONCURRENCY_KEY: bad})
        sink.write_batch(_suppliers(8), request_id="t")
        sink.write_batch(_suppliers(8), request_id="t")
    assert executor_spy == [3, 3], executor_spy
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and SINK_CONCURRENCY_KEY in r.getMessage()]
    if bad in (None, ""):
        # Absent / blank is "unset", not invalid - no warning.
        assert warnings == []
    else:
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        assert str(bad) in warnings[0].getMessage()


def test_concurrency_is_clamped_to_the_number_of_chunks(platform_default, executor_spy):
    sink = _sink({SINK_CONCURRENCY_KEY: "4"})
    sink.write_batch(_suppliers(4), request_id="t")  # 2 chunks of 2
    assert executor_spy == [2], executor_spy
    executor_spy.clear()
    sink.write_batch(_suppliers(2), request_id="t")  # 1 chunk -> sequential, no executor
    assert executor_spy == []


def test_concurrency_never_exceeds_four_even_if_settings_say_more(monkeypatch, executor_spy):
    """The config.py validator bounds the platform setting to 1..4; a value
    forced past it (an operator shell, a future validator change) is still
    clamped by the sink."""
    monkeypatch.setattr(settings, "autocount_sink_batch_size", 1)
    object.__setattr__(settings, "autocount_sink_concurrency", 8)
    try:
        sink = _sink({})
        sink.write_batch(_suppliers(8), request_id="t")  # 8 chunks
    finally:
        object.__setattr__(settings, "autocount_sink_concurrency", 1)
    assert executor_spy == [4], executor_spy


# ── tenant scoping: the tenant's own connection row ─────────────────────────


def test_sink_for_company_reads_the_setting_from_the_tenants_own_connection(
    session_factory, executor_spy, monkeypatch
):
    from app.models.connection import Connection
    from app.models.tenant import Tenant
    from app.secrets import encrypt_secret
    from modules.autocount.canonical.masters import ENTITY_SUPPLIER
    from modules.autocount.models import AcCompany
    from modules.autocount.services.company_service import AutocountServiceError, CompanyService

    monkeypatch.setattr(settings, "autocount_sink_batch_size", 2)
    monkeypatch.setattr(settings, "autocount_sink_concurrency", 1)
    db = session_factory()
    other_tenant = "tenant-other-sink-conc"
    if db.get(Tenant, other_tenant) is None:
        base = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(Tenant(id=other_tenant, slug="other-sink-conc", name="Other", status_id=base.status_id))
        db.commit()

    def connection(tenant_id: str, value: str) -> Connection:
        row = Connection(
            tenant_id=tenant_id, provider="sorento", type="consumer", name=f"Sorento {tenant_id}",
            config_json={"baseUrl": "http://sorento.test", SINK_CONCURRENCY_KEY: value},
            credentials_json=encrypt_secret({"apiKey": "k"}), is_active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    api = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="api",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "a", "password": "p"}), is_active=True,
    )
    db.add(api)
    db.commit()
    mine = connection(DEFAULT_TENANT_ID, "3")
    theirs = connection(other_tenant, "4")

    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name="AED_X",
        company_name="X", name="X", is_active=True,
        sink_impl="sorento", sink_connection_id=mine.id, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()

    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    monkeypatch.setattr(
        company_module, "sorento_sink_from_connection",
        lambda config, credentials, *, entity_type, company_code=None, transport=None: real(
            config, credentials, entity_type=entity_type, company_code=company_code,
            transport=httpx.MockTransport(_ok),
        ),
    )

    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_SUPPLIER)
    sink.write_batch(_suppliers(8), request_id="t")
    assert executor_spy == [3], executor_spy

    # A connection row owned by ANOTHER tenant is never resolved for this
    # company, whatever its id says.
    company.sink_connection_id = theirs.id
    db.commit()
    with pytest.raises(AutocountServiceError):
        CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_SUPPLIER)
    db.close()
