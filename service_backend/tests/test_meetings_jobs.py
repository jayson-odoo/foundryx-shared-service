"""Calendar-sync background job + beat fan-out - AC-S0-7 (the 60 s path), AC-S0-11.

The job rides the core ``background_jobs`` framework, so what is pinned here is
the wiring: which tenants a tick picks up, what happens when a tenant has no
Google connection yet, and that a run leaves both a finished job and its activity
row behind.
"""
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.meetings.calendar.base import SyncPage
from tests.conftest import ACTIVE_EMAIL
from tests.meetings_helpers import (
    FakeCalendarSource,
    make_admin_user,
    make_tenant,
    opt_in,
    raw_event,
    utc,
)

OTHER_TENANT_ID = "66666666-6666-6666-6666-666666666666"


@pytest.fixture
def db(meetings_session_factory):
    session = meetings_session_factory()
    yield session
    session.close()


def _demo_user(session):
    from app.models import User

    return session.query(User).filter(User.email == ACTIVE_EMAIL).one()


def _google_connection(session, tenant_id=DEFAULT_TENANT_ID):
    from app.models.connection import Connection
    from app.secrets import encrypt_secret

    row = Connection(
        tenant_id=tenant_id,
        provider="google_dwd",
        type="calendar",
        name="Workspace calendar",
        config_json={"impersonateEmail": "admin@example.com"},
        credentials_json=encrypt_secret({"serviceAccountJson": '{"type":"service_account"}'}),
    )
    session.add(row)
    session.flush()
    return row


def test_the_handler_type_is_registered():
    """AC-S0-11: an unregistered type makes ``JobService.create`` refuse - and
    would leave the beat tick silently creating nothing."""
    from app.jobs.registry import handler_for
    from modules.meetings.jobs import CALENDAR_SYNC

    assert handler_for(CALENDAR_SYNC).handler is not None


def test_tenants_due_needs_both_the_module_and_an_opted_in_user(db):
    """A tenant with the module but nobody opted in costs nothing per tick."""
    from app.services.app_store_service import AppStoreService
    from modules.meetings.jobs import tenants_due

    assert tenants_due(db) == []

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    _google_connection(db)
    db.commit()
    assert tenants_due(db) == [DEFAULT_TENANT_ID]

    # A second tenant with the module AND a connection but everyone opted out.
    make_tenant(db, OTHER_TENANT_ID, "Other Co")
    AppStoreService(db).install(OTHER_TENANT_ID, "meetings")
    other = make_admin_user(db, OTHER_TENANT_ID, "other@example.com")
    opt_in(db, OTHER_TENANT_ID, other.id, enabled=False)
    _google_connection(db, OTHER_TENANT_ID)
    db.commit()
    assert tenants_due(db) == [DEFAULT_TENANT_ID]


def test_tenants_due_skips_a_tenant_with_no_calendar_connection(db):
    """A tenant with nobody to ask is not due: without this it would enqueue a
    job that does nothing, once a minute, forever."""
    from modules.meetings.jobs import tenants_due

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()
    assert tenants_due(db) == []

    _google_connection(db)
    db.commit()
    assert tenants_due(db) == [DEFAULT_TENANT_ID]


def test_the_tick_skips_a_tenant_whose_last_sync_is_still_in_flight(db):
    """A pass slower than the tick would otherwise pile up jobs that race on the
    same ``sync_token`` and collide on ``uq_meetings_event_calendar``."""
    from app.jobs.service import JobService
    from app.models.background_job import JOB_PENDING, BackgroundJob
    from modules.meetings import jobs as jobs_module

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    _google_connection(db)
    db.commit()

    # A previous tick's job that has not finished yet (created, never run).
    stuck = JobService(db).create(type=jobs_module.CALENDAR_SYNC, tenant_id=DEFAULT_TENANT_ID)
    assert stuck.status == JOB_PENDING

    assert jobs_module.enqueue_due_calendar_syncs(db) == 0
    assert (
        db.query(BackgroundJob)
        .filter(BackgroundJob.type == jobs_module.CALENDAR_SYNC)
        .count()
        == 1
    )


def test_a_tenant_without_a_calendar_connection_finishes_clean(db):
    """Installing the module before onboarding Google is not an error."""
    from app.jobs.service import JobService, run_job
    from app.models.background_job import JOB_DONE
    from modules.meetings.jobs import CALENDAR_SYNC

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    db.commit()

    job = JobService(db).create(type=CALENDAR_SYNC, tenant_id=DEFAULT_TENANT_ID)
    finished = run_job(db, job.id)

    assert finished.status == JOB_DONE
    assert finished.result_json == {"skipped": "no calendar connection"}


def test_a_run_finishes_the_job_and_leaves_one_activity_row(db, monkeypatch):
    """AC-S0-11: counts land on the job AND on the integration-activity row."""
    from app.jobs.service import JobService, run_job
    from app.models.background_job import JOB_DONE
    from app.models.integration_activity import IntegrationActivity
    from modules.meetings import jobs as jobs_module
    from modules.meetings.models import CalendarEvent

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    _google_connection(db)
    db.commit()

    source = FakeCalendarSource(
        {user.email: [SyncPage(events=[raw_event("g1", starts_at=utc(2026, 9, 1, 2))])]}
    )
    monkeypatch.setattr(
        jobs_module, "calendar_source_from_connection", lambda config, creds: source
    )

    job = JobService(db).create(type=jobs_module.CALENDAR_SYNC, tenant_id=DEFAULT_TENANT_ID)
    finished = run_job(db, job.id)

    assert finished.status == JOB_DONE
    assert finished.result_json["eventsUpserted"] == 1
    assert finished.result_json["usersSynced"] == 1
    assert db.query(CalendarEvent).count() == 1

    rows = (
        db.query(IntegrationActivity)
        .filter(IntegrationActivity.tenant_id == DEFAULT_TENANT_ID)
        .all()
    )
    assert len(rows) == 1 and rows[0].source == "meetings"


def test_stale_ciphertext_is_an_operator_message_not_a_crash(db):
    """A rotated FERNET_KEY must name the connection to re-enter, not 500."""
    from app.jobs.service import JobService, run_job
    from app.models.background_job import JOB_FAILED
    from app.models.connection import CONNECTION_STATUS_ERROR
    from modules.meetings.jobs import CALENDAR_SYNC

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    connection = _google_connection(db)
    connection.credentials_json = "gAAAAA-not-decryptable"
    db.commit()

    job = JobService(db).create(type=CALENDAR_SYNC, tenant_id=DEFAULT_TENANT_ID)
    finished = run_job(db, job.id)

    assert finished.status == JOB_FAILED
    assert "Re-enter" in (finished.error or "")
    db.refresh(connection)
    assert connection.status == CONNECTION_STATUS_ERROR


def test_the_beat_tick_enqueues_one_job_per_due_tenant(db, monkeypatch):
    """AC-S0-7: the minute tick is what makes a new event surface within 60 s."""
    from app.models.background_job import BackgroundJob
    from modules.meetings import jobs as jobs_module

    user = _demo_user(db)
    opt_in(db, DEFAULT_TENANT_ID, user.id)
    _google_connection(db)
    db.commit()

    source = FakeCalendarSource({user.email: [SyncPage(events=[])]})
    monkeypatch.setattr(
        jobs_module, "calendar_source_from_connection", lambda config, creds: source
    )

    assert jobs_module.enqueue_due_calendar_syncs(db) == 1
    jobs = (
        db.query(BackgroundJob)
        .filter(BackgroundJob.type == jobs_module.CALENDAR_SYNC)
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].tenant_id == DEFAULT_TENANT_ID
