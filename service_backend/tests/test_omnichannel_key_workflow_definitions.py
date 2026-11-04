"""Plan 38 gap 7, slice S2: workflow definitions under the API key
(AC-38-128..135). RED tests written before the implementation.

Contract: documentation/plans/sprint-5/38-gap7-key-workflows.md, "Wire contract"
(S2 lines) and "Code check 2026-11-04". Not-yet-existing code
(`modules.omnichannel.models.WorkflowOwner`, `modules.omnichannel.services.
key_workflows`, `app.workflow_engine.executor.RunRefused`) is imported lazily.

Every test seeds its own workspaces, channels, contacts and workflows. The
"staff-published" workflows are written through `WorkflowService` with
`actor=None` (no node permission gate) and then owned by a workspace through a
direct owner row: that is the situation a key can never create but the run
guard must still hold.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import (
    NODE_FAILED,
    NODE_RUNNING,
    NODE_SUCCESS,
    RUN_FAILED,
    RUN_SUCCESS,
    Workflow,
    WorkflowRun,
    WorkflowVersion,
)
from app.services.workflow_service import WorkflowService
from tests.test_omnichannel_api_gateway import _default_workspace_id
from tests.test_omnichannel_contacts_module import _seed_contact
from tests.test_omnichannel_gateway_channels import _channel
from tests.test_omnichannel_key_workflows import (
    BASE,
    EMPTY_DEF,
    _counts,
    _key,
    _new_workspace,
    _owner_cls,
    _owner_rows,
    _wf_count,
    _wf_row,
)
from tests.test_omnichannel_webhooks import _process, _wa_payload

SPY_KEY = "test.s2_spy"
AC_128_SET = {
    "omnichannel.message_received", "omnichannel.conversation_opened",
    "omnichannel.conversation_closed", "omnichannel.conversation_assigned",
    "omnichannel.contact_tag_added", "omnichannel.contact_tag_removed",
    "omnichannel.contact_field_changed", "omnichannel.lifecycle_changed",
    "omnichannel.broadcast_completed", "entity.shortcut",
    "omnichannel.get_contact", "omnichannel.send_message", "omnichannel.add_tag",
    "omnichannel.remove_tag", "omnichannel.update_field", "omnichannel.update_lifecycle",
    "omnichannel.open_conversation", "omnichannel.close_conversation",
    "omnichannel.add_comment", "omnichannel.ask_question", "omnichannel.wait",
    "omnichannel.business_hours", "http.request", "if",
}


# -- shared builders ------------------------------------------------------------
@pytest.fixture
def spy():
    """A registered action that is NOT on the allow-list; records executions."""
    from app.workflow_engine import registry
    from app.workflow_engine.registry import ActionDef, register_action

    calls = []

    def _exec(db, tenant_id, config, ctx):
        calls.append(config)
        return {"ok": True}

    register_action(ActionDef(key=SPY_KEY, label="S2 spy", description="test", icon="Zap",
                              category="Actions", executor=_exec))
    yield calls
    registry._ACTIONS.pop(SPY_KEY, None)


def _node(nid, ntype, config=None, kind="action"):
    return {"id": nid, "kind": kind, "type": ntype, "config": config or {}}


def _doc(*nodes, trigger=None, chain=True):
    trg = trigger or _node("trg", "omnichannel.message_received", kind="trigger")
    items = [trg, *nodes]
    edges = []
    if chain:
        for a, b in zip(items, items[1:]):
            edges.append({"id": f"e_{a['id']}_{b['id']}", "source": a["id"], "target": b["id"]})
    return {"schemaVersion": 1, "nodes": items, "edges": edges}


def _comment(nid="note_1", contact="{{ trigger.contact.id }}"):
    return _node(nid, "omnichannel.add_comment", {"contactId": contact, "body": "hello"})


def _staff_publish(session_factory, doc, name="staff wf"):
    """Create + activate + publish with no actor (no node permission gate)."""
    db = session_factory()
    try:
        svc = WorkflowService(db)
        wf = svc.create(DEFAULT_TENANT_ID, name=name, description="", draft=doc, actor_id=None)
        svc.set_active(wf.id, DEFAULT_TENANT_ID, True)
        svc.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
        return wf.id
    finally:
        db.close()


def _own(session_factory, wf_id, ws, by="apikey:seed"):
    db = session_factory()
    try:
        db.add(_owner_cls()(tenant_id=DEFAULT_TENANT_ID, workflow_id=wf_id, workspace_id=ws,
                            created_by=by))
        db.commit()
    finally:
        db.close()


def _runs(session_factory, wf_id):
    db = session_factory()
    try:
        out = []
        for r in db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf_id).all():
            out.append({
                "id": r.id, "status": r.status, "error": r.error or "",
                "nodes": [(n.node_id, n.status, n.error or "") for n in r.nodes],
            })
        return out
    finally:
        db.close()


def _msg_count(session_factory, contact_id=None):
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    try:
        q = db.query(ConversationMessage)
        if contact_id:
            q = q.filter(ConversationMessage.contact_id == contact_id)
        return q.count()
    finally:
        db.close()


def _versions(session_factory, wf_id):
    db = session_factory()
    try:
        return db.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == wf_id).count()
    finally:
        db.close()


def _world(client, session_factory):
    """Two workspaces of ONE tenant, each with a channel, tag, field, stage,
    close reason, template, contact. Returns a dict."""
    from modules.omnichannel.models import CloseReason, ContactField, ContactTag, Workspace
    from modules.omnichannel.services import lifecycle_service
    from tests.test_omnichannel_broadcasts import _ensure_template

    ws1 = _default_workspace_id(session_factory)
    ws2 = _new_workspace(session_factory, "Second")
    w = {"ws1": ws1, "ws2": ws2}
    db = session_factory()
    try:
        lifecycle_service.materialize_for_workspace(db, db.get(Workspace, ws2))
        db.commit()
        for tag, ws in (("1", ws1), ("2", ws2)):
            t = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, name=f"tag-w{tag}")
            f = ContactField(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, key=f"field_w{tag}",
                             label=f"Field W{tag}", type="text")
            r = CloseReason(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, name=f"reason-w{tag}")
            db.add_all([t, f, r])
            db.flush()
            w[f"tag{tag}"], w[f"field{tag}"], w[f"reason{tag}"] = t.id, f.key, r.id
        db.commit()
        for n, ws in (("1", ws1), ("2", ws2)):
            stages = lifecycle_service.stages_for_workspace(db, DEFAULT_TENANT_ID, ws)
            w[f"stage{n}"] = stages[0].id
    finally:
        db.close()
    w["ch1"] = _channel(session_factory, ws1, name="s2c1", age_rank=1, pn="pn-s2-1")
    w["ch2"] = _channel(session_factory, ws2, name="s2c2", age_rank=2, pn="pn-s2-2")
    w["tpl1"] = _ensure_template(session_factory, w["ch1"], name="tpl_w1")
    w["tpl2"] = _ensure_template(session_factory, w["ch2"], name="tpl_w2")
    w["contact1"] = _seed_contact(session_factory, ws1, first="One", phone="+60177000001",
                                  channel_id=w["ch1"])
    w["contact2"] = _seed_contact(session_factory, ws2, first="Two", phone="+60177000002",
                                  channel_id=w["ch2"])
    _, w["hdr1"] = _key(client, ws1, "w1-key")
    _, w["hdr2"] = _key(client, ws2, "w2-key")
    return w


def _post(client, hdr, doc, **extra):
    body = {"name": "From key", "draftDefinition": doc, **extra}
    return client.post(f"{BASE}/workflows", json=body, headers=hdr)


def _inbound(session_factory, channel_id, phone, text, wamid=None):
    return _process(session_factory, channel_id,
                    _wa_payload(wamid=wamid or f"wamid.s2-{uuid.uuid4().hex[:10]}",
                                from_=phone, text=text))


# -- AC-38-128 ------------------------------------------------------------------
def test_ac_38_128_allow_list_is_exactly_the_set():
    from modules.omnichannel.services.key_workflows import KEY_WORKFLOW_NODE_TYPES

    assert set(KEY_WORKFLOW_NODE_TYPES) == AC_128_SET
    assert len(set(KEY_WORKFLOW_NODE_TYPES)) == len(AC_128_SET) == 24
    for banned in ("code.run", "ai_agent.run", "omnichannel.assign_conversation",
                   "manual", "schedule.cron"):
        assert banned not in KEY_WORKFLOW_NODE_TYPES


# -- AC-38-129 ------------------------------------------------------------------
def _bad_doc(case):
    if case == "entity.shortcut-other":
        trg = _node("bad_1", "entity.shortcut", {"entityType": "user"}, kind="trigger")
        return _doc(_comment(), trigger=trg), "bad_1", "entity.shortcut"
    typ = {"code.run": "code.run", "ai_agent.run": "ai_agent.run",
           "assign": "omnichannel.assign_conversation", "unknown": "no.such_type",
           "registered-later": "test.s2_registered_later"}[case]
    return _doc(_node("bad_1", typ, {})), "bad_1", typ


BAD_CASES = ["code.run", "ai_agent.run", "assign", "entity.shortcut-other", "unknown",
             "registered-later"]


@pytest.fixture
def later_type():
    """A type registered after the change and never added to the constant."""
    from app.workflow_engine import registry
    from app.workflow_engine.registry import ActionDef, register_action

    register_action(ActionDef(key="test.s2_registered_later", label="Later", description="t",
                              icon="Zap", category="Actions",
                              executor=lambda db, t, c, x: {}))
    yield
    registry._ACTIONS.pop("test.s2_registered_later", None)


def _assert_not_allowed(r, nid, ntype):
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == "node_not_allowed"
    assert nid in err["message"] and ntype in err["message"]
    assert err["details"]["nodeId"] == nid


@pytest.mark.parametrize("case", BAD_CASES)
def test_ac_38_129_refused_on_create_update_validate_publish(client, session_factory, later_type, case):
    w = _world(client, session_factory)
    hdr = w["hdr1"]
    bad, nid, ntype = _bad_doc(case)

    # create: refused, nothing saved
    before = (_wf_count(session_factory), _counts(session_factory))
    r = _post(client, hdr, bad)
    _assert_not_allowed(r, nid, ntype)
    assert (_wf_count(session_factory), _counts(session_factory)) == before

    # update: a good workflow stays exactly as it was
    good = _post(client, hdr, _doc(_comment()))
    assert good.status_code == 201, good.text
    wid = good.json()["id"]
    row_before = _wf_row(session_factory, wid)
    r = client.patch(f"{BASE}/workflows/{wid}", json={"draftDefinition": bad}, headers=hdr)
    _assert_not_allowed(r, nid, ntype)
    assert _wf_row(session_factory, wid) == row_before

    # validate: 200, valid false, a node_not_allowed issue; nothing saved
    counts = _counts(session_factory)
    r = client.post(f"{BASE}/workflows/validate", json={"draftDefinition": bad}, headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is False
    issue = next(i for i in body["issues"] if i["code"] == "node_not_allowed")
    assert issue["nodeId"] == nid and ntype in issue["message"]
    assert _counts(session_factory) == counts

    # publish: write the disallowed draft straight into the core row (save refuses it)
    from app.models.workflow import Workflow as W

    db = session_factory()
    try:
        db.query(W).filter(W.id == wid).update({"draft_definition_json": bad})
        db.commit()
    finally:
        db.close()
    row_before = _wf_row(session_factory, wid)
    r = client.post(f"{BASE}/workflows/{wid}/publish", headers=hdr)
    _assert_not_allowed(r, nid, ntype)
    assert _wf_row(session_factory, wid) == row_before
    assert _wf_row(session_factory, wid)["current_version_id"] is None
    assert _versions(session_factory, wid) == 0


# -- AC-38-130 ------------------------------------------------------------------
def _spy_doc():
    return _doc(_comment("note_1"), _node("spy_node", SPY_KEY, {"n": 1}))


def _assert_refused_no_node(run, spy):
    assert run["status"] == RUN_FAILED, run
    assert "node_not_allowed" in run["error"] and "spy_node" in run["error"]
    assert [n for n in run["nodes"] if n[1] in (NODE_SUCCESS, NODE_RUNNING, NODE_FAILED)] == []
    assert spy == []


def test_ac_38_130_owned_run_refused_before_any_node(client, session_factory, spy):
    w = _world(client, session_factory)
    owned = _staff_publish(session_factory, _spy_doc(), "owned spy")
    _own(session_factory, owned, w["ws1"])
    unowned = _staff_publish(session_factory, _spy_doc(), "unowned spy")

    notes_before = _msg_count(session_factory)
    _inbound(session_factory, w["ch1"], "60177000001", "hi")

    # event-fired: the owned run failed before its first node; the unowned control ran
    runs = _runs(session_factory, owned)
    assert len(runs) == 1
    assert runs[0]["status"] == RUN_FAILED
    assert "node_not_allowed" in runs[0]["error"] and "spy_node" in runs[0]["error"]
    assert [n for n in runs[0]["nodes"] if n[1] in (NODE_SUCCESS, NODE_RUNNING, NODE_FAILED)] == []
    ctrl = _runs(session_factory, unowned)
    assert len(ctrl) == 1 and ctrl[0]["status"] == RUN_SUCCESS, ctrl
    assert len(spy) == 1, "only the unowned control executed the spy node"
    # the owned workflow's comment node never wrote: only the control's comment exists
    inbound_only = _msg_count(session_factory) - notes_before
    assert inbound_only == 2, "one inbound message + one control comment, no owned comment"


def test_ac_38_130_resumed_parked_run_refused(client, session_factory, spy):
    from app.workflow_engine.executor import resume_run
    from tests.test_omnichannel_workflow_waits import _ask_doc, _park_via_inbound

    doc = _ask_doc(tail=False)
    doc["nodes"].append(_node("spy_node", SPY_KEY, {"n": 1}))
    doc["edges"].append({"id": "e_spy", "source": "ask_1", "target": "spy_node",
                         "sourcePort": "answer"})
    wf_id, contact_id, channel_id = _park_via_inbound(session_factory, doc=doc)
    run = _runs(session_factory, wf_id)[0]
    assert run["status"] == "waiting"
    # it becomes owned while parked; the resume pass must hold it to the allow-list
    _own(session_factory, wf_id, _default_workspace_id(session_factory))
    db = session_factory()
    try:
        resume_run(db, run["id"], DEFAULT_TENANT_ID, node_id="ask_1",
                   output={"answer": "Pro"}, branch="answer")
    finally:
        db.close()
    after = _runs(session_factory, wf_id)[0]
    assert after["status"] == RUN_FAILED, after
    assert "node_not_allowed" in after["error"] and "spy_node" in after["error"]
    assert spy == []


def test_ac_38_130_debug_execute_refused(client, session_factory, spy):
    from app.workflow_engine.executor import RunRefused, debug_execute

    w = _world(client, session_factory)
    doc = _spy_doc()
    wf_id = _staff_publish(session_factory, doc, "debug owned")
    _own(session_factory, wf_id, w["ws1"])
    db = session_factory()
    try:
        run = WorkflowRun(tenant_id=DEFAULT_TENANT_ID, workflow_id=wf_id, status="pending",
                          definition_snapshot_json=doc, trigger_payload_json={})
        db.add(run)
        db.flush()
        with pytest.raises(RunRefused) as exc:
            debug_execute(db, run, target_node_id="spy_node", scratch={}, stale_node_ids=[])
        assert exc.value.code == "node_not_allowed"
        assert "spy_node" in str(exc.value)
    finally:
        db.close()
    assert spy == []

    # control: an unowned workflow with the same definition debugs normally
    ctrl_doc = _doc(_comment("note_1", contact=w["contact1"]), _node("spy_node", SPY_KEY, {"n": 1}))
    other = _staff_publish(session_factory, ctrl_doc, "debug unowned")
    db = session_factory()
    try:
        run = WorkflowRun(tenant_id=DEFAULT_TENANT_ID, workflow_id=other, status="pending",
                          definition_snapshot_json=ctrl_doc, trigger_payload_json={})
        db.add(run)
        db.flush()
        debug_execute(db, run, target_node_id="spy_node", scratch={}, stale_node_ids=[])
    finally:
        db.close()
    assert len(spy) == 1


# -- AC-38-131 ------------------------------------------------------------------
def test_ac_38_131_schema_version_caps_edit_conflict(client, session_factory):
    w = _world(client, session_factory)
    hdr = w["hdr1"]
    good = _doc(_comment())

    before = _counts(session_factory)
    v2 = {**good, "schemaVersion": 2}
    r = _post(client, hdr, v2)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_definition", r.text

    many = {"schemaVersion": 1, "edges": [],
            "nodes": [_node("trg", "omnichannel.message_received", kind="trigger")]
                     + [_comment(f"n{i}") for i in range(200)]}  # 201 nodes
    r = _post(client, hdr, many)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request", r.text

    r = client.post(f"{BASE}/workflows",
                    json={"name": "x" * (300 * 1024), "draftDefinition": good}, headers=hdr)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request", r.text
    assert _counts(session_factory) == before

    # edit conflict
    item = _post(client, hdr, good).json()
    wid = item["id"]
    db = session_factory()
    try:
        row = db.query(Workflow).filter(Workflow.id == wid).one()
        row.updated_at = datetime.now(timezone.utc) + timedelta(days=1)  # changed after item
        row.current_version_id = "ver-live"
        db.commit()
    finally:
        db.close()
    row_before = _wf_row(session_factory, wid)
    r = client.patch(f"{BASE}/workflows/{wid}",
                     json={"name": "stale", "expectedUpdatedAt": item["updatedAt"]}, headers=hdr)
    assert r.status_code == 409 and r.json()["error"]["code"] == "edit_conflict", r.text
    assert _wf_row(session_factory, wid) == row_before

    # without expectedUpdatedAt: saves the draft only, nothing published or fired
    new_draft = _doc(_comment(), _comment("note_2"))
    r = client.patch(f"{BASE}/workflows/{wid}", json={"draftDefinition": new_draft}, headers=hdr)
    assert r.status_code == 200, r.text
    after = _wf_row(session_factory, wid)
    assert after["current_version_id"] == "ver-live"
    assert r.json()["draftDefinition"] == new_draft
    assert _versions(session_factory, wid) == 0

    # with the current stamp: accepted
    cur = r.json()["updatedAt"]
    r = client.patch(f"{BASE}/workflows/{wid}",
                     json={"name": "fresh", "expectedUpdatedAt": cur}, headers=hdr)
    assert r.status_code == 200 and r.json()["name"] == "fresh", r.text


# -- AC-38-132 ------------------------------------------------------------------
def test_ac_38_132_validate_saves_nothing_publish_same_issues(client, session_factory):
    w = _world(client, session_factory)
    hdr = w["hdr1"]
    gate = _doc(_node("send_1", "omnichannel.send_message", {}))  # required fields missing

    tables = lambda: (_counts(session_factory), _wf_count(session_factory))  # noqa: E731
    before = tables()
    r = client.post(f"{BASE}/workflows/validate", json={"draftDefinition": gate}, headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is False and body["issues"]
    assert set(body["issues"][0]) >= {"code", "message", "nodeId", "field"}
    assert body["issues"][0]["code"] == "invalid_definition"
    assert "required" in body["issues"][0]["message"]
    assert tables() == before

    ok = client.post(f"{BASE}/workflows/validate", json={"draftDefinition": _doc(_comment())},
                     headers=hdr)
    assert ok.status_code == 200 and ok.json() == {"valid": True, "issues": []}
    assert tables() == before

    wid = _post(client, hdr, gate).json()["id"]  # a draft may hold gate issues
    row_before = _wf_row(session_factory, wid)
    r = client.post(f"{BASE}/workflows/{wid}/publish", headers=hdr)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_definition", r.text
    assert r.json()["error"]["message"] == body["issues"][0]["message"]
    assert _wf_row(session_factory, wid) == row_before and _versions(session_factory, wid) == 0

    # control: a clean draft publishes
    good = _post(client, hdr, _doc(_comment())).json()["id"]
    r = client.post(f"{BASE}/workflows/{good}/publish", headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["publishedVersionId"] and r.json()["triggerType"] == "omnichannel.message_received"
    assert _versions(session_factory, good) == 1


# -- AC-38-133 ------------------------------------------------------------------
def _pin_cases(w, other):
    """(label, doc builder taking own/other ids, nodeId, field)."""
    o = lambda k: w[f"{k}{'1' if not other else '2'}"]  # noqa: E731
    ws = w["ws1"] if not other else w["ws2"]
    return {
        "workspace": (_doc(_comment(), trigger=_node("trg", "omnichannel.conversation_opened",
                      {"workspaceId": ws}, kind="trigger")), "trg", "workspaceId"),
        "channel": (_doc(_comment(), trigger=_node("trg", "omnichannel.message_received",
                    {"channelId": o("ch")}, kind="trigger")), "trg", "channelId"),
        "contact": (_doc(_node("act", "omnichannel.add_comment",
                    {"contactId": o("contact"), "body": "x"})), "act", "contactId"),
        "tag": (_doc(_node("act", "omnichannel.add_tag", {"contactId": "{{ trigger.contact.id }}",
                "workspaceId": w["ws1"], "tagId": o("tag")})), "act", "tagId"),
        "field": (_doc(_node("act", "omnichannel.update_field", {"contactId": "{{ trigger.contact.id }}",
                  "workspaceId": w["ws1"], "fieldKey": o("field"), "value": "v"})), "act", "fieldKey"),
        "stage": (_doc(_node("act", "omnichannel.update_lifecycle", {"contactId": "{{ trigger.contact.id }}",
                  "workspaceId": w["ws1"], "toStageId": o("stage")})), "act", "toStageId"),
        "reason": (_doc(_node("act", "omnichannel.close_conversation", {"contactId": "{{ trigger.contact.id }}",
                   "workspaceId": w["ws1"], "closeReasonId": o("reason")})), "act", "closeReasonId"),
        "template": (_doc(_node("act", "omnichannel.send_message", {"contactId": "{{ trigger.contact.id }}",
                     "mode": "template", "templateId": o("tpl")})), "act", "templateId"),
    }


PIN_LABELS = ["workspace", "channel", "contact", "tag", "field", "stage", "reason", "template"]


@pytest.mark.parametrize("via", ["create", "update", "validate"])
@pytest.mark.parametrize("label", PIN_LABELS)
def test_ac_38_133_literal_ids_pinned_trigger_stamped(client, session_factory, label, via):
    w = _world(client, session_factory)
    hdr = w["hdr1"]
    own_doc, _, _ = _pin_cases(w, other=False)[label]
    foreign_doc, nid, field = _pin_cases(w, other=True)[label]

    base = _post(client, hdr, _doc(_comment()))  # a workflow to update
    assert base.status_code == 201, base.text
    wid = base.json()["id"]

    def call(doc):
        if via == "create":
            return _post(client, hdr, doc)
        if via == "update":
            return client.patch(f"{BASE}/workflows/{wid}", json={"draftDefinition": doc}, headers=hdr)
        return client.post(f"{BASE}/workflows/validate", json={"draftDefinition": doc}, headers=hdr)

    # control: the key's own ids are accepted
    r = call(own_doc)
    assert r.status_code in (200, 201), r.text
    if via == "validate":
        assert r.json()["valid"] is True, r.json()

    counts, row = _counts(session_factory), _wf_row(session_factory, wid)
    r = call(foreign_doc)
    if via == "validate":
        assert r.status_code == 200, r.text
        issue = next(i for i in r.json()["issues"] if i["code"] == "invalid_definition"
                     and i["nodeId"] == nid)
        assert issue["field"] == field
    else:
        assert r.status_code == 422, r.text
        err = r.json()["error"]
        assert err["code"] == "invalid_definition"
        assert err["details"]["nodeId"] == nid and err["details"]["field"] == field
    assert _counts(session_factory) == counts
    if via == "update":
        assert _wf_row(session_factory, wid)["draft"] != ""
        assert _wf_row(session_factory, wid) == row or _wf_row(session_factory, wid)["draft"] != \
            _doc_json(foreign_doc)


def _doc_json(doc):
    import json

    return json.dumps(doc, sort_keys=True)


def test_ac_38_133_merge_token_accepted_and_trigger_stamped(client, session_factory):
    w = _world(client, session_factory)
    hdr = w["hdr1"]
    merged = _doc(_node("act", "omnichannel.add_tag", {
        "contactId": "{{ trigger.contact.id }}", "workspaceId": w["ws1"],
        "tagId": "{{ trigger.message.text }}"}))
    assert _post(client, hdr, merged).status_code == 201

    # the server sets the trigger workspace to the key's, even if the body names none
    doc = _doc(_comment(), trigger=_node("trg", "omnichannel.conversation_opened", {},
                                         kind="trigger"))
    r = _post(client, hdr, doc)
    assert r.status_code == 201, r.text
    trg = next(n for n in r.json()["draftDefinition"]["nodes"] if n["id"] == "trg")
    assert trg["config"]["workspaceId"] == w["ws1"]
    saved = _wf_row(session_factory, r.json()["id"])["draft"]
    assert w["ws1"] in saved

    # the same body through the second workspace's key stamps ITS workspace
    r2 = _post(client, w["hdr2"], doc)
    trg2 = next(n for n in r2.json()["draftDefinition"]["nodes"] if n["id"] == "trg")
    assert trg2["config"]["workspaceId"] == w["ws2"]


# -- AC-38-134 ------------------------------------------------------------------
@pytest.mark.parametrize("action", ["omnichannel.add_comment", "omnichannel.send_message"])
def test_ac_38_134_run_pinning_and_event_isolation(client, session_factory, action):
    w = _world(client, session_factory)
    cfg = ({"contactId": "{{ trigger.message.text }}", "body": "pinned"}
           if action.endswith("comment")
           else {"contactId": "{{ trigger.message.text }}", "mode": "text", "message": "pinned"})
    wf = _staff_publish(session_factory, _doc(_node("act", action, cfg)), "pinned")
    _own(session_factory, wf, w["ws1"])

    # merged id of ANOTHER workspace's contact: node fails, nothing written or sent
    foreign_before = _msg_count(session_factory, w["contact2"])
    all_before = _msg_count(session_factory)
    _inbound(session_factory, w["ch1"], "60177000001", w["contact2"])
    run = _runs(session_factory, wf)[0]
    assert run["status"] == RUN_FAILED
    failed = [n for n in run["nodes"] if n[0] == "act"]
    assert failed and failed[0][1] == NODE_FAILED and "record_not_in_workspace" in failed[0][2]
    assert _msg_count(session_factory, w["contact2"]) == foreign_before
    assert _msg_count(session_factory) == all_before + 1, "only the inbound message itself"

    # control: the key's own workspace contact resolves and the node runs
    _inbound(session_factory, w["ch1"], "60177000001", w["contact1"])
    assert [r["status"] for r in _runs(session_factory, wf)].count(RUN_SUCCESS) == 1


@pytest.mark.parametrize("trigger", ["omnichannel.message_received", "omnichannel.conversation_opened"])
def test_ac_38_134_event_isolation_between_workspaces(client, session_factory, trigger):
    w = _world(client, session_factory)
    wf1 = _staff_publish(session_factory, _doc(_comment(), trigger=_node("trg", trigger, {}, "trigger")), "w1")
    wf2 = _staff_publish(session_factory, _doc(_comment(), trigger=_node("trg", trigger, {}, "trigger")), "w2")
    _own(session_factory, wf1, w["ws1"])
    _own(session_factory, wf2, w["ws2"])

    _inbound(session_factory, w["ch1"], "60177010001", "hello from one")
    assert len(_runs(session_factory, wf1)) == 1 and _runs(session_factory, wf2) == []
    _inbound(session_factory, w["ch2"], "60177010002", "hello from two")
    assert len(_runs(session_factory, wf1)) == 1 and len(_runs(session_factory, wf2)) == 1

    # staff edit the owned trigger to name W2 in the core draft AND version: still no fire on W2
    db = session_factory()
    try:
        wf = db.get(Workflow, wf1)
        edited = _doc(_comment(), trigger=_node("trg", "omnichannel.conversation_opened",
                                                {"workspaceId": w["ws2"]}, "trigger"))
        wf.draft_definition_json = edited
        ver = db.get(WorkflowVersion, wf.current_version_id)
        ver.definition_json = edited
        db.commit()
    finally:
        db.close()
    _inbound(session_factory, w["ch2"], "60177010003", "another from two")
    assert len(_runs(session_factory, wf1)) == 1, "owner check holds against a staff edit"
    assert len(_runs(session_factory, wf2)) == 2


def test_ac_38_134_broadcast_completed_carries_workspace(client, session_factory):
    from app.workflow_engine.entity_events import register_event_subscriber, unregister_event_subscriber
    from tests.test_omnichannel_broadcasts import _broadcasts_base, _create_payload, _fixture
    from tests.test_omnichannel_workflow_parity_triggers import _publish, _runs_for

    events = []

    def capture(session, ev):
        events.append(ev)

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    other_ws = _new_workspace(session_factory, "Not the broadcast workspace")
    db = session_factory()
    try:
        mine = _publish(db, "omnichannel.broadcast_completed", {"workspaceId": ws}).id
        theirs = _publish(db, "omnichannel.broadcast_completed", {"workspaceId": other_ws}).id
    finally:
        db.close()

    register_event_subscriber(capture)
    try:
        created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
            channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
        )).json()
        assert client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h,
                           json={}).status_code == 200
    finally:
        unregister_event_subscriber(capture)

    done = [e for e in events if e["entity_type"] == "omnichannel_broadcast"
            and e["action"] == "completed" and e["record_id"] == created["id"]]
    assert len(done) == 1
    assert done[0]["extra"]["workspaceId"] == ws, "SENT emit site carries workspaceId"

    db = session_factory()
    try:
        assert len(_runs_for(db, mine)) == 1, "a staff workflow filtered to this workspace fires"
        assert _runs_for(db, theirs) == [], "filtered to another workspace it does not"
    finally:
        db.close()


def test_ac_38_134_broadcast_failed_and_cancelled_sites_carry_workspace(client, session_factory):
    from app.workflow_engine.entity_events import register_event_subscriber, unregister_event_subscriber
    from modules.omnichannel.models import Broadcast
    from modules.omnichannel.services.broadcast_send_service import _fail_broadcast
    from modules.omnichannel.services.broadcast_service import BroadcastService
    from tests.test_omnichannel_broadcasts import _fixture
    from tests.test_omnichannel_deferred_actions import _make_broadcast

    events = []

    def capture(session, ev):
        events.append(ev)

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    db = session_factory()
    try:
        failing = _make_broadcast(db, ws, channel_id, template_id, key="SENDING", name="fails").id
        cancelling = _make_broadcast(db, ws, channel_id, template_id, key="SCHEDULED", name="cancels").id
    finally:
        db.close()

    register_event_subscriber(capture)
    try:
        db = session_factory()
        try:
            _fail_broadcast(db, db.get(Broadcast, failing), "boom")
        finally:
            db.close()
        db = session_factory()
        try:
            BroadcastService(db).cancel(cancelling, DEFAULT_TENANT_ID, ws)
        finally:
            db.close()
    finally:
        unregister_event_subscriber(capture)

    for bid, status in ((failing, "FAILED"), (cancelling, "CANCELLED")):
        done = [e for e in events if e["entity_type"] == "omnichannel_broadcast"
                and e["action"] == "completed" and e["record_id"] == bid]
        assert len(done) == 1 and done[0]["extra"]["status"] == status
        assert done[0]["extra"]["workspaceId"] == ws, f"{status} emit site carries workspaceId"


# -- AC-38-135 ------------------------------------------------------------------
def test_ac_38_135_catalog_allowed_registered_workspace_options(client, session_factory, later_type):
    from app.workflow_engine.registry import get_action, get_trigger
    from modules.omnichannel.services.key_workflows import KEY_WORKFLOW_NODE_TYPES

    w = _world(client, session_factory)
    r = client.get(f"{BASE}/workflows/catalog", headers=w["hdr1"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"nodes", "options"}

    types = [n["type"] for n in body["nodes"]]
    assert len(types) == len(set(types))
    registered = {t for t in KEY_WORKFLOW_NODE_TYPES
                  if t == "if" or get_trigger(t) or get_action(t)}
    assert set(types) == registered, "allow-listed AND registered, and only those"
    assert "test.s2_registered_later" not in types
    for banned in ("code.run", "ai_agent.run", "omnichannel.assign_conversation", "manual"):
        assert banned not in types

    by = {n["type"]: n for n in body["nodes"]}
    for n in body["nodes"]:
        assert set(n) >= {"type", "kind", "label", "description", "fields", "outputs"}
        assert n["kind"] in ("trigger", "action", "if")
        for f in n["fields"]:
            assert set(f) >= {"key", "label", "type", "required", "options", "showWhen", "mergeable"}
    assert by["omnichannel.message_received"]["kind"] == "trigger"
    assert by["omnichannel.add_comment"]["kind"] == "action"
    send = {f["key"]: f for f in by["omnichannel.send_message"]["fields"]}
    assert set(send) == {"contactId", "mode", "message", "templateId", "templateVariables"}
    assert send["contactId"]["mergeable"] is True and send["contactId"]["required"] is True
    assert send["message"]["showWhen"] == {"field": "mode", "value": "text"} \
        or send["message"]["showWhen"] == ["mode", "text"], "showWhen is camelCase data"
    assert by["if"]["kind"] == "if" and isinstance(by["if"]["conditionFormat"], dict)

    opts = body["options"]
    assert set(opts) == {"channels", "contactTags", "contactFields", "lifecycleStages",
                         "closeReasons", "templates"}
    assert {c["id"] for c in opts["channels"]} == {w["ch1"]}
    assert {t["id"] for t in opts["contactTags"]} == {w["tag1"]}
    assert {f["key"] for f in opts["contactFields"]} == {w["field1"]}
    reason_ids = {c["id"] for c in opts["closeReasons"]}
    assert w["reason1"] in reason_ids and w["reason2"] not in reason_ids
    assert {t["id"] for t in opts["templates"]} == {w["tpl1"]}
    assert w["stage1"] in {s["id"] for s in opts["lifecycleStages"]}
    assert w["stage2"] not in {s["id"] for s in opts["lifecycleStages"]}
    blob = r.text
    for foreign in (w["ch2"], w["tag2"], w["field2"], w["reason2"], w["tpl2"], w["ws2"]):
        assert foreign not in blob, "nothing of the second workspace leaks"

    # two keys of one workspace get equal bodies; the other workspace gets its own
    _, hdr1b = _key(client, w["ws1"], "w1-second")
    assert client.get(f"{BASE}/workflows/catalog", headers=hdr1b).json() == body
    other = client.get(f"{BASE}/workflows/catalog", headers=w["hdr2"]).json()
    assert {c["id"] for c in other["options"]["channels"]} == {w["ch2"]}


# -- review round 1 guards ------------------------------------------------------
def test_ac_38_133_publish_pins_a_staff_edited_draft(client, session_factory):
    """A staff edit can put another workspace's literal id into the draft of a key-owned
    workflow; publish must re-check pinning and refuse, publishing nothing."""
    w = _world(client, session_factory)
    hdr = w["hdr1"]
    wid = _post(client, hdr, _doc(_comment())).json()["id"]
    edited = _doc(_node("act", "omnichannel.add_tag", {
        "contactId": "{{ trigger.contact.id }}", "workspaceId": w["ws1"], "tagId": w["tag2"]}))
    db = session_factory()
    try:
        db.query(Workflow).filter(Workflow.id == wid).update({"draft_definition_json": edited})
        db.commit()
    finally:
        db.close()
    before = _wf_row(session_factory, wid)
    r = client.post(f"{BASE}/workflows/{wid}/publish", headers=hdr)
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == "invalid_definition"
    assert err["details"]["nodeId"] == "act" and err["details"]["field"] == "tagId"
    assert _wf_row(session_factory, wid) == before and _versions(session_factory, wid) == 0
    # control: with the key's own tag it publishes
    ok = _doc(_node("act", "omnichannel.add_tag", {
        "contactId": "{{ trigger.contact.id }}", "workspaceId": w["ws1"], "tagId": w["tag1"]}))
    db = session_factory()
    try:
        db.query(Workflow).filter(Workflow.id == wid).update({"draft_definition_json": ok})
        db.commit()
    finally:
        db.close()
    assert client.post(f"{BASE}/workflows/{wid}/publish", headers=hdr).status_code == 200


def test_ac_38_134_business_hours_node_merged_foreign_workspace(client, session_factory):
    from modules.omnichannel.services.business_hours import BusinessHoursService

    w = _world(client, session_factory)
    db = session_factory()
    try:
        BusinessHoursService(db).set(DEFAULT_TENANT_ID, w["ws1"], timezone="UTC",
                                     windows={d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})
        BusinessHoursService(db).set(DEFAULT_TENANT_ID, w["ws2"], timezone="UTC",
                                     windows={d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})
    finally:
        db.close()
    doc = _doc(_node("bh", "omnichannel.business_hours", {"workspaceId": "{{ trigger.message.text }}"}))
    wf = _staff_publish(session_factory, doc, "bh pinned")
    _own(session_factory, wf, w["ws1"])

    _inbound(session_factory, w["ch1"], "60177000001", w["ws2"])  # another workspace's id, merged
    run = _runs(session_factory, wf)[0]
    node = next(n for n in run["nodes"] if n[0] == "bh")
    assert run["status"] == RUN_FAILED
    assert node[1] == NODE_FAILED and "record_not_in_workspace" in node[2], node

    _inbound(session_factory, w["ch1"], "60177000001", w["ws1"])  # control: its own workspace
    statuses = sorted(r["status"] for r in _runs(session_factory, wf))
    assert statuses == [RUN_FAILED, RUN_SUCCESS], statuses


def test_ac_38_134_broadcast_completed_staff_edit_isolation(client, session_factory):
    from app.workflow_engine.entity_events import _match_and_enqueue

    w = _world(client, session_factory)
    doc = _doc(_node("act", "omnichannel.add_comment", {"contactId": w["contact1"], "body": "done"}),
               trigger=_node("trg", "omnichannel.broadcast_completed", {}, "trigger"))
    wf = _staff_publish(session_factory, doc, "bc owned")
    _own(session_factory, wf, w["ws1"])

    def emit(ws):
        ev = {"entity_type": "omnichannel_broadcast", "action": "completed",
              "tenant_id": DEFAULT_TENANT_ID, "record_id": str(uuid.uuid4()), "actor": None,
              "changes": None, "record_facts": {},
              "extra": {"broadcastId": "bc-1", "workspaceId": ws}, "source": None}
        db = session_factory()
        try:
            _match_and_enqueue(db, ev)
            db.commit()
        finally:
            db.close()

    emit(w["ws2"])
    assert _runs(session_factory, wf) == [], "an owned workflow never fires on another workspace"
    emit(w["ws1"])
    assert len(_runs(session_factory, wf)) == 1

    # staff edit the owned trigger to name W2 in the draft and the version: still no fire on W2
    edited = _doc(_node("act", "omnichannel.add_comment", {"contactId": w["contact1"], "body": "done"}),
                  trigger=_node("trg", "omnichannel.broadcast_completed", {"workspaceId": w["ws2"]}, "trigger"))
    db = session_factory()
    try:
        row = db.get(Workflow, wf)
        row.draft_definition_json = edited
        db.get(WorkflowVersion, row.current_version_id).definition_json = edited
        db.commit()
    finally:
        db.close()
    emit(w["ws2"])
    assert len(_runs(session_factory, wf)) == 1, "owner check holds against a staff edit"
