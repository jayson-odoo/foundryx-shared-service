"""Plan 33 round 2 (SS-INTEGRATION-ALERT) - RED tests after the crew audit,
review and security review. Spec: the amended UAC (AC-33-01 terms, 05, 07, 11,
18, 19). Written BEFORE the fixes; each test carries its AC id.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    ETL_STATUS_PAUSED,
    RUN_FAILED,
    RUN_MODE_INCREMENTAL,
    RUN_SUCCESS,
    AcEntityConfig,
    AcSyncRun,
)
from tests.test_s33_integration_alerts import (  # noqa: F401 - fixtures + helpers
    MANAGE,
    NOW,
    _all_incidents,
    _clean,
    _company,
    _emails,
    _evaluate,
    _fail,
    _incident_model,
    _only_recipients,
    _open_incidents,
    _task,
    _user,
    failing,
)

BUDGET = "Budget reached after page 3; continues on the next tick."
PUSH_ERROR = "Sorento rejected the batch: HTTP 500"


def _success_run(
    db, company, *, finished_at: datetime, error: Optional[str], truncated: bool = False,
    mode: str = RUN_MODE_INCREMENTAL,
) -> AcSyncRun:
    run = AcSyncRun(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type="customer",
        mode=mode, outcome=RUN_SUCCESS, error=error, truncated=truncated,
        started_at=finished_at - timedelta(minutes=1), finished_at=finished_at,
    )
    db.add(run)
    db.commit()
    return run


def _failed_run_at(db, company, finished_at: datetime) -> AcSyncRun:
    run = AcSyncRun(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type="customer",
        mode=RUN_MODE_INCREMENTAL, outcome=RUN_FAILED,
        error="AutoCount answered HTTP 502 on page 3.",
        started_at=finished_at - timedelta(minutes=1), finished_at=finished_at,
    )
    db.add(run)
    db.commit()
    return run


# ── 1. budget cut-short runs are not failures (crew HIGH) ────────────────────


def test_ac_33_01_two_budget_cut_short_runs_in_a_row_open_no_incident(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    _success_run(db, company, finished_at=NOW - timedelta(minutes=20), error=BUDGET, truncated=True)
    _success_run(db, company, finished_at=NOW - timedelta(minutes=5), error=BUDGET, truncated=True)
    _evaluate(db)
    assert _open_incidents(db, config.id) == []
    db.close()


def test_ac_33_01_a_budget_cut_short_run_counts_as_clean_and_resets_the_count(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    _fail(db, company, 25)
    _success_run(db, company, finished_at=NOW - timedelta(minutes=15), error=BUDGET, truncated=True)
    _fail(db, company, 5)
    _evaluate(db)
    assert _open_incidents(db, config.id) == []
    db.close()


def test_ac_33_06_a_budget_cut_short_run_after_a_failing_streak_closes_the_incident(failing):
    db, company, config = failing
    _evaluate(db)
    assert len(_open_incidents(db, config.id)) == 1
    _success_run(db, company, finished_at=NOW + timedelta(minutes=1), error=BUDGET, truncated=True)
    result = _evaluate(db, now=NOW + timedelta(minutes=2))
    assert result["recovered"] == 1
    assert _open_incidents(db, config.id) == []
    assert _emails(db)[-1].subject == "Customer (Alert Co) is running again"


def test_ac_33_01_a_real_push_error_on_a_SUCCESS_run_still_counts_as_failed(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    _success_run(db, company, finished_at=NOW - timedelta(minutes=20), error=PUSH_ERROR)
    _success_run(db, company, finished_at=NOW - timedelta(minutes=5), error=PUSH_ERROR)
    _evaluate(db)
    assert len(_open_incidents(db, config.id)) == 1
    db.close()


def test_ac_33_01_a_budget_note_with_an_appended_push_error_still_counts_as_failed(
    session_factory,
):
    """sync.py appends the push error to the budget note (truncated pass AND a
    push fault): that run did fail."""
    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    combined = f"{BUDGET} {PUSH_ERROR}"
    _success_run(db, company, finished_at=NOW - timedelta(minutes=20), error=combined, truncated=True)
    _success_run(db, company, finished_at=NOW - timedelta(minutes=5), error=combined, truncated=True)
    _evaluate(db)
    assert len(_open_incidents(db, config.id)) == 1
    db.close()


# ── 2. guarded claim: overlapping checks never double-send ───────────────────


def _stale_second_session(session_factory, monkeypatch, config_id: str):
    """A second session that already loaded the open incident before the first
    check committed: its ``get_open`` returns that stale row (a real overlap)."""
    from modules.autocount.repositories import TaskIncidentRepository

    db_b = session_factory()
    stale = TaskIncidentRepository(db_b).get_open(DEFAULT_TENANT_ID, config_id)
    assert stale is not None
    original = TaskIncidentRepository.get_open

    def get_open(self, tenant_id, entity_config_id):
        if self.db is db_b:
            return stale
        return original(self, tenant_id, entity_config_id)

    monkeypatch.setattr(TaskIncidentRepository, "get_open", get_open)
    return db_b


def test_ac_33_05_two_overlapping_checks_enqueue_the_reminder_once(
    failing, session_factory, monkeypatch
):
    db, _company_row, config = failing
    _evaluate(db)
    assert len(_emails(db)) == 1
    db_b = _stale_second_session(session_factory, monkeypatch, config.id)
    due = NOW + timedelta(hours=4, minutes=1)
    _evaluate(db, now=due)
    _evaluate(db_b, now=due)
    assert len(_emails(db)) == 2, "the same due reminder must be sent once"
    db_b.close()


def test_ac_33_05_two_overlapping_checks_enqueue_the_recovered_notice_once(
    failing, session_factory, monkeypatch
):
    db, company, config = failing
    _evaluate(db)
    db_b = _stale_second_session(session_factory, monkeypatch, config.id)
    _clean(db, company, -1)
    soon = NOW + timedelta(minutes=2)
    _evaluate(db, now=soon)
    _evaluate(db_b, now=soon)
    recovered = [e for e in _emails(db) if e.subject.endswith("is running again")]
    assert len(recovered) == 1, "the same recovered notice must be sent once"
    db_b.close()


# ── 3. resume, pause+resume between checks, deleted integration ──────────────


def _service(db):
    from modules.autocount.services.etl_service import EtlService

    return EtlService(db)


def test_ac_33_07_resume_keeps_activated_at_sets_resumed_at_and_restarts_the_clock(
    session_factory,
):
    real_now = datetime.now(timezone.utc)
    db = session_factory()
    company = _company(db)
    config = _task(db, company, activated_ago=timedelta(days=3))
    config.activated_at = real_now - timedelta(days=3)
    db.commit()
    activated = config.activated_at
    svc = _service(db)
    svc.pause_task(DEFAULT_TENANT_ID, company.id, "customer")
    svc.resume_task(DEFAULT_TENANT_ID, company.id, "customer")
    db.refresh(config)
    assert config.etl_status == ETL_STATUS_ACTIVE
    assert config.activated_at == activated
    assert config.resumed_at is not None
    # the stale clock restarted at the resume: no instant stale incident
    _evaluate(db, now=real_now + timedelta(minutes=5))
    assert _open_incidents(db, config.id) == []
    db.close()


def test_ac_33_07_a_pause_and_resume_between_two_checks_close_the_open_incident_silently(
    failing,
):
    db, company, config = failing
    _evaluate(db)
    sent = len(_emails(db))
    svc = _service(db)
    svc.pause_task(DEFAULT_TENANT_ID, company.id, "customer")
    svc.resume_task(DEFAULT_TENANT_ID, company.id, "customer")
    real_now = datetime.now(timezone.utc)
    result = _evaluate(db, now=real_now + timedelta(minutes=1))
    assert result["closed"] == 1
    assert _open_incidents(db, config.id) == []
    assert _all_incidents(db, config.id)[0].close_reason == "paused"
    assert len(_emails(db)) == sent

    # fresh start: a NEW failing streak after the resume opens a NEW incident
    _failed_run_at(db, company, real_now + timedelta(minutes=10))
    _failed_run_at(db, company, real_now + timedelta(minutes=20))
    _evaluate(db, now=real_now + timedelta(minutes=30))
    rows = _all_incidents(db, config.id)
    assert len(rows) == 2
    assert len(_open_incidents(db, config.id)) == 1


def test_ac_33_07_an_open_incident_whose_integration_was_deleted_is_closed(failing):
    db, _company_row, config = failing
    _evaluate(db)
    sent = len(_emails(db))
    config_id = config.id
    db.delete(config)
    db.commit()
    _evaluate(db, now=NOW + timedelta(minutes=1))
    assert _open_incidents(db, config_id) == []
    assert len(_emails(db)) == sent


# ── 4. alert-only save (AC-33-11) ────────────────────────────────────────────

from tests.test_autocount_etl_task_routes import (  # noqa: E402,F401 - fixtures
    _auth,
    _clean_runtime,
    _config_row,
    _url,
    consumer,
    rig,
)
from tests.test_s33_integration_alert_api import _put  # noqa: E402


def _activate_gate(session_factory, company_id: str):
    db = session_factory()
    config = _config_row(db, type("C", (), {"id": company_id}))
    stamp = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)
    config.etl_status = ETL_STATUS_ACTIVE
    config.activated_at = stamp
    config.last_preview_at = stamp
    config.last_preview_failed_count = 0
    db.commit()
    db.close()
    return stamp


def test_ac_33_11_an_alert_only_save_keeps_the_task_active_and_the_gate_stamp(
    client, session_factory, rig
):
    company_id, _sql = rig
    stamp = _activate_gate(session_factory, company_id)
    db = session_factory()
    jobs_before = db.query(BackgroundJob).count()
    db.close()

    response = client.put(
        _url(company_id),
        json={"alertsEnabled": False, "alertAfterFailedRuns": 4},
        headers=_auth(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["etlStatus"] == ETL_STATUS_ACTIVE
    assert body["alertsEnabled"] is False
    assert body["alertAfterFailedRuns"] == 4

    db = session_factory()
    config = _config_row(db, type("C", (), {"id": company_id}))
    assert config.etl_status == ETL_STATUS_ACTIVE
    assert config.last_preview_at == stamp, "an alert-only save must not clear the gate"
    assert config.last_preview_failed_count == 0
    assert config.source_config["alertsEnabled"] is False
    assert config.source_config["alertAfterFailedRuns"] == 4
    assert db.query(BackgroundJob).count() == jobs_before, "no preview job may be enqueued"
    db.close()


@pytest.mark.parametrize(
    "bad",
    [
        "a​@b.co",          # zero-width space, non-ASCII
        "josé@b.co",        # non-ASCII letter
        "a<x>@b.co",             # angle brackets
        "a@b.co\r\nBcc: x@y.z",  # header injection
        "ok@b.co\r\n",           # trailing CRLF (strip must not launder it)
        "ok@b.co\n",
    ],
)
def test_ac_33_11_unsafe_also_email_addresses_are_a_422_naming_the_field(
    client, rig, bad
):
    company_id, sql_id = rig
    response = _put(client, company_id, sql_id, alertEmails=["fine@example.com", bad])
    assert response.status_code == 422, response.text
    assert "alertEmails" in response.text


# ── 5. AC-33-18 mail budget ──────────────────────────────────────────────────


def test_ac_33_18_toggling_alerts_off_and_on_does_not_re_alert_within_four_hours(failing):
    db, _company_row, config = failing
    _evaluate(db)
    assert len(_emails(db)) == 1

    config.source_config = {**config.source_config, "alertsEnabled": False}
    db.commit()
    _evaluate(db, now=NOW + timedelta(minutes=10))
    assert _open_incidents(db, config.id) == []

    config.source_config = {**config.source_config, "alertsEnabled": True}
    db.commit()
    result = _evaluate(db, now=NOW + timedelta(minutes=20))
    assert result["opened"] == 1
    assert len(_open_incidents(db, config.id)) == 1, "the banner and badge still show"
    assert len(_emails(db)) == 1, "no second alert inside 4 h of the first"

    _evaluate(db, now=NOW + timedelta(hours=3, minutes=59))
    assert len(_emails(db)) == 1
    # the first email follows the 4 h cadence from the LAST NOTICE (NOW)
    _evaluate(db, now=NOW + timedelta(hours=4, minutes=1))
    assert len(_emails(db)) == 2


def test_ac_33_18_a_flapping_source_sends_one_alert_and_one_recovered_per_four_hours(failing):
    db, company, config = failing
    _evaluate(db)                                            # alert (email 1)
    _clean(db, company, -1)
    _evaluate(db, now=NOW + timedelta(minutes=2))            # recovered (email 2)
    _fail(db, company, -3)
    _fail(db, company, -4)
    result = _evaluate(db, now=NOW + timedelta(minutes=5))   # re-trips inside 4 h
    assert result["opened"] == 1
    assert len(_open_incidents(db, config.id)) == 1
    assert len(_emails(db)) == 2, "the second incident opens silently inside the 4 h budget"

    _clean(db, company, -6)
    _evaluate(db, now=NOW + timedelta(minutes=7))            # silent incident recovers
    assert _open_incidents(db, config.id) == []
    subjects = [e.subject for e in _emails(db)]
    assert len(subjects) == 2, subjects
    assert sum(s.endswith("is running again") for s in subjects) == 1
    assert sum("has failed" in s for s in subjects) == 1


def test_ac_33_18_a_silent_incident_that_recovers_sends_no_recovered_email(failing):
    db, company, config = failing
    _evaluate(db)
    config.source_config = {**config.source_config, "alertsEnabled": False}
    db.commit()
    _evaluate(db, now=NOW + timedelta(minutes=10))
    config.source_config = {**config.source_config, "alertsEnabled": True}
    db.commit()
    _evaluate(db, now=NOW + timedelta(minutes=20))           # silent incident
    assert len(_open_incidents(db, config.id)) == 1
    sent = len(_emails(db))
    _clean(db, company, -21)
    result = _evaluate(db, now=NOW + timedelta(minutes=22))
    assert result["recovered"] >= 0
    assert _open_incidents(db, config.id) == []
    assert len(_emails(db)) == sent, "no recovered notice for an incident that never emailed"


def test_ac_33_18_after_four_hours_a_new_incident_alerts_normally(failing):
    db, company, config = failing
    _evaluate(db)
    _clean(db, company, -1)
    _evaluate(db, now=NOW + timedelta(minutes=2))
    base = NOW + timedelta(hours=5)
    for minutes in (1, 2):
        run = AcSyncRun(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type="customer",
            mode=RUN_MODE_INCREMENTAL, outcome=RUN_FAILED, error="boom",
            started_at=base + timedelta(minutes=minutes - 1),
            finished_at=base + timedelta(minutes=minutes),
        )
        db.add(run)
    db.commit()
    _evaluate(db, now=base + timedelta(minutes=3))
    assert len(_emails(db)) == 3, "outside the 4 h budget the new incident alerts"
    assert _emails(db)[-1].subject.endswith("has failed 2 runs in a row")


# ── 6. AC-33-19 email safety ─────────────────────────────────────────────────


def test_ac_33_19_control_characters_in_a_company_name_never_reach_the_subject(session_factory):
    db = session_factory()
    _only_recipients(db)
    _user(db, "safe@example.com", perms=[MANAGE])
    company = _company(db, name="Acme\r\nBcc: x@y.z", database_name="ACME_DB")
    company.name = "Acme\r\nBcc: x@y.z"
    company.company_name = "Acme\r\nBcc: x@y.z"
    db.commit()
    _task(db, company)
    _fail(db, company, 20)
    _fail(db, company, 5)
    _evaluate(db)
    subject = _emails(db)[0].subject
    assert "\r" not in subject and "\n" not in subject
    assert all(ch.isprintable() for ch in subject), repr(subject)
    assert subject == "Customer (Acme Bcc: x@y.z) has failed 2 runs in a row"
    db.close()


def test_ac_33_19_other_control_characters_collapse_to_single_spaces(session_factory):
    db = session_factory()
    _only_recipients(db)
    _user(db, "ctl@example.com", perms=[MANAGE])
    company = _company(db, name="A\x00B\x1b[31m\t\tC", database_name="CTL_DB")
    _task(db, company)
    _fail(db, company, 20)
    _fail(db, company, 5)
    _evaluate(db)
    subject = _emails(db)[0].subject
    assert all(ch.isprintable() for ch in subject), repr(subject)
    assert "  " not in subject
    db.close()


def test_ac_33_19_tenant_and_remote_text_is_html_escaped_in_the_body(session_factory):
    db = session_factory()
    _only_recipients(db)
    _user(db, "esc@example.com", perms=[MANAGE])
    company = _company(db, name="<b>x</b>", database_name="ESC_DB")
    _task(db, company)
    _fail(db, company, 20, error="<script>alert(1)</script>")
    _fail(db, company, 5, error="<script>alert(1)</script>")
    _evaluate(db)
    html_body = _emails(db)[0].html_body
    assert "&lt;b&gt;x&lt;/b&gt;" in html_body
    assert "&lt;script&gt;" in html_body
    assert "<b>x</b>" not in html_body
    assert "<script>" not in html_body
    db.close()
