"""Workflow engine — triggers/actions breadth (plan sprint-2/09 Phase B TDD).

Covers: the CRUD event bus (emit→match→enqueue), field_changed refinement,
loop-guard chain exclusion, cron next_run_at + timezone, the scheduler tick,
status_changed subscription, the storage/transition/update executors, and IF
true/false routing. A synthetic ``wfticket`` entity (real ORM table, registered
like a module would) exercises the entity paths.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import Boolean, Column, String

from app.database import Base
from app.models import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID, User
from app.models.ai import AiAgent
from app.models.status import Status
from app.models.status_transition import StatusTransition
from app.models.workflow import WorkflowRun
from app.services.workflow_service import WorkflowService
from app.status_engine.registry import StatusEntity, register_status_entity
from app.workflow_engine.entities import WorkflowEntity, register_workflow_entity
from app.workflow_engine.entity_events import emit_entity_event


# ---- synthetic entity (a module's domain table) ----------------------------


class WfTicket(Base):
    __tablename__ = "test_wf_tickets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False, default="Ticket")
    archived = Column(Boolean, nullable=False, default=False)
    status_id = Column(String, nullable=True, index=True)


def _wf_count(db, status_id, tenant_id):
    q = db.query(WfTicket).filter(WfTicket.status_id == status_id)
    return (q.filter(WfTicket.tenant_id == tenant_id) if tenant_id else q).count()


def _wf_migrate(db, from_status_id, to_status_id, tenant_id):
    q = db.query(WfTicket).filter(WfTicket.status_id == from_status_id)
    if tenant_id:
        q = q.filter(WfTicket.tenant_id == tenant_id)
    n = q.update({WfTicket.status_id: to_status_id}, synchronize_session=False)
    db.flush()
    return n


register_status_entity(
    StatusEntity(
        entity_type="wfticket",
        label="WF Ticket",
        module="test",
        count_records=_wf_count,
        migrate_records=_wf_migrate,
    )
)
register_workflow_entity(
    WorkflowEntity(
        entity_type="wfticket",
        label="WF Ticket",
        model=WfTicket,
        fact_attrs=("name", "archived"),
        writable=frozenset({"name", "archived"}),
        has_status=True,
    )
)


# ---- helpers ---------------------------------------------------------------


def _node(nid, kind, ntype, config=None):
    return {"id": nid, "kind": kind, "type": ntype, "config": config or {}, "position": {"x": 0, "y": 0}}


def _edge(src, tgt, port="out"):
    return {"id": f"e_{src}_{tgt}_{port}", "source": src, "target": tgt, "sourcePort": port}


def _email(nid, to="a@b.com"):
    # Unique name per node id — names must be unique within a workflow.
    return _node(nid, "action", "email.send", {"mode": "custom", "to": to, "subject": "S", "body": "B", "name": f"Email {nid}"})


def _actor(db):
    return db.query(User).filter(User.tenant_id == DEFAULT_TENANT_ID).first()


def _publish(db, doc, *, active=True):
    svc = WorkflowService(db)
    actor = _actor(db)
    wf = svc.create(DEFAULT_TENANT_ID, name="WF", description="", draft=doc, actor_id=actor.id)
    svc.publish(wf.id, DEFAULT_TENANT_ID, actor.id)
    if active:
        svc.set_active(wf.id, DEFAULT_TENANT_ID, True)
    return wf.id


def _runs_for(db, workflow_id):
    return db.query(WorkflowRun).filter(WorkflowRun.workflow_id == workflow_id).all()


def _make_ticket(db, name="T1", status_id=None):
    t = WfTicket(tenant_id=DEFAULT_TENANT_ID, name=name, status_id=status_id)
    db.add(t)
    db.flush()
    return t


def _status(db, label, **flags):
    s = Status(
        entity_type="wfticket",
        key=label.lower(),
        label=label,
        color="blue",
        tenant_id=DEFAULT_TENANT_ID,
        **flags,
    )
    db.add(s)
    db.flush()
    return s


# ---- IF routing ------------------------------------------------------------


def _gt_tree(fact, value):
    return {"kind": "group", "combinator": "and", "rules": [
        {"kind": "condition", "fact": fact, "operator": "gt", "valueKind": "literal", "value": value}
    ]}


def test_if_routes_true_branch(session_factory):
    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "manual", {"inputs": [{"key": "score", "label": "Score", "type": "number"}]}),
        _node("cond", "if", "if", {"conditions": _gt_tree("trigger.input.score", 10)}),
        _email("yes", "yes@x.com"),
        _email("no", "no@x.com"),
    ], "edges": [
        _edge("trg", "cond"), _edge("cond", "yes", "true"), _edge("cond", "no", "false"),
    ]}
    wid = _publish(db, doc)
    run = WorkflowService(db).run(wid, DEFAULT_TENANT_ID, inputs={"score": 20}, is_test=False, actor=_actor(db))
    by_node = {n.node_id: n.status for n in db.query(WorkflowRun).filter(WorkflowRun.id == run.id).first().nodes}
    assert by_node["yes"] == "success"
    assert by_node["no"] == "skipped"


def test_debug_staleness_propagates_through_taken_if_branch(session_factory):
    """D6 — editing an upstream node re-runs it AND its active descendants on the
    TAKEN branch (staleness propagates), while the IF (unchanged) is reused and
    the untaken branch is never touched."""
    from app.workflow_engine.executor import debug_execute

    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "manual", {"inputs": [{"key": "score", "label": "Score", "type": "number"}]}),
        _node("cond", "if", "if", {"conditions": _gt_tree("trigger.input.score", 10)}),
        _email("a", "a@x.com"),
        _email("b", "b@x.com"),
        _email("c", "c@x.com"),
    ], "edges": [
        _edge("trg", "cond"),
        _edge("cond", "a", "true"),
        _edge("a", "b"),
        _edge("cond", "c", "false"),
    ]}
    wid = _publish(db, doc)
    run = WorkflowService(db).run(wid, DEFAULT_TENANT_ID, inputs={"score": 20}, is_test=False, actor=_actor(db))
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run.id).first()
    # Sanity: true branch ran, false branch skipped.
    statuses = {n.node_id: n.status for n in run.nodes}
    assert statuses["a"] == "success" and statuses["c"] == "skipped"

    # Edit "a" (scratch) and re-execute target "b": a re-runs (edited), b re-runs
    # (downstream of a recomputed node). cond reused, c never reached.
    touched = debug_execute(
        db, run, target_node_id="b", scratch={"a": {"subject": "Edited"}}, stale_node_ids=[]
    )
    ids = {t["nodeId"] for t in touched}
    assert "a" in ids and "b" in ids
    assert "cond" not in ids  # unchanged IF reused from cache
    assert "c" not in ids  # untaken (false) branch never re-runs

    # A stale id on the UNTAKEN branch is ignored — it isn't active.
    touched2 = debug_execute(
        db, run, target_node_id="a", scratch={}, stale_node_ids=["c"]
    )
    assert "c" not in {t["nodeId"] for t in touched2}

    # Full UNCHANGED scratch (the real frontend sends every node's config) must
    # NOT blanket-stale every node — only the explicit target re-runs, the rest
    # reuse cache (else side effects re-fire for the whole chain every Execute).
    full_scratch = {n["id"]: n["config"] for n in run.definition_snapshot_json["nodes"]}
    touched3 = debug_execute(
        db, run, target_node_id="b", scratch=full_scratch, stale_node_ids=[]
    )
    assert {t["nodeId"] for t in touched3} == {"b"}

    # Explicit "execute this node" on an OFF-PATH target (false branch) still
    # runs it — the n8n affordance, never a silent no-op.
    touched4 = debug_execute(
        db, run, target_node_id="c", scratch={}, stale_node_ids=[]
    )
    assert "c" in {t["nodeId"] for t in touched4}


def test_if_routes_false_branch(session_factory):
    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "manual", {"inputs": [{"key": "score", "label": "Score", "type": "number"}]}),
        _node("cond", "if", "if", {"conditions": _gt_tree("trigger.input.score", 10)}),
        _email("yes", "yes@x.com"),
        _email("no", "no@x.com"),
    ], "edges": [
        _edge("trg", "cond"), _edge("cond", "yes", "true"), _edge("cond", "no", "false"),
    ]}
    wid = _publish(db, doc)
    run = WorkflowService(db).run(wid, DEFAULT_TENANT_ID, inputs={"score": 5}, is_test=False, actor=_actor(db))
    by_node = {n.node_id: n.status for n in db.query(WorkflowRun).filter(WorkflowRun.id == run.id).first().nodes}
    assert by_node["no"] == "success"
    assert by_node["yes"] == "skipped"


# ---- CRUD event bus → match → enqueue --------------------------------------


def test_entity_created_triggers_a_run(session_factory):
    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "entity.created", {"entityType": "wfticket"}),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid = _publish(db, doc)

    ticket = _make_ticket(db)
    emit_entity_event(db, "wfticket", "created", ticket, tenant_id=DEFAULT_TENANT_ID)
    db.commit()

    runs = _runs_for(db, wid)
    assert len(runs) == 1
    assert runs[0].triggered_by == "event"
    assert runs[0].status == "success"


def test_inactive_or_unpublished_workflow_does_not_fire(session_factory):
    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "entity.created", {"entityType": "wfticket"}),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid = _publish(db, doc, active=False)  # published but inactive

    emit_entity_event(db, "wfticket", "created", _make_ticket(db), tenant_id=DEFAULT_TENANT_ID)
    db.commit()
    assert len(_runs_for(db, wid)) == 0


def test_field_changed_only_fires_for_the_named_field(session_factory):
    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "entity.field_changed", {"entityType": "wfticket", "field": "name"}),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid = _publish(db, doc)
    ticket = _make_ticket(db)

    emit_entity_event(db, "wfticket", "updated", ticket, tenant_id=DEFAULT_TENANT_ID,
                      changes={"archived": {"from": False, "to": True}})
    db.commit()
    assert len(_runs_for(db, wid)) == 0  # wrong field

    emit_entity_event(db, "wfticket", "updated", ticket, tenant_id=DEFAULT_TENANT_ID,
                      changes={"name": {"from": "T1", "to": "T2"}})
    db.commit()
    assert len(_runs_for(db, wid)) == 1  # the named field changed


# ---- loop guard ------------------------------------------------------------


def test_self_updating_workflow_does_not_storm(session_factory):
    db = session_factory()
    # Trigger on update, then update the same record → would loop forever
    # without the chain-exclusion guard.
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "entity.updated", {"entityType": "wfticket"}),
        _node("upd", "action", "entity.update", {
            "entityType": "wfticket",
            "recordId": "{{ trigger.recordId }}",
            "assignments": [{"field": "name", "value": "{{ trigger.changes.name.to }}-x"}],
        }),
    ], "edges": [_edge("trg", "upd")]}
    wid = _publish(db, doc)
    ticket = _make_ticket(db, name="A")

    emit_entity_event(db, "wfticket", "updated", ticket, tenant_id=DEFAULT_TENANT_ID,
                      changes={"name": {"from": "A", "to": "B"}})
    db.commit()

    # Exactly ONE run — the action's own write can't re-trigger the same workflow.
    assert len(_runs_for(db, wid)) == 1


# ---- real service instrumentation ------------------------------------------


def test_user_create_with_datetime_fact_dispatches_cleanly(session_factory):
    """Regression: user.created carries a datetime fact (createdAt) — the run
    payload (a JSON column) must serialize it, and a dispatch failure must never
    propagate to the create request."""
    from app.models.role import Role
    from app.services.user_service import UserService

    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "entity.created", {"entityType": "user"}),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid = _publish(db, doc)

    role = db.query(Role).filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin").first()
    UserService(db).create("New Person", "newperson@example.com", [role.id], tenant_id=DEFAULT_TENANT_ID)

    runs = _runs_for(db, wid)
    assert len(runs) == 1
    assert runs[0].trigger_payload_json["recordFacts"]["record.email"] == "newperson@example.com"


def test_real_role_create_fires_workflow(session_factory):
    from app.services.role_service import RoleService

    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "entity.created", {"entityType": "role"}),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid = _publish(db, doc)

    RoleService(db).create("Support", DEFAULT_TENANT_ID, description="Helps")

    runs = _runs_for(db, wid)
    assert len(runs) == 1
    assert runs[0].trigger_payload_json["recordFacts"].get("record.name") == "Support"


# ---- status_changed subscription -------------------------------------------


def test_status_change_triggers_a_run(session_factory):
    from app.services import status_machine

    db = session_factory()
    open_s = _status(db, "Open", is_initial=True)
    done_s = _status(db, "Done", is_terminal=True)
    db.add(StatusTransition(
        entity_type="wfticket", tenant_id=DEFAULT_TENANT_ID,
        from_status_id=open_s.id, to_status_id=done_s.id, label="Resolve",
    ))
    db.flush()
    ticket = _make_ticket(db, status_id=open_s.id)

    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "entity.status_changed", {"entityType": "wfticket", "toStatus": done_s.id}),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid = _publish(db, doc)

    status_machine.transition(db, "wfticket", ticket, done_s.id, actor=_actor(db), tenant_id=DEFAULT_TENANT_ID)

    runs = _runs_for(db, wid)
    assert len(runs) == 1
    assert runs[0].trigger_payload_json["toStatus"] == done_s.id


# ---- action executors ------------------------------------------------------


def test_transition_status_action_moves_the_record(session_factory):
    db = session_factory()
    open_s = _status(db, "Open", is_initial=True)
    done_s = _status(db, "Done", is_terminal=True)
    db.add(StatusTransition(
        entity_type="wfticket", tenant_id=DEFAULT_TENANT_ID,
        from_status_id=open_s.id, to_status_id=done_s.id, label="Resolve",
    ))
    db.flush()
    ticket = _make_ticket(db, status_id=open_s.id)

    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "manual", {"inputs": []}),
        _node("mv", "action", "entity.transition_status",
              {"entityType": "wfticket", "recordId": ticket.id, "toStatus": done_s.id}),
    ], "edges": [_edge("trg", "mv")]}
    wid = _publish(db, doc)
    WorkflowService(db).run(wid, DEFAULT_TENANT_ID, inputs={}, is_test=False, actor=_actor(db))

    db.refresh(ticket)
    assert ticket.status_id == done_s.id


def test_update_action_patches_whitelisted_field(session_factory):
    db = session_factory()
    ticket = _make_ticket(db, name="Before")
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "manual", {"inputs": []}),
        _node("upd", "action", "entity.update",
              {"entityType": "wfticket", "recordId": ticket.id,
               "assignments": [{"field": "name", "value": "After"}]}),
    ], "edges": [_edge("trg", "upd")]}
    wid = _publish(db, doc)
    WorkflowService(db).run(wid, DEFAULT_TENANT_ID, inputs={}, is_test=False, actor=_actor(db))

    db.refresh(ticket)
    assert ticket.name == "After"


def test_storage_put_and_get_roundtrip(session_factory):
    from app.workflow_engine.actions import storage_actions

    db = session_factory()
    ctx = {"trigger.input.id": "42"}
    out = storage_actions.storage_put(
        db, DEFAULT_TENANT_ID,
        {"key": "wf/{{ trigger.input.id }}.txt", "content": "hello"}, ctx,
    )
    assert out["size"] == 5 and out["mime"] == "text/plain" and out["key"]
    got = storage_actions.storage_get(db, DEFAULT_TENANT_ID, {"key": out["key"]}, {})
    assert got["mime"] == "text/plain"
    storage_actions.storage_delete(db, DEFAULT_TENANT_ID, {"key": out["key"]}, {})


def test_storage_actions_reject_path_traversal(session_factory):
    """A tenant-authored key must not escape the media root (read/delete)."""
    from app.workflow_engine.actions import storage_actions
    from app.workflow_engine.actions.storage_actions import ActionError

    db = session_factory()
    for bad in ["../../../etc/passwd", "/etc/passwd", "a/../../b", "~/secret"]:
        for fn in (storage_actions.storage_get, storage_actions.storage_delete, storage_actions.storage_put):
            with pytest.raises(ActionError):
                fn(db, DEFAULT_TENANT_ID, {"key": bad, "content": "x"}, {})


def test_entity_update_field_keyspace_is_canonical():
    """camelCase UI field keys normalize to the snake attr for the whitelist."""
    from app.workflow_engine.entities import attr_for

    assert attr_for("createdAt") == "created_at"
    assert attr_for("isActive") == "is_active"
    assert attr_for("name") == "name"


# ---- metadata endpoint -----------------------------------------------------


def test_metadata_lists_entities_statuses_and_fields(session_factory):
    db = session_factory()
    open_s = _status(db, "Open", is_initial=True)
    db.flush()

    meta = WorkflowService(db).metadata(DEFAULT_TENANT_ID)
    by_type = {e["type"]: e for e in meta["entities"]}
    assert {"user", "role", "tenant", "connection", "template", "workflow"} <= set(by_type)
    assert any(f["key"] == "email" for f in by_type["user"]["fields"])
    # entity.update may only write the whitelist — email is NOT writable.
    assert "name" in by_type["user"]["writableFields"]
    assert "email" not in by_type["user"]["writableFields"]
    # wfticket adopts the status engine → real status rows surface as options.
    assert by_type["wfticket"]["hasStatus"] is True
    assert any(s["value"] == open_s.id for s in by_type["wfticket"]["statuses"])


def test_workflow_metadata_omits_ai_agents_without_read_permission(client, session_factory):
    db = session_factory()
    role = db.query(User).filter(User.email == "demo@example.com").first().roles[0]
    role.permissions = [
        permission
        for permission in role.permissions
        if permission.key not in {"ai_agents.read", "ai_agents.manage"}
    ]
    db.add(AiAgent(tenant_id=DEFAULT_TENANT_ID, name="Hidden agent", model="stub-model-1"))
    db.commit()
    db.close()

    login = client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    assert login.status_code == 200, login.text
    response = client.get(
        "/workflows/metadata",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert response.status_code == 200, response.text
    assert "aiAgents" not in response.json()


def test_workflow_metadata_ai_agents_is_tenant_scoped(client, session_factory):
    db = session_factory()
    own = AiAgent(tenant_id=DEFAULT_TENANT_ID, name="Own agent", model="stub-model-1")
    foreign = AiAgent(tenant_id=PLATFORM_TENANT_ID, name="Foreign agent", model="stub-model-2")
    db.add_all([own, foreign])
    db.commit()
    own_item = {"id": own.id, "name": own.name, "model": own.model}
    db.close()

    login = client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    assert login.status_code == 200, login.text
    response = client.get(
        "/workflows/metadata",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["aiAgents"] == [own_item]


# ---- scheduler -------------------------------------------------------------


def test_compute_next_run_at_respects_timezone():
    from app.workflow_engine.scheduler import compute_next_run_at

    # 2026-06-09 08:00 UTC; "0 9 * * *" in New York (EDT, UTC-4) → 13:00 UTC.
    after = datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc)
    nxt = compute_next_run_at("0 9 * * *", "America/New_York", after=after)
    assert nxt == datetime(2026, 6, 9, 13, 0, tzinfo=timezone.utc)

    # Same cron in UTC → 09:00 UTC same day.
    assert compute_next_run_at("0 9 * * *", "", after=after) == datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)


def test_publish_arms_next_run_at(session_factory):
    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "schedule.cron", {"cron": "0 9 * * *", "timezone": ""}),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid = _publish(db, doc)
    from app.models.workflow import Workflow

    wf = db.query(Workflow).filter(Workflow.id == wid).first()
    assert wf.next_run_at is not None


def test_scheduler_tick_fires_due_workflow(session_factory):
    from app.models.workflow import Workflow
    from app.workflow_engine.scheduler import run_due_workflows

    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "schedule.cron", {"cron": "0 9 * * *", "timezone": ""}),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid = _publish(db, doc)
    wf = db.query(Workflow).filter(Workflow.id == wid).first()
    armed = wf.next_run_at

    # Advance "now" past the armed time → the tick fires + re-arms.
    fired = run_due_workflows(db, now=datetime(2099, 1, 1, tzinfo=timezone.utc))
    assert fired == 1
    runs = _runs_for(db, wid)
    assert len(runs) == 1 and runs[0].triggered_by == "schedule"
    db.refresh(wf)
    assert wf.next_run_at > armed


def test_prune_runs_drops_old_runs_and_cascades_nodes(session_factory):
    from datetime import timedelta

    from app.models.workflow import WorkflowRun, WorkflowRunNode
    from app.workflow_engine.scheduler import prune_runs

    db = session_factory()
    now = datetime(2099, 6, 1, tzinfo=timezone.utc)

    def _run(created_at):
        r = WorkflowRun(
            tenant_id=DEFAULT_TENANT_ID,
            workflow_id="wf-x",
            status="succeeded",
            triggered_by="manual",
            definition_snapshot_json={},
            trigger_payload_json={},
            created_at=created_at,
        )
        db.add(r)
        db.flush()
        db.add(WorkflowRunNode(run_id=r.id, node_id="n1", node_type="trigger", order_index=0))
        db.flush()
        return r.id

    # Default retention = 30d. One ancient run, one fresh run.
    old_id = _run(now - timedelta(days=45))
    fresh_id = _run(now - timedelta(days=5))
    db.commit()

    deleted = prune_runs(db, now=now)

    assert deleted == 1
    assert db.query(WorkflowRun).filter(WorkflowRun.id == old_id).first() is None
    assert db.query(WorkflowRun).filter(WorkflowRun.id == fresh_id).first() is not None
    # Cascade: the old run's nodes are gone too; the fresh run keeps its node.
    assert db.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == old_id).count() == 0
    assert db.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == fresh_id).count() == 1


def test_prune_runs_honors_per_tenant_retention(session_factory):
    from datetime import timedelta

    from app.models.workflow import WorkflowRun, WorkflowSettings
    from app.workflow_engine.scheduler import prune_runs

    db = session_factory()
    now = datetime(2099, 6, 1, tzinfo=timezone.utc)

    def _run(tenant_id, created_at):
        r = WorkflowRun(
            tenant_id=tenant_id, workflow_id="wf", status="success", triggered_by="manual",
            definition_snapshot_json={}, trigger_payload_json={}, created_at=created_at,
        )
        db.add(r)
        db.flush()
        return r.id

    # Tenant A: 7-day override → a 10-day-old run is pruned.
    # Tenant B: no override → default 30d keeps a 10-day-old run.
    db.add(WorkflowSettings(tenant_id="tenant-a", run_retention_days=7))
    a_old = _run("tenant-a", now - timedelta(days=10))
    b_keep = _run("tenant-b", now - timedelta(days=10))
    db.commit()

    deleted = prune_runs(db, now=now)

    assert deleted == 1
    assert db.query(WorkflowRun).filter(WorkflowRun.id == a_old).first() is None
    assert db.query(WorkflowRun).filter(WorkflowRun.id == b_keep).first() is not None


def test_workflow_settings_get_and_set(session_factory):
    from app.services.workflow_service import WorkflowService

    db = session_factory()
    svc = WorkflowService(db)
    days, is_default = svc.get_run_retention(DEFAULT_TENANT_ID)
    assert is_default and days == 30  # global default
    days, is_default = svc.set_run_retention(DEFAULT_TENANT_ID, 14)
    assert days == 14 and not is_default
    days, is_default = svc.get_run_retention(DEFAULT_TENANT_ID)
    assert days == 14 and not is_default


def test_emit_seam_notifies_registered_subscriber(session_factory):
    """D5 — the audit-log subscription seam is stable: a registered subscriber
    receives every domain event after commit, with the documented shape
    (entity_type/action/tenant_id/actor/changes old-new/record_facts)."""
    from app.workflow_engine import entity_events as ee

    db = session_factory()
    captured = []
    ee.register_event_subscriber(lambda _s, ev: captured.append(ev))
    sub = ee._subscribers[-1]
    try:
        ticket = _make_ticket(db, name="Seam")
        db.commit()
        ee.notify_entity_event(
            db, "wfticket", "updated", ticket,
            tenant_id=DEFAULT_TENANT_ID, actor=_actor(db),
            changes={"name": {"from": "Old", "to": "Seam"}},
        )
    finally:
        ee.unregister_event_subscriber(sub)

    assert captured, "subscriber received no event"
    ev = captured[-1]
    assert ev["entity_type"] == "wfticket"
    assert ev["action"] == "updated"
    assert ev["tenant_id"] == DEFAULT_TENANT_ID
    assert ev["actor"] and ev["actor"]["id"]
    assert ev["changes"]["name"] == {"from": "Old", "to": "Seam"}
    assert "record_facts" in ev and ev["record_id"] == ticket.id
