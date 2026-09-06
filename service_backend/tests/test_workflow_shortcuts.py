"""Plan sprint-4/27 (A3) S3 - the GENERIC `entity.shortcut` core trigger,
`create_run_for_event` extraction, and `WorkflowService.list_shortcuts` /
`run_shortcut`. Covers AC-IVE-35/37/38 at the core-service level (module-level
route tests - AC-IVE-36/39/40/42 - live in `tests/test_omnichannel_shortcuts.py`).

A synthetic ``WfShortcutTarget`` entity (a real ORM table, registered like a
module would - mirrors the `WfTicket` pattern in `test_workflow_triggers.py`)
proves the trigger/service are entity-agnostic, never hardcoded to
omnichannel.
"""
import uuid

import pytest
from sqlalchemy import Column, String

from app.database import Base
from app.models import DEFAULT_TENANT_ID, User
from app.models.workflow import RUN_PENDING, RUN_SUCCESS, WorkflowRun, WorkflowVersion
from app.services.workflow_service import (
    ShortcutCodeNotAuthorized,
    ShortcutNotFound,
    WorkflowService,
)
from app.workflow_engine.entities import WorkflowEntity, register_workflow_entity
from app.workflow_engine.entity_events import CodeNotAuthorized, _create_run, create_run_for_event
from app.workflow_engine.registry import get_trigger
from app.workflow_engine.code_runner import use_code_runner_client
from tests.test_code_workflow_action import FakeRunner

ENTITY_TYPE = "wf_shortcut_target"


class WfShortcutTarget(Base):
    __tablename__ = "test_wf_shortcut_targets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False, default="Target")
    note = Column(String, nullable=True)


register_workflow_entity(
    WorkflowEntity(
        entity_type=ENTITY_TYPE,
        label="Shortcut Target",
        model=WfShortcutTarget,
        fact_attrs=("name", "note"),
        writable=frozenset({"note"}),
        supports_shortcut=True,
    )
)


def _actor(db, email="demo@example.com") -> User:
    return db.query(User).filter(User.email == email).one()


def _make_record(db, *, tenant_id=DEFAULT_TENANT_ID, name="Rec 1") -> WfShortcutTarget:
    rec = WfShortcutTarget(tenant_id=tenant_id, name=name)
    db.add(rec)
    db.flush()
    return rec


def _doc(entity_type=ENTITY_TYPE, *, trigger_type="entity.shortcut", note_value=None):
    """Trigger + one `entity.update` action writing `note` from a trigger
    fact - proves the run context (`trigger.record.*`) reaches the action."""
    return {
        "schemaVersion": 1,
        "nodes": [
            {"id": "trg_1", "kind": "trigger", "type": trigger_type, "config": {"entityType": entity_type}},
            {
                "id": "upd_1",
                "kind": "action",
                "type": "entity.update",
                "config": {
                    "entityType": entity_type,
                    "recordId": "{{ trigger.record.id }}",
                    "assignments": [
                        {"field": "note", "value": note_value or "shortcut ran for {{ trigger.record.name }}"}
                    ],
                },
            },
        ],
        "edges": [{"id": "e1", "source": "trg_1", "target": "upd_1", "sourcePort": "out"}],
    }


def _publish_workflow(
    db, *, tenant_id=DEFAULT_TENANT_ID, entity_type=ENTITY_TYPE, name=None,
    is_active=True, actor=None, actor_id=None, trigger_type="entity.shortcut", draft=None,
):
    service = WorkflowService(db)
    wf = service.create(
        tenant_id, name=name or f"Shortcut WF {uuid.uuid4().hex[:8]}", description="",
        draft=draft or _doc(entity_type, trigger_type=trigger_type), actor_id=actor_id, actor=actor,
    )
    if is_active:
        service.set_active(wf.id, tenant_id, True)
    service.publish(wf.id, tenant_id, actor_id=actor_id, actor=actor)
    db.refresh(wf)
    return wf


# ── AC-IVE-35: trigger registration + entity opt-in ─────────────────────────
def test_entity_shortcut_trigger_registered():
    trig = get_trigger("entity.shortcut")
    assert trig is not None
    assert trig.label == "Shortcut"
    field = next(f for f in trig.fields if f.key == "entityType")
    assert field.required is True
    assert field.entity_filter == "shortcut"


def test_workflow_entity_supports_shortcut_flag(session_factory):
    from app.workflow_engine.entities import get_workflow_entity

    assert get_workflow_entity(ENTITY_TYPE).supports_shortcut is True
    # A core entity that never opted in stays False (default) - proves this
    # isn't a blanket flag.
    assert get_workflow_entity("user").supports_shortcut is False


def test_metadata_advertises_supports_shortcut(session_factory):
    db = session_factory()
    meta = WorkflowService(db).metadata(DEFAULT_TENANT_ID)
    by_type = {e["type"]: e for e in meta["entities"]}
    assert by_type[ENTITY_TYPE]["supportsShortcut"] is True
    assert by_type["user"]["supportsShortcut"] is False


# ── publish denormalization (no special-casing needed - the generic
# `entityType` config key already resolves for any entity.* trigger) ────────
def test_publish_denormalizes_entity_shortcut_trigger(session_factory):
    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(db, actor=admin, actor_id=admin.id)
    assert wf.trigger_type == "entity.shortcut"
    assert wf.trigger_entity_type == ENTITY_TYPE
    assert wf.current_version_id is not None


# ── create_run_for_event extraction - the bus's existing behavior is
# unchanged (this mirrors test_code_workflow_action.py's direct `_create_run`
# call, now routed through the extracted helper) ────────────────────────────
def test_create_run_for_event_returns_the_run(session_factory):
    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(db, actor=admin, actor_id=admin.id)
    rec = _make_record(db, name="Direct")
    db.commit()

    ev = {
        "entity_type": ENTITY_TYPE, "action": "shortcut", "tenant_id": DEFAULT_TENANT_ID,
        "record_id": rec.id, "actor": {"id": admin.id, "name": admin.name, "email": admin.email},
        "changes": None, "extra": {}, "record_facts": {"record.name": "Direct", "record.note": None},
        "source": None,
    }
    run = create_run_for_event(db, wf, ev, depth=0)
    assert run is not None
    assert run.status == RUN_SUCCESS
    assert run.correlation_key_digest is None or isinstance(run.correlation_key_digest, str)


def test_create_run_for_event_raises_on_unauthorized_code(session_factory):
    """The extraction preserves the exact fail-closed semantics the bus relies
    on (mirrors `test_automated_triggers_skip_unstamped_code_versions`)."""
    from app.services.workflow_service import CodeRunnerRequired  # noqa: F401 - not raised here

    db = session_factory()
    admin = _actor(db)
    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trigger", "kind": "trigger", "type": "manual", "config": {}},
            {"id": "code_1", "kind": "action", "type": "code.run", "config": {
                "language": "python", "source": "result = {}", "inputs": [],
                "outputs": [{"key": "ok", "type": "string", "required": True}],
            }},
        ],
        "edges": [{"id": "e1", "source": "trigger", "target": "code_1"}],
    }
    service = WorkflowService(db)
    wf = service.create(DEFAULT_TENANT_ID, name="Code shortcut", description="", draft=doc, actor_id=admin.id, actor=admin)
    with use_code_runner_client(FakeRunner(healthy=True)):
        service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=admin.id, actor=admin)
    version = db.query(WorkflowVersion).filter(WorkflowVersion.id == wf.current_version_id).one()
    version.code_authorized_by = None  # simulate a tampered/legacy stamp
    db.commit()

    ev = {
        "entity_type": "user", "action": "shortcut", "tenant_id": DEFAULT_TENANT_ID,
        "record_id": admin.id, "actor": {}, "changes": None, "extra": {}, "record_facts": {}, "source": None,
    }
    with pytest.raises(CodeNotAuthorized):
        create_run_for_event(db, wf, ev, depth=0)
    assert db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf.id).count() == 0


def test_bus_create_run_still_skips_silently_on_unauthorized_code(session_factory):
    """`_create_run` (the CRUD event bus) must keep its ORIGINAL fire-and-
    forget behavior after the extraction - it catches `CodeNotAuthorized`
    itself, never propagating."""
    db = session_factory()
    admin = _actor(db)
    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trigger", "kind": "trigger", "type": "manual", "config": {}},
            {"id": "code_1", "kind": "action", "type": "code.run", "config": {
                "language": "python", "source": "result = {}", "inputs": [],
                "outputs": [{"key": "ok", "type": "string", "required": True}],
            }},
        ],
        "edges": [{"id": "e1", "source": "trigger", "target": "code_1"}],
    }
    service = WorkflowService(db)
    wf = service.create(DEFAULT_TENANT_ID, name="Code bus", description="", draft=doc, actor_id=admin.id, actor=admin)
    with use_code_runner_client(FakeRunner(healthy=True)):
        service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=admin.id, actor=admin)
    version = db.query(WorkflowVersion).filter(WorkflowVersion.id == wf.current_version_id).one()
    version.code_authorized_by = None
    db.commit()

    before = db.query(WorkflowRun).count()
    _create_run(
        db, wf,
        {"entity_type": "user", "action": "created", "tenant_id": DEFAULT_TENANT_ID, "record_id": "x",
         "actor": {}, "changes": {}, "record_facts": {}},
        depth=0,
    )
    db.commit()
    assert db.query(WorkflowRun).count() == before


# ── AC-IVE-36 (core half): list_shortcuts ───────────────────────────────────
def test_list_shortcuts_published_active_matching_entity_only(session_factory):
    db = session_factory()
    admin = _actor(db)
    visible = _publish_workflow(db, actor=admin, actor_id=admin.id, name="Visible")

    # draft only (never published) - hidden
    WorkflowService(db).create(
        DEFAULT_TENANT_ID, name="Draft only", description="", draft=_doc(), actor_id=admin.id, actor=admin
    )
    # published but inactive - hidden
    _publish_workflow(db, actor=admin, actor_id=admin.id, name="Inactive", is_active=False)
    # published + active, then archived - hidden
    archived = _publish_workflow(db, actor=admin, actor_id=admin.id, name="Archived")
    WorkflowService(db).archive(archived.id, DEFAULT_TENANT_ID)
    # published + active but a DIFFERENT trigger type - hidden
    _publish_workflow(
        db, actor=admin, actor_id=admin.id, name="Not a shortcut",
        draft={
            "schemaVersion": 1,
            "nodes": [{"id": "trg_1", "kind": "trigger", "type": "entity.updated", "config": {"entityType": ENTITY_TYPE}}],
            "edges": [],
        },
    )
    # published + active shortcut, but a DIFFERENT entity type - hidden
    _publish_workflow(db, actor=admin, actor_id=admin.id, name="Wrong entity", entity_type="user", draft=_doc("user"))

    rows = WorkflowService(db).list_shortcuts(DEFAULT_TENANT_ID, ENTITY_TYPE)
    assert [r["workflowId"] for r in rows] == [visible.id]
    assert rows[0]["name"] == "Visible"


def test_list_shortcuts_tenant_isolation(session_factory):
    db = session_factory()
    admin = _actor(db)
    _publish_workflow(db, actor=admin, actor_id=admin.id, name="Mine")

    rows = WorkflowService(db).list_shortcuts("some-other-tenant-id", ENTITY_TYPE)
    assert rows == []


# ── AC-IVE-37/38 (core half): run_shortcut ──────────────────────────────────
def test_run_shortcut_happy_path(session_factory):
    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(db, actor=admin, actor_id=admin.id, name="Runnable")
    rec = _make_record(db, name="Acme Co")
    db.commit()

    run = WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, ENTITY_TYPE, rec, admin)

    assert run.status == RUN_SUCCESS
    assert run.triggered_by == "event"
    assert run.version_id == wf.current_version_id
    payload = run.trigger_payload_json
    assert payload["action"] == "shortcut"
    assert payload["recordId"] == rec.id
    assert payload["actor"]["id"] == admin.id
    db.refresh(rec)
    assert rec.note == "shortcut ran for Acme Co"


def test_run_shortcut_rejects_wrong_entity(session_factory):
    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(db, actor=admin, actor_id=admin.id, name="For target only")
    rec = _make_record(db)
    db.commit()
    with pytest.raises(ShortcutNotFound):
        WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, "user", rec, admin)


def test_run_shortcut_rejects_unpublished(session_factory):
    db = session_factory()
    admin = _actor(db)
    wf = WorkflowService(db).create(
        DEFAULT_TENANT_ID, name="Draft", description="", draft=_doc(), actor_id=admin.id, actor=admin
    )
    rec = _make_record(db)
    db.commit()
    with pytest.raises(ShortcutNotFound):
        WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, ENTITY_TYPE, rec, admin)


def test_run_shortcut_rejects_inactive(session_factory):
    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(db, actor=admin, actor_id=admin.id, name="Inactive one", is_active=False)
    rec = _make_record(db)
    db.commit()
    with pytest.raises(ShortcutNotFound):
        WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, ENTITY_TYPE, rec, admin)


def test_run_shortcut_rejects_archived(session_factory):
    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(db, actor=admin, actor_id=admin.id, name="Archived one")
    WorkflowService(db).archive(wf.id, DEFAULT_TENANT_ID)
    rec = _make_record(db)
    db.commit()
    with pytest.raises(ShortcutNotFound):
        WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, ENTITY_TYPE, rec, admin)


def test_run_shortcut_rejects_foreign_tenant(session_factory):
    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(db, actor=admin, actor_id=admin.id, name="Mine only")
    rec = _make_record(db)
    db.commit()
    with pytest.raises(ShortcutNotFound):
        WorkflowService(db).run_shortcut("some-other-tenant-id", wf.id, ENTITY_TYPE, rec, admin)


def test_run_shortcut_rejects_non_shortcut_trigger(session_factory):
    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(
        db, actor=admin, actor_id=admin.id, name="Not a shortcut trigger",
        draft={
            "schemaVersion": 1,
            "nodes": [{"id": "trg_1", "kind": "trigger", "type": "entity.updated", "config": {"entityType": ENTITY_TYPE}}],
            "edges": [],
        },
    )
    rec = _make_record(db)
    db.commit()
    with pytest.raises(ShortcutNotFound):
        WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, ENTITY_TYPE, rec, admin)


def test_run_shortcut_rejects_unauthorized_code_node(session_factory):
    db = session_factory()
    admin = _actor(db)
    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trg_1", "kind": "trigger", "type": "entity.shortcut", "config": {"entityType": ENTITY_TYPE}},
            {"id": "code_1", "kind": "action", "type": "code.run", "config": {
                "language": "python", "source": "result = {}", "inputs": [],
                "outputs": [{"key": "ok", "type": "string", "required": True}],
            }},
        ],
        "edges": [{"id": "e1", "source": "trg_1", "target": "code_1"}],
    }
    service = WorkflowService(db)
    wf = service.create(DEFAULT_TENANT_ID, name="Shortcut with code", description="", draft=doc, actor_id=admin.id, actor=admin)
    service.set_active(wf.id, DEFAULT_TENANT_ID, True)
    with use_code_runner_client(FakeRunner(healthy=True)):
        service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=admin.id, actor=admin)
    version = db.query(WorkflowVersion).filter(WorkflowVersion.id == wf.current_version_id).one()
    version.code_authorized_by = None  # simulate a tampered/legacy stamp
    db.commit()
    rec = _make_record(db)
    db.commit()

    before = db.query(WorkflowRun).count()
    with pytest.raises(ShortcutCodeNotAuthorized):
        WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, ENTITY_TYPE, rec, admin)
    assert db.query(WorkflowRun).count() == before


# ── loop guard - a shortcut run that updates a record may fire an
# `entity.updated` workflow ONCE, depth-limited (D5, generic bus behavior -
# the shortcut path is just a new ENTRY POINT into the same guard) ──────────
def test_shortcut_run_respects_loop_guard_depth(session_factory):
    db = session_factory()
    admin = _actor(db)
    shortcut_wf = _publish_workflow(db, actor=admin, actor_id=admin.id, name="Shortcut trigger")

    # A second workflow subscribed to entity.updated on the SAME entity - the
    # shortcut's `entity.update` action should fire it exactly once, at depth 1.
    updated_wf = _publish_workflow(
        db, actor=admin, actor_id=admin.id, name="Reacts to update",
        draft={
            "schemaVersion": 1,
            "nodes": [{"id": "trg_1", "kind": "trigger", "type": "entity.updated", "config": {"entityType": ENTITY_TYPE}}],
            "edges": [],
        },
    )
    rec = _make_record(db, name="Loop Co")
    db.commit()

    WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, shortcut_wf.id, ENTITY_TYPE, rec, admin)

    child_runs = db.query(WorkflowRun).filter(WorkflowRun.workflow_id == updated_wf.id).all()
    assert len(child_runs) == 1
    assert child_runs[0].depth == 1
    assert child_runs[0].triggered_by_run_id is not None


# ── round-3 codex triage B1: `run_shortcut` must not trust `entity_type` +
# `record` blindly - it resolves the WorkflowEntity and requires
# `supports_shortcut`, then RELOADS the record tenant-scoped rather than
# trusting the caller's object ────────────────────────────────────────────
NO_OPT_ENTITY_TYPE = "wf_shortcut_target_no_opt"

register_workflow_entity(
    WorkflowEntity(
        entity_type=NO_OPT_ENTITY_TYPE,
        label="Shortcut Target (no opt-in)",
        model=WfShortcutTarget,
        fact_attrs=("name", "note"),
        writable=frozenset({"note"}),
        supports_shortcut=False,
    ),
    register_facts=False,
)


def test_run_shortcut_rejects_entity_without_supports_shortcut(session_factory):
    """Even though `publish()` denormalizes ANY `entityType` onto
    `trigger_entity_type` with no registry check, `run_shortcut` refuses an
    entity that never opted in via `supports_shortcut=True` - defense in
    depth against a future caller (or a hand-crafted definition) targeting a
    non-shortcut entity."""
    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(
        db, actor=admin, actor_id=admin.id, name="No opt-in target",
        entity_type=NO_OPT_ENTITY_TYPE, draft=_doc(NO_OPT_ENTITY_TYPE),
    )
    rec = _make_record(db)
    db.commit()
    with pytest.raises(ShortcutNotFound):
        WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, NO_OPT_ENTITY_TYPE, rec, admin)


def test_run_shortcut_rejects_unregistered_entity_type(session_factory):
    db = session_factory()
    admin = _actor(db)
    rec = _make_record(db)
    db.commit()
    with pytest.raises(ShortcutNotFound):
        WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, "does-not-exist", "not_an_entity", rec, admin)


def test_run_shortcut_reloads_record_tenant_scoped(session_factory):
    """A record belonging to a DIFFERENT tenant than the one authorizing the
    run must never be operated on, even if the caller (by bug or malice)
    hands it straight to `run_shortcut` - the generic core function reloads
    it tenant-scoped via `load_record` rather than trusting the object."""
    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(db, actor=admin, actor_id=admin.id, name="Tenant guard", tenant_id=DEFAULT_TENANT_ID)
    foreign_rec = _make_record(db, tenant_id="some-other-tenant-id", name="Foreign")
    db.commit()

    with pytest.raises(ShortcutNotFound):
        WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, ENTITY_TYPE, foreign_rec, admin)
    db.refresh(foreign_rec)
    assert foreign_rec.note is None  # never touched


# ── round-3 codex triage B2: an unresolved serialized correlation key is a
# 409 conflict, never an opaque 500, and persists no run ────────────────────
def test_run_shortcut_serialized_execution_unresolved_key_is_conflict(session_factory):
    from app.services.workflow_service import ShortcutSerializationConflict

    db = session_factory()
    admin = _actor(db)
    doc = _doc()
    doc["execution"] = {"mode": "serialized", "correlationKey": "{{ trigger.record.missingField }}"}
    wf = _publish_workflow(db, actor=admin, actor_id=admin.id, name="Serialized shortcut", draft=doc)
    rec = _make_record(db, name="Acme Co")
    db.commit()

    before = db.query(WorkflowRun).count()
    with pytest.raises(ShortcutSerializationConflict):
        WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, ENTITY_TYPE, rec, admin)
    assert db.query(WorkflowRun).count() == before


# ── round-3 codex triage B4 (pre-merge follow-up item 1): a dispatch-side
# failure in the NON-EAGER path happens AFTER the run is committed
# durable-Pending, so it must never propagate (500 + a client retry
# duplicating the run) - it stays Pending, logged, run returned. The EAGER
# path is different: `dispatch_persisted_run` there IS execution (inline,
# same session, run row not yet durably committed on its own), so an
# executor crash must propagate - swallowing it would let a caller (e.g.
# `run_shortcut`) hand back a `runId` for a row whose transaction then rolls
# back, and tests/dev would silently lose real executor failures ─────────
def test_run_shortcut_survives_a_dispatch_failure_when_not_eager(session_factory, monkeypatch):
    import app.workflow_engine.serialization as serialization_mod
    from app.config import settings

    monkeypatch.setattr(settings, "celery_task_always_eager", False)

    def _boom(*args, **kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(serialization_mod, "dispatch_persisted_run", _boom)

    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(db, actor=admin, actor_id=admin.id, name="Dispatch failure")
    rec = _make_record(db, name="Acme Co")
    db.commit()

    run = WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, ENTITY_TYPE, rec, admin)
    assert run is not None
    assert run.status == RUN_PENDING
    assert db.query(WorkflowRun).filter(WorkflowRun.id == run.id).count() == 1


def test_run_shortcut_propagates_an_executor_crash_when_eager(session_factory, monkeypatch):
    """The default test settings are eager (`settings.celery_task_always_eager
    = True`, conftest) - the guard around `dispatch_persisted_run` must NOT
    swallow an exception raised in this mode, since eager dispatch IS
    execution on this session."""
    import app.workflow_engine.serialization as serialization_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("executor crashed")

    monkeypatch.setattr(serialization_mod, "dispatch_persisted_run", _boom)

    db = session_factory()
    admin = _actor(db)
    wf = _publish_workflow(db, actor=admin, actor_id=admin.id, name="Eager crash")
    rec = _make_record(db, name="Acme Co")
    db.commit()

    with pytest.raises(RuntimeError, match="executor crashed"):
        WorkflowService(db).run_shortcut(DEFAULT_TENANT_ID, wf.id, ENTITY_TYPE, rec, admin)
