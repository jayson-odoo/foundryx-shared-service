"""Plan 47 (AC-47-05): a message the code builds for operators, with no driver
text in it, keeps its wording at every site that stores an error."""
import dataclasses
from datetime import timedelta

import pytest

PLAIN = "plain operator note 4747"


def test_ac_47_05_a_non_database_sink_fault_keeps_its_wording():
    from modules.autocount.services.sync_service import SyncService

    summary = {}
    SyncService(None)._account_failure(summary, RuntimeError(PLAIN), sink=None)
    assert summary["error"] == f"Consumer error: {PLAIN}"
    assert summary["firstFailure"]["message"] == f"Consumer error: {PLAIN}"


def test_ac_47_05_a_consumer_status_fault_keeps_its_wording():
    from modules.autocount.services.sync_service import SyncService

    class Refused(Exception):
        status_code = 500
        body = "upstream said no"

    summary = {}
    SyncService(None)._account_failure(summary, Refused(), sink=None)
    assert summary["error"] == "Consumer said: HTTP 500 upstream said no"


def test_ac_47_05_a_non_database_enqueue_fault_keeps_its_wording(session_factory, monkeypatch):
    from app.jobs.service import JobService
    from modules.autocount.scheduler import sweep_etl_tasks
    from tests.test_autocount_scheduler import NOW, _company, _task

    db = session_factory()
    company = _company(db)
    config = _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    reached = {"n": 0}

    def raising_enqueue(self, **kwargs):
        reached["n"] += 1
        raise RuntimeError(PLAIN)

    monkeypatch.setattr(JobService, "create_and_enqueue", raising_enqueue)
    sweep_etl_tasks(db, now=NOW)
    assert reached["n"] == 1
    db.refresh(config)
    assert config.last_run_error == f"Scheduled run could not be enqueued: {PLAIN}"


def _errors(session_factory, job_id):
    from app.models.import_job import ImportJob

    db = session_factory()
    try:
        return db.query(ImportJob).filter(ImportJob.id == job_id).one().errors_json or []
    finally:
        db.close()


def test_ac_47_05_a_row_validation_message_keeps_its_wording(client, session_factory):
    from tests.test_import_engine import _admin, _csv, _ident_map, _map_and_validate, _upload

    h = _admin(client)
    job_id = _upload(client, h, _csv("Email,Name\nnotanemail,Bad\n"), "u.csv").json()["jobId"]
    _map_and_validate(client, h, job_id, _ident_map(["Email", "Name"]))
    errors = _errors(session_factory, job_id)
    assert errors and all(e["row"] != 0 for e in errors)
    assert any(e["column"] == "email" and e["message"] for e in errors)
    update_only = _upload(client, h, _csv("ID,Email\nmissing-id,x@e2e.com\n"), "v.csv", mode="update_only").json()["jobId"]
    _map_and_validate(client, h, update_only, _ident_map(["ID", "Email"]))
    assert any(e["message"] == "no record with this id" for e in _errors(session_factory, update_only))


def test_ac_47_05_a_non_database_commit_fault_keeps_its_wording(client, session_factory, monkeypatch):
    from app.import_engine import service as import_service
    from app.import_engine.registry import get_importer
    from tests.test_import_engine import _admin, _csv, _ident_map, _map_and_validate, _upload

    h = _admin(client)
    job_id = _upload(client, h, _csv("Email,Name\nfirst@e2e.com,First\n"), "u.csv").json()["jobId"]
    assert _map_and_validate(client, h, job_id, _ident_map(["Email", "Name"])).status_code == 200
    reached = {"n": 0}

    def failing_create(db, tenant_id, rows, context):
        reached["n"] += 1
        raise RuntimeError(PLAIN)

    patched = dataclasses.replace(get_importer("user"), create_rows=failing_create)
    monkeypatch.setattr(import_service, "get_importer", lambda _entity: patched)
    client.post(f"/imports/{job_id}/commit", headers=h)
    assert reached["n"] == 1
    assert _errors(session_factory, job_id)[0]["message"] == f"Commit failed: {PLAIN}"


def test_ac_47_05_a_non_database_gateway_fault_keeps_its_wording(client, session_factory, monkeypatch):
    from app.models.integration_activity import IntegrationActivity
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService
    from tests.conftest import DEFAULT_TENANT_ID
    from tests.test_omnichannel_api_gateway import _default_workspace_id, _mint

    ws = _default_workspace_id(session_factory)
    key = _mint(client, ws).json()["fullKey"]
    reached = {"n": 0}

    def failing_list(self, *args, **kwargs):
        reached["n"] += 1
        raise RuntimeError(PLAIN)

    monkeypatch.setattr(PublicGatewayService, "list_channels", failing_list)
    try:
        client.get("/api/v1/omnichannel/channels", headers={"Authorization": f"Bearer {key}"})
    except Exception:  # noqa: BLE001
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
    assert [r.error_message for r in rows] == [f"RuntimeError: {PLAIN}"]
