"""Workflow engine tests (plan sprint-2/08) - validate gate, executor, publish/
versioning, run-the-draft, run logs + replay, debug execute, archive/restore,
tenant scoping, permission reachability."""

from app.models.email_outbox import EmailOutbox
from app.models.workflow import Workflow
from app.services.workflow_service import WorkflowNotFound, WorkflowService
from app.workflow_engine import (
    WorkflowValidationError,
    definition_issues,
    parse_definition,
    topo_order,
    validate_definition,
)
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, DEFAULT_TENANT_ID


def _login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def _demo_headers(client):
    res = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _manual_email_doc(template_id: str) -> dict:
    return {
        "schemaVersion": 1,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "manual",
             "config": {"inputs": [{"key": "email", "label": "Email", "type": "string"}]},
             "position": {"x": 0, "y": 0}},
            {"id": "act", "kind": "action", "type": "email.send",
             "config": {"templateId": template_id, "to": "{{ trigger.input.email }}"},
             "position": {"x": 0, "y": 120}},
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "act", "sourcePort": "out"}],
    }


# ---- validation (unit) ----


def test_validate_passes_complete_graph():
    doc = _manual_email_doc("tpl-1")
    assert definition_issues(parse_definition(doc)) == []
    validate_definition(doc)  # no raise


def test_validate_requires_trigger():
    issues = definition_issues(parse_definition({"schemaVersion": 1, "nodes": [], "edges": []}))
    assert any("trigger" in i.lower() for i in issues)


def test_validate_blocks_orphan_and_missing_config():
    doc = {
        "schemaVersion": 1,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "manual", "config": {}, "position": {}},
            {"id": "act", "kind": "action", "type": "email.send", "config": {"mode": "template"}, "position": {}},
        ],
        "edges": [],  # act is orphaned + missing required template/to
    }
    issues = definition_issues(parse_definition(doc))
    assert any("not connected" in i for i in issues)
    assert any("Template" in i for i in issues)


def test_validate_rejects_two_triggers():
    doc = _manual_email_doc("t")
    doc["nodes"].append({"id": "trg2", "kind": "trigger", "type": "manual", "config": {}, "position": {}})
    try:
        validate_definition(doc)
        assert False, "expected WorkflowValidationError"
    except WorkflowValidationError as exc:
        assert any("only one trigger" in i for i in exc.issues)


def test_topo_order_trigger_first():
    order = [n.id for n in topo_order(parse_definition(_manual_email_doc("t")))]
    assert order == ["trg", "act"]


# ---- API lifecycle ----


def _a_template_id(client, headers) -> str:
    res = client.get("/workflows/template-options", headers=headers)
    assert res.status_code == 200, res.text
    opts = res.json()
    assert opts, "seeded platform templates expected"
    return opts[0]["value"]


def test_full_lifecycle(client):
    h = _demo_headers(client)

    # create
    res = client.post("/workflows", headers=h, json={"name": "WF", "description": "d", "draftDefinition": {"schemaVersion": 1, "nodes": [], "edges": []}})
    assert res.status_code == 201, res.text
    wf = res.json()
    wid = wf["id"]
    assert wf["isActive"] is False and wf["currentVersionId"] is None

    # publish empty draft → 422 (no trigger)
    assert client.post(f"/workflows/{wid}/publish", headers=h).status_code == 422

    # set a valid draft + publish
    tpl = _a_template_id(client, h)
    res = client.patch(f"/workflows/{wid}", headers=h, json={"name": "WF", "description": "d", "draftDefinition": _manual_email_doc(tpl)})
    assert res.status_code == 200, res.text
    assert res.json()["hasUnpublishedChanges"] is True

    res = client.post(f"/workflows/{wid}/publish", headers=h)
    assert res.status_code == 200, res.text
    detail = res.json()
    assert detail["currentVersion"]["versionNumber"] == 1
    assert detail["hasUnpublishedChanges"] is False
    assert detail["triggerType"] == "manual"

    # run the draft (no re-publish needed) - eager → completes inline
    res = client.post(f"/workflows/{wid}/run", headers=h, json={"inputs": {"email": "x@y.com"}})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "success"

    # logs
    res = client.get(f"/workflows/{wid}/runs", headers=h)
    assert res.status_code == 200
    runs = res.json()["data"]
    assert len(runs) == 1 and runs[0]["status"] == "success"
    run_id = runs[0]["id"]

    # run detail + replay nodes
    res = client.get(f"/workflows/runs/{run_id}", headers=h)
    assert res.status_code == 200, res.text
    rd = res.json()
    node_status = {n["nodeId"]: n["status"] for n in rd["nodes"]}
    assert node_status == {"trg": "success", "act": "success"}
    assert rd["definition"]["nodes"], "snapshot present for replay"

    # email enqueued by the action (dev fallback marks it sent)
    # (the outbox row carries the workflow.<key> template_key)


def _manual_custom_email_doc() -> dict:
    return {
        "schemaVersion": 1,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "manual",
             "config": {"inputs": [{"key": "email", "label": "Email", "type": "string"}, {"key": "name", "label": "Name", "type": "string"}]},
             "position": {"x": 0, "y": 0}},
            {"id": "act", "kind": "action", "type": "email.send",
             "config": {"mode": "custom", "subject": "Hi {{ trigger.input.name }}",
                        "body": "<p>Hello {{ trigger.input.name }}</p>", "to": "{{ trigger.input.email }}"},
             "position": {"x": 0, "y": 120}},
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "act", "sourcePort": "out"}],
    }


def test_custom_email_mode_validates_and_runs(client, session_factory):
    h = _demo_headers(client)
    # validate: custom mode requires subject + body (template NOT required).
    bad = _manual_custom_email_doc()
    bad["nodes"][1]["config"] = {"mode": "custom", "to": "{{ trigger.input.email }}"}
    issues = definition_issues(parse_definition(bad))
    assert any("Subject" in i for i in issues) and any("Body" in i for i in issues)
    assert not any("Template" in i for i in issues)  # template hidden in custom mode

    wid = client.post("/workflows", headers=h, json={"name": "Custom", "description": "", "draftDefinition": _manual_custom_email_doc()}).json()["id"]
    assert client.post(f"/workflows/{wid}/publish", headers=h).status_code == 200
    run = client.post(f"/workflows/{wid}/run", headers=h, json={"inputs": {"email": "c@x.com", "name": "Sam"}}).json()
    assert run["status"] == "success"

    db = session_factory()
    from app.models.email_outbox import EmailOutbox
    row = db.query(EmailOutbox).filter(EmailOutbox.to_email == "c@x.com").first()
    assert row is not None
    assert row.template_key == "workflow.custom"
    assert "Sam" in row.subject and "Sam" in row.html_body


def test_run_enqueues_email(client, session_factory):
    h = _demo_headers(client)
    tpl = _a_template_id(client, h)
    res = client.post("/workflows", headers=h, json={"name": "M", "description": "", "draftDefinition": _manual_email_doc(tpl)})
    wid = res.json()["id"]
    client.post(f"/workflows/{wid}/run", headers=h, json={"inputs": {"email": "to@x.com"}})

    db = session_factory()
    rows = db.query(EmailOutbox).filter(EmailOutbox.to_email == "to@x.com").all()
    assert len(rows) == 1
    assert rows[0].template_key.startswith("workflow.")


def test_edit_after_publish_marks_unpublished(client):
    h = _demo_headers(client)
    tpl = _a_template_id(client, h)
    wid = client.post("/workflows", headers=h, json={"name": "E", "description": "", "draftDefinition": _manual_email_doc(tpl)}).json()["id"]
    client.post(f"/workflows/{wid}/publish", headers=h)
    doc = _manual_email_doc(tpl)
    doc["nodes"][1]["config"]["to"] = "{{ trigger.input.email }} changed"
    client.patch(f"/workflows/{wid}", headers=h, json={"name": "E", "description": "", "draftDefinition": doc})
    assert client.get(f"/workflows/{wid}", headers=h).json()["hasUnpublishedChanges"] is True

    # publish v2, then unpublish
    assert client.post(f"/workflows/{wid}/publish", headers=h).json()["currentVersion"]["versionNumber"] == 2
    res = client.get(f"/workflows/{wid}/versions", headers=h)
    assert res.json()["total"] == 2
    assert client.post(f"/workflows/{wid}/unpublish", headers=h).json()["currentVersionId"] is None


def test_archive_restore_views(client):
    h = _demo_headers(client)
    tpl = _a_template_id(client, h)
    wid = client.post("/workflows", headers=h, json={"name": "Arch", "description": "", "draftDefinition": _manual_email_doc(tpl)}).json()["id"]

    client.post(f"/workflows/{wid}/archive", headers=h)
    active_ids = [w["id"] for w in client.get("/workflows", headers=h).json()["data"]]
    assert wid not in active_ids
    archived_ids = [w["id"] for w in client.get("/workflows?status_view=trashed", headers=h).json()["data"]]
    assert wid in archived_ids

    client.post(f"/workflows/{wid}/restore", headers=h)
    active_ids = [w["id"] for w in client.get("/workflows", headers=h).json()["data"]]
    assert wid in active_ids


def test_debug_execute_returns_nodes(client):
    h = _demo_headers(client)
    tpl = _a_template_id(client, h)
    wid = client.post("/workflows", headers=h, json={"name": "Dbg", "description": "", "draftDefinition": _manual_email_doc(tpl)}).json()["id"]
    run_id = client.post(f"/workflows/{wid}/run", headers=h, json={"inputs": {"email": "d@x.com"}}).json()["id"]

    res = client.post(
        f"/workflows/{wid}/debug",
        headers=h,
        json={"runId": run_id, "targetNodeId": "act", "scratch": {}, "staleNodeIds": ["act"]},
    )
    assert res.status_code == 200, res.text
    touched = {n["nodeId"] for n in res.json()["nodes"]}
    assert "act" in touched


# ---- tenant scoping ----


def test_tenant_scoped(client, session_factory):
    h = _demo_headers(client)
    wid = client.post("/workflows", headers=h, json={"name": "T", "description": "", "draftDefinition": {"schemaVersion": 1, "nodes": [], "edges": []}}).json()["id"]
    db = session_factory()
    service = WorkflowService(db)
    # belongs to default tenant
    assert service.get(wid, DEFAULT_TENANT_ID).id == wid
    # invisible to another tenant
    try:
        service.get(wid, "other-tenant-id")
        assert False, "expected WorkflowNotFound"
    except WorkflowNotFound:
        pass


# ---- permission gate ----


def test_requires_permission(client):
    assert client.get("/workflows").status_code == 401
