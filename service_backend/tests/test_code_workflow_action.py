"""S4 ``code.run`` workflow action + permission + publish tests (AC-SAR-62..70)."""
import json

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import RUN_PENDING, Workflow, WorkflowRun, WorkflowRunNode, WorkflowVersion
from app.workflow_engine.code_runner import (
    CodeRunResult,
    CodeRunnerUnavailable,
    code_runner_available,
    use_code_runner_client,
)


class FakeRunner:
    def __init__(self, *, healthy=True, result=None, fail=None, termination="completed", error=""):
        self.healthy = healthy
        self.result = result
        self.fail = fail
        self.termination = termination
        self.error = error
        self.jobs = []

    def run(self, source, inputs):
        self.jobs.append({"source": source, "input": inputs})
        if self.fail:
            raise self.fail
        return CodeRunResult(
            ok=self.result is not None,
            termination=self.termination if self.result is None else "completed",
            result=self.result,
            error=self.error,
            stdout="log line\n",
            stderr="",
            duration_ms=7,
            runner_version="test",
        )

    def health(self):
        return self.healthy


def _actor(db, email="demo@example.com"):
    from app.models import User

    return db.query(User).filter(User.email == email).one()


def _doc(source="result = {'summary': input['task'] + '!'}", outputs=None, inputs=None):
    return {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trigger", "kind": "trigger", "type": "manual", "config": {"inputs": [{"key": "task", "label": "Task"}]}, "position": {}},
            {
                "id": "code_1",
                "kind": "action",
                "type": "code.run",
                "config": {
                    "language": "python",
                    "source": source,
                    "inputs": inputs if inputs is not None else [{"key": "task", "value": "{{ trigger.input.task }}"}],
                    "outputs": outputs or [{"key": "summary", "type": "string", "required": True}],
                },
                "position": {},
            },
            {"id": "after", "kind": "action", "type": "redis.command", "config": {"operation": "get", "key": "{{ nodes.code_1.summary }}"}, "position": {}},
        ],
        "edges": [
            {"id": "e1", "source": "trigger", "target": "code_1"},
            {"id": "e2", "source": "code_1", "target": "after"},
        ],
    }


def _execute(db, doc, payload=None):
    workflow = Workflow(tenant_id=DEFAULT_TENANT_ID, name="Code", description="", draft_definition_json=doc)
    db.add(workflow)
    db.flush()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        definition_snapshot_json=doc,
        trigger_payload_json=payload or {"triggeredBy": "manual", "input": {"task": "Launch"}},
    )
    db.add(run)
    db.commit()
    from app.workflow_engine.executor import run_workflow

    result = run_workflow(db, run.id)
    nodes = {n.node_id: n for n in db.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run.id).all()}
    return result, nodes


@pytest.fixture
def fake_redis():
    import fakeredis

    from app.workflow_engine.actions.redis_actions import use_workflow_redis_client

    with use_workflow_redis_client(fakeredis.FakeRedis(decode_responses=True)):
        yield


def test_worker_submits_rendered_inputs_and_flattens_validated_outputs(session_factory, fake_redis):
    db = session_factory()
    runner = FakeRunner(result={"summary": "Launch!", "undeclared": "dropped"})
    with use_code_runner_client(runner):
        result, nodes = _execute(db, _doc())
    assert result.status == "success"
    assert runner.jobs == [{"source": "result = {'summary': input['task'] + '!'}", "input": {"task": "Launch"}}]
    out = nodes["code_1"].output_json
    assert out["summary"] == "Launch!" and "undeclared" not in out
    assert out["runtime"]["stdout"] == "log line\n" and out["runtime"]["termination"] == "completed"
    assert out["runtime"]["input"] == {"task": "Launch"} and out["runtime"]["runnerVersion"] == "test"
    assert nodes["after"].status == "success"  # {{ nodes.code_1.summary }} resolved


def test_mistyped_or_missing_required_output_fails_only_the_code_node(session_factory, fake_redis):
    db = session_factory()
    with use_code_runner_client(FakeRunner(result={"summary": 42})):
        result, nodes = _execute(db, _doc())
    assert result.status == "failed" and "does not match its declared type" in nodes["code_1"].error
    assert nodes["after"].status == "skipped"
    db2 = session_factory()
    with use_code_runner_client(FakeRunner(result={"other": "x"})):
        result, nodes = _execute(db2, _doc())
    assert "required" in nodes["code_1"].error


def test_runner_failures_and_transport_errors_stay_bounded_and_redacted(session_factory, fake_redis):
    db = session_factory()
    with use_code_runner_client(FakeRunner(termination="timeout", error="Code exceeded the 5s time limit.")):
        result, nodes = _execute(db, _doc())
    assert result.status == "failed" and "time limit" in nodes["code_1"].error
    assert nodes["code_1"].input_json["runtime"]["termination"] == "timeout"
    db2 = session_factory()
    with use_code_runner_client(FakeRunner(fail=CodeRunnerUnavailable("runner rejected the job (401) http://code-runner:8011 token=abc"))):
        result, nodes = _execute(db2, _doc())
    assert nodes["code_1"].error == "The Code runner is unavailable."
    assert "8011" not in json.dumps([nodes["code_1"].input_json, nodes["code_1"].output_json, nodes["code_1"].error])
    db3 = session_factory()
    with use_code_runner_client(False):
        result, nodes = _execute(db3, _doc())
    assert nodes["code_1"].error == "The Code runner is not configured."


def test_worker_never_executes_source_locally(session_factory, fake_redis):
    """A source that would raise loudly if evaluated in-process is only ever
    forwarded to the runner client."""
    db = session_factory()
    poison = "raise RuntimeError('executed locally')\nresult = {'summary': 'x'}"
    runner = FakeRunner(result={"summary": "from-runner"})
    with use_code_runner_client(runner):
        result, nodes = _execute(db, _doc(source=poison))
    assert result.status == "success" and nodes["code_1"].output_json["summary"] == "from-runner"
    assert runner.jobs[0]["source"] == poison
    import app.workflow_engine.actions.code_actions as module

    import re

    text = open(module.__file__).read()
    # No interpreter entry point in the worker-side action (re.compile is a regex).
    assert re.search(r"(?<![\w.])(exec|eval|compile|__import__)\(", text) is None


def test_publish_gate_rejects_policy_and_input_mapping_issues():
    from app.workflow_engine.schemas import definition_issues, parse_definition

    doc = parse_definition(_doc(source="import os\nresult = {}", inputs=[{"key": "1bad", "value": "x"}, {"key": "dup", "value": "a"}, {"key": "dup", "value": "b"}]))
    issues = definition_issues(doc)
    assert any("Unsupported syntax" in i for i in issues)
    assert any('"1bad"' in i for i in issues)
    assert any("duplicate input name" in i for i in issues)


def _limited_editor(db):
    """A user holding workflows.read/manage/run but NOT workflows.code."""
    from app.models import Role, User, UserStatus
    from app.repositories.permission_repository import PermissionRepository
    from app.security import hash_password

    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Workflow editor", is_system=False)
    db.add(role)
    db.flush()
    wanted = {"workflows.read", "workflows.manage", "workflows.run"}
    role.permissions = [p for p in PermissionRepository(db).list_all() if p.key in wanted]
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="editor@example.com",
        name="Editor",
        password=hash_password("editor1234"),
        status=UserStatus.ACTIVE.value,
        roles=[role],
    )
    db.add(user)
    db.commit()
    return user


def test_workflows_code_permission_gates_create_update_publish_and_run(session_factory):
    from app.dependencies import effective_permission_keys
    from app.services.workflow_service import WorkflowPermissionError, WorkflowService

    db = session_factory()
    admin = _actor(db)
    service = WorkflowService(db)
    assert "workflows.code" in effective_permission_keys(admin)  # seeded Admin grant
    wf = service.create(DEFAULT_TENANT_ID, name="Code", description="", draft=_doc(), actor_id=admin.id, actor=admin)
    limited = _limited_editor(db)
    assert "workflows.code" not in effective_permission_keys(limited)
    with pytest.raises(WorkflowPermissionError):
        service.create(DEFAULT_TENANT_ID, name="Nope", description="", draft=_doc(), actor_id=limited.id, actor=limited)
    with pytest.raises(WorkflowPermissionError):
        service.update(wf.id, DEFAULT_TENANT_ID, name="Code", description="", draft=_doc(), actor=limited)
    with pytest.raises(WorkflowPermissionError):
        service.run(wf.id, DEFAULT_TENANT_ID, inputs={"task": "x"}, is_test=True, actor=limited)
    with pytest.raises(WorkflowPermissionError):
        service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=limited.id, actor=limited)
    # Non-code graphs are untouched by the new permission.
    plain = {"schemaVersion": 2, "nodes": [{"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}}], "edges": []}
    assert service.create(DEFAULT_TENANT_ID, name="Plain", description="", draft=plain, actor_id=limited.id, actor=limited).id


def test_http_boundary_returns_403_without_workflows_code(client, session_factory):
    db = session_factory()
    _limited_editor(db)
    db.close()
    res = client.post("/auth/login", json={"email": "editor@example.com", "password": "editor1234"})
    hdrs = {"Authorization": f"Bearer {res.json()['access_token']}"}
    body = {"name": "Code", "description": "", "draftDefinition": _doc()}
    assert client.post("/workflows", json=body, headers=hdrs).status_code == 403
    body["draftDefinition"] = {"schemaVersion": 2, "nodes": [{"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}}], "edges": []}
    assert client.post("/workflows", json=body, headers=hdrs).status_code in (200, 201)


def test_publish_requires_runner_health_and_stamps_authorization(session_factory):
    from app.services.workflow_service import CodeRunnerRequired, WorkflowService

    db = session_factory()
    admin = _actor(db)
    service = WorkflowService(db)
    wf = service.create(DEFAULT_TENANT_ID, name="Code", description="", draft=_doc(), actor_id=admin.id, actor=admin)
    with use_code_runner_client(FakeRunner(healthy=False)):
        assert code_runner_available(force=True) is False
        with pytest.raises(CodeRunnerRequired):
            service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=admin.id, actor=admin)
        assert service.metadata(DEFAULT_TENANT_ID)["codeRunnerAvailable"] is False
    with use_code_runner_client(FakeRunner(healthy=True)):
        published = service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=admin.id, actor=admin)
        version = db.query(WorkflowVersion).filter(WorkflowVersion.id == published.current_version_id).one()
        assert version.code_authorized_by == admin.id
        meta = service.metadata(DEFAULT_TENANT_ID)
        assert meta["codeRunnerAvailable"] is True and len(meta["codeCapabilities"]) == 5


def test_retry_executes_the_published_snapshot_not_a_later_draft(session_factory, fake_redis):
    from app.services.workflow_service import WorkflowService

    db = session_factory()
    admin = _actor(db)
    service = WorkflowService(db)
    wf = service.create(DEFAULT_TENANT_ID, name="Code", description="", draft=_doc(source="result = {'summary': 'v1'}"), actor_id=admin.id, actor=admin)
    with use_code_runner_client(FakeRunner(healthy=True)):
        service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=admin.id, actor=admin)
    service.update(wf.id, DEFAULT_TENANT_ID, name="Code", description="", draft=_doc(source="result = {'summary': 'draft'}"), actor=admin)
    version = db.query(WorkflowVersion).filter(WorkflowVersion.id == wf.current_version_id).one()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=wf.id,
        version_id=version.id,
        version_number=version.version_number,
        status=RUN_PENDING,
        triggered_by="event",
        definition_snapshot_json=json.loads(json.dumps(version.definition_json)),
        trigger_payload_json={"triggeredBy": "event", "input": {"task": "t"}},
    )
    db.add(run)
    db.commit()
    runner = FakeRunner(result={"summary": "ok"})
    from app.workflow_engine.executor import run_workflow

    with use_code_runner_client(runner):
        run_workflow(db, run.id)
    assert runner.jobs[0]["source"] == "result = {'summary': 'v1'}"


def test_automated_triggers_skip_unstamped_code_versions(session_factory):
    from app.workflow_engine.entity_events import _create_run

    db = session_factory()
    admin = _actor(db)
    from app.services.workflow_service import WorkflowService

    service = WorkflowService(db)
    wf = service.create(DEFAULT_TENANT_ID, name="Code", description="", draft=_doc(), actor_id=admin.id, actor=admin)
    with use_code_runner_client(FakeRunner(healthy=True)):
        service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=admin.id, actor=admin)
    version = db.query(WorkflowVersion).filter(WorkflowVersion.id == wf.current_version_id).one()
    version.code_authorized_by = None  # simulate a tampered/legacy stamp
    db.commit()
    before = db.query(WorkflowRun).count()
    _create_run(db, wf, {"entity_type": "user", "action": "created", "tenant_id": DEFAULT_TENANT_ID, "record_id": "x", "actor": {}, "changes": {}, "record_facts": {}}, depth=0)
    db.commit()
    assert db.query(WorkflowRun).count() == before
