"""Plan 47 (AC-47-01 to AC-47-04): a database error that is stored or emailed
is fixed text built by db_error_text, never the driver's message.

The driver message of every failure below holds MARKER (as a value the driver
echoes). Each stored surface is checked for it, and for the error class and
code that must still be present. Each test asserts its stub was reached so a
test cannot pass for the wrong reason.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError, OperationalError

from app.models.email_outbox import EmailOutbox
from modules.autocount.models import RUN_MODE_INCREMENTAL, AcTaskIncident

# Reused rig helpers and fixtures (the run loop with a scripted consumer).
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

MARKER = "zzmarker4747"


class PgLikeError(Exception):
    def __init__(self, pgcode):
        self.pgcode = pgcode
        self.diag = SimpleNamespace(constraint_name=None)
        super().__init__(f"server said no\nDETAIL:  Key (name)=({MARKER}) exists.\n")


def _db_error(cls=IntegrityError, code="23505"):
    return cls("INSERT INTO t (name) VALUES (%(v)s)", {"v": MARKER}, PgLikeError(code))


# ── AC-47-01: the Sorento sink's chunk commit ───────────────────────────────


def test_ac_47_01_a_chunk_commit_database_error_is_fixed_text_everywhere(session_factory, consumer, monkeypatch):
    from modules.autocount.alerts import evaluate_integration_alerts
    from modules.autocount.services.sync_service import SyncService

    reached = {"n": 0}
    real_commit_chunk = SyncService._commit_chunk

    def failing_commit_chunk(self, summary, *, sink):
        real_commit = self.db.commit

        def boom():
            reached["n"] += 1
            raise _db_error()

        self.db.commit = boom
        try:
            return real_commit_chunk(self, summary, sink=sink)
        finally:
            self.db.commit = real_commit

    monkeypatch.setattr(SyncService, "_commit_chunk", failing_commit_chunk)

    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(3))
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
    assert reached["n"] >= 2, "the chunk commit must have been reached on both runs"
    for run in runs:
        assert run.error, "the push failure must be stored on the run"
        assert MARKER not in run.error
        assert "IntegrityError" in run.error and "23505" in run.error, run.error
        assert MARKER not in str(run.first_failure or "")
    db.expire_all()
    task_error = _config_row(db, company_id).last_run_error
    assert task_error and MARKER not in task_error
    assert "IntegrityError" in task_error

    evaluate_integration_alerts(db, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    incidents = db.query(AcTaskIncident).all()
    assert incidents, "two failed pushes must open an incident"
    for incident in incidents:
        assert incident.last_error and MARKER not in incident.last_error
        assert "IntegrityError" in incident.last_error
    from modules.autocount.alerts import ALERT_EMAIL_SENTENCE

    emails = db.query(EmailOutbox).all()
    assert emails, "the incident must send an alert email"
    for mail in emails:
        body = f"{mail.subject}{mail.html_body}{mail.text_body}"
        assert MARKER not in body
        assert "IntegrityError" not in body
        assert "23505" not in body
        assert ALERT_EMAIL_SENTENCE in body
    db.close()


# ── AC-47-02: the scheduler's stored task error ─────────────────────────────


def test_ac_47_02_a_database_error_on_enqueue_stores_fixed_text(session_factory, monkeypatch):
    from app.jobs.service import JobService
    from modules.autocount.scheduler import sweep_etl_tasks
    from tests.test_autocount_scheduler import NOW, _company, _task

    db = session_factory()
    company = _company(db)
    config = _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    reached = {"n": 0}

    def raising_enqueue(self, **kwargs):
        reached["n"] += 1
        raise _db_error()

    monkeypatch.setattr(JobService, "create_and_enqueue", raising_enqueue)
    result = sweep_etl_tasks(db, now=NOW)

    assert reached["n"] == 1
    assert result == {"fired": 0, "skipped": 0, "failed": 1}
    db.refresh(config)
    assert config.last_run_error_code == "ENQUEUE_FAILED"
    assert config.last_run_error
    assert MARKER not in config.last_run_error
    assert "IntegrityError" in config.last_run_error and "23505" in config.last_run_error


# ── AC-47-03: the import engine's stored errors ─────────────────────────────


def _validated_job(client, session_factory):
    from tests.test_import_engine import _admin, _csv, _ident_map, _map_and_validate, _upload

    h = _admin(client)
    content = _csv("Email,Name\nfirst@e2e.com,First\n")
    job_id = _upload(client, h, content, "u.csv").json()["jobId"]
    return h, job_id, _ident_map(["Email", "Name"]), _map_and_validate


def _stored_errors(session_factory, job_id):
    from app.models.import_job import ImportJob

    db = session_factory()
    try:
        job = db.query(ImportJob).filter(ImportJob.id == job_id).one()
        return job.status, job.errors_json or []
    finally:
        db.close()


def test_ac_47_03_a_database_error_while_committing_an_import_stores_fixed_text(client, session_factory, monkeypatch):
    from app.import_engine.registry import get_importer
    from app.models.import_job import STATUS_FAILED

    h, job_id, mapping, map_and_validate = _validated_job(client, session_factory)
    assert map_and_validate(client, h, job_id, mapping).status_code == 200
    importer = get_importer("user")
    reached = {"n": 0}
    import dataclasses

    from app.import_engine import service as import_service

    def failing_create(db, tenant_id, rows, context):
        reached["n"] += 1
        raise _db_error()

    patched = dataclasses.replace(importer, create_rows=failing_create)
    monkeypatch.setattr(import_service, "get_importer", lambda _entity: patched)
    client.post(f"/imports/{job_id}/commit", headers=h)

    assert reached["n"] == 1
    status, errors = _stored_errors(session_factory, job_id)
    assert status == STATUS_FAILED
    assert errors, "the failure must be stored"
    text = " ".join(str(e.get("message")) for e in errors)
    assert MARKER not in text
    assert "IntegrityError" in text and "23505" in text, text


def test_ac_47_03_a_database_error_while_validating_an_import_stores_fixed_text(client, session_factory, monkeypatch):
    from app.import_engine.service import ImportService
    from app.models.import_job import STATUS_FAILED

    h, job_id, mapping, map_and_validate = _validated_job(client, session_factory)
    reached = {"n": 0}

    def failing_prepare(self, job, importer):
        reached["n"] += 1
        raise _db_error(OperationalError, "08006")

    monkeypatch.setattr(ImportService, "_prepare", failing_prepare)
    map_and_validate(client, h, job_id, mapping)

    assert reached["n"] >= 1
    status, errors = _stored_errors(session_factory, job_id)
    assert status == STATUS_FAILED
    text = " ".join(str(e.get("message")) for e in errors)
    assert MARKER not in text
    assert "OperationalError" in text and "08006" in text, text


# ── AC-47-04: the gateway activity log's stored error message ───────────────


def test_ac_47_04_a_database_error_in_a_gateway_request_stores_fixed_text(client, session_factory, monkeypatch):
    from app.models.integration_activity import IntegrationActivity
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService
    from tests.conftest import DEFAULT_TENANT_ID
    from tests.test_omnichannel_api_gateway import _default_workspace_id, _mint

    ws = _default_workspace_id(session_factory)
    key = _mint(client, ws).json()["fullKey"]
    reached = {"n": 0}

    def failing_list(self, *args, **kwargs):
        reached["n"] += 1
        raise _db_error()

    monkeypatch.setattr(PublicGatewayService, "list_channels", failing_list)
    try:
        client.get("/api/v1/omnichannel/channels", headers={"Authorization": f"Bearer {key}"})
    except Exception:  # noqa: BLE001 - the app may re-raise to the test client
        pass

    assert reached["n"] == 1
    db = session_factory()
    try:
        rows = (
            db.query(IntegrationActivity)
            .filter(IntegrationActivity.tenant_id == DEFAULT_TENANT_ID, IntegrationActivity.operation.like("%/channels"))
            .all()
        )
    finally:
        db.close()
    assert rows, "the failed request must be logged"
    for row in rows:
        assert row.error_message
        assert MARKER not in row.error_message
        assert "IntegrityError" in row.error_message and "23505" in row.error_message, row.error_message
