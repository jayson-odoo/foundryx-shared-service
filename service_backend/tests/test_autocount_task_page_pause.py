"""AUTOCOUNT-LOAD-STRATEGY s6 (owner 27 Nov ~13:55: "i thought is I can
control per entity") - "Pause between pages (seconds)" per task and per
document feed, 0-90. Blank = the connection's value (the connection field
stays the default). The adaptive pause and the safety stop sit on top.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcSyncRun, RUN_SUCCESS
from modules.autocount.services.etl_service import EtlService, EtlValidationError
from modules.autocount.sources import Watermark
from tests.test_ss_stock_bal_soothe import (  # noqa: F401 - fixtures
    _company,
    _open_connection,
    _source,
    _stock_config,
    server,
)


@pytest.fixture
def pauses(monkeypatch):
    import modules.autocount.http_source.gentle as gentle

    recorded: List[float] = []
    monkeypatch.setattr(gentle, "sleep_between_pages", lambda s, **_k: recorded.append(s) or True)
    return recorded


def _http_raw(conn_id: str, **overrides):
    raw = {
        "sourceImpl": "autocount_http", "connectionId": conn_id, "path": "/itembypage",
        "keyFields": ["ItemCode"], "watermarkField": "LastModified", "comparedFields": [],
        "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
        "reconcileHours": None, "reconcileAt": "02:00",
    }
    raw.update(overrides)
    return raw


def _saved(db, company):
    return EtlService(db).configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT).source_config


# ── save ────────────────────────────────────────────────────────────────────


def test_a_task_saves_its_own_pause(session_factory):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
                               _http_raw(conn.id, pagePauseSeconds="5"))
    assert _saved(db, company)["pagePauseSeconds"] == 5.0


def test_blank_means_the_connection_value(session_factory):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    service = EtlService(db)
    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(conn.id, pagePauseSeconds="5"))
    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(conn.id, pagePauseSeconds=""))
    assert "pagePauseSeconds" not in _saved(db, company)


def test_a_save_that_does_not_send_it_keeps_the_stored_one(session_factory):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    service = EtlService(db)
    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(conn.id, pagePauseSeconds="7"))
    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(conn.id))
    assert _saved(db, company)["pagePauseSeconds"] == 7.0


@pytest.mark.parametrize("raw", ["91", "-1", "abc", "nan", "1e9"])
def test_out_of_range_is_refused_on_the_field(session_factory, raw):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    with pytest.raises(EtlValidationError) as caught:
        EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
                                   _http_raw(conn.id, pagePauseSeconds=raw))
    assert caught.value.field_errors["pagePauseSeconds"] == (
        "Pause between pages must be a number from 0 to 90 seconds "
        "(max 90 s: longer pauses make the stock run exceed its 2 h limit)."
    )


# ── the walk ────────────────────────────────────────────────────────────────


def test_the_tasks_pause_wins_over_the_connections(session_factory, server, pauses):
    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="1", slowPageSeconds="0")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)
    config.source_config = {**config.source_config, "pagePauseSeconds": 4}
    db.commit()
    source = _source(db, company, config)
    source.fetch_changes(Watermark())
    assert pauses == [4.0, 4.0]
    assert source.source_pause_seconds == 4.0


def test_a_task_set_to_zero_does_not_pause_even_if_the_connection_does(session_factory, server, pauses):
    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="3", slowPageSeconds="0")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)
    config.source_config = {**config.source_config, "pagePauseSeconds": 0}
    db.commit()
    _source(db, company, config).fetch_changes(Watermark())
    assert pauses == []


def test_without_its_own_value_the_task_uses_the_connections(session_factory, server, pauses):
    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="2", slowPageSeconds="0")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)
    _source(db, company, config).fetch_changes(Watermark())
    assert pauses == [2.0, 2.0]


# ── the run-time hint, per task ─────────────────────────────────────────────


def test_the_task_carries_its_own_run_time_hint(session_factory):
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE

    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="1")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)
    db.add(AcSyncRun(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_STOCK_BALANCE,
        outcome=RUN_SUCCESS, mode="incremental", rows_scanned=24000, source_pages=24,
        duration_ms=90_000, page_pause_ms=2000,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        finished_at=datetime.now(timezone.utc),
    ))
    db.commit()
    view = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert view.page_run_hint == {
        "kind": "pageRun", "pages": 24, "lastRunSeconds": 90.0, "lastPauseSeconds": 2.0,
        "maxRunSeconds": view.page_run_hint["maxRunSeconds"],
    }
    assert config.id


def test_no_run_yet_means_no_hint(session_factory):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(conn.id))
    assert EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT).page_run_hint is None


def test_the_task_route_carries_the_hint(client, session_factory):
    from modules.autocount.routers.companies import _task_response
    from modules.autocount.schemas import EtlTaskResponse
    from modules.autocount.services.etl_service import EtlTaskView

    assert "pageRunHint" in EtlTaskResponse.model_fields
    hint = {"kind": "pageRun", "pages": 3, "lastRunSeconds": 9.0, "lastPauseSeconds": 1.0, "maxRunSeconds": 7200}
    view = EtlTaskView(company_id="c", entity_type="product", etl_status="draft", activated_at=None,
                       page_run_hint=hint)
    assert _task_response(view).pageRunHint == hint


# ── document feeds ──────────────────────────────────────────────────────────


def test_a_feed_window_carries_its_own_pause():
    from modules.autocount.doc_feed.window import resolve_window, validate_doc_feed_window

    clean, errors = validate_doc_feed_window(
        {"pollBasis": "lastModified", "pollLookbackDays": 1, "recheckDays": 45, "pagePauseSeconds": "3"}
    )
    assert errors == {} and clean["pagePauseSeconds"] == 3.0
    clean, errors = validate_doc_feed_window(
        {"pollBasis": "lastModified", "pollLookbackDays": 1, "recheckDays": 45, "pagePauseSeconds": ""}
    )
    assert errors == {} and clean.get("pagePauseSeconds") is None
    _clean, errors = validate_doc_feed_window(
        {"pollBasis": "lastModified", "pollLookbackDays": 1, "recheckDays": 45, "pagePauseSeconds": "91"}
    )
    assert "pagePauseSeconds" in errors
    assert resolve_window(None)["pagePauseSeconds"] is None


@pytest.fixture
def _contract(monkeypatch):
    from modules.autocount import sinks_sorento

    monkeypatch.setattr(
        sinks_sorento.SorentoSink, "fetch_contract_detail",
        lambda self: sinks_sorento.SorentoContractInfo(
            version=2.7, entities=["delivery_orders", "goods_receive_notes"]
        ),
    )


def test_a_feeds_own_pause_paces_its_days(session_factory, _contract, monkeypatch):
    import modules.autocount.http_source.gentle as gentle
    from modules.autocount.doc_feed.runner import run_sweep
    from modules.autocount.models import AcDocFeed
    from tests.s14_doc_feed_helpers import wired_company

    pauses: List[float] = []
    monkeypatch.setattr(gentle, "sleep_between_pages", lambda s, **_k: pauses.append(s) or True)
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    ac_conn.config_json = {**ac_conn.config_json, "pagePauseSeconds": "9", "slowPageSeconds": "0"}
    feed = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push", cursor_day=date(2026, 9, 29),
        window_config={"recheckDays": 3, "pagePauseSeconds": 2},
    )
    db.add(feed)
    db.commit()
    vendor = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    run_sweep(db, feed, dry_run=True, now=datetime(2026, 9, 29, 10, tzinfo=timezone.utc), vendor_transport=vendor)
    assert pauses == [2.0, 2.0]
