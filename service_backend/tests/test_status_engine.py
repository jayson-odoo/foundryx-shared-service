"""Status & state-machine engine tests (sprint-2/01 §TDD).

Covers: registry resolution · two-tier fork+override · strict transition
reject · edge-role auth · branching (fan-out + loop-back) · block-delete →
deactivate → migrate-records · flag-based tenant lifecycle · notification
recipient resolution (USER/ROLE/DYNAMIC) + outbox enqueue · the
StatusTransitioned event.

A synthetic tenant-owned ``ticket`` entity (real ORM table, registered like a
module would) exercises the tenant-tier paths; the platform-owned ``tenant``
entity exercises operator paths against real lifecycle behavior.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Column, Integer, String

from app.database import Base
from app.models.utc_datetime import UTCDateTime
from app.events import EVENT_STATUS_TRANSITIONED, subscribe, unsubscribe
from app.models import DEFAULT_TENANT_ID, EmailOutbox, Role, User, UserStatus
from app.security import hash_password
from app.services import status_machine
from app.services.status_machine import TransitionForbidden, TransitionNotAllowed
from app.status_engine.registry import StatusEntity, register_status_entity
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, PLATFORM_EMAIL, PLATFORM_PASSWORD


class TicketRecord(Base):
    """Test-only entity table - what a module's domain table looks like."""

    __tablename__ = "test_tickets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False, default="Ticket")
    status_id = Column(String, nullable=False, index=True)
    assignee_id = Column(String, nullable=True)
    owner_id = Column(String, nullable=True)


class TicketLineRecord(Base):
    """Test-only CHILD table - exercises aggregate facts + DerivedTrigger
    (sprint-4/03 slice 2): a ticket's derived status reads SUM/COUNT of lines."""

    __tablename__ = "test_ticket_lines"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    ticket_id = Column(String, nullable=False, index=True)
    amount = Column(Integer, nullable=False, default=0)


class ScopedTicketRecord(Base):
    """Test-only SCOPED entity - each scope_id owns its own status graph
    (sprint-4/03 slice 2, AC-03-17 derived re-eval on a scoped machine)."""

    __tablename__ = "test_scoped_tickets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False, default="Scoped")
    status_id = Column(String, nullable=False, index=True)
    scope_id = Column(String, nullable=False, index=True)


class TimedTicketRecord(Base):
    """Test-only entity with a date column - exercises the TIME-based sweep
    (sprint-4/03 slice 3: Overdue when due_at < now)."""

    __tablename__ = "test_timed_tickets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False, default="Timed")
    status_id = Column(String, nullable=False, index=True)
    due_at = Column(UTCDateTime(), nullable=True)


def _ticket_count(db, status_id, tenant_id):
    q = db.query(TicketRecord).filter(TicketRecord.status_id == status_id)
    if tenant_id is not None:
        q = q.filter(TicketRecord.tenant_id == tenant_id)
    return q.count()


def _ticket_migrate(db, from_status_id, to_status_id, tenant_id):
    q = db.query(TicketRecord).filter(TicketRecord.status_id == from_status_id)
    if tenant_id is not None:
        q = q.filter(TicketRecord.tenant_id == tenant_id)
    count = q.update({TicketRecord.status_id: to_status_id}, synchronize_session=False)
    db.flush()
    return count


# NB: entity_type is "synthetic_ticket", NOT "ticket" - the EMS module
# (sprint-4/05 Cluster D slice 3) registers a REAL "ticket" status entity, and
# the registry is keyed by entity_type (last register wins). Squatting "ticket"
# here made the EMS bootstrap clobber this fixture mid-suite (the status-entity
# analogue of the templates.* / wa_templates.* permission-key collision lesson).
register_status_entity(
    StatusEntity(
        entity_type="synthetic_ticket",
        label="Ticket",
        module="test",
        count_records=_ticket_count,
        migrate_records=_ticket_migrate,
    )
)


# Rule fact source for the synthetic ticket - auto-edge conditions (derived
# status, sprint-4/03) are authored over ``record:ticket`` facts. Identical to
# test_rule_engine's registration (idempotent overwrite).
from app.rule_engine.registry import FactDef, register_fact_source  # noqa: E402

register_fact_source(
    "record:synthetic_ticket",
    "Ticket record",
    [FactDef(key="record.name", label="Name", type="string", resolver=lambda obj, db: obj.name)],
)


# Time-based derived entity (sprint-4/03 slice 3) - Overdue when due_at < now.
def _timed_candidates(db):
    return db.query(TimedTicketRecord).all()


register_status_entity(
    StatusEntity(
        entity_type="ticket_timed",
        label="Timed Ticket",
        module="test",
        count_records=lambda db, sid, tid: 0,
        migrate_records=lambda db, f, t, tid: 0,
        has_time_auto_edges=True,
        time_candidates=_timed_candidates,
    )
)

register_fact_source(
    "record:ticket_timed",
    "Timed ticket",
    [
        FactDef(
            key="record.isOverdue",
            label="Is overdue",
            type="boolean",
            resolver=lambda o, db: o.due_at is not None
            and o.due_at < datetime.now(timezone.utc),
        )
    ],
)


def _cond(fact, operator, value):
    return {
        "kind": "condition",
        "fact": fact,
        "operator": operator,
        "valueKind": "literal",
        "value": value,
    }


def _group(*rules, combinator="and"):
    return {"kind": "group", "combinator": combinator, "rules": list(rules)}


# ---- helpers ----


def _login(client, email, password, slug=None):
    payload = {"email": email, "password": password}
    if slug:
        payload["tenantSlug"] = slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _operator(client):
    return _login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform")


def _admin(client):
    return _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)


def _create_status(client, headers, entity, label, flags=None, key=None):
    payload = {"entityType": entity, "label": label, "color": "blue"}
    if flags:
        payload["flags"] = flags
    if key:
        payload["key"] = key
    res = client.post("/statuses", json=payload, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _create_edge(client, headers, entity, from_id, to_id, label, **extra):
    payload = {
        "entityType": entity,
        "fromStatusId": from_id,
        "toStatusId": to_id,
        "label": label,
        **extra,
    }
    res = client.post("/statuses/transitions", json=payload, headers=headers)
    return res


def _graph(client, headers, entity):
    res = client.get("/statuses", params={"entityType": entity}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _build_ticket_graph(client, headers):
    """Pending → Approved, Pending → Rejected, Rejected → Pending (loop-back)."""
    pending = _create_status(client, headers, "synthetic_ticket", "Pending", {"isInitial": True, "isDefault": True})
    approved = _create_status(client, headers, "synthetic_ticket", "Approved", {"isTerminal": True})
    rejected = _create_status(client, headers, "synthetic_ticket", "Rejected")
    assert _create_edge(client, headers, "synthetic_ticket", pending["id"], approved["id"], "Approve").status_code == 201
    assert _create_edge(client, headers, "synthetic_ticket", pending["id"], rejected["id"], "Reject").status_code == 201
    assert _create_edge(client, headers, "synthetic_ticket", rejected["id"], pending["id"], "Resubmit").status_code == 201
    return pending, approved, rejected


def _demo_user(db):
    return db.query(User).filter(User.email == ACTIVE_EMAIL).first()


# ---- registry resolution ----


def test_status_entities_registry_visibility(client):
    operator = _operator(client)
    res = client.get("/status-entities", headers=operator)
    assert res.status_code == 200
    types = {e["entityType"]: e for e in res.json()["data"]}
    assert "tenant" in types and types["tenant"]["platformOwned"] is True
    assert "synthetic_ticket" in types and types["synthetic_ticket"]["platformOwned"] is False

    # Tenant callers don't see platform-owned entities.
    admin = _admin(client)
    res = client.get("/status-entities", headers=admin)
    types = {e["entityType"] for e in res.json()["data"]}
    assert "synthetic_ticket" in types
    assert "tenant" not in types


def test_statuses_require_permission(client, session_factory):
    # A user with no roles holds no statuses.* keys.
    db = session_factory()
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email="norole@example.com",
            password=hash_password("password123"),
            name="No Role",
            status=UserStatus.ACTIVE.value,
        )
    )
    db.commit()
    db.close()
    headers = _login(client, "norole@example.com", "password123")
    assert client.get("/status-entities", headers=headers).status_code == 403
    assert client.get("/statuses", params={"entityType": "synthetic_ticket"}, headers=headers).status_code == 403


# ---- two-tier fork + override ----


def test_two_tier_platform_fallback_and_fork_on_edit(client, session_factory):
    operator = _operator(client)
    pending, approved, rejected = _build_ticket_graph(client, operator)

    # Tenant admin reads the platform defaults (no fork yet).
    admin = _admin(client)
    graph = _graph(client, admin, "synthetic_ticket")
    assert graph["source"] == "platform"
    assert {s["label"] for s in graph["statuses"]} == {"Pending", "Approved", "Rejected"}

    # A record pointing at a platform status, owned by the default tenant.
    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="T-1", status_id=pending["id"])
    db.add(ticket)
    db.commit()
    ticket_id = ticket.id
    db.close()

    # First tenant edit forks the WHOLE set…
    res = client.patch(
        f"/statuses/{pending['id']}", json={"label": "Awaiting Review"}, headers=admin
    )
    assert res.status_code == 200, res.text
    graph = _graph(client, admin, "synthetic_ticket")
    assert graph["source"] == "tenant"
    labels = {s["label"] for s in graph["statuses"]}
    assert "Awaiting Review" in labels and "Approved" in labels
    # …the edge graph rides along…
    assert len(graph["transitions"]) == 3
    # …and the tenant's records were remapped onto the forked rows.
    forked_ids = {s["id"] for s in graph["statuses"]}
    db = session_factory()
    assert db.query(TicketRecord).get(ticket_id).status_id in forked_ids
    db.close()

    # The platform tier is untouched (override, not mutation).
    graph = _graph(client, operator, "synthetic_ticket")
    assert graph["source"] == "platform"
    assert {s["label"] for s in graph["statuses"]} == {"Pending", "Approved", "Rejected"}


# ---- strict graph + branching ----


def test_strict_transition_rejected_without_edge(client, session_factory):
    operator = _operator(client)
    pending, approved, rejected = _build_ticket_graph(client, operator)

    db = session_factory()
    actor = _demo_user(db)
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, status_id=approved["id"])
    db.add(ticket)
    db.commit()

    # Approved is terminal and has no outgoing edge - no wall-cut (D4).
    with pytest.raises(TransitionNotAllowed):
        status_machine.transition(db, "synthetic_ticket", ticket, rejected["id"], actor)
    db.close()


def test_branching_fan_out_and_loop_back(client, session_factory):
    operator = _operator(client)
    pending, approved, rejected = _build_ticket_graph(client, operator)

    db = session_factory()
    actor = _demo_user(db)
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, status_id=pending["id"])
    db.add(ticket)
    db.commit()

    # Fan-out: Pending → Rejected; loop-back: Rejected → Pending; then Approve.
    status_machine.transition(db, "synthetic_ticket", ticket, rejected["id"], actor)
    assert ticket.status_id == rejected["id"]
    status_machine.transition(db, "synthetic_ticket", ticket, pending["id"], actor)
    assert ticket.status_id == pending["id"]
    status_machine.transition(db, "synthetic_ticket", ticket, approved["id"], actor)
    assert ticket.status_id == approved["id"]
    db.close()


def test_graph_validation_rules(client):
    operator = _operator(client)
    pending, approved, rejected = _build_ticket_graph(client, operator)

    # Self-loop refused.
    assert _create_edge(client, operator, "synthetic_ticket", pending["id"], pending["id"], "Loop").status_code == 422
    # Outgoing edge from a terminal status refused.
    assert _create_edge(client, operator, "synthetic_ticket", approved["id"], pending["id"], "Reopen").status_code == 422
    # Duplicate edge refused.
    assert _create_edge(client, operator, "synthetic_ticket", pending["id"], approved["id"], "Approve again").status_code == 422
    # Cross-entity edge refused (statuses must live in the entity's set).
    tenant_graph = _graph(client, operator, "tenant")
    tenant_status = tenant_graph["statuses"][0]["id"]
    assert _create_edge(client, operator, "synthetic_ticket", pending["id"], tenant_status, "Bad").status_code == 404


# ---- edge-role authorization (D5) ----


def test_edge_roles_gate_who_can_fire(client, session_factory):
    operator = _operator(client)
    pending, approved, rejected = _build_ticket_graph(client, operator)

    admin = _admin(client)
    # Fork to the tenant tier first (roles are tenant-scoped).
    client.patch(f"/statuses/{pending['id']}", json={"label": "Pending"}, headers=admin)
    graph = _graph(client, admin, "synthetic_ticket")
    by_label = {s["label"]: s for s in graph["statuses"]}
    edge = next(t for t in graph["transitions"] if t["label"] == "Approve")

    db = session_factory()
    admin_role = (
        db.query(Role)
        .filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin")
        .first()
    )
    # Gate "Approve" behind Admin.
    res = client.patch(
        f"/statuses/transitions/{edge['id']}",
        json={"roleIds": [admin_role.id]},
        headers=admin,
    )
    assert res.status_code == 200, res.text

    actor = _demo_user(db)  # holds Admin
    bystander = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=f"nobody-{uuid.uuid4().hex[:6]}@example.com",
        password=hash_password("password123"),
        name="No Roles",
        status=UserStatus.ACTIVE.value,
    )
    db.add(bystander)
    db.commit()

    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, status_id=by_label["Pending"]["id"])
    db.add(ticket)
    db.commit()

    # Denied without the role…
    with pytest.raises(TransitionForbidden):
        status_machine.transition(db, "synthetic_ticket", ticket, by_label["Approved"]["id"], bystander)
    # …allowed with it.
    status_machine.transition(db, "synthetic_ticket", ticket, by_label["Approved"]["id"], actor)
    assert ticket.status_id == by_label["Approved"]["id"]
    db.close()


# ---- delete / deactivate / migrate (D8) ----


def test_block_delete_then_deactivate_and_migrate(client, session_factory):
    operator = _operator(client)
    pending, approved, rejected = _build_ticket_graph(client, operator)

    db = session_factory()
    db.add(TicketRecord(tenant_id=DEFAULT_TENANT_ID, status_id=rejected["id"]))
    db.add(TicketRecord(tenant_id=DEFAULT_TENANT_ID, status_id=rejected["id"]))
    db.commit()
    db.close()

    # Hard delete blocked while referenced.
    res = client.delete(f"/statuses/{rejected['id']}", headers=operator)
    assert res.status_code == 409
    assert "2 record(s)" in res.json()["detail"]

    # Deactivate instead - hidden from pickers, records keep it.
    res = client.post(f"/statuses/{rejected['id']}/deactivate", headers=operator)
    assert res.status_code == 200 and res.json()["isActive"] is False

    # Migrate the records off, then delete cleanly (edges drop with the node).
    res = client.post(
        f"/statuses/{rejected['id']}/migrate-records",
        json={"toStatusId": pending["id"]},
        headers=operator,
    )
    assert res.status_code == 200 and res.json()["migrated"] == 2
    assert client.delete(f"/statuses/{rejected['id']}", headers=operator).status_code == 204
    graph = _graph(client, operator, "synthetic_ticket")
    assert {s["label"] for s in graph["statuses"]} == {"Pending", "Approved"}
    assert len(graph["transitions"]) == 1  # Reject + Resubmit died with the node


def test_system_status_locks(client):
    operator = _operator(client)
    graph = _graph(client, operator, "tenant")
    active = next(s for s in graph["statuses"] if s["key"] == "active")

    # Label/color editable on system rows…
    res = client.patch(
        f"/statuses/{active['id']}", json={"label": "Live", "color": "emerald"}, headers=operator
    )
    assert res.status_code == 200 and res.json()["label"] == "Live"
    # …behavior flags and delete are locked.
    res = client.patch(
        f"/statuses/{active['id']}", json={"flags": {"blocksAccess": True}}, headers=operator
    )
    assert res.status_code == 409
    assert client.delete(f"/statuses/{active['id']}", headers=operator).status_code == 409
    # Restore the label for other tests' readability.
    client.patch(f"/statuses/{active['id']}", json={"label": "Active", "color": "green"}, headers=operator)


def test_reorder_is_batch_and_display_only(client):
    operator = _operator(client)
    pending, approved, rejected = _build_ticket_graph(client, operator)
    res = client.post(
        "/statuses/reorder",
        json={"entityType": "synthetic_ticket", "orderedIds": [rejected["id"], approved["id"], pending["id"]]},
        headers=operator,
    )
    assert res.status_code == 200
    labels = [s["label"] for s in res.json()["statuses"]]
    assert labels == ["Rejected", "Approved", "Pending"]
    # Partial reorder refused.
    res = client.post(
        "/statuses/reorder",
        json={"entityType": "synthetic_ticket", "orderedIds": [pending["id"]]},
        headers=operator,
    )
    assert res.status_code == 422


# ---- flag-based tenant lifecycle (the rewrite) ----


def test_custom_blocking_status_gates_login_by_flag(client):
    """A NEW operator-defined status with blocks_access kills sign-in - proof
    the lifecycle reads flags, not a category enum."""
    operator = _operator(client)

    # Provision a tenant with a user.
    res = client.post(
        "/platform/tenants",
        json={
            "name": "Flagged Co",
            "slug": "flagged-co",
            "adminName": "Flag Admin",
            "adminEmail": "admin@flagged.co",
            "adminPassword": "ChangeMe1!",
        },
        headers=operator,
    )
    assert res.status_code == 201, res.text
    tenant_id = res.json()["id"]
    assert _login(client, "admin@flagged.co", "ChangeMe1!", "flagged-co")

    # New status "On Hold" (blocks access) + edge Active → On Hold.
    on_hold = _create_status(
        client, operator, "tenant", "On Hold", {"blocksAccess": True}
    )
    graph = _graph(client, operator, "tenant")
    active = next(s for s in graph["statuses"] if s["key"] == "active")
    assert _create_edge(
        client, operator, "tenant", active["id"], on_hold["id"], "Put on hold"
    ).status_code == 201

    # Fire it through the generic transition endpoint (button = edge label).
    res = client.get(f"/platform/tenants/{tenant_id}/transitions", headers=operator)
    assert res.status_code == 200
    hold_edge = next(t for t in res.json()["data"] if t["label"] == "Put on hold")
    res = client.post(
        f"/platform/tenants/{tenant_id}/transition",
        json={"transitionId": hold_edge["id"]},
        headers=operator,
    )
    assert res.status_code == 200
    assert res.json()["statusLabel"] == "On Hold"

    # Login now blocked purely by the flag.
    res = client.post(
        "/auth/login",
        json={"email": "admin@flagged.co", "password": "ChangeMe1!", "tenantSlug": "flagged-co"},
    )
    assert res.status_code == 403


def test_generic_transition_keeps_legacy_permission_boundary(client, session_factory):
    """The generic /transition endpoint must not widen privileges
    (code-review fix): suspend-like moves need tenants.suspend, archive-like
    moves need tenants.archive - tenants.update alone is NOT enough."""
    from app.models import PLATFORM_TENANT_ID, Permission

    operator = _operator(client)
    res = client.post(
        "/platform/tenants",
        json={
            "name": "Boundary Co",
            "slug": "boundary-co",
            "adminName": "B Admin",
            "adminEmail": "admin@boundary.co",
            "adminPassword": "ChangeMe1!",
        },
        headers=operator,
    )
    assert res.status_code == 201, res.text
    tenant_id = res.json()["id"]

    # A platform user holding tenants.read + tenants.update but NO
    # suspend/archive keys.
    db = session_factory()
    keys = {"tenants.read", "tenants.update"}
    perms = db.query(Permission).filter(Permission.key.in_(keys)).all()
    assert len(perms) == 2
    limited_role = Role(tenant_id=PLATFORM_TENANT_ID, name="Limited Ops")
    limited_role.permissions = perms
    db.add(limited_role)
    db.flush()
    limited = User(
        tenant_id=PLATFORM_TENANT_ID,
        email="limited@platform.example.com",
        password=hash_password("ChangeMe1!"),
        name="Limited Operator",
        status=UserStatus.ACTIVE.value,
    )
    limited.roles = [limited_role]
    db.add(limited)
    db.commit()
    db.close()

    limited_headers = _login(client, "limited@platform.example.com", "ChangeMe1!", "platform")

    # Edge ids come from the operator's transitions listing.
    edges = client.get(
        f"/platform/tenants/{tenant_id}/transitions", headers=operator
    ).json()["data"]
    suspend_edge = next(e for e in edges if e["label"] == "Suspend")

    # tenants.update alone → 403 naming the key it lacks.
    res = client.post(
        f"/platform/tenants/{tenant_id}/transition",
        json={"transitionId": suspend_edge["id"]},
        headers=limited_headers,
    )
    assert res.status_code == 403
    assert "tenants.suspend" in res.json()["detail"]

    # The console graph endpoint needs only tenants.read (decoupled from
    # statuses.read - the limited role holds no statuses.* keys).
    res = client.get("/platform/tenants/status-graph", headers=limited_headers)
    assert res.status_code == 200
    assert {s["key"] for s in res.json()["statuses"]} >= {"active", "suspended", "archived"}

    # With tenants.suspend granted, the same call succeeds.
    db = session_factory()
    role = db.query(Role).filter(Role.name == "Limited Ops").first()
    role.permissions = role.permissions + (
        db.query(Permission).filter(Permission.key == "tenants.suspend").all()
    )
    db.commit()
    db.close()
    res = client.post(
        f"/platform/tenants/{tenant_id}/transition",
        json={"transitionId": suspend_edge["id"]},
        headers=limited_headers,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "SUSPENDED"


def test_archived_is_restorable(client, session_factory):
    """Sprint-2/02 revision: archive is reversible - archived is NOT terminal
    and the seeded Restore edge moves a tenant back to active."""
    operator = _operator(client)
    graph = _graph(client, operator, "tenant")
    archived = next(s for s in graph["statuses"] if s["key"] == "archived")
    active = next(s for s in graph["statuses"] if s["key"] == "active")
    assert archived["isTerminal"] is False
    restore = next(
        t
        for t in graph["transitions"]
        if t["fromStatusId"] == archived["id"] and t["toStatusId"] == active["id"]
    )
    assert restore["label"] == "Restore"

    # Archive the default tenant, then restore it through the machine.
    from app.models import DEFAULT_TENANT_ID
    from app.models.tenant import Tenant

    db = session_factory()
    tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
    status_machine.transition(db, "tenant", tenant, archived["id"], None)
    assert tenant.status_id == archived["id"]
    status_machine.transition(db, "tenant", tenant, active["id"], None)
    assert tenant.status_id == active["id"]
    db.close()


# ---- notifications (D6) ----


def test_notification_recipients_resolve_and_enqueue_email(client, session_factory):
    operator = _operator(client)
    pending, approved, rejected = _build_ticket_graph(client, operator)

    admin = _admin(client)
    client.patch(f"/statuses/{pending['id']}", json={"label": "Pending"}, headers=admin)
    graph = _graph(client, admin, "synthetic_ticket")
    by_label = {s["label"]: s for s in graph["statuses"]}
    edge = next(t for t in graph["transitions"] if t["label"] == "Approve")

    db = session_factory()
    viewer_role = Role(
        tenant_id=DEFAULT_TENANT_ID, name="Watchers", description="Gets notified"
    )
    db.add(viewer_role)
    db.flush()
    owner = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="owner@example.com",
        password=hash_password("password123"),
        name="Record Owner",
        status=UserStatus.ACTIVE.value,
    )
    watcher = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="watcher@example.com",
        password=hash_password("password123"),
        name="Watcher",
        status=UserStatus.ACTIVE.value,
    )
    watcher.roles = [viewer_role]
    db.add_all([owner, watcher])
    db.commit()

    # Spec: USER (owner directly), ROLE (Viewer), DYNAMIC ACTOR + RECORD_OWNER.
    res = client.patch(
        f"/statuses/transitions/{edge['id']}",
        json={
            "notifications": [
                {
                    "channel": "EMAIL",
                    "templateSubject": "{{recordLabel}} moved to {{toStatus}}",
                    "templateBody": "{{actorName}} performed {{transitionLabel}} on {{recordLabel}}.",
                    "recipients": [
                        {"targetType": "USER", "targetId": owner.id},
                        {"targetType": "ROLE", "targetId": viewer_role.id},
                        {"targetType": "DYNAMIC", "dynamicKey": "ACTOR"},
                        {"targetType": "DYNAMIC", "dynamicKey": "RECORD_OWNER"},
                    ],
                }
            ]
        },
        headers=admin,
    )
    assert res.status_code == 200, res.text
    assert len(res.json()["notifications"][0]["recipients"]) == 4

    actor = _demo_user(db)
    ticket = TicketRecord(
        tenant_id=DEFAULT_TENANT_ID,
        name="T-99",
        status_id=by_label["Pending"]["id"],
        owner_id=owner.id,
    )
    db.add(ticket)
    db.commit()

    before = db.query(EmailOutbox).count()
    status_machine.transition(db, "synthetic_ticket", ticket, by_label["Approved"]["id"], actor)
    rows = db.query(EmailOutbox).offset(before).all()

    # owner (USER + RECORD_OWNER dedup to one), watcher (ROLE), actor (DYNAMIC).
    recipients = {r.to_email for r in rows}
    assert recipients == {"owner@example.com", "watcher@example.com", ACTIVE_EMAIL}
    sample = rows[0]
    assert sample.subject == "T-99 moved to Approved"
    assert "Demo User performed Approve on T-99." in sample.text_body
    assert sample.template_key == "status_notification"
    db.close()


def test_recipient_targets_must_belong_to_author_tenant(client, session_factory):
    """Code-review fix: a spec may only reference the author tier's own users/
    roles - a foreign tenant's role_id/user_id is rejected at save (422), or
    cross-tenant email leaks at dispatch."""
    operator = _operator(client)
    _build_ticket_graph(client, operator)

    admin = _admin(client)
    graph = _graph(client, admin, "synthetic_ticket")
    edge = next(t for t in graph["transitions"] if t["label"] == "Approve")

    db = session_factory()
    from app.models import PLATFORM_TENANT_ID

    foreign_role = db.query(Role).filter(Role.tenant_id == PLATFORM_TENANT_ID).first()
    foreign_user = db.query(User).filter(User.tenant_id == PLATFORM_TENANT_ID).first()
    assert foreign_role is not None and foreign_user is not None
    foreign_role_id, foreign_user_id = foreign_role.id, foreign_user.id
    db.close()

    def _spec(recipient):
        return {
            "notifications": [
                {
                    "channel": "EMAIL",
                    "templateSubject": "s",
                    "templateBody": "b",
                    "recipients": [recipient],
                }
            ]
        }

    res = client.patch(
        f"/statuses/transitions/{edge['id']}",
        json=_spec({"targetType": "ROLE", "targetId": foreign_role_id}),
        headers=admin,
    )
    assert res.status_code == 422, res.text

    res = client.patch(
        f"/statuses/transitions/{edge['id']}",
        json=_spec({"targetType": "USER", "targetId": foreign_user_id}),
        headers=admin,
    )
    assert res.status_code == 422, res.text


def test_dispatch_never_resolves_cross_tenant_recipients(client, session_factory):
    """Defense-in-depth: even a recipient row planted PAST the API validation
    (direct DB write) must not email a foreign tenant's users at dispatch."""
    operator = _operator(client)
    _build_ticket_graph(client, operator)

    admin = _admin(client)
    graph = _graph(client, admin, "synthetic_ticket")
    edge = next(t for t in graph["transitions"] if t["label"] == "Approve")

    # Legit spec first (own-tenant role keeps the spec non-empty).
    db = session_factory()
    own_role = Role(tenant_id=DEFAULT_TENANT_ID, name="Own Watchers")
    db.add(own_role)
    db.commit()
    res = client.patch(
        f"/statuses/transitions/{edge['id']}",
        json={
            "notifications": [
                {
                    "channel": "EMAIL",
                    "templateSubject": "s",
                    "templateBody": "b",
                    "recipients": [{"targetType": "ROLE", "targetId": own_role.id}],
                }
            ]
        },
        headers=admin,
    )
    assert res.status_code == 200, res.text

    # The tenant edit forks the set - re-read for the TENANT tier's ids.
    graph = _graph(client, admin, "synthetic_ticket")
    by_label = {s["label"]: s for s in graph["statuses"]}

    # Plant a cross-tenant ROLE recipient + a cross-tenant assignee directly.
    from app.models import PLATFORM_TENANT_ID
    from app.models.notification_spec import NotificationRecipient, NotificationSpec

    foreign_role = db.query(Role).filter(Role.tenant_id == PLATFORM_TENANT_ID).first()
    foreign_user = db.query(User).filter(User.tenant_id == PLATFORM_TENANT_ID).first()
    spec = db.query(NotificationSpec).filter(NotificationSpec.tenant_id == DEFAULT_TENANT_ID).first()
    spec.recipients.append(
        NotificationRecipient(target_type="ROLE", target_id=foreign_role.id)
    )
    spec.recipients.append(
        NotificationRecipient(target_type="DYNAMIC", dynamic_key="ASSIGNEE")
    )
    db.commit()

    actor = _demo_user(db)
    ticket = TicketRecord(
        tenant_id=DEFAULT_TENANT_ID,
        name="T-XT",
        status_id=by_label["Pending"]["id"],
        assignee_id=foreign_user.id,  # cross-tenant assignee (corrupt FK)
    )
    db.add(ticket)
    db.commit()

    before = db.query(EmailOutbox).count()
    status_machine.transition(db, "synthetic_ticket", ticket, by_label["Approved"]["id"], actor)
    rows = db.query(EmailOutbox).offset(before).all()
    recipients = {r.to_email for r in rows}

    foreign_emails = {
        u.email for u in db.query(User).filter(User.tenant_id == PLATFORM_TENANT_ID)
    }
    assert recipients.isdisjoint(foreign_emails), recipients
    db.close()


def test_in_app_channel_is_modeled_but_inert(client, session_factory):
    operator = _operator(client)
    pending, approved, rejected = _build_ticket_graph(client, operator)
    graph = _graph(client, operator, "synthetic_ticket")
    edge = next(t for t in graph["transitions"] if t["label"] == "Approve")

    db = session_factory()
    actor = _demo_user(db)
    res = client.patch(
        f"/statuses/transitions/{edge['id']}",
        json={
            "notifications": [
                {
                    "channel": "IN_APP",
                    "templateSubject": "Heads up",
                    "templateBody": "{{recordLabel}} approved.",
                    "recipients": [{"targetType": "DYNAMIC", "dynamicKey": "ACTOR"}],
                }
            ]
        },
        headers=operator,
    )
    assert res.status_code == 200, res.text

    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, status_id=pending["id"])
    db.add(ticket)
    db.commit()
    before = db.query(EmailOutbox).count()
    status_machine.transition(db, "synthetic_ticket", ticket, approved["id"], actor)
    assert db.query(EmailOutbox).count() == before  # no email for IN_APP
    db.close()


# ---- event seam ----


def test_status_transitioned_event_emitted(client, session_factory):
    operator = _operator(client)
    pending, approved, rejected = _build_ticket_graph(client, operator)

    events = []
    handler = events.append
    subscribe(EVENT_STATUS_TRANSITIONED, handler)
    try:
        db = session_factory()
        actor = _demo_user(db)
        actor_id = actor.id  # capture before the machine's commit expires it
        ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, status_id=pending["id"])
        db.add(ticket)
        db.commit()
        status_machine.transition(db, "synthetic_ticket", ticket, approved["id"], actor)
        db.close()
    finally:
        unsubscribe(EVENT_STATUS_TRANSITIONED, handler)

    assert len(events) == 1
    payload = events[0]
    assert payload["entity_type"] == "synthetic_ticket"
    assert payload["from_status_id"] == pending["id"]
    assert payload["to_status_id"] == approved["id"]
    assert payload["actor_id"] == actor_id


# ---- derived / computed status (sprint-4/03, slice 1) ----


def _auto_edge(client, headers, from_id, to_id, label, value, sort_order=None):
    """Create an AUTO edge fired when record.name == value."""
    extra = {"triggerMode": "auto", "conditionsJson": _group(_cond("record.name", "eq", value))}
    if sort_order is not None:
        extra["sortOrder"] = sort_order
    return _create_edge(client, headers, "synthetic_ticket", from_id, to_id, label, **extra)


def test_trigger_mode_defaults_manual(client):
    """AC-03-01 - a normal edge is 'manual'; the graph wire carries triggerMode."""
    operator = _operator(client)
    pending, approved, _rejected = _build_ticket_graph(client, operator)
    graph = _graph(client, operator, "synthetic_ticket")
    assert all(t["triggerMode"] == "manual" for t in graph["transitions"])


def test_auto_edge_requires_conditions(client):
    """AC-03-02 - an auto edge with no conditions is rejected (would fire always)."""
    operator = _operator(client)
    pending, approved, _rejected = _build_ticket_graph(client, operator)
    res = _create_edge(
        client, operator, "synthetic_ticket", pending["id"], approved["id"], "Auto", triggerMode="auto"
    )
    assert res.status_code == 422
    assert "conditions" in res.json()["detail"].lower()


def test_auto_edge_forbids_roles(client, session_factory):
    """AC-03-03 - an auto edge cannot be role-restricted (system-fired)."""
    operator = _operator(client)
    admin = _admin(client)
    # Fork to tenant tier (roles are tenant-scoped) and grab the Admin role.
    pending, approved, _rejected = _build_ticket_graph(client, operator)
    client.patch(f"/statuses/{pending['id']}", json={"label": "Pending"}, headers=admin)
    graph = _graph(client, admin, "synthetic_ticket")
    by_label = {s["label"]: s for s in graph["statuses"]}
    db = session_factory()
    admin_role = (
        db.query(Role).filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin").first()
    )
    role_id = admin_role.id
    db.close()
    res = _create_edge(
        client,
        admin,
        "synthetic_ticket",
        by_label["Pending"]["id"],
        by_label["Approved"]["id"],
        "AutoRole",
        triggerMode="auto",
        conditionsJson=_group(_cond("record.name", "eq", "x")),
        roleIds=[role_id],
    )
    assert res.status_code == 422
    assert "role" in res.json()["detail"].lower()


def test_update_to_auto_validates_resulting_state(client):
    """AC-03-02/03 (update path) - flipping an edge to auto needs conditions."""
    operator = _operator(client)
    pending, approved, _rejected = _build_ticket_graph(client, operator)
    graph = _graph(client, operator, "synthetic_ticket")
    approve = next(t for t in graph["transitions"] if t["label"] == "Approve")

    # No conditions on the row → flip to auto rejected.
    res = client.patch(
        f"/statuses/transitions/{approve['id']}", json={"triggerMode": "auto"}, headers=operator
    )
    assert res.status_code == 422

    # Provide conditions in the SAME patch → accepted.
    res = client.patch(
        f"/statuses/transitions/{approve['id']}",
        json={"triggerMode": "auto", "conditionsJson": _group(_cond("record.name", "eq", "ok"))},
        headers=operator,
    )
    assert res.status_code == 200 and res.json()["triggerMode"] == "auto"


def test_is_initial_still_converges_to_at_most_one(client):
    """AC-20 pre-existing behaviour, unaffected by the new guard: marking a
    SECOND status `isInitial` silently converges the first one off."""
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    b = _create_status(client, operator, "synthetic_ticket", "B", {"isInitial": True})
    graph = _graph(client, operator, "synthetic_ticket")
    initial = [s for s in graph["statuses"] if s["isInitial"]]
    assert [s["id"] for s in initial] == [b["id"]]
    assert next(s for s in graph["statuses"] if s["id"] == a["id"])["isInitial"] is False


def test_is_initial_cannot_be_unset_on_the_last_initial_status(client):
    """AC-20: EXACTLY one `is_initial` per set, never zero - `is_initial`
    converging to AT MOST one (above) must never converge a set to ZERO
    either, or a new record has nowhere to start. Generic - the guard lives
    in `StatusService._apply_flags`, not any one entity's code."""
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    res = client.patch(
        f"/statuses/{a['id']}", json={"flags": {"isInitial": False}}, headers=operator
    )
    assert res.status_code == 422, res.text
    assert "initial" in res.json()["detail"].lower()
    # Nothing was written - re-fetch confirms the flag is untouched.
    graph = _graph(client, operator, "synthetic_ticket")
    assert next(s for s in graph["statuses"] if s["id"] == a["id"])["isInitial"] is True


def test_is_initial_status_cannot_be_deleted_when_it_is_the_last_one(client):
    """Same AC-20 guard on delete (finding 6's second half) - even with zero
    records referencing it (so the reference-count guard alone would allow
    the delete), deleting the sole `isInitial` status must still 422."""
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    res = client.delete(f"/statuses/{a['id']}", headers=operator)
    assert res.status_code == 422, res.text
    assert "initial" in res.json()["detail"].lower()


def test_is_initial_status_can_be_deleted_once_another_becomes_initial(client):
    """The guard is about the SET, not the individual row - once a second
    status has taken over as the initial one, the (now non-initial) first
    status is free to be deleted."""
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    _create_status(client, operator, "synthetic_ticket", "B", {"isInitial": True})
    res = client.delete(f"/statuses/{a['id']}", headers=operator)
    assert res.status_code == 204, res.text


def test_auto_edges_excluded_from_user_surfaces(client, session_factory):
    """AC-03-04 - auto edges never appear in available_transitions / fireable_edge_ids;
    manual edges from the same status still do."""
    operator = _operator(client)
    pending = _create_status(client, operator, "synthetic_ticket", "Pending", {"isInitial": True})
    approved = _create_status(client, operator, "synthetic_ticket", "Approved")
    done = _create_status(client, operator, "synthetic_ticket", "Done")
    # Manual Pending→Approved, auto Pending→Done (when name == "auto").
    assert _create_edge(client, operator, "synthetic_ticket", pending["id"], approved["id"], "Approve").status_code == 201
    assert _auto_edge(client, operator, pending["id"], done["id"], "AutoDone", "auto").status_code == 201

    db = session_factory()
    actor = _demo_user(db)
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="auto", status_id=pending["id"])
    db.add(ticket)
    db.commit()

    avail = status_machine.available_transitions(db, "synthetic_ticket", ticket, actor)
    labels = {e.label for e in avail}
    assert "Approve" in labels and "AutoDone" not in labels

    ids = status_machine.fireable_edge_ids(db, "synthetic_ticket", [ticket], actor)
    # The probe ignores auto edges → no manual conditioned edge exists → None.
    assert ids is None
    db.close()


def test_reevaluate_fires_first_passing_auto_edge(client, session_factory):
    """AC-03-05/07 - reevaluate fires the first auto edge whose conditions pass;
    none passing = no move."""
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    b = _create_status(client, operator, "synthetic_ticket", "B")
    c = _create_status(client, operator, "synthetic_ticket", "C")
    assert _auto_edge(client, operator, a["id"], b["id"], "ToB", "wantB").status_code == 201
    assert _auto_edge(client, operator, a["id"], c["id"], "ToC", "wantC").status_code == 201

    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="wantC", status_id=a["id"])
    db.add(ticket)
    db.commit()
    hops = status_machine.reevaluate(db, "synthetic_ticket", ticket, tenant_id=DEFAULT_TENANT_ID)
    db.commit()
    assert hops == 1 and ticket.status_id == c["id"]

    # Nothing passes → no move.
    ticket2 = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="nope", status_id=a["id"])
    db.add(ticket2)
    db.commit()
    assert status_machine.reevaluate(db, "synthetic_ticket", ticket2, tenant_id=DEFAULT_TENANT_ID) == 0
    assert ticket2.status_id == a["id"]
    db.close()


def test_reevaluate_cascades_to_fixpoint(client, session_factory):
    """AC-03-06 - a single reevaluate cascades A→B→C when both auto edges pass."""
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "Issued", {"isInitial": True})
    b = _create_status(client, operator, "synthetic_ticket", "Partial")
    c = _create_status(client, operator, "synthetic_ticket", "Paid")
    assert _auto_edge(client, operator, a["id"], b["id"], "ToPartial", "go").status_code == 201
    assert _auto_edge(client, operator, b["id"], c["id"], "ToPaid", "go").status_code == 201

    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="go", status_id=a["id"])
    db.add(ticket)
    db.commit()
    hops = status_machine.reevaluate(db, "synthetic_ticket", ticket, tenant_id=DEFAULT_TENANT_ID)
    db.commit()
    assert hops == 2 and ticket.status_id == c["id"]
    db.close()


def test_reevaluate_first_wins_by_sort_order(client, session_factory):
    """AC-03-07 - when two auto edges from a status both pass, the lower
    sort_order fires."""
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    b = _create_status(client, operator, "synthetic_ticket", "B")
    c = _create_status(client, operator, "synthetic_ticket", "C")
    assert _auto_edge(client, operator, a["id"], c["id"], "ToC", "go", sort_order=5).status_code == 201
    assert _auto_edge(client, operator, a["id"], b["id"], "ToB", "go", sort_order=1).status_code == 201

    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="go", status_id=a["id"])
    db.add(ticket)
    db.commit()
    status_machine.reevaluate(db, "synthetic_ticket", ticket, tenant_id=DEFAULT_TENANT_ID)
    db.commit()
    assert ticket.status_id == b["id"]  # sort_order 1 beat sort_order 5
    db.close()


def test_reevaluate_terminates_on_cycle(client, session_factory):
    """AC-03-06 - a cycle of passing auto edges terminates (no-revisit guard)."""
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    b = _create_status(client, operator, "synthetic_ticket", "B")
    assert _auto_edge(client, operator, a["id"], b["id"], "ToB", "go").status_code == 201
    assert _auto_edge(client, operator, b["id"], a["id"], "ToA", "go").status_code == 201

    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="go", status_id=a["id"])
    db.add(ticket)
    db.commit()
    hops = status_machine.reevaluate(db, "synthetic_ticket", ticket, tenant_id=DEFAULT_TENANT_ID)
    db.commit()
    # A→B→(A already visited) → stops. Bounded, no infinite loop.
    assert hops == 2 and ticket.status_id in {a["id"], b["id"]}
    db.close()


def test_reevaluate_stable_state_not_pulled_back(client, session_factory):
    """AC-03-09 - a status with no outgoing auto edge is never re-derived."""
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    b = _create_status(client, operator, "synthetic_ticket", "B")
    assert _auto_edge(client, operator, a["id"], b["id"], "ToB", "go").status_code == 201

    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="go", status_id=b["id"])  # already at B
    db.add(ticket)
    db.commit()
    assert status_machine.reevaluate(db, "synthetic_ticket", ticket, tenant_id=DEFAULT_TENANT_ID) == 0
    assert ticket.status_id == b["id"]
    db.close()


def test_manual_override_edge_to_derived_state_coexists(client, session_factory):
    """AC-03-08 - a derived state may also have a role-free MANUAL edge; that
    manual edge IS offered while the auto one stays hidden."""
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    b = _create_status(client, operator, "synthetic_ticket", "B")
    paid = _create_status(client, operator, "synthetic_ticket", "Paid")
    # Auto B→Paid (derivation) + manual A→Paid (write-off override).
    assert _auto_edge(client, operator, b["id"], paid["id"], "AutoPaid", "go").status_code == 201
    assert _create_edge(client, operator, "synthetic_ticket", a["id"], paid["id"], "Write off").status_code == 201

    db = session_factory()
    actor = _demo_user(db)
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="go", status_id=a["id"])
    db.add(ticket)
    db.commit()
    labels = {e.label for e in status_machine.available_transitions(db, "synthetic_ticket", ticket, actor)}
    assert "Write off" in labels and "AutoPaid" not in labels
    db.close()


def test_fork_carries_trigger_mode(client, session_factory):
    """AC-03-18 - forking the platform set to a tenant keeps an auto edge auto."""
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    b = _create_status(client, operator, "synthetic_ticket", "B")
    assert _auto_edge(client, operator, a["id"], b["id"], "ToB", "go").status_code == 201

    admin = _admin(client)
    # First tenant edit forks the whole set (statuses + edges).
    client.patch(f"/statuses/{a['id']}", json={"label": "A2"}, headers=admin)
    graph = _graph(client, admin, "synthetic_ticket")
    assert graph["source"] == "tenant"
    auto = next(t for t in graph["transitions"] if t["label"] == "ToB")
    assert auto["triggerMode"] == "auto"
    assert auto["conditionsJson"] is not None


# ---- derived dependency wiring (sprint-4/03, slice 2) ----


@pytest.fixture(autouse=True)
def _reset_derived_triggers():
    """Derived triggers are module-global + dedup'd by (owner, trigger) - clear
    them around every test so each registers a fresh resolver in isolation. The
    subscriber (_on_event) stays registered but no-ops while _TRIGGERS is empty."""
    from app.status_engine import derived

    derived._TRIGGERS.clear()
    yield
    derived._TRIGGERS.clear()


def _register_ticket_aggregates():
    """record:ticket with name + aggregate facts over its lines. Registered at
    test runtime (test_rule_engine's import-time register would otherwise win)."""
    from app.rule_engine.aggregates import aggregate_fact

    register_fact_source(
        "record:synthetic_ticket",
        "Ticket record",
        [
            FactDef(key="record.name", label="Name", type="string", resolver=lambda o, db: o.name),
            aggregate_fact(
                "record.lineCount", "Line count",
                child_model=TicketLineRecord, fk_attr="ticket_id", op="count",
            ),
            aggregate_fact(
                "record.amountPaid", "Amount paid",
                child_model=TicketLineRecord, fk_attr="ticket_id", op="sum", column="amount",
            ),
        ],
    )


def _resolve_ticket_from_line(db, tenant_id, ev):
    line = (
        db.query(TicketLineRecord)
        .filter(TicketLineRecord.id == ev["record_id"], TicketLineRecord.tenant_id == tenant_id)
        .first()
    )
    if line is None:
        return []
    ticket = (
        db.query(TicketRecord)
        .filter(TicketRecord.id == line.ticket_id, TicketRecord.tenant_id == tenant_id)
        .first()
    )
    return [ticket] if ticket else []


def _wire_line_derivation():
    """Register the subscriber + the line→ticket DerivedTrigger (idempotent)."""
    from app.status_engine.derived import (
        DerivedTrigger,
        install_derived_status,
        register_derived_trigger,
    )

    install_derived_status()
    register_derived_trigger(
        DerivedTrigger(
            owner_entity="synthetic_ticket",
            trigger_entity="ticket_line",
            resolve_owners=_resolve_ticket_from_line,
        )
    )


def _emit_line(db, ticket, amount):
    from app.workflow_engine.entity_events import dispatch_pending, emit_entity_event

    line = TicketLineRecord(tenant_id=ticket.tenant_id, ticket_id=ticket.id, amount=amount)
    db.add(line)
    db.flush()
    emit_entity_event(db, "ticket_line", "created", line, tenant_id=ticket.tenant_id)
    db.commit()
    dispatch_pending(db)


def test_aggregate_fact_registered_and_authorable(client):
    """AC-03-13 - aggregate facts surface in the rule-fact catalog and pass
    save-time validation as an auto-edge condition."""
    _register_ticket_aggregates()
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    b = _create_status(client, operator, "synthetic_ticket", "B")
    res = _create_edge(
        client, operator, "synthetic_ticket", a["id"], b["id"], "Auto",
        triggerMode="auto",
        conditionsJson=_group(_cond("record.lineCount", "gte", 1)),
    )
    assert res.status_code == 201, res.text
    # Catalog exposes the aggregate facts.
    facts = client.get("/rule-facts", params={"sources": "record:synthetic_ticket"}, headers=operator).json()
    keys = {f["key"] for f in facts["data"]}
    assert {"record.lineCount", "record.amountPaid"} <= keys


def test_child_event_reevaluates_owner(client, session_factory):
    """AC-03-11 - creating a child fires the owner's auto edge via the bus."""
    _register_ticket_aggregates()
    _wire_line_derivation()
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "Open", {"isInitial": True})
    paid = _create_status(client, operator, "synthetic_ticket", "Paid")
    # Auto Open→Paid when amount paid >= 100.
    assert _create_edge(
        client, operator, "synthetic_ticket", a["id"], paid["id"], "AutoPaid",
        triggerMode="auto", conditionsJson=_group(_cond("record.amountPaid", "gte", 100)),
    ).status_code == 201

    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="T", status_id=a["id"])
    db.add(ticket)
    db.commit()
    ticket_id = ticket.id

    _emit_line(db, ticket, 100)  # child created → owner re-evaluated → Paid

    db2 = session_factory()
    assert db2.query(TicketRecord).filter(TicketRecord.id == ticket_id).first().status_id == paid["id"]
    db2.close()
    db.close()


def test_aggregate_facts_are_tenant_scoped(client, session_factory):
    """AC-03-13 - an aggregate counts only the owner's own children."""
    _register_ticket_aggregates()
    operator = _operator(client)
    db = session_factory()
    t1 = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="t1", status_id="x")
    t2 = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="t2", status_id="x")
    db.add_all([t1, t2])
    db.flush()
    db.add_all([
        TicketLineRecord(tenant_id=DEFAULT_TENANT_ID, ticket_id=t1.id, amount=40),
        TicketLineRecord(tenant_id=DEFAULT_TENANT_ID, ticket_id=t1.id, amount=60),
        TicketLineRecord(tenant_id=DEFAULT_TENANT_ID, ticket_id=t2.id, amount=999),
    ])
    db.commit()

    from app.rule_engine.registry import resolve_facts

    f1 = resolve_facts(db, {"record:synthetic_ticket": t1}, only_keys={"record.lineCount", "record.amountPaid"})
    assert f1["record.lineCount"] == 2 and f1["record.amountPaid"] == 100  # t2's line excluded
    db.close()


def test_self_trigger_reevaluates_on_update(client, session_factory):
    """AC-03-12 - an owner's OWN update re-evaluates its auto edges."""
    _register_ticket_aggregates()
    from app.status_engine.derived import (
        DerivedTrigger,
        install_derived_status,
        register_derived_trigger,
    )
    from app.workflow_engine.entity_events import dispatch_pending, emit_entity_event

    install_derived_status()
    register_derived_trigger(
        DerivedTrigger(
            owner_entity="synthetic_ticket",
            trigger_entity="synthetic_ticket",  # self-trigger
            resolve_owners=lambda db, tid, ev: (
                [db.query(TicketRecord).filter(
                    TicketRecord.id == ev["record_id"], TicketRecord.tenant_id == tid
                ).first()]
                if ev["record_id"]
                else []
            ),
        )
    )
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "Draft", {"isInitial": True})
    ready = _create_status(client, operator, "synthetic_ticket", "Ready")
    assert _create_edge(
        client, operator, "synthetic_ticket", a["id"], ready["id"], "AutoReady",
        triggerMode="auto", conditionsJson=_group(_cond("record.name", "eq", "go")),
    ).status_code == 201

    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="wait", status_id=a["id"])
    db.add(ticket)
    db.commit()
    tid = ticket.id
    # Flip name to "go" + emit a self update → re-eval fires AutoReady.
    ticket.name = "go"
    db.add(ticket)
    db.flush()
    emit_entity_event(db, "synthetic_ticket", "updated", ticket, tenant_id=DEFAULT_TENANT_ID,
                      changes={"name": {"from": "wait", "to": "go"}})
    db.commit()
    dispatch_pending(db)

    db2 = session_factory()
    assert db2.query(TicketRecord).filter(TicketRecord.id == tid).first().status_id == ready["id"]
    db2.close()
    db.close()


def test_generic_self_derivation_needs_no_explicit_trigger(client, session_factory):
    """sprint-4/03 - an unscoped status entity that declares a ``model`` re-evaluates
    its OWN auto edges on its own update with NO registered DerivedTrigger
    (closes the foolproof gap: authoring an auto edge is enough to make it fire)."""
    from app.status_engine.derived import install_derived_status
    from app.workflow_engine.entity_events import dispatch_pending, emit_entity_event

    install_derived_status()
    # A self-derivable entity backed by TicketRecord, with a model → the generic
    # self path loads + re-evaluates it; fact_attrs auto-registers record facts.
    register_status_entity(
        StatusEntity(
            entity_type="ticket_self",
            label="Ticket (self)",
            module="test",
            count_records=_ticket_count,
            migrate_records=_ticket_migrate,
            model=TicketRecord,
            fact_attrs=["name"],
        )
    )
    operator = _operator(client)
    a = _create_status(client, operator, "ticket_self", "Draft", {"isInitial": True})
    ready = _create_status(client, operator, "ticket_self", "Ready")
    assert _create_edge(
        client, operator, "ticket_self", a["id"], ready["id"], "AutoReady",
        triggerMode="auto", conditionsJson=_group(_cond("record.name", "eq", "go")),
    ).status_code == 201

    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="wait", status_id=a["id"])
    db.add(ticket)
    db.commit()
    tid = ticket.id
    # Flip name to "go" + emit a self update → generic re-eval fires AutoReady,
    # though NO DerivedTrigger was ever registered for "ticket_self".
    ticket.name = "go"
    db.add(ticket)
    db.flush()
    emit_entity_event(db, "ticket_self", "updated", ticket, tenant_id=DEFAULT_TENANT_ID,
                      changes={"name": {"from": "wait", "to": "go"}})
    db.commit()
    dispatch_pending(db)

    db2 = session_factory()
    assert db2.query(TicketRecord).filter(TicketRecord.id == tid).first().status_id == ready["id"]
    db2.close()
    db.close()


# ---- Slice 4: configurable aggregate whitelist (sprint-4/03) ----


def test_relation_expands_to_count_and_column_facts():
    """AC-03-28/29/30 - a relation generates count + (column×op) facts with
    stable dotted keys, derived labels, and correct types."""
    import pytest

    from app.rule_engine.aggregates import (
        AggColumn,
        AggregatableRelation,
        expand_relation_facts,
    )

    rel = AggregatableRelation(
        key="lines",
        label="Lines",
        child_entity_type="ticket_line",
        child_model=TicketLineRecord,
        fk_attr="ticket_id",
        count=True,
        columns=[AggColumn("amount", "Amount", "number", ops=["sum", "avg", "max"])],
    )
    by = {f.key: f for f in expand_relation_facts(rel)}
    assert set(by) == {
        "record.lines.count",
        "record.lines.sum.amount",
        "record.lines.avg.amount",
        "record.lines.max.amount",
    }
    assert by["record.lines.count"].label == "Lines · Count"
    assert by["record.lines.count"].type == "number"
    assert by["record.lines.sum.amount"].label == "Lines · Sum of Amount"
    assert by["record.lines.sum.amount"].type == "number"  # sum always numeric
    assert by["record.lines.max.amount"].type == "number"  # min/max inherit column type
    del pytest  # silence unused in this body


def test_relation_count_only_omits_columns():
    """A count-only relation (no columns) generates exactly one fact."""
    from app.rule_engine.aggregates import AggregatableRelation, expand_relation_facts

    rel = AggregatableRelation(
        key="lines", label="Lines", child_entity_type="ticket_line",
        child_model=TicketLineRecord, fk_attr="ticket_id", count=True,
    )
    facts = expand_relation_facts(rel)
    assert [f.key for f in facts] == ["record.lines.count"]


def test_relation_bad_op_and_missing_column_raise():
    """AC-03-31 - an op outside {sum,avg,min,max} or an absent column is a loud
    ValueError at registration."""
    import pytest

    from app.rule_engine.aggregates import (
        AggColumn,
        AggregatableRelation,
        expand_relation_facts,
    )

    with pytest.raises(ValueError):
        expand_relation_facts(AggregatableRelation(
            key="lines", label="Lines", child_entity_type="ticket_line",
            child_model=TicketLineRecord, fk_attr="ticket_id",
            columns=[AggColumn("amount", "Amount", "number", ops=["median"])],
        ))
    with pytest.raises(ValueError):
        expand_relation_facts(AggregatableRelation(
            key="lines", label="Lines", child_entity_type="ticket_line",
            child_model=TicketLineRecord, fk_attr="ticket_id",
            columns=[AggColumn("nope", "Nope", "number", ops=["sum"])],
        ))


def test_relation_registration_wires_facts_and_trigger(client):
    """AC-03-32/34 - registering an entity with a relation appends the generated
    facts to its rule source AND auto-registers the child→owner DerivedTrigger."""
    from app.rule_engine.aggregates import AggregatableRelation
    from app.rule_engine.registry import get_facts
    from app.status_engine.derived import install_derived_status, list_derived_triggers

    install_derived_status()
    register_status_entity(
        StatusEntity(
            entity_type="ticket_agg",
            label="Ticket Agg",
            module="test",
            count_records=_ticket_count,
            migrate_records=_ticket_migrate,
            model=TicketRecord,
            aggregatable_relations=[
                AggregatableRelation(
                    key="lines", label="Lines", child_entity_type="ticket_line",
                    child_model=TicketLineRecord, fk_attr="ticket_id", count=True,
                ),
            ],
        )
    )
    keys = {f[2].key for f in get_facts(["record:ticket_agg"])}
    assert "record.lines.count" in keys
    assert any(
        t.owner_entity == "ticket_agg" and t.trigger_entity == "ticket_line"
        for t in list_derived_triggers()
    )


def test_broken_derivation_never_breaks_the_child_write(client, session_factory):
    """AC-03-14 - a raising owner resolver is isolated: the child write stands,
    nothing propagates."""
    _register_ticket_aggregates()
    from app.status_engine.derived import (
        DerivedTrigger,
        install_derived_status,
        register_derived_trigger,
    )
    from app.workflow_engine.entity_events import dispatch_pending, emit_entity_event

    install_derived_status()

    def _boom(db, tid, ev):
        raise RuntimeError("derivation blew up")

    register_derived_trigger(
        DerivedTrigger(owner_entity="synthetic_ticket", trigger_entity="ticket_line", resolve_owners=_boom)
    )
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "S", {"isInitial": True})

    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="T", status_id=a["id"])
    db.add(ticket)
    db.commit()
    line = TicketLineRecord(tenant_id=DEFAULT_TENANT_ID, ticket_id=ticket.id, amount=10)
    db.add(line)
    db.flush()
    emit_entity_event(db, "ticket_line", "created", line, tenant_id=DEFAULT_TENANT_ID)
    db.commit()
    line_id = line.id
    # Drain must NOT raise despite the broken derivation.
    dispatch_pending(db)

    db2 = session_factory()
    assert db2.query(TicketLineRecord).filter(TicketLineRecord.id == line_id).first() is not None
    db2.close()
    db.close()


def test_fail_closed_on_missing_aggregate_fact(client, session_factory):
    """AC-03-15 - an auto edge whose condition can't resolve fires nothing."""
    # Register record:ticket WITHOUT the aggregate the edge will reference, so
    # the fact resolves None → condition fails closed.
    register_fact_source(
        "record:synthetic_ticket", "Ticket record",
        [FactDef(key="record.name", label="Name", type="string", resolver=lambda o, db: o.name)],
    )
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "A", {"isInitial": True})
    b = _create_status(client, operator, "synthetic_ticket", "B")
    # Author the edge while the aggregate IS registered (so save validates)…
    _register_ticket_aggregates()
    assert _create_edge(
        client, operator, "synthetic_ticket", a["id"], b["id"], "AutoB",
        triggerMode="auto", conditionsJson=_group(_cond("record.amountPaid", "gte", 100)),
    ).status_code == 201
    # …then drop it so resolution fails at re-eval time.
    register_fact_source(
        "record:synthetic_ticket", "Ticket record",
        [FactDef(key="record.name", label="Name", type="string", resolver=lambda o, db: o.name)],
    )
    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="T", status_id=a["id"])
    db.add(ticket)
    db.commit()
    assert status_machine.reevaluate(db, "synthetic_ticket", ticket, tenant_id=DEFAULT_TENANT_ID) == 0
    assert ticket.status_id == a["id"]
    db.close()
    _register_ticket_aggregates()  # restore for other tests


def test_derived_reeval_does_not_self_reenter(client, session_factory):
    """AC-03-16 - a derived transition's own status_changed event is skipped by
    the subscriber (no infinite re-entry); cascade still reaches the fixpoint."""
    _register_ticket_aggregates()
    _wire_line_derivation()
    operator = _operator(client)
    a = _create_status(client, operator, "synthetic_ticket", "Issued", {"isInitial": True})
    partial = _create_status(client, operator, "synthetic_ticket", "Partial")
    paid = _create_status(client, operator, "synthetic_ticket", "Paid")
    assert _create_edge(
        client, operator, "synthetic_ticket", a["id"], partial["id"], "ToPartial",
        triggerMode="auto", conditionsJson=_group(_cond("record.amountPaid", "gte", 1)),
    ).status_code == 201
    assert _create_edge(
        client, operator, "synthetic_ticket", partial["id"], paid["id"], "ToPaid",
        triggerMode="auto", conditionsJson=_group(_cond("record.amountPaid", "gte", 100)),
    ).status_code == 201

    db = session_factory()
    ticket = TicketRecord(tenant_id=DEFAULT_TENANT_ID, name="T", status_id=a["id"])
    db.add(ticket)
    db.commit()
    tid = ticket.id
    _emit_line(db, ticket, 100)  # one big payment cascades Issued→Partial→Paid

    db2 = session_factory()
    assert db2.query(TicketRecord).filter(TicketRecord.id == tid).first().status_id == paid["id"]
    db2.close()
    db.close()


def test_scoped_graph_derivation(client, session_factory):
    """AC-03-17 - reevaluate resolves the correct SCOPED owner graph."""
    from app.status_engine.registry import StatusEntity, register_status_entity
    from app.status_engine.scoped import ScopeSeedEdge, ScopeSeedStatus, materialize_scope

    # A scoped synthetic entity: each scope owns its own graph.
    register_status_entity(
        StatusEntity(
            entity_type="ticket_scoped",
            label="Scoped Ticket",
            module="test",
            count_records=lambda db, sid, tid: 0,
            migrate_records=lambda db, f, t, tid: 0,
            scoped=True,
            scope_attr="scope_id",
            scope_label="batch",
        )
    )
    register_fact_source(
        "record:ticket_scoped", "Scoped ticket",
        [FactDef(key="record.name", label="Name", type="string", resolver=lambda o, db: o.name)],
    )

    db = session_factory()
    scope_id = "batch-" + uuid.uuid4().hex[:6]
    by_key = materialize_scope(
        db, "ticket_scoped", DEFAULT_TENANT_ID, scope_id,
        [
            ScopeSeedStatus(key="draft", label="Draft", flags={"is_initial": True, "is_active": True}),
            ScopeSeedStatus(key="locked", label="Locked"),
        ],
        [
            ScopeSeedEdge(
                from_key="draft", to_key="locked", label="AutoLock",
                trigger_mode="auto", conditions=_group(_cond("record.name", "eq", "lock")),
            )
        ],
    )
    db.commit()

    rec = ScopedTicketRecord(
        tenant_id=DEFAULT_TENANT_ID, name="lock", status_id=by_key["draft"].id, scope_id=scope_id
    )
    db.add(rec)
    db.commit()
    hops = status_machine.reevaluate(db, "ticket_scoped", rec, tenant_id=DEFAULT_TENANT_ID)
    db.commit()
    assert hops == 1 and rec.status_id == by_key["locked"].id
    db.close()


def test_time_based_sweep_advances_overdue(client, session_factory):
    """AC-03-19 - the scheduler sweep advances a record whose time-conditioned
    auto edge now passes; a not-yet-due record stays put."""
    from app.workflow_engine.scheduler import reevaluate_time_based

    operator = _operator(client)
    open_s = _create_status(client, operator, "ticket_timed", "Open", {"isInitial": True})
    overdue = _create_status(client, operator, "ticket_timed", "Overdue")
    assert _create_edge(
        client, operator, "ticket_timed", open_s["id"], overdue["id"], "AutoOverdue",
        triggerMode="auto", conditionsJson=_group(_cond("record.isOverdue", "is_true", True)),
    ).status_code == 201

    db = session_factory()
    past = TimedTicketRecord(
        tenant_id=DEFAULT_TENANT_ID, name="late", status_id=open_s["id"],
        due_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    future = TimedTicketRecord(
        tenant_id=DEFAULT_TENANT_ID, name="early", status_id=open_s["id"],
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.add_all([past, future])
    db.commit()
    past_id, future_id = past.id, future.id
    db.close()

    advanced = reevaluate_time_based(session_factory())
    assert advanced == 1

    db2 = session_factory()
    assert db2.query(TimedTicketRecord).filter(TimedTicketRecord.id == past_id).first().status_id == overdue["id"]
    assert db2.query(TimedTicketRecord).filter(TimedTicketRecord.id == future_id).first().status_id == open_s["id"]
    db2.close()
