"""SS-STOCK-BAL-SOOTHE - a gentle stock balance sync
(``documentation/plans/sprint-5/ss-stock-bal-soothe.md``).

AC-1 page pause, AC-2 1 h stock lookup cache, AC-3 connection settings.
Every scheduled stock run still walks the balance endpoint in full (owner
26 Nov: no skip on "no document changed"). Rig mirrors
``test_s13_stock_reconcile_delete.py`` (``HttpApiClient`` monkeypatched to a
``MockTransport``).
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT, ENTITY_STOCK_BALANCE
from modules.autocount.models import (
    RUN_MODE_INCREMENTAL,
    RUN_MODE_MANUAL,
    RUN_SUCCESS,
    AcCompany,
    AcEntityConfig,
    AcSyncRun,
)
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark

BASE_URL = "https://autocount-wrapper.example.com/api/db3"

BALANCE_PATH = "/itembatchbalqtybypage"
ITEM_LOOKUP = {
    "path": "/itembypage",
    "as": "item",
    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
    "fields": [{"remote": "BaseUOM", "as": "ItemBaseUOM"}],
}


# ── rig ────────────────────────────────────────────────────────────────────


def _open_connection(db, **extra: Any) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db3 REST",
        config_json={"baseUrl": BASE_URL, "auth": "none", **extra},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="DB3",
        company_name="Db3", name="Db3", is_active=True, sorento_company_code="DB3",
    )
    db.add(company)
    db.flush()
    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()
    db.refresh(company)
    return company


def _stock_config(db, company, conn, *, lookups=None, entity_type=ENTITY_STOCK_BALANCE) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl="autocount_http",
        source_config={
            "connectionId": conn.id,
            "path": BALANCE_PATH,
            "keyFields": ["ItemCode", "Location"],
            "watermarkField": None,
            "comparedFields": [],
            "distinctOf": None,
            "lookups": lookups or [],
            "combine": None,
            "incrementalMinutes": 5,
            "reconcileMode": "dailyAt",
            "reconcileAt": "02:00",
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


def _envelope(rows, *, page: int, total_pages: int, total: int) -> Dict[str, Any]:
    return {"TotalCount": total, "Page": page, "PageSize": 1000, "TotalPages": total_pages, "Data": rows}


class Server:
    """A fake wrapper: a 3-page balance endpoint and a 2-page item lookup."""

    def __init__(self) -> None:
        self.calls: List[httpx.Request] = []

    def count(self, suffix: str) -> int:
        return sum(1 for r in self.calls if r.url.path.endswith(suffix))

    def walks(self, suffix: str) -> int:
        """Full walks of an endpoint = its page-1 requests."""
        return sum(
            1 for r in self.calls
            if r.url.path.endswith(suffix) and r.url.params.get("page") == "1"
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        page = int(request.url.params.get("page", "1"))
        if path.endswith(BALANCE_PATH):
            rows = [{"ItemCode": f"I{page}", "Location": "HQ", "BalQty": page}]
            return httpx.Response(200, json=_envelope(rows, page=page, total_pages=3, total=3))
        if path.endswith("/itembypage"):
            codes = (1, 2) if page == 1 else (3,)
            rows = [{"ItemCode": f"I{n}", "BaseUOM": "UNIT"} for n in codes]
            return httpx.Response(200, json=_envelope(rows, page=page, total_pages=2, total=3))
        return httpx.Response(404)


@pytest.fixture
def server(monkeypatch):
    import modules.autocount.http_source.source as source_module
    from modules.autocount.http_source.client import HttpApiClient

    srv = Server()
    # A fresh mock client per source: ``source.close()`` closes its own.
    monkeypatch.setattr(
        source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(
            base_url, transport=httpx.Client(transport=httpx.MockTransport(srv.handler)),
            auth_headers=kw.get("auth_headers"),
        ),
    )
    return srv


@pytest.fixture
def pauses(monkeypatch):
    import modules.autocount.http_source.gentle as gentle

    recorded: List[float] = []
    monkeypatch.setattr(
        gentle, "sleep_between_pages",
        lambda seconds, **_kw: recorded.append(seconds) or True,
    )
    return recorded


def _source(db, company, config, *, mode=RUN_MODE_INCREMENTAL):
    from modules.autocount.http_source.source import HttpApiSource

    return HttpApiSource(_ctx(db, company, config), entity_type=config.entity_type, mode=mode)


# ── AC-3: connection settings ──────────────────────────────────────────────


def test_gentle_settings_defaults_for_a_connection_without_the_keys():
    from modules.autocount.http_source.gentle import gentle_settings

    s = gentle_settings({"baseUrl": BASE_URL, "auth": "none"})
    # SS-STOCK-PAGE-PAUSE-CONFIG (owner 27 Nov): the pause default is 0.
    assert s.page_pause_seconds == 0.0
    assert s.lookup_cache_minutes == 60


def test_gentle_settings_read_and_clamp_stored_values():
    from modules.autocount.http_source.gentle import gentle_settings

    s = gentle_settings({"pagePauseSeconds": "1.5", "lookupCacheMinutes": "0"})
    assert (s.page_pause_seconds, s.lookup_cache_minutes) == (1.5, 0)
    junk = gentle_settings({"pagePauseSeconds": "9999", "lookupCacheMinutes": "x"})
    assert junk.page_pause_seconds == 90.0
    assert junk.lookup_cache_minutes == 60


def test_provider_exposes_and_validates_the_new_fields():
    from modules.autocount.provider import AutoCountProvider

    provider = AutoCountProvider()
    fields = {f["key"]: f for f in provider.fields()}
    for key in ("pagePauseSeconds", "lookupCacheMinutes"):
        assert key in fields, key
        assert fields[key]["showWhen"] == {"field": "auth", "values": ["none"]}
    for key in ("stockSkipWhenUnchanged", "stockFullWalkMinutes"):
        assert key not in fields, "owner 26 Nov: no skip setting"
    base = {"baseUrl": "", "auth": "none"}
    assert provider.validate_config({**base, "pagePauseSeconds": "91"})
    assert provider.validate_config({**base, "pagePauseSeconds": "abc"})
    assert provider.validate_config({**base, "lookupCacheMinutes": "-1"})
    assert provider.validate_config({**base, "lookupCacheMinutes": "1441"})
    assert provider.validate_config(
        {**base, "pagePauseSeconds": "1.5", "lookupCacheMinutes": "60"}
    ) is None


# ── AC-1: pause between pages ──────────────────────────────────────────────


def test_walk_pauses_between_pages_only(session_factory, server, pauses):
    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="1")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)

    _source(db, company, config).fetch_changes(Watermark())

    assert server.count(BALANCE_PATH) == 3
    assert pauses == [1.0, 1.0], "two gaps between three pages, none before page 1"


def test_lookup_walks_are_not_paused(session_factory, server, pauses):
    """A cache-miss run must still fit the 5-minute tick: only the balance
    walk is spread out."""
    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="1")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])

    _source(db, company, config).fetch_changes(Watermark())

    assert server.count("/itembypage") == 2
    assert pauses == [1.0, 1.0], "only the 3-page balance walk pauses"
    db.close()


def test_pause_zero_switches_it_off(session_factory, server, pauses):
    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="0")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)

    _source(db, company, config).fetch_changes(Watermark())

    assert server.count(BALANCE_PATH) == 3
    assert pauses == []
    db.close()


# ── AC-2: lookup cache ─────────────────────────────────────────────────────


def test_stock_lookup_is_reused_inside_the_ttl_and_walked_again_after(session_factory, server, monkeypatch):
    import modules.autocount.http_source.gentle as gentle

    clock = {"now": 1000.0}
    monkeypatch.setattr(gentle, "_monotonic", lambda: clock["now"])
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])

    first = _source(db, company, config).fetch_changes(Watermark())
    assert server.walks("/itembypage") == 1
    clock["now"] += 30 * 60
    second = _source(db, company, config).fetch_changes(Watermark())
    assert server.walks("/itembypage") == 1, "inside 60 min the lookup is not walked again"
    assert [r.raw.get("ItemBaseUOM") for r in second.records] == ["UNIT"] * 3
    assert second.walk_verified == first.walk_verified is True

    clock["now"] += 31 * 60
    _source(db, company, config).fetch_changes(Watermark())
    assert server.walks("/itembypage") == 2, "after the TTL the lookup is walked again"
    db.close()


def test_lowering_the_ttl_takes_effect_on_the_next_run(session_factory, server, monkeypatch):
    import modules.autocount.http_source.gentle as gentle

    clock = {"now": 1000.0}
    monkeypatch.setattr(gentle, "_monotonic", lambda: clock["now"])
    db = session_factory()
    conn = _open_connection(db, lookupCacheMinutes="1440")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])

    _source(db, company, config).fetch_changes(Watermark())
    clock["now"] += 20 * 60
    conn.config_json = {**conn.config_json, "lookupCacheMinutes": "15"}
    db.commit()
    _source(db, company, config).fetch_changes(Watermark())
    assert server.walks("/itembypage") == 2
    db.close()


def test_a_manual_run_refreshes_the_cache_for_the_next_scheduled_run(session_factory, server):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])

    _source(db, company, config, mode=RUN_MODE_MANUAL).fetch_changes(Watermark())
    _source(db, company, config).fetch_changes(Watermark())
    assert server.walks("/itembypage") == 1, "the scheduled run reuses the manual run's walk"
    db.close()


def test_manual_run_and_other_entities_never_use_the_cache(session_factory, server):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])
    product = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP], entity_type=ENTITY_PRODUCT)

    _source(db, company, config).fetch_changes(Watermark())
    _source(db, company, config, mode=RUN_MODE_MANUAL).fetch_changes(Watermark())
    assert server.walks("/itembypage") == 2, "a manual run reads fresh lookups"
    _source(db, company, product).fetch_changes(Watermark())
    _source(db, company, product).fetch_changes(Watermark())
    assert server.walks("/itembypage") == 4, "only stock_balance lookups are cached"
    db.close()


def test_cache_off_when_minutes_is_zero(session_factory, server):
    db = session_factory()
    conn = _open_connection(db, lookupCacheMinutes="0")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])

    _source(db, company, config).fetch_changes(Watermark())
    _source(db, company, config).fetch_changes(Watermark())
    assert server.walks("/itembypage") == 2
    db.close()


# ── owner 26 Nov: every scheduled stock run walks in full ───────────────


def _run_job(db, company, *, mode=RUN_MODE_INCREMENTAL):
    from app.jobs.service import JobService
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_STOCK_BALANCE, "mode": mode},
    )
    run_autocount_sync(db, job)
    return db.query(AcSyncRun).filter(AcSyncRun.job_id == job.id).one()


def test_every_scheduled_stock_run_walks_the_balances_lookups_cached(session_factory, server, pauses):
    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="1")
    company = _company(db, conn.id)
    _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])

    first = _run_job(db, company)
    second = _run_job(db, company)

    assert server.count(BALANCE_PATH) == 6, "both runs walk all 3 balance pages"
    assert server.walks("/itembypage") == 1, "the second run reuses the lookup"
    assert first.outcome == second.outcome == RUN_SUCCESS
    assert first.mode == second.mode == RUN_MODE_INCREMENTAL
    assert pauses == [1.0] * 4
    db.close()
