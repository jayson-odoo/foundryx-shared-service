"""SS-STOCK-BAL-SOOTHE - a gentle stock balance sync
(``documentation/plans/sprint-5/ss-stock-bal-soothe.md``).

AC-1 page pause, AC-2/3 skip a scheduled stock walk when no document moved,
AC-4 1 h lookup cache, AC-5 connection settings. Rig mirrors
``test_s13_stock_reconcile_delete.py`` (``HttpApiClient`` monkeypatched to a
``MockTransport``).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT, ENTITY_STOCK_BALANCE
from modules.autocount.models import (
    RUN_MODE_INCREMENTAL,
    RUN_MODE_MANUAL,
    RUN_MODE_SKIPPED,
    RUN_SUCCESS,
    STOCK_UNCHANGED_REASON,
    AcCompany,
    AcEntityConfig,
    AcSyncRun,
)
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark

BASE_URL = "https://autocount-wrapper.example.com/api/db3"
MYT = timezone(timedelta(hours=8))

BALANCE_PATH = "/itembatchbalqtybypage"
ITEM_LOOKUP = {
    "path": "/itembypage",
    "as": "item",
    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
    "fields": [{"remote": "BaseUOM", "as": "ItemBaseUOM"}],
}
PROBE_PATHS = (
    "/deliveryorderbyLastModified",
    "/goodsreceivenotebyLastModified",
    "/salesorderbyLastModified",
    "/purchaseorderbyLastModified",
)


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
    """A fake wrapper: a 3-page balance endpoint, a 1-page item lookup, and
    the four byLastModified day doors (``docs`` per path, default empty)."""

    def __init__(self) -> None:
        self.calls: List[httpx.Request] = []
        self.docs: Dict[str, List[Dict[str, Any]]] = {p: [] for p in PROBE_PATHS}
        self.fail_probe = False

    def count(self, suffix: str) -> int:
        return sum(1 for r in self.calls if r.url.path.endswith(suffix))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        for probe in PROBE_PATHS:
            if path.endswith(probe):
                if self.fail_probe:
                    return httpx.Response(500, text="boom")
                return httpx.Response(200, json=self.docs[probe])
        page = int(request.url.params.get("page", "1"))
        if path.endswith(BALANCE_PATH):
            rows = [{"ItemCode": f"I{page}", "Location": "HQ", "BalQty": page}]
            return httpx.Response(200, json=_envelope(rows, page=page, total_pages=3, total=3))
        if path.endswith("/itembypage"):
            rows = [{"ItemCode": f"I{n}", "BaseUOM": "UNIT"} for n in (1, 2, 3)]
            return httpx.Response(200, json=_envelope(rows, page=1, total_pages=1, total=3))
        return httpx.Response(404)


@pytest.fixture
def server(monkeypatch):
    import modules.autocount.http_source.source as source_module
    from modules.autocount.http_source.client import HttpApiClient

    srv = Server()
    transport = httpx.Client(transport=httpx.MockTransport(srv.handler))
    monkeypatch.setattr(
        source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(
            base_url, transport=transport, auth_headers=kw.get("auth_headers"),
        ),
    )
    return srv


@pytest.fixture
def pauses(monkeypatch):
    import modules.autocount.http_source.gentle as gentle

    recorded: List[float] = []
    monkeypatch.setattr(gentle, "sleep_between_pages", lambda seconds: recorded.append(seconds))
    return recorded


def _source(db, company, config, *, mode=RUN_MODE_INCREMENTAL):
    from modules.autocount.http_source.source import HttpApiSource

    return HttpApiSource(_ctx(db, company, config), entity_type=config.entity_type, mode=mode)


# ── AC-5: connection settings ──────────────────────────────────────────────


def test_gentle_settings_default_on_for_a_connection_without_the_keys():
    from modules.autocount.http_source.gentle import gentle_settings

    s = gentle_settings({"baseUrl": BASE_URL, "auth": "none"})
    assert s.page_pause_seconds == 1.0
    assert s.skip_when_unchanged is True
    assert s.full_walk_minutes == 60
    assert s.lookup_cache_minutes == 60


def test_gentle_settings_read_and_clamp_stored_values():
    from modules.autocount.http_source.gentle import gentle_settings

    s = gentle_settings({
        "pagePauseSeconds": "0", "stockSkipWhenUnchanged": "no",
        "stockFullWalkMinutes": "30", "lookupCacheMinutes": "0",
    })
    assert (s.page_pause_seconds, s.skip_when_unchanged, s.full_walk_minutes, s.lookup_cache_minutes) == (
        0.0, False, 30, 0,
    )
    junk = gentle_settings({"pagePauseSeconds": "999", "stockFullWalkMinutes": "x"})
    assert junk.page_pause_seconds == 10.0
    assert junk.full_walk_minutes == 60


def test_provider_exposes_and_validates_the_new_fields():
    from modules.autocount.provider import AutoCountProvider

    provider = AutoCountProvider()
    fields = {f["key"]: f for f in provider.fields()}
    for key in ("pagePauseSeconds", "stockSkipWhenUnchanged", "stockFullWalkMinutes", "lookupCacheMinutes"):
        assert key in fields, key
        assert fields[key]["showWhen"] == {"field": "auth", "values": ["none"]}
    base = {"baseUrl": "", "auth": "none"}
    assert provider.validate_config({**base, "pagePauseSeconds": "11"})
    assert provider.validate_config({**base, "pagePauseSeconds": "abc"})
    assert provider.validate_config({**base, "stockFullWalkMinutes": "2"})
    assert provider.validate_config({**base, "lookupCacheMinutes": "-1"})
    assert provider.validate_config({**base, "stockSkipWhenUnchanged": "maybe"})
    assert provider.validate_config(
        {**base, "pagePauseSeconds": "1.5", "stockFullWalkMinutes": "60",
         "lookupCacheMinutes": "60", "stockSkipWhenUnchanged": "yes"}
    ) is None


# ── AC-1: pause between pages ──────────────────────────────────────────────


def test_walk_pauses_between_pages_only(session_factory, server, pauses):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)

    _source(db, company, config).fetch_changes(Watermark())

    assert server.count(BALANCE_PATH) == 3
    assert pauses == [1.0, 1.0], "two gaps between three pages, none before page 1"
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


# ── AC-4: lookup cache ─────────────────────────────────────────────────────


def test_stock_lookup_is_reused_inside_the_ttl_and_walked_again_after(session_factory, server, monkeypatch):
    import modules.autocount.http_source.gentle as gentle

    clock = {"now": 1000.0}
    monkeypatch.setattr(gentle, "_monotonic", lambda: clock["now"])
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])

    first = _source(db, company, config).fetch_changes(Watermark())
    assert server.count("/itembypage") == 1
    clock["now"] += 30 * 60
    second = _source(db, company, config).fetch_changes(Watermark())
    assert server.count("/itembypage") == 1, "inside 60 min the lookup is not walked again"
    assert [r.raw.get("ItemBaseUOM") for r in second.records] == ["UNIT"] * 3
    assert second.walk_verified == first.walk_verified is True

    clock["now"] += 31 * 60
    _source(db, company, config).fetch_changes(Watermark())
    assert server.count("/itembypage") == 2, "after the TTL the lookup is walked again"
    db.close()


def test_manual_run_and_other_entities_never_use_the_cache(session_factory, server):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])
    product = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP], entity_type=ENTITY_PRODUCT)

    _source(db, company, config).fetch_changes(Watermark())
    _source(db, company, config, mode=RUN_MODE_MANUAL).fetch_changes(Watermark())
    assert server.count("/itembypage") == 2, "a manual run reads fresh lookups"
    _source(db, company, product).fetch_changes(Watermark())
    _source(db, company, product).fetch_changes(Watermark())
    assert server.count("/itembypage") == 4, "only stock_balance lookups are cached"
    db.close()


def test_cache_off_when_minutes_is_zero(session_factory, server):
    db = session_factory()
    conn = _open_connection(db, lookupCacheMinutes="0")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])

    _source(db, company, config).fetch_changes(Watermark())
    _source(db, company, config).fetch_changes(Watermark())
    assert server.count("/itembypage") == 2
    db.close()


# ── AC-2/3: skip a scheduled walk when nothing moved ──────────────────────


def _prior_walk(db, company, *, started_at: datetime, entity_type=ENTITY_STOCK_BALANCE) -> None:
    db.add(AcSyncRun(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        job_id=None, mode=RUN_MODE_INCREMENTAL, outcome=RUN_SUCCESS,
        started_at=started_at, finished_at=started_at + timedelta(minutes=3), duration_ms=180000,
    ))
    db.commit()


def _run_job(db, company, *, mode=RUN_MODE_INCREMENTAL):
    from app.jobs.service import JobService
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_STOCK_BALANCE, "mode": mode},
    )
    run_autocount_sync(db, job)
    db.refresh(job)
    run = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.job_id == job.id)
        .one()
    )
    return job, run


def _myt(dt: datetime) -> str:
    return dt.astimezone(MYT).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def test_scheduled_stock_run_is_skipped_when_no_document_moved(session_factory, server):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])
    now = datetime.now(timezone.utc)
    _prior_walk(db, company, started_at=now - timedelta(minutes=10))
    # A document from BEFORE the last walk started does not count.
    server.docs["/salesorderbyLastModified"] = [
        {"DocNo": "SO-1", "LastModified": _myt(now - timedelta(minutes=30))}
    ]

    job, run = _run_job(db, company)

    assert server.count(BALANCE_PATH) == 0, "no balance walk"
    assert server.count("/itembypage") == 0
    assert all(server.count(p) >= 1 for p in PROBE_PATHS)
    assert run.mode == RUN_MODE_SKIPPED
    assert run.skip_reason and run.skip_reason.startswith(STOCK_UNCHANGED_REASON)
    assert run.finished_at is not None
    assert job.status == "done"
    db.close()


def test_a_changed_document_forces_the_full_walk(session_factory, server):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _stock_config(db, company, conn)
    now = datetime.now(timezone.utc)
    _prior_walk(db, company, started_at=now - timedelta(minutes=10))
    server.docs["/goodsreceivenotebyLastModified"] = [
        {"DocNo": "GRN-1", "LastModified": _myt(now - timedelta(minutes=4))}
    ]

    _job, run = _run_job(db, company)

    assert server.count(BALANCE_PATH) == 3
    assert run.mode == RUN_MODE_INCREMENTAL
    assert run.outcome == RUN_SUCCESS
    db.close()


@pytest.mark.parametrize("case", ["probe_error", "too_old", "manual", "no_prior", "switched_off", "bad_stamp"])
def test_any_doubt_walks(session_factory, server, case):
    db = session_factory()
    conn = _open_connection(db, **({"stockSkipWhenUnchanged": "no"} if case == "switched_off" else {}))
    company = _company(db, conn.id)
    _stock_config(db, company, conn)
    now = datetime.now(timezone.utc)
    if case != "no_prior":
        _prior_walk(db, company, started_at=now - timedelta(minutes=61 if case == "too_old" else 10))
    if case == "probe_error":
        server.fail_probe = True
    if case == "bad_stamp":
        server.docs["/deliveryorderbyLastModified"] = [{"DocNo": "DO-1", "LastModified": None}]

    _job, run = _run_job(db, company, mode=RUN_MODE_MANUAL if case == "manual" else RUN_MODE_INCREMENTAL)

    assert server.count(BALANCE_PATH) == 3, case
    assert run.mode != RUN_MODE_SKIPPED
    db.close()


def test_an_unchanged_skip_counts_as_a_clean_run_for_stale_alerts(session_factory):
    from modules.autocount.alerts import CLEAN_RUN_MODES
    from modules.autocount.repositories import SyncRunRepository

    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    now = datetime.now(timezone.utc)
    _prior_walk(db, company, started_at=now - timedelta(minutes=55))
    db.add(AcSyncRun(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_STOCK_BALANCE,
        job_id="j1", mode=RUN_MODE_SKIPPED, skip_reason=f"{STOCK_UNCHANGED_REASON}.",
        started_at=now - timedelta(minutes=1), finished_at=now - timedelta(minutes=1), duration_ms=10,
    ))
    # An overlap skip is not a clean run.
    db.add(AcSyncRun(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_STOCK_BALANCE,
        job_id=None, mode=RUN_MODE_SKIPPED, skip_reason="A run for this task was still in progress",
        started_at=now, finished_at=now, duration_ms=0,
    ))
    db.commit()

    last = SyncRunRepository(db).last_clean_finished_at(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, CLEAN_RUN_MODES
    )
    last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    assert abs((last - (now - timedelta(minutes=1))).total_seconds()) < 1
    db.close()
