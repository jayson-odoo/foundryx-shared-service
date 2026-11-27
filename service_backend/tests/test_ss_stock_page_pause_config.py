"""SS-STOCK-PAGE-PAUSE-CONFIG - the owner sets the pause between AutoCount
pages in the app (``documentation/plans/sprint-5/ss-stock-page-pause-config.md``).

Owner 27 Nov: default 0 s ("then you let me control"), range 0-90 s (crew 27 Nov: a 70-page run stays under the 2 h job limit). The
pause sleeps in short slices and a stopped run never sits out the rest of it.
Rig reused from ``test_ss_stock_bal_soothe.py`` (a fake 3-page balance
endpoint behind a ``MockTransport``); no real waits anywhere.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_ABORTED, JOB_RUNNING, BackgroundJob
from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
from modules.autocount.http_source.gentle import sleep_between_pages as REAL_SLEEP_BETWEEN_PAGES
from modules.autocount.models import (
    RUN_ABORTED,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_SKIPPED,
    RUN_SUCCESS,
    AcSyncRun,
)
from modules.autocount.sources import Watermark
from tests.test_ss_stock_bal_soothe import (  # noqa: F401 - fixtures
    BALANCE_PATH,
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

    def fake(seconds, **_kw):
        recorded.append(seconds)
        return True

    monkeypatch.setattr(gentle, "sleep_between_pages", fake)
    return recorded


@pytest.fixture
def slices(monkeypatch):
    """The REAL sliced pause, with the clock sleep itself recorded."""
    import modules.autocount.http_source.gentle as gentle

    recorded: List[float] = []
    monkeypatch.setattr(gentle, "sleep_between_pages", REAL_SLEEP_BETWEEN_PAGES)
    monkeypatch.setattr(gentle, "_sleep", lambda s: recorded.append(s))
    return recorded


def _run_job(db, company):
    """A claimed (RUNNING) stock job run inline, as a worker would."""
    from app.jobs.service import JobService
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_STOCK_BALANCE,
                 "mode": RUN_MODE_INCREMENTAL},
    )
    job.status = JOB_RUNNING
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    run_autocount_sync(db, job)
    return db.query(AcSyncRun).filter(AcSyncRun.job_id == job.id).one()


# ── the setting ───────────────────────────────────────────────────────────


def test_default_is_zero_for_a_connection_without_the_key():
    from modules.autocount.http_source.gentle import gentle_settings

    assert gentle_settings({"baseUrl": "x", "auth": "none"}).page_pause_seconds == 0.0
    assert gentle_settings({"pagePauseSeconds": ""}).page_pause_seconds == 0.0
    assert gentle_settings(None).page_pause_seconds == 0.0


def test_saved_values_up_to_90_seconds_are_read_back():
    from modules.autocount.http_source.gentle import gentle_settings

    for raw, expected in (("60", 60.0), ("90", 90.0), ("2.5", 2.5), ("0", 0.0)):
        assert gentle_settings({"pagePauseSeconds": raw}).page_pause_seconds == expected
    # A stored value is never trusted outright: past the max clamps, junk = default.
    assert gentle_settings({"pagePauseSeconds": "600"}).page_pause_seconds == 90.0
    assert gentle_settings({"pagePauseSeconds": "abc"}).page_pause_seconds == 0.0


def test_field_sits_next_to_page_size_with_default_zero_and_range_0_90():
    from modules.autocount.provider import AutoCountProvider

    fields = AutoCountProvider().fields()
    keys = [f["key"] for f in fields]
    assert keys.index("pagePauseSeconds") > keys.index("pageSize")
    field = next(f for f in fields if f["key"] == "pagePauseSeconds")
    assert field["label"] == "Pause between pages (seconds)"
    assert field["defaultValue"] == "0"
    assert (field["min"], field["max"]) == (0, 90)


@pytest.mark.parametrize("raw", ["91", "600", "-1", "abc", "1e9", "nan"])
def test_out_of_range_is_rejected_with_a_plain_message(raw):
    from modules.autocount.provider import AutoCountProvider

    error = AutoCountProvider().validate_config(
        {"baseUrl": "", "auth": "none", "pagePauseSeconds": raw}
    )
    assert error == (
        "Pause between pages must be a number from 0 to 90 seconds "
        "(max 90 s: longer pauses make the stock run exceed its 2 h limit)."
    )


@pytest.mark.parametrize("raw", ["0", "1", "60", "90", "0.5", ""])
def test_in_range_is_accepted(raw):
    from modules.autocount.provider import AutoCountProvider

    assert AutoCountProvider().validate_config(
        {"baseUrl": "", "auth": "none", "pagePauseSeconds": raw}
    ) is None


def test_setting_is_saved_and_read_through_the_connection(session_factory):
    from app.schemas.integration import ConnectionUpdateRequest
    from app.services.integration_service import IntegrationService

    db = session_factory()
    conn = _open_connection(db)
    service = IntegrationService(db)
    service.update(
        DEFAULT_TENANT_ID, conn.id,
        ConnectionUpdateRequest(config={"pagePauseSeconds": "60"}),
    )
    assert service.get(DEFAULT_TENANT_ID, conn.id).config["pagePauseSeconds"] == "60"
    db.close()


# ── the walk ──────────────────────────────────────────────────────────────


def test_a_legacy_connection_no_longer_pauses(session_factory, server, pauses):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)

    _source(db, company, config).fetch_changes(Watermark())

    assert server.count(BALANCE_PATH) == 3
    assert pauses == []
    db.close()


def test_the_configured_pause_is_used_between_pages_only(session_factory, server, pauses):
    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="60")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)

    _source(db, company, config).fetch_changes(Watermark())

    assert server.count(BALANCE_PATH) == 3
    assert pauses == [60.0, 60.0], "two gaps for three pages: none before page 1 or after page 3"
    db.close()


def test_the_pause_sleeps_in_short_slices(slices):
    from modules.autocount.http_source.gentle import PAUSE_SLICE_SECONDS, sleep_between_pages

    checks: List[int] = []
    assert sleep_between_pages(12, should_stop=lambda: checks.append(1) or False) is True
    assert sum(slices) == pytest.approx(12)
    assert max(slices) <= PAUSE_SLICE_SECONDS
    assert len(checks) == len(slices)


def test_a_stop_ends_the_pause_at_the_next_slice(slices):
    from modules.autocount.http_source.gentle import PAUSE_SLICE_SECONDS, sleep_between_pages

    assert sleep_between_pages(90, should_stop=lambda: True) is False
    assert slices == [PAUSE_SLICE_SECONDS], "one slice, never the full 90 s"


def test_zero_never_sleeps(slices):
    from modules.autocount.http_source.gentle import sleep_between_pages

    assert sleep_between_pages(0, should_stop=lambda: True) is True
    assert slices == []


def test_a_stopped_walk_requests_no_further_page(session_factory, server, slices):
    from modules.autocount.http_source.errors import HttpSourceError
    from modules.autocount.http_source.gentle import PAUSE_STOPPED_CODE
    from modules.autocount.http_source.source import HttpApiSource
    from tests.test_ss_stock_bal_soothe import _ctx

    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="90")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=config.entity_type,
        mode=RUN_MODE_INCREMENTAL, should_stop=lambda: True,
    )
    with pytest.raises(HttpSourceError) as raised:
        source.fetch_changes(Watermark())
    assert raised.value.code == PAUSE_STOPPED_CODE
    assert server.count(BALANCE_PATH) == 1
    db.close()


def test_an_aborted_run_stops_during_the_pause_and_reads_aborted(
    session_factory, server, monkeypatch
):
    """The job is aborted (from another session) while the run waits out a
    90 s pause: the run stops at the next slice, asks for no more pages,
    and the operator's abort stands."""
    import modules.autocount.http_source.gentle as gentle

    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="90")
    company = _company(db, conn.id)
    _stock_config(db, company, conn)

    slept: List[float] = []

    def abort_on_first_slice(seconds):
        slept.append(seconds)
        if len(slept) == 1:
            other = session_factory()
            job = other.query(BackgroundJob).filter(BackgroundJob.status == JOB_RUNNING).one()
            job.status = JOB_ABORTED
            other.commit()
            other.close()

    monkeypatch.setattr(gentle, "sleep_between_pages", REAL_SLEEP_BETWEEN_PAGES)
    monkeypatch.setattr(gentle, "_sleep", abort_on_first_slice)

    run = _run_job(db, company)

    assert server.count(BALANCE_PATH) == 1
    assert len(slept) == 1, "stopped after one slice, not 90 s"
    assert run.outcome == RUN_ABORTED
    job = db.query(BackgroundJob).filter(BackgroundJob.id == run.job_id).one()
    db.refresh(job)
    assert job.status == JOB_ABORTED
    db.close()


def test_a_long_pause_keeps_the_job_alive(session_factory, server, monkeypatch):
    """Each slice beats the job's heartbeat, so a run waiting out long pauses
    is never mistaken for a crashed one by the 15-minute orphan sweep."""
    import modules.autocount.http_source.gentle as gentle

    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="10")
    company = _company(db, conn.id)
    _stock_config(db, company, conn)

    import modules.autocount.sync as sync_module

    events: List[str] = []
    real_heartbeat = sync_module._heartbeat

    def counting_heartbeat(service, job_id):
        events.append("beat")
        return real_heartbeat(service, job_id)

    monkeypatch.setattr(sync_module, "_heartbeat", counting_heartbeat)
    monkeypatch.setattr(gentle, "sleep_between_pages", REAL_SLEEP_BETWEEN_PAGES)
    monkeypatch.setattr(gentle, "_sleep", lambda s: events.append("slice"))

    run = _run_job(db, company)

    assert run.outcome == RUN_SUCCESS
    assert server.count(BALANCE_PATH) == 3
    assert events.count("slice") == 4, "two 10 s pauses in 5 s slices"
    # Every slice is followed by a beat before the next slice or page.
    for i, e in enumerate(events):
        if e == "slice":
            assert events[i + 1] == "beat", events
    db.close()


def test_a_run_records_its_pages_and_pause(session_factory, server, pauses):
    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="2.5")
    company = _company(db, conn.id)
    _stock_config(db, company, conn)

    run = _run_job(db, company)

    assert run.outcome == RUN_SUCCESS
    assert (run.source_pages, run.page_pause_ms) == (3, 2500)
    db.close()


def test_a_stop_after_the_orphan_sweep_leaves_its_verdict(session_factory, server, monkeypatch):
    """The job was failed elsewhere while the run paused: the run stops and
    writes nothing over that verdict (no failure counted on the task)."""
    import modules.autocount.http_source.gentle as gentle
    from app.models.background_job import JOB_FAILED
    from modules.autocount.models import AcEntityConfig

    db = session_factory()
    conn = _open_connection(db, pagePauseSeconds="90")
    company = _company(db, conn.id)
    _stock_config(db, company, conn)

    def sweep_on_first_slice(seconds):
        other = session_factory()
        job = other.query(BackgroundJob).filter(BackgroundJob.status == JOB_RUNNING).one()
        job.status = JOB_FAILED
        job.error = "swept"
        other.commit()
        other.close()

    monkeypatch.setattr(gentle, "sleep_between_pages", REAL_SLEEP_BETWEEN_PAGES)
    monkeypatch.setattr(gentle, "_sleep", sweep_on_first_slice)

    run = _run_job(db, company)

    assert server.count(BALANCE_PATH) == 1
    job = db.query(BackgroundJob).filter(BackgroundJob.id == run.job_id).one()
    db.refresh(job)
    assert (job.status, job.error) == (JOB_FAILED, "swept")
    task = db.query(AcEntityConfig).filter(
        AcEntityConfig.company_id == company.id,
        AcEntityConfig.entity_type == ENTITY_STOCK_BALANCE,
    ).one()
    assert task.last_run_error is None
    db.close()


# ── overlap guard (exists since plan 22 S3, scheduler._sweep_one) ─────────


def test_a_scheduled_tick_during_a_long_running_run_is_skipped(session_factory):
    """The guard is per task and entity-agnostic; a seeded task stands in."""
    from modules.autocount.canonical.masters import ENTITY_CUSTOMER
    from modules.autocount.scheduler import sweep_etl_tasks
    from modules.autocount.sync import AUTOCOUNT_SYNC
    from tests.test_autocount_scheduler import _company as sched_company
    from tests.test_autocount_scheduler import _task

    now = datetime(2026, 11, 27, 4, 0, tzinfo=timezone.utc)
    db = session_factory()
    company = sched_company(db)
    _task(db, company, entity_type=ENTITY_CUSTOMER, next_incremental_at=now - timedelta(minutes=1))
    running = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_RUNNING,
        payload_json={"companyId": company.id, "entityType": ENTITY_CUSTOMER},
        created_at=now - timedelta(minutes=40),
        started_at=now - timedelta(minutes=40),
        heartbeat_at=now - timedelta(seconds=5),
    )
    db.add(running)
    db.commit()

    assert sweep_etl_tasks(db, now=now)["skipped"] == 1
    skip = db.query(AcSyncRun).filter(AcSyncRun.company_id == company.id).one()
    assert skip.mode == RUN_MODE_SKIPPED
    assert "still in progress" in skip.skip_reason
    db.refresh(running)
    assert running.status == JOB_RUNNING, "a live run is never swept as orphaned"
    assert db.query(BackgroundJob).filter(BackgroundJob.id != running.id).count() == 0
    db.close()


# ── the hint under the field ──────────────────────────────────────────────


def _past_run(db, company, entity_type, *, rows, seconds, mode=RUN_MODE_INCREMENTAL,
              outcome=RUN_SUCCESS, minutes_ago=10, pages=None, pause_ms=None):
    finished = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db.add(AcSyncRun(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        mode=mode, outcome=outcome, rows_scanned=rows, duration_ms=int(seconds * 1000),
        source_pages=pages, page_pause_ms=pause_ms,
        started_at=finished - timedelta(seconds=seconds), finished_at=finished,
    ))
    db.commit()


def test_hint_reports_the_last_run_page_count(session_factory):
    from app.services.integration_service import IntegrationService

    db = session_factory()
    conn = _open_connection(db, pageSize="1000", pagePauseSeconds="1")
    company = _company(db, conn.id)
    _stock_config(db, company, conn)
    _past_run(db, company, ENTITY_STOCK_BALANCE, rows=60_000, seconds=200, minutes_ago=60)
    _past_run(db, company, ENTITY_STOCK_BALANCE, rows=69_500, seconds=150)
    _past_run(db, company, ENTITY_STOCK_BALANCE, rows=0, seconds=0, mode=RUN_MODE_SKIPPED,
              outcome=None, minutes_ago=1)

    out = IntegrationService(db).get(DEFAULT_TENANT_ID, conn.id)

    assert out.fieldHints == {
        "pagePauseSeconds": {
            "kind": "pageRun",
            "pages": 70,
            "lastRunSeconds": 150.0,
            "lastPauseSeconds": 1.0,
            "maxRunSeconds": 7200,
        }
    }
    db.close()


def test_hint_is_absent_before_any_run(session_factory):
    from app.services.integration_service import IntegrationService

    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _stock_config(db, company, conn)

    assert IntegrationService(db).get(DEFAULT_TENANT_ID, conn.id).fieldHints == {}
    db.close()


def test_hint_ignores_another_connections_tasks(session_factory):
    from app.services.integration_service import IntegrationService

    db = session_factory()
    conn = _open_connection(db)
    other = _open_connection(db)
    company = _company(db, other.id)
    _stock_config(db, company, other)
    _past_run(db, company, ENTITY_STOCK_BALANCE, rows=69_500, seconds=150)

    assert IntegrationService(db).get(DEFAULT_TENANT_ID, conn.id).fieldHints == {}
    db.close()


def test_hint_uses_the_pages_and_pause_the_run_recorded(session_factory):
    from app.services.integration_service import IntegrationService

    db = session_factory()
    conn = _open_connection(db, pageSize="1000", pagePauseSeconds="0")
    company = _company(db, conn.id)
    _stock_config(db, company, conn)
    _past_run(db, company, ENTITY_STOCK_BALANCE, rows=69_500, seconds=4200,
              pages=71, pause_ms=60_000)

    hint = IntegrationService(db).get(DEFAULT_TENANT_ID, conn.id).fieldHints["pagePauseSeconds"]

    assert (hint["pages"], hint["lastPauseSeconds"]) == (71, 60.0)
    db.close()


def test_hint_survives_a_save(session_factory):
    from app.schemas.integration import ConnectionUpdateRequest
    from app.services.integration_service import IntegrationService

    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _stock_config(db, company, conn)
    _past_run(db, company, ENTITY_STOCK_BALANCE, rows=69_500, seconds=150)

    out = IntegrationService(db).update(
        DEFAULT_TENANT_ID, conn.id, ConnectionUpdateRequest(config={"pagePauseSeconds": "60"}),
    )
    assert out.fieldHints["pagePauseSeconds"]["pages"] == 70
    db.close()


def test_a_failing_hint_never_breaks_opening_the_connection(session_factory, monkeypatch):
    import modules.autocount.services.page_pause_hint as hint_module
    from app.services.integration_service import IntegrationService

    def boom(db, connection):
        raise RuntimeError("hint failed")

    monkeypatch.setattr(hint_module, "page_run_hint", boom)
    db = session_factory()
    conn = _open_connection(db)
    out = IntegrationService(db).get(DEFAULT_TENANT_ID, conn.id)
    assert out.fieldHints == {}
    assert out.config["baseUrl"]
    db.close()
