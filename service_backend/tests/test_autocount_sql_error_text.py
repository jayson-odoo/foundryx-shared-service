"""Plan 46 (AC-46-06): the AutoCount SQL source returns and stores fixed
error text built from the error class and codes, never the driver's message.

The driver message of every failure below holds MARKER (as a table name or a
value). Each surface an operator can read is checked for it: the test and
preview route responses, the call record, the run and task error, the
incident's last error and the alert email.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.pool import StaticPool

from app.models import DEFAULT_TENANT_ID
from app.models.email_outbox import EmailOutbox
from app.models.integration_activity import IntegrationActivity
from modules.autocount.models import (
    RUN_MODE_INCREMENTAL,
    AcTaskIncident,
)
from modules.autocount.sql_provider import SqlDatabaseProvider
from modules.autocount.sql_source.errors import SqlQueryError
from modules.autocount.sql_source.runtime import RUNTIME, sanitize_error
from modules.autocount.sql_source.source import SqlDbSource
from modules.autocount.sources import Watermark
from modules.autocount.canonical.masters import ENTITY_CUSTOMER

# Reused rig helpers and fixtures (the run loop with a scripted consumer).
from tests.test_autocount_bulk_load import (  # noqa: F401
    _clean_runtime,
    _config_row,
    _make_rig,
    _run,
    _run_row,
    _watermark_row,
    consumer,
)
from tests.test_autocount_etl_routes import _auth, _sql_connection
from tests.test_autocount_sql_db_source import _ctx
from tests.test_s33_integration_alerts import MANAGE, _only_recipients, _user

MARKER = "zzmarker9137"
MISSING_TABLE = f"{MARKER}_tbl"


class PgLikeError(Exception):
    def __init__(self, pgcode):
        self.pgcode = pgcode
        self.diag = SimpleNamespace(constraint_name=None)
        super().__init__(f"server said no\nDETAIL:  Key (name)=({MARKER}) exists.\n")


class MssqlLikeError(Exception):
    def __init__(self, number):
        super().__init__(number, f"Login failed for user '{MARKER}'.".encode())


def _wrap(cls, orig):
    return cls("SELECT 1 WHERE name = %(v)s", {"v": MARKER}, orig)


def _empty_engine():
    return sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


# ── the sanitiser ─────────────────────────────────────────────────────────


def test_ac_46_06_an_unknown_query_failure_text_holds_no_driver_message():
    text = sanitize_error(_wrap(IntegrityError, PgLikeError("23505")))
    assert MARKER not in text
    assert "IntegrityError" in text and "23505" in text


def test_ac_46_06_a_refused_sql_server_login_gives_one_fixed_sentence():
    text = sanitize_error(_wrap(OperationalError, MssqlLikeError(18456)))
    assert MARKER not in text
    assert any(w in text.lower() for w in ("login", "sign in", "password", "credentials"))


def test_ac_46_06_a_refused_postgres_login_gives_one_fixed_sentence():
    text = sanitize_error(_wrap(OperationalError, PgLikeError("28P01")))
    assert MARKER not in text
    assert any(w in text.lower() for w in ("login", "sign in", "password", "credentials"))


# ── the test route ───────────────────────────────────────────────────────


def test_ac_46_06_the_test_connection_message_holds_no_driver_message():
    config = {
        "dbType": "postgresql", "host": "db.example.com", "port": "5432",
        "database": "sample", "username": "reader",
    }

    def factory(_config, _credentials):
        raise _wrap(OperationalError, PgLikeError("08006"))

    result = SqlDatabaseProvider().test(config, {"password": "placeholder-pw"}, engine_factory=factory)
    assert result.ok is False
    assert MARKER not in result.message
    assert "08006" in result.message


# ── the preview route ────────────────────────────────────────────────────


def test_ac_46_06_the_preview_error_response_holds_no_driver_message(client, session_factory):
    db = session_factory()
    conn = _sql_connection(db, engine=_empty_engine())
    db.close()
    response = client.post(
        "/autocount/sql/preview",
        json={"connectionId": conn.id, "query": f"SELECT * FROM {MISSING_TABLE}"},
        headers=_auth(client),
    )
    assert response.status_code == 400, response.text
    assert MARKER not in response.text
    RUNTIME.dispose_all()


# ── the call record, run, task, incident and email ──────────────────────


def _failing_executes(engine):
    """Make the source's execute raise a driver error whose message holds
    MARKER (as a driver echoes row data), while the query stays plain."""

    def boom(conn, cursor, statement, parameters, context, executemany):
        if "debtor" in statement.lower():
            raise _wrap(IntegrityError, PgLikeError("23505"))

    sa.event.listen(engine, "before_cursor_execute", boom)


def test_ac_46_06_the_call_record_of_a_failed_query_holds_no_driver_message(session_factory):
    from tests.test_autocount_sql_db_source import (
        _company, _configure, _source_engine, _sql_connection as _src_conn,
    )

    db = session_factory()
    try:
        engine = _source_engine()
        _failing_executes(engine)
        conn = _src_conn(db, engine)
        company = _company(db)
        config = _configure(db, company, connection_id=conn.id)
        source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER)
        with pytest.raises(SqlQueryError) as caught:
            source.fetch_changes(Watermark())
        calls = source.drain_activity()
        assert len(calls) == 1
        assert calls[0].error_message
        assert MARKER not in repr(calls)
        assert MARKER not in str(caught.value)
        assert calls[0].request["sql"].startswith("SELECT acc_no")
    finally:
        db.close()
        RUNTIME.dispose_all()


def test_ac_46_06_run_task_incident_and_email_hold_no_driver_message(session_factory, consumer):
    from modules.autocount.alerts import evaluate_integration_alerts

    company_id, _sql_id, engine = _make_rig(session_factory)
    _failing_executes(engine)
    db = session_factory()
    config = _config_row(db, company_id)
    config.activated_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()
    _only_recipients(db)
    _user(db, "ops-a@example.com", perms=[MANAGE])

    runs = []
    for _ in range(2):
        job = _run(db, company_id, RUN_MODE_INCREMENTAL)
        runs.append(_run_row(db, company_id, job.id))
    assert all(run.error for run in runs), "the runs must have failed with an error"
    for run in runs:
        assert MARKER not in run.error
    db.expire_all()
    assert _config_row(db, company_id).last_run_error
    assert MARKER not in _config_row(db, company_id).last_run_error
    assert MARKER not in (_watermark_row(db, company_id).last_error or "")

    evaluate_integration_alerts(db, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    incidents = db.query(AcTaskIncident).all()
    assert incidents, "two failed runs must open an incident"
    for incident in incidents:
        assert incident.last_error
        assert MARKER not in incident.last_error
    emails = db.query(EmailOutbox).all()
    assert emails, "the incident must send an alert email"
    for mail in emails:
        assert MARKER not in f"{mail.subject}{mail.html_body}{mail.text_body}"
    for row in db.query(IntegrationActivity).all():
        assert MARKER not in repr(
            (row.error_message, row.request_summary_json, row.response_summary_json)
        )
    db.close()
