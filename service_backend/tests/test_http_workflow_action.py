"""``http.request`` core workflow action + ``workflows.http`` permission tests
(plan sprint-4/31 S5, AC-WFP-57..62)."""
import json

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import RUN_PENDING, Workflow, WorkflowRun, WorkflowRunNode


def _actor(db, email="demo@example.com"):
    from app.models import User

    return db.query(User).filter(User.email == email).one()


class _FakeStream:
    """A context manager shaped like ``httpx.stream(...)``'s return value."""

    def __init__(self, *, status_code=200, headers=None, body=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self):
        chunk = 4096
        for i in range(0, len(self._body), chunk):
            yield self._body[i : i + chunk]


@pytest.fixture
def fake_http(monkeypatch):
    """Patch ``http_actions.httpx.stream``; return the call log + a settable
    response/exception. Mirrors the pre-existing webhook-delivery tests'
    ``monkeypatch.setattr(wd.httpx, "post", ...)`` shape."""
    import app.workflow_engine.actions.http_actions as http_actions

    calls = []
    state = {"responses": [], "raise": None}

    def fake_stream(method, url, *, headers=None, content=None, timeout=None, follow_redirects=None):
        calls.append(
            {"method": method, "url": url, "headers": dict(headers or {}), "content": content}
        )
        if state["raise"]:
            raise state["raise"]
        if state["responses"]:
            return state["responses"].pop(0)
        return _FakeStream(status_code=200, headers={"content-type": "text/plain"}, body=b"ok")

    monkeypatch.setattr(http_actions.httpx, "stream", fake_stream)
    return calls, state


def _doc(config, *, second=None):
    nodes = [
        {"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}},
        {"id": "http_1", "kind": "action", "type": "http.request", "config": config, "position": {}},
    ]
    edges = [{"id": "e1", "source": "trigger", "target": "http_1"}]
    if second is not None:
        nodes.append({"id": "http_2", "kind": "action", "type": "http.request", "config": second, "position": {}})
        edges.append({"id": "e2", "source": "http_1", "target": "http_2"})
    return {"schemaVersion": 2, "nodes": nodes, "edges": edges}


def _execute(db, doc, payload=None):
    workflow = Workflow(tenant_id=DEFAULT_TENANT_ID, name="Http", description="", draft_definition_json=doc)
    db.add(workflow)
    db.flush()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        definition_snapshot_json=doc,
        trigger_payload_json=payload or {"triggeredBy": "manual", "input": {}},
    )
    db.add(run)
    db.commit()
    from app.workflow_engine.executor import run_workflow

    result = run_workflow(db, run.id)
    nodes = {n.node_id: n for n in db.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run.id).all()}
    return result, nodes


# ── AC-WFP-57: method/url/headers/body merge-rendered, outputs ─────────────


def test_sends_configured_method_url_headers_body_and_captures_json_output(session_factory, fake_http):
    calls, state = fake_http
    state["responses"] = [
        _FakeStream(
            status_code=200,
            headers={"content-type": "application/json"},
            body=json.dumps({"user": {"id": "123", "name": "Ada"}}).encode(),
        )
    ]
    doc = _doc(
        {
            "method": "POST",
            "url": "https://api.example.com/users/{{ trigger.input.userId }}",
            "headers": [{"key": "Authorization", "value": "Bearer {{ trigger.input.token }}"}],
            "bodyMode": "json",
            "body": '{"name": "{{ trigger.input.name }}"}',
            "timeoutSeconds": "5",
        }
    )
    db = session_factory()
    result, nodes = _execute(
        db, doc,
        payload={"triggeredBy": "manual", "input": {"userId": "77", "token": "secret-abc", "name": "Grace"}},
    )
    assert result.status == "success"
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.example.com/users/77"
    assert call["headers"]["Authorization"] == "Bearer secret-abc"
    assert call["content"] == b'{"name": "Grace"}'

    out = nodes["http_1"].output_json
    assert out["statusCode"] == 200
    assert out["ok"] is True
    assert out["json.user.id"] == "123"
    assert out["json.user.name"] == "Ada"
    assert isinstance(out["durationMs"], int)


def test_downstream_node_resolves_the_json_dotted_path_output(session_factory, fake_http):
    """Proves the flat-dotted contract end-to-end: `nodes.http_1.json.user.id`
    resolves through the SAME merge renderer every other output uses."""
    calls, state = fake_http
    state["responses"] = [
        _FakeStream(
            status_code=200,
            headers={"content-type": "application/json"},
            body=json.dumps({"user": {"id": "77"}}).encode(),
        ),
        _FakeStream(status_code=200, headers={"content-type": "text/plain"}, body=b"ok"),
    ]
    first = {"method": "GET", "url": "https://api.example.com/whoami", "timeoutSeconds": "5"}
    second = {
        "method": "GET",
        "url": "https://api.example.com/users/{{ nodes.http_1.json.user.id }}",
        "timeoutSeconds": "5",
    }
    doc = _doc(first, second=second)
    db = session_factory()
    result, nodes = _execute(db, doc)
    assert result.status == "success"
    assert calls[1]["url"] == "https://api.example.com/users/77"


# ── AC-WFP-58: the SSRF guard runs BEFORE every request, one shared guard ──


def test_ssrf_guard_refuses_private_targets_and_sends_nothing(session_factory, fake_http):
    calls, _state = fake_http
    doc = _doc({"method": "GET", "url": "https://169.254.169.254/latest/meta-data", "timeoutSeconds": "5"})
    db = session_factory()
    result, nodes = _execute(db, doc)
    assert result.status == "failed"
    assert "refused" in nodes["http_1"].error.lower()
    assert calls == []  # no request was ever sent


def test_ssrf_guard_is_the_shared_core_guard(monkeypatch):
    """Same implementation the consumer-webhook delivery guard delegates to."""
    from app.services.url_guard import UrlGuardError, assert_deliverable
    from app.workflow_engine.actions.http_actions import http_request

    with pytest.raises(UrlGuardError):
        assert_deliverable("http://example.com")  # non-https, same guard
    with pytest.raises(Exception):
        http_request(None, DEFAULT_TENANT_ID, {"method": "GET", "url": "http://example.com"}, {})


# ── AC-WFP-59: header values never traced; response truncation + non-text ──


def test_header_values_never_reach_the_run_trace(session_factory, fake_http):
    """The header VALUE is authored as a merge TOKEN (never a literal secret
    typed into the graph) - the trace must never show the RESOLVED secret,
    only the unrendered token the author typed (the graph's own content, not
    a leak)."""
    calls, state = fake_http
    state["responses"] = [_FakeStream(status_code=200, headers={"content-type": "text/plain"}, body=b"ok")]
    doc = _doc(
        {
            "method": "GET",
            "url": "https://api.example.com/ping",
            "headers": [{"key": "Authorization", "value": "Bearer {{ trigger.input.token }}"}],
            "timeoutSeconds": "5",
        }
    )
    db = session_factory()
    result, nodes = _execute(
        db, doc, payload={"triggeredBy": "manual", "input": {"token": "super-secret-token"}}
    )
    assert result.status == "success"
    # The actual header VALUE was sent (merge-rendered at request time)...
    assert calls[0]["headers"]["Authorization"] == "Bearer super-secret-token"
    # ...but the RESOLVED secret never reaches the run's trace - only the
    # unrendered `{{ trigger.input.token }}` token the author typed (via the
    # raw `config`, which every action stores regardless).
    trace = json.dumps(nodes["http_1"].input_json)
    assert "super-secret-token" not in trace
    assert "{{ trigger.input.token }}" in trace
    assert nodes["http_1"].input_json.get("resolved") is None or "headers" not in (
        nodes["http_1"].input_json.get("resolved") or {}
    )


def test_response_body_truncated_at_the_cap(session_factory, fake_http, monkeypatch):
    import app.workflow_engine.actions.http_actions as http_actions

    monkeypatch.setattr(http_actions, "MAX_RESPONSE_BYTES", 10)
    calls, state = fake_http
    state["responses"] = [
        _FakeStream(status_code=200, headers={"content-type": "text/plain"}, body=b"x" * 100)
    ]
    doc = _doc({"method": "GET", "url": "https://api.example.com/big", "timeoutSeconds": "5"})
    db = session_factory()
    result, nodes = _execute(db, doc)
    assert result.status == "success"
    assert "(truncated)" in nodes["http_1"].output_json["body"]


def test_non_text_response_records_size_and_content_type_only(session_factory, fake_http):
    calls, state = fake_http
    state["responses"] = [
        _FakeStream(
            status_code=200,
            headers={"content-type": "image/png"},
            body=b"\x89PNG\r\n\x1a\nBINARYJUNK",
        )
    ]
    doc = _doc({"method": "GET", "url": "https://api.example.com/logo.png", "timeoutSeconds": "5"})
    db = session_factory()
    result, nodes = _execute(db, doc)
    assert result.status == "success"
    out = nodes["http_1"].output_json
    assert "image/png" in out["body"]
    assert "PNG" not in out["body"]
    assert "json" not in out


# ── AC-WFP-60: non-2xx / transport errors fail the node, downstream skips ──


def test_non_2xx_fails_the_node_with_status_code_and_skips_downstream(session_factory, fake_http):
    calls, state = fake_http
    state["responses"] = [_FakeStream(status_code=500, headers={}, body=b"boom")]
    first = {"method": "GET", "url": "https://api.example.com/fail", "timeoutSeconds": "5"}
    second = {"method": "GET", "url": "https://api.example.com/never-called", "timeoutSeconds": "5"}
    doc = _doc(first, second=second)
    db = session_factory()
    result, nodes = _execute(db, doc)
    assert result.status == "failed"
    assert "500" in nodes["http_1"].error
    assert nodes["http_2"].status == "skipped"
    assert len(calls) == 1  # the second node's request was never sent


def test_transport_error_fails_the_node_with_the_error_class(session_factory, fake_http):
    _calls, state = fake_http
    state["raise"] = httpx.ConnectTimeout("timed out")
    doc = _doc({"method": "GET", "url": "https://api.example.com/slow", "timeoutSeconds": "5"})
    db = session_factory()
    result, nodes = _execute(db, doc)
    assert result.status == "failed"
    assert "ConnectTimeout" in nodes["http_1"].error


# ── AC-WFP-62: a json body mode must parse as JSON before sending ──────────


def test_unparseable_json_body_fails_before_any_request_is_sent(session_factory, fake_http):
    calls, _state = fake_http
    doc = _doc(
        {
            "method": "POST",
            "url": "https://api.example.com/create",
            "bodyMode": "json",
            "body": "{not valid json",
            "timeoutSeconds": "5",
        }
    )
    db = session_factory()
    result, nodes = _execute(db, doc)
    assert result.status == "failed"
    assert "not valid json" in nodes["http_1"].error.lower()
    assert calls == []


# ── AC-WFP-61: workflows.http gates create/update/publish/manual run ───────


def _limited_editor(db):
    """A user holding workflows.read/manage/run but NOT workflows.http."""
    from app.models import Role, User, UserStatus
    from app.repositories.permission_repository import PermissionRepository
    from app.security import hash_password

    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Workflow editor (no http)", is_system=False)
    db.add(role)
    db.flush()
    wanted = {"workflows.read", "workflows.manage", "workflows.run"}
    role.permissions = [p for p in PermissionRepository(db).list_all() if p.key in wanted]
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="http-editor@example.com",
        name="Editor",
        password=hash_password("editor1234"),
        status=UserStatus.ACTIVE.value,
        roles=[role],
    )
    db.add(user)
    db.commit()
    return user


def _http_doc():
    return _doc({"method": "GET", "url": "https://api.example.com/x", "timeoutSeconds": "5"})


def test_workflows_http_permission_gates_create_update_publish_and_run(session_factory):
    from app.dependencies import effective_permission_keys
    from app.services.workflow_service import WorkflowPermissionError, WorkflowService

    db = session_factory()
    admin = _actor(db)
    service = WorkflowService(db)
    assert "workflows.http" in effective_permission_keys(admin)  # seeded Admin grant
    wf = service.create(DEFAULT_TENANT_ID, name="Http", description="", draft=_http_doc(), actor_id=admin.id, actor=admin)
    limited = _limited_editor(db)
    assert "workflows.http" not in effective_permission_keys(limited)
    with pytest.raises(WorkflowPermissionError):
        service.create(DEFAULT_TENANT_ID, name="Nope", description="", draft=_http_doc(), actor_id=limited.id, actor=limited)
    with pytest.raises(WorkflowPermissionError):
        service.update(wf.id, DEFAULT_TENANT_ID, name="Http", description="", draft=_http_doc(), actor=limited)
    with pytest.raises(WorkflowPermissionError):
        service.run(wf.id, DEFAULT_TENANT_ID, inputs={}, is_test=True, actor=limited)
    with pytest.raises(WorkflowPermissionError):
        service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=limited.id, actor=limited)
    # A non-http graph is untouched by the new permission.
    plain = {"schemaVersion": 2, "nodes": [{"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}}], "edges": []}
    assert service.create(DEFAULT_TENANT_ID, name="Plain", description="", draft=plain, actor_id=limited.id, actor=limited).id


def test_http_boundary_returns_403_without_workflows_http(client, session_factory):
    db = session_factory()
    _limited_editor(db)
    db.close()
    res = client.post("/auth/login", json={"email": "http-editor@example.com", "password": "editor1234"})
    hdrs = {"Authorization": f"Bearer {res.json()['access_token']}"}
    body = {"name": "Http", "description": "", "draftDefinition": _http_doc()}
    denied = client.post("/workflows", json=body, headers=hdrs)
    assert denied.status_code == 403 and "workflows.http" in denied.json()["detail"]
    body["draftDefinition"] = {"schemaVersion": 2, "nodes": [{"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}}], "edges": []}
    assert client.post("/workflows", json=body, headers=hdrs).status_code in (200, 201)
