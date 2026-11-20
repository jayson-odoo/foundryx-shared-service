"""Plan 48 (AC-48-01 to AC-48-03): the AutoCount failure alert email, its
reminder and its recovered email carry the integration name, the status, a
fixed sentence and a link, never the run's error text. The in-app run error
and the incident's last error keep the full text.

Sorento's reply to every failing push below holds MARKER (a 422 body echoing
a value). The chain is real: run loop, alert evaluator, outbox.
"""
from datetime import datetime, timedelta, timezone

import httpx

from app.models.email_outbox import EmailOutbox
from modules.autocount.alerts import evaluate_integration_alerts
from modules.autocount.models import RUN_MODE_INCREMENTAL, AcTaskIncident

from tests.test_autocount_bulk_load import (  # noqa: F401
    _clean_runtime,
    _config_row,
    _insert_rows,
    _make_rig,
    _rows,
    _run,
    _run_row,
    consumer,
)
from tests.test_s33_integration_alerts import MANAGE, _only_recipients, _user

MARKER = "zzmarker4848"
ALSO = "also-extra@example.com"
MANAGER = "ops-a@example.com"


def _refuse_with_marker(consumer):
    """Sorento answers 422 and echoes a value (MARKER) in the body."""
    original = consumer._upsert
    state = {"reached": 0, "refuse": True, "original": original}

    def upsert(body):
        if state["refuse"]:
            state["reached"] += 1
            return httpx.Response(422, json={"message": f"value {MARKER} is not allowed"})
        return original(body)

    consumer._upsert = upsert
    return state


def _chain(session_factory, consumer):
    """Two failed scheduled runs, an open alert; returns (db, company_id, state, t0)."""
    state = _refuse_with_marker(consumer)
    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(3))
    db = session_factory()
    config = _config_row(db, company_id)
    config.activated_at = datetime.now(timezone.utc) - timedelta(hours=2)
    config.source_config = {**config.source_config, "alertEmails": [ALSO]}
    db.commit()
    _only_recipients(db)
    _user(db, MANAGER, perms=[MANAGE])
    runs = []
    for _ in range(2):
        job = _run(db, company_id, RUN_MODE_INCREMENTAL)
        runs.append(_run_row(db, company_id, job.id))
    assert state["reached"] >= 2, "Sorento's refusal must have been reached on both runs"
    t0 = datetime.now(timezone.utc)
    evaluate_integration_alerts(db, now=t0)
    return db, company_id, config.entity_type, state, runs, t0


def _mails(db, kind):
    return [m for m in db.query(EmailOutbox).all() if m.template_key == f"autocount_incident_{kind}"]


def _assert_fixed(db, kind, company_id, entity_type, status_word):
    mails = _mails(db, kind)
    assert {m.to_email.lower() for m in mails} == {MANAGER, ALSO}, "every recipient, Also email included"
    for mail in mails:
        subject, body = mail.subject, f"{mail.html_body}\n{mail.text_body}"
        assert MARKER not in subject and MARKER not in body, f"{kind}: error text in the email"
        assert "HTTP 422" not in body
        assert "Customer" in subject
        assert status_word in subject.lower() or status_word in body.lower()
        assert f"/autocount/companies/{company_id}/entities/{entity_type}" in body


def test_ac_48_01_the_alert_email_carries_no_error_text_for_every_recipient(session_factory, consumer):
    db, company_id, entity_type, _state, _runs, _t0 = _chain(session_factory, consumer)
    assert _mails(db, "alert"), "the alert email must have been sent"
    _assert_fixed(db, "alert", company_id, entity_type, "failed")
    db.close()


def test_ac_48_01_the_reminder_email_carries_no_error_text_for_every_recipient(session_factory, consumer):
    db, company_id, entity_type, _state, _runs, t0 = _chain(session_factory, consumer)
    evaluate_integration_alerts(db, now=t0 + timedelta(hours=4, minutes=1))
    assert _mails(db, "reminder"), "the 4 h reminder must have been sent"
    _assert_fixed(db, "reminder", company_id, entity_type, "failing")
    db.close()


def test_ac_48_01_the_recovered_email_carries_no_error_text_for_every_recipient(session_factory, consumer):
    db, company_id, entity_type, state, _runs, t0 = _chain(session_factory, consumer)
    state["refuse"] = False
    job = _run(db, company_id, RUN_MODE_INCREMENTAL)
    assert _run_row(db, company_id, job.id).error is None, "the recovery run must be clean"
    evaluate_integration_alerts(db, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    assert _mails(db, "recovered"), "the recovered email must have been sent"
    _assert_fixed(db, "recovered", company_id, entity_type, "running again")
    db.close()


def test_ac_48_03_the_run_error_and_the_incident_keep_the_full_text(session_factory, consumer):
    db, company_id, _entity, _state, runs, _t0 = _chain(session_factory, consumer)
    for run in runs:
        assert run.error and MARKER in run.error and "HTTP 422" in run.error, run.error
    incidents = db.query(AcTaskIncident).all()
    assert incidents
    for incident in incidents:
        assert incident.last_error and MARKER in incident.last_error and "HTTP 422" in incident.last_error
    db.close()
