"""Plan 38 gap 7, slice S3: publish, versions, runs and run for one contact
under the API key (AC-38-138..141). RED tests written before the implementation.

Contract: documentation/plans/sprint-5/38-gap7-key-workflows.md, "Wire contract"
S3 bullets. Owned shortcut workflows are written the way staff would publish
them (WorkflowService, no actor) plus a direct owner row, so each test controls
exactly which state (unpublished / inactive / other trigger) it is in.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import Workflow, WorkflowRun, WorkflowVersion
from app.services.workflow_service import WorkflowService
from tests.test_omnichannel_key_workflows import (
    BASE,
    EMPTY_DEF,
    _counts,
    _key,
    _new_workspace,
    _owner_cls,
    _wf_row,
)
from tests.test_omnichannel_api_gateway import _default_workspace_id
from tests.test_omnichannel_contacts_module import _seed_contact

SHORTCUT_TRIGGER = {"id": "trg", "kind": "trigger", "type": "entity.shortcut",
                    "config": {"entityType": "omnichannel_contact"}}


def _action(nid, ntype, config):
    return {"id": nid, "kind": "action", "type": ntype, "config": config}


def _chain(trigger, *nodes):
    items = [trigger, *nodes]
    return {"schemaVersion": 1, "nodes": items,
            "edges": [{"id": f"e{i}", "source": a["id"], "target": b["id"]}
                      for i, (a, b) in enumerate(zip(items, items[1:]))]}


def _note_node(nid="note_1", body="hello {{ trigger.input.note }}"):
    return _action(nid, "omnichannel.add_comment",
                   {"contactId": "{{ trigger.record.id }}", "body": body})


def _owned_workflow(session_factory, ws, *, nodes=None, trigger=None, publish=True, active=True,
                    name="owned shortcut"):
    """Staff-style owned workflow. Returns its id."""
    doc = _chain(trigger or SHORTCUT_TRIGGER, *(nodes or [_note_node()]))
    db = session_factory()
    try:
        svc = WorkflowService(db)
        wf = svc.create(DEFAULT_TENANT_ID, name=name, description="", draft=doc, actor_id=None)
        if active:
            svc.set_active(wf.id, DEFAULT_TENANT_ID, True)
        if publish:
            svc.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
        db.add(_owner_cls()(tenant_id=DEFAULT_TENANT_ID, workflow_id=wf.id, workspace_id=ws,
                            created_by="apikey:seed"))
        db.commit()
        return wf.id
    finally:
        db.close()


def _runs_of(session_factory, wf_id):
    db = session_factory()
    try:
        return [(r.id, r.status, r.actor_id, r.triggered_by, r.trigger_payload_json)
                for r in db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf_id).all()]
    finally:
        db.close()


def _contact_count(session_factory):
    from modules.omnichannel.models import Contact

    db = session_factory()
    try:
        return db.query(Contact).count()
    finally:
        db.close()


def _rig(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ws2 = _new_workspace(session_factory)
    kid, hdr = _key(client, ws)
    contact = _seed_contact(session_factory, ws, first="One", phone="+60177030001")
    foreign = _seed_contact(session_factory, ws2, first="Two", phone="+60177030002")
    return {"ws": ws, "ws2": ws2, "kid": kid, "hdr": hdr, "contact": contact, "foreign": foreign}


def _post_run(client, hdr, wid, contact, inputs=None, **extra):
    body = {"contact": contact, **extra}
    if inputs is not None:
        body["inputs"] = inputs
    return client.post(f"{BASE}/workflows/{wid}/runs", json=body, headers=hdr)


# -- AC-38-138 ------------------------------------------------------------------
def test_ac_38_138_publish_versions(client, session_factory):
    r = _rig(client, session_factory)
    hdr, kid = r["hdr"], r["kid"]
    doc = _chain({"id": "trg", "kind": "trigger", "type": "omnichannel.message_received",
                  "config": {}}, _note_node())
    item = client.post(f"{BASE}/workflows", json={"name": "v", "draftDefinition": doc},
                       headers=hdr).json()
    wid = item["id"]

    pub = client.post(f"{BASE}/workflows/{wid}/publish", headers=hdr)
    assert pub.status_code == 200, pub.text
    v1 = pub.json()["publishedVersionId"]
    assert v1
    db = session_factory()
    try:
        ver = db.get(WorkflowVersion, v1)
        assert ver.published_by == f"apikey:{kid}"
        assert ver.version_number == 1
    finally:
        db.close()

    # change the draft, publish again: two versions
    second = _note_node("note_2")
    second["config"]["name"] = "Second note"
    doc2 = _chain(doc["nodes"][0], _note_node(), second)
    assert client.patch(f"{BASE}/workflows/{wid}", json={"draftDefinition": doc2},
                        headers=hdr).status_code == 200
    rp = client.post(f"{BASE}/workflows/{wid}/publish", headers=hdr)
    assert rp.status_code == 200, rp.text
    v2 = rp.json()["publishedVersionId"]
    assert v2 and v2 != v1

    # versions: newest first, paged, with the contract fields
    page = client.get(f"{BASE}/workflows/{wid}/versions?limit=1", headers=hdr)
    assert page.status_code == 200, page.text
    body = page.json()
    assert [d["id"] for d in body["data"]] == [v2] and body["nextCursor"]
    first = body["data"][0]
    assert set(first) >= {"id", "versionNumber", "publishedAt", "publishedBy", "definition"}
    assert first["versionNumber"] == 2 and first["publishedBy"] == f"apikey:{kid}"
    assert first["publishedAt"].endswith("Z") and first["definition"] == doc2
    nxt = client.get(f"{BASE}/workflows/{wid}/versions?limit=1&cursor={body['nextCursor']}",
                     headers=hdr).json()
    assert [d["id"] for d in nxt["data"]] == [v1] and nxt["nextCursor"] is None
    assert client.get(f"{BASE}/workflows/{wid}/versions?limit=0", headers=hdr).status_code == 422

    # active, like the dashboard toggle
    on = client.put(f"{BASE}/workflows/{wid}/active", json={"isActive": True}, headers=hdr)
    assert on.status_code == 200 and on.json()["isActive"] is True, on.text
    assert _wf_row(session_factory, wid)["is_active"] is True
    bad = client.put(f"{BASE}/workflows/{wid}/active", json={"isActive": "yes"}, headers=hdr)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"
    off = client.put(f"{BASE}/workflows/{wid}/active", json={"isActive": False}, headers=hdr)
    assert off.json()["isActive"] is False

    # unpublish: the published pointer clears, history stays, active is as the dashboard leaves it
    client.put(f"{BASE}/workflows/{wid}/active", json={"isActive": True}, headers=hdr)
    un = client.post(f"{BASE}/workflows/{wid}/unpublish", headers=hdr)
    assert un.status_code == 200, un.text
    assert un.json()["publishedVersionId"] is None
    assert _wf_row(session_factory, wid)["current_version_id"] is None
    assert _wf_row(session_factory, wid)["is_active"] is True
    all_versions = client.get(f"{BASE}/workflows/{wid}/versions", headers=hdr).json()["data"]
    assert [d["id"] for d in all_versions] == [v2, v1]


# -- AC-38-139 ------------------------------------------------------------------
def test_ac_38_139_runs_list_detail_redacted(client, session_factory):
    r = _rig(client, session_factory)
    hdr = r["hdr"]
    secret = "Bearer sk_live_S3_LITERAL_SECRET"
    http = _action("http_1", "http.request", {
        "method": "GET", "url": "https://api.example.com/ping",
        "headers": [{"key": "Authorization", "value": secret}], "timeoutSeconds": "5"})
    wid = _owned_workflow(session_factory, r["ws"], nodes=[_note_node(), http])
    other = _owned_workflow(session_factory, r["ws"], name="other wf")

    ids = []
    for i in range(3):
        resp = _post_run(client, hdr, wid, r["contact"], {"note": f"n{i}"})
        assert resp.status_code == 202, resp.text
        ids.append(resp.json()["id"])
    _post_run(client, hdr, other, r["contact"])
    # distinct timestamps so "newest first" is not a same-second tie
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db = session_factory()
    try:
        for i, rid in enumerate(ids):
            row = db.get(WorkflowRun, rid)
            row.created_at = base + timedelta(minutes=i)
            row.started_at = base + timedelta(minutes=i)
        db.commit()
    finally:
        db.close()

    seen, cursor = [], None
    while True:
        url = f"{BASE}/workflows/{wid}/runs?limit=2" + (f"&cursor={cursor}" if cursor else "")
        page = client.get(url, headers=hdr)
        assert page.status_code == 200, page.text
        seen += [d["id"] for d in page.json()["data"]]
        cursor = page.json()["nextCursor"]
        if not cursor:
            break
    assert seen == list(reversed(ids)), "paged, newest first, only this workflow's runs"
    item = page.json()["data"][0]
    assert set(item) >= {"id", "workflowId", "status", "triggeredBy", "actorId", "error",
                         "startedAt", "finishedAt"}
    assert item["workflowId"] == wid

    detail = client.get(f"{BASE}/workflows/runs/{ids[0]}", headers=hdr)
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["id"] == ids[0] and d["workflowId"] == wid
    by = {n["nodeId"]: n for n in d["nodes"]}
    assert {"note_1", "http_1"} <= set(by)
    for n in by.values():
        assert set(n) >= {"nodeId", "nodeType", "status", "input", "output", "error"}
    assert by["note_1"]["nodeType"] == "omnichannel.add_comment"
    assert by["note_1"]["status"] == "success"
    cfg = by["http_1"]["input"]["config"]
    assert cfg["headers"][0]["key"] == "Authorization" and cfg["headers"][0]["value"] == "***"
    assert "sk_live_S3_LITERAL_SECRET" not in detail.text


# -- AC-38-140 ------------------------------------------------------------------
def test_ac_38_140_run_for_one_contact(client, session_factory):
    r = _rig(client, session_factory)
    hdr, kid = r["hdr"], r["kid"]
    wid = _owned_workflow(session_factory, r["ws"])

    resp = _post_run(client, hdr, wid, r["contact"])
    assert resp.status_code == 202, resp.text
    item = resp.json()
    assert set(item) >= {"id", "workflowId", "status", "triggeredBy", "actorId", "error",
                         "startedAt", "finishedAt"}
    assert item["workflowId"] == wid and item["actorId"] == f"apikey:{kid}"
    runs = _runs_of(session_factory, wid)
    assert [x[0] for x in runs] == [item["id"]] and runs[0][2] == f"apikey:{kid}"
    # the other identifier forms of guide 6a resolve the same contact
    assert _post_run(client, hdr, wid, f"id:{r['contact']}").status_code == 202
    assert _post_run(client, hdr, wid, "phone:+60177030001").status_code == 202
    assert len(_runs_of(session_factory, wid)) == 3

    # contact not found: another workspace's contact, an unknown id, an unknown phone
    runs_before, contacts_before = len(_runs_of(session_factory, wid)), _contact_count(session_factory)
    for ident in (r["foreign"], f"id:{r['foreign']}", "phone:+60177030002", str(uuid.uuid4()),
                  "phone:+60177039999", "+60177039998"):
        bad = _post_run(client, hdr, wid, ident)
        assert bad.status_code == 404, (ident, bad.text)
        assert bad.json()["error"]["code"] == "contact_not_found"
        assert len(_runs_of(session_factory, wid)) == runs_before
        assert _contact_count(session_factory) == contacts_before, "a miss never creates a contact"

    # not runnable: unpublished / inactive / other trigger
    cases = {
        "unpublished": _owned_workflow(session_factory, r["ws"], publish=False, name="u"),
        "inactive": _owned_workflow(session_factory, r["ws"], active=False, name="i"),
        "trigger": _owned_workflow(session_factory, r["ws"], name="t", trigger={
            "id": "trg", "kind": "trigger", "type": "omnichannel.conversation_opened", "config": {}}),
    }
    for reason, other in cases.items():
        before = _counts(session_factory)
        bad = _post_run(client, hdr, other, r["contact"])
        assert bad.status_code == 409, (reason, bad.text)
        err = bad.json()["error"]
        assert err["code"] == "workflow_not_runnable" and err["details"]["reason"] == reason
        assert reason in err["message"]
        assert _runs_of(session_factory, other) == []
        assert _counts(session_factory) == before


# -- AC-38-141 ------------------------------------------------------------------
def test_ac_38_141_inputs_caps(client, session_factory):
    r = _rig(client, session_factory)
    hdr = r["hdr"]
    wid = _owned_workflow(session_factory, r["ws"])

    ok = _post_run(client, hdr, wid, r["contact"], {"note": "from key", "Other_1": "x" * 1000})
    assert ok.status_code == 202, ok.text
    payload = _runs_of(session_factory, wid)[0][4]
    assert payload["input"] == {"note": "from key", "Other_1": "x" * 1000}
    # it reached the run context: the comment node rendered trigger.input.note
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    try:
        bodies = [m.body for m in db.query(ConversationMessage)
                  .filter(ConversationMessage.contact_id == r["contact"]).all()]
    finally:
        db.close()
    assert any("hello from key" in (b or "") for b in bodies), bodies

    # no inputs at all is fine
    assert _post_run(client, hdr, wid, r["contact"]).status_code == 202
    assert _post_run(client, hdr, wid, r["contact"], {}).status_code == 202

    runs_before = len(_runs_of(session_factory, wid))
    bad_inputs = {
        "21 keys": {f"k{i}": "v" for i in range(21)},
        "key starts with digit": {"1abc": "v"},
        "key with dash": {"a-b": "v"},
        "key too long": {"a" * 41: "v"},
        "empty key": {"": "v"},
        "number value": {"a": 5},
        "bool value": {"a": True},
        "null value": {"a": None},
        "object value": {"a": {"b": "c"}},
        "value over 1000": {"a": "x" * 1001},
        "inputs not an object": ["a"],
        "inputs a string": "a=b",
    }
    for label, bad in bad_inputs.items():
        resp = _post_run(client, hdr, wid, r["contact"], bad)
        assert resp.status_code == 422, (label, resp.text)
        assert resp.json()["error"]["code"] == "invalid_request", label
        assert len(_runs_of(session_factory, wid)) == runs_before, label
    # exactly 20 keys and a 40 char key are the inclusive bounds
    edge = {("a" * 40): "v", **{f"k{i}": "v" for i in range(19)}}
    assert _post_run(client, hdr, wid, r["contact"], edge).status_code == 202


# -- review round 1, B4 ------------------------------------------------------------
def test_ac_38_140_run_key_rendering_empty_is_422_not_409(client, session_factory):
    r = _rig(client, session_factory)
    hdr = r["hdr"]
    doc = _chain(SHORTCUT_TRIGGER, _note_node())
    doc["schemaVersion"] = 2
    doc["execution"] = {"mode": "serialized", "correlationKey": "{{ trigger.input.ticket }}"}
    db = session_factory()
    try:
        svc = WorkflowService(db)
        wf = svc.create(DEFAULT_TENANT_ID, name="keyed", description="", draft=doc, actor_id=None)
        svc.set_active(wf.id, DEFAULT_TENANT_ID, True)
        svc.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
        db.add(_owner_cls()(tenant_id=DEFAULT_TENANT_ID, workflow_id=wf.id, workspace_id=r["ws"],
                            created_by="apikey:seed"))
        db.commit()
        wid = wf.id
    finally:
        db.close()

    for inputs in (None, {}, {"other": "x"}, {"ticket": ""}):
        before = _counts(session_factory)
        resp = _post_run(client, hdr, wid, r["contact"], inputs)
        assert resp.status_code == 422, (inputs, resp.status_code, resp.text)
        err = resp.json()["error"]
        assert err["code"] == "invalid_request"
        assert "key" in err["message"].lower(), err["message"]
        assert _runs_of(session_factory, wid) == [] and _counts(session_factory) == before
    ok = _post_run(client, hdr, wid, r["contact"], {"ticket": "T-1"})  # control
    assert ok.status_code == 202, ok.text
    assert len(_runs_of(session_factory, wid)) == 1
