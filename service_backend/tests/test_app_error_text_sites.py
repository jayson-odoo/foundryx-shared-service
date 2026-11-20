"""Plan 46 (AC-46-07): the workflow node error, the deferred action error and
the document download error store fixed text, never the driver's message."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.deferred_actions.registry import DeferredActionDef, register_deferred_action
from app.deferred_actions.service import PendingActionService
from app.models import DEFAULT_TENANT_ID, User
from app.models.document import DOWNLOAD_FAILED, DownloadJob
from app.models.pending_action import PENDING_ACTION_FAILED, PendingAction
from app.models.workflow import RUN_PENDING, Workflow, WorkflowRun
from tests.conftest import ACTIVE_EMAIL

MARKER = "zz-placeholder-marker-9137"


class PgLikeError(Exception):
    def __init__(self):
        self.pgcode = "23505"
        self.diag = SimpleNamespace(constraint_name="sample_name_key")
        super().__init__(f"duplicate key\nDETAIL:  Key (name)=({MARKER}) already exists.\n")


def _db_error() -> IntegrityError:
    return IntegrityError(
        "INSERT INTO sample_table (name) VALUES (%(v)s)", {"v": MARKER}, PgLikeError()
    )


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ── workflow node error ─────────────────────────────────────────────────


def _two_node_run(db):
    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}},
            {"id": "n1", "kind": "action", "type": "redis.command",
             "config": {"operation": "get", "key": "k"}, "position": {}},
        ],
        "edges": [{"id": "e1", "source": "trigger", "target": "n1"}],
    }
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID, name="Sample", description="", draft_definition_json=doc
    )
    db.add(workflow)
    db.flush()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID, workflow_id=workflow.id, status=RUN_PENDING,
        definition_snapshot_json=doc, trigger_payload_json={"triggeredBy": "manual"},
    )
    db.add(run)
    db.commit()
    return run


def _failing_node(monkeypatch):
    import app.workflow_engine.executor as executor

    real = executor._execute_node
    reached = {"n": 0}

    def fake(db, tenant_id, node, ctx):
        if node.id == "n1":
            reached["n"] += 1
            raise _db_error()
        return real(db, tenant_id, node, ctx)

    monkeypatch.setattr(executor, "_execute_node", fake)
    return reached


def test_ac_46_07_a_failed_workflow_node_stores_no_driver_message(db, monkeypatch):
    from app.workflow_engine.executor import run_workflow

    run = _two_node_run(db)
    reached = _failing_node(monkeypatch)
    result = run_workflow(db, run.id)
    assert reached["n"] == 1
    errors = [n.error for n in result.nodes if n.error]
    assert errors, "the failed node must carry an error"
    for error in errors:
        assert MARKER not in error
        assert "IntegrityError" in error
    assert MARKER not in (result.error or "")


def test_ac_46_07_a_failed_node_in_a_debug_rerun_returns_no_driver_message(db, monkeypatch):
    from app.workflow_engine.executor import debug_execute

    run = _two_node_run(db)
    reached = _failing_node(monkeypatch)
    touched = debug_execute(db, run, target_node_id="n1", scratch={}, stale_node_ids=[])
    assert reached["n"] == 1
    failed = [t for t in touched if t.get("error")]
    assert failed
    for item in failed:
        assert MARKER not in item["error"]


# ── deferred action error ───────────────────────────────────────────────


def _explode(*_args, **_kwargs):
    raise _db_error()


EXPLODING = DeferredActionDef(
    key="sample.explode",
    entity_type="sample",
    permission="users.delete",
    window="destructive",
    label="Explode",
    execute=_explode,
    exists=lambda *a, **k: True,
)


def test_ac_46_07_a_failed_deferred_action_stores_no_driver_message(db):
    register_deferred_action(EXPLODING)
    admin = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
    service = PendingActionService(db)
    row = service.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key="sample.explode", entity_type="sample", entity_id="s-1",
    )
    pending = db.get(PendingAction, row.id)
    pending.commit_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    assert service.commit_due() == 1
    settled = db.get(PendingAction, row.id)
    assert settled.status == PENDING_ACTION_FAILED
    assert settled.error_text
    assert MARKER not in settled.error_text
    assert "IntegrityError" in settled.error_text


# ── document download error ─────────────────────────────────────────────


def test_ac_46_07_a_failed_download_build_stores_no_driver_message(db, monkeypatch):
    import app.services.document_service as document_service

    class FailingStorage:
        def save(self, *_args, **_kwargs):
            raise _db_error()

    monkeypatch.setattr(document_service, "storage_for_tenant", lambda *a, **k: FailingStorage())
    admin = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
    job = DownloadJob(
        tenant_id=DEFAULT_TENANT_ID, user_id=admin.id, filename="sample.zip", file_count=0
    )
    db.add(job)
    db.commit()

    document_service.DocumentService(db)._build_zip(DEFAULT_TENANT_ID, job.id, [])
    db.expire_all()
    stored = db.get(DownloadJob, job.id)
    assert stored.status == DOWNLOAD_FAILED
    assert stored.error
    assert MARKER not in stored.error
    assert "IntegrityError" in stored.error
