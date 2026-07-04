"""The shared transition executor (sprint-2/01 §backend) — ONE path for every
status change in the system.

``transition(...)``: resolve the edge (STRICT — no edge, no move, D4) → check
edge roles (≥1 shared role, empty = unrestricted, D5) → write the record's
``status_id`` → dispatch notifications (outbox, D6) → emit
``StatusTransitioned`` (Workflow engine plugs in later). Commits the unit —
record + outbox rows land atomically.
"""
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.events import EVENT_STATUS_TRANSITIONED, emit
from app.models.status import Status
from app.models.status_transition import StatusTransition
from app.models.user import User
from app.repositories.status_repository import StatusRepository
from app.repositories.status_transition_repository import StatusTransitionRepository
from app.rule_engine.evaluator import collect_fact_keys, evaluate, failed_conditions
from app.rule_engine.prose import condition_text
from app.rule_engine.registry import fact_map, resolve_facts
from app.services.notification_dispatch import dispatch_specs
from app.status_engine.registry import StatusEntity, get_status_entity


class StatusMachineError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class TransitionNotAllowed(StatusMachineError):
    """No edge from the record's current status to the target (strict graph)."""


class TransitionForbidden(StatusMachineError):
    """The actor holds none of the edge's roles."""


class TransitionConditionsNotMet(StatusMachineError):
    """The edge's rule-engine conditions evaluate False for this record/actor
    (sprint-2/02 D6) — distinct from the role block; lists what failed."""


class UnknownStatusEntity(StatusMachineError):
    pass


def _tier_and_scope(
    status_repo: StatusRepository,
    entity: StatusEntity,
    record: Any,
    actor: Optional[User],
    tenant_id: Optional[str],
):
    """Resolve (tier, record_scope_id) for a record (sprint-3/01 D4).

    Scoped entities skip two-tier resolution — their graphs are tenant-owned
    from birth: tier = the RECORD's tenant (defense-first; falls back to the
    caller), and every status touched must carry the record's ``scope_id``
    (a submission can never move onto another form's graph — same guard
    class as polymorphic target_id)."""
    if entity.scoped:
        tier = (
            getattr(record, "tenant_id", None)
            or tenant_id
            or (actor.tenant_id if actor else None)
        )
        return tier, getattr(record, entity.scope_attr)
    scope = None if entity.platform_owned else (tenant_id or (actor.tenant_id if actor else None))
    return status_repo.resolve_tier(entity.entity_type, scope), None


def _scope_guard(entity: StatusEntity, edge, record_scope_id: Optional[str]) -> bool:
    """An edge is valid for a scoped record only when BOTH endpoints belong
    to the record's scope. Unscoped entities pass through."""
    if not entity.scoped:
        return True
    return (
        edge.from_status.scope_id == record_scope_id
        and edge.to_status.scope_id == record_scope_id
    )


def _actor_may_fire(transition: StatusTransition, actor: Optional[User]) -> bool:
    if not transition.roles:
        return True  # unrestricted edge — the endpoint's own gate applies
    if actor is None:
        return False
    actor_role_ids = {role.id for role in actor.roles}
    return any(role.id in actor_role_ids for role in transition.roles)


def _edge_facts(
    db: Session,
    entity_type: str,
    record: Any,
    actor: Optional[User],
    only_keys: Optional[set] = None,
) -> dict:
    """The fact dict an edge's conditions evaluate against — the consumer's
    declared sources (D2): the acting user + this entity's record.

    NOTE: with ``actor=None`` every actor.* fact resolves None and fails
    closed (D5) — actor-conditioned edges are unfireable from actor-less
    (system/background) contexts BY DESIGN. Pass the acting user whenever
    one exists."""
    return resolve_facts(
        db, {"actor": actor, f"record:{entity_type}": record}, only_keys=only_keys
    )


def _conditions_pass(edge: StatusTransition, facts: dict) -> bool:
    return evaluate(edge.conditions_json, facts) if edge.conditions_json else True


def transition(
    db: Session,
    entity_type: str,
    record: Any,
    to_status_id: str,
    actor: Optional[User] = None,
    *,
    tenant_id: Optional[str] = None,
    commit: bool = True,
) -> StatusTransition:
    """Move ``record`` along a defined edge. Raises on any rule violation.

    ``tenant_id`` scopes tier resolution for tenant-owned entities (defaults to
    the actor's tenant); platform-owned entities always use the NULL tier.
    """
    entity: Optional[StatusEntity] = get_status_entity(entity_type)
    if entity is None:
        raise UnknownStatusEntity(f"Unknown status entity '{entity_type}'.")

    status_repo = StatusRepository(db)
    # ``scope`` = the caller's tenant (notification routing) — distinct from
    # ``tier`` = the tenant owning the visible status rows.
    scope = None if entity.platform_owned else (tenant_id or (actor.tenant_id if actor else None))
    tier, record_scope_id = _tier_and_scope(status_repo, entity, record, actor, tenant_id)

    # Scope guard BEFORE edge lookup (D4): the target must belong to the
    # record's own graph — clearer failure than a generic missing-edge.
    if entity.scoped:
        to_status = status_repo.get_by_id(to_status_id)
        if (
            to_status is None
            or to_status.entity_type != entity_type
            or to_status.tenant_id != tier
            or to_status.scope_id != record_scope_id
        ):
            raise TransitionNotAllowed(
                "Target status does not belong to this record's "
                f"{entity.scope_label or 'scope'}."
            )

    from_status_id = getattr(record, entity.status_attr)
    edge = StatusTransitionRepository(db).find_edge(from_status_id, to_status_id, tier)
    if edge is None or not _scope_guard(entity, edge, record_scope_id):
        from_status = status_repo.get_by_id(from_status_id)
        to_status = status_repo.get_by_id(to_status_id)
        raise TransitionNotAllowed(
            "No transition from "
            f"'{from_status.label if from_status else from_status_id}' to "
            f"'{to_status.label if to_status else to_status_id}'."
        )
    if not _actor_may_fire(edge, actor):
        raise TransitionForbidden(
            f"You are not allowed to perform '{edge.label}'."
        )
    # Rule-engine conditions re-check at fire (D6 — the listing already hides
    # failing edges, but the server boundary wins races/API bypass).
    if edge.conditions_json:
        facts = _edge_facts(
            db, entity_type, record, actor, only_keys=collect_fact_keys(edge.conditions_json)
        )
        if not _conditions_pass(edge, facts):
            labels = fact_map(["actor", f"record:{entity_type}"])
            details = "; ".join(
                condition_text(c, labels)
                for c in failed_conditions(edge.conditions_json, facts)
            )
            raise TransitionConditionsNotMet(
                f"'{edge.label}' is not available: conditions not met — {details}."
            )

    setattr(record, entity.status_attr, to_status_id)
    db.add(record)
    db.flush()

    # Notifications ride the same transaction as the status write.
    record_label = str(getattr(record, entity.record_label_attr, "") or "")
    context = {
        "entityLabel": entity.label,
        "recordLabel": record_label,
        "fromStatus": edge.from_status.label,
        "toStatus": edge.to_status.label,
        "transitionLabel": edge.label,
        "actorName": actor.name if actor else "",
    }
    notify_tenant_id = scope or getattr(record, "tenant_id", None) or _record_tenant(record)
    dispatch_specs(
        db,
        edge.notification_specs,
        record=record,
        actor=actor,
        tenant_id=notify_tenant_id,
        context=context,
    )

    # Workflow domain event (slice 09): buffered now, drained after commit →
    # matches `entity.status_changed` triggers. Loop-guarded by the run origin.
    from app.workflow_engine.entity_events import emit_entity_event

    emit_entity_event(
        db,
        entity_type,
        "status_changed",
        record,
        tenant_id=notify_tenant_id,
        actor=actor,
        changes={"status": {"from": from_status_id, "to": to_status_id}},
        extra={"from_status_id": from_status_id, "to_status_id": to_status_id},
    )

    # Capture the event payload BEFORE commit — expire_on_commit would make
    # post-commit attribute reads lazy-load (and explode for any subscriber
    # holding the payload past the session's life). Code-review fix.
    payload = {
        "entity_type": entity_type,
        "record_id": getattr(record, "id", None),
        "transition_id": edge.id,
        "transition_label": edge.label,
        "from_status_id": from_status_id,
        "to_status_id": to_status_id,
        "actor_id": actor.id if actor else None,
    }

    if commit:
        db.commit()

    emit(EVENT_STATUS_TRANSITIONED, payload)
    return edge


def _record_tenant(record: Any) -> str:
    """Tenant for notification routing when the record has no tenant_id —
    e.g. the tenant entity itself (the record IS a tenant)."""
    from app.models.tenant import PLATFORM_TENANT_ID, Tenant

    if isinstance(record, Tenant):
        return record.id
    return PLATFORM_TENANT_ID


def available_transitions(
    db: Session,
    entity_type: str,
    record: Any,
    actor: Optional[User] = None,
    *,
    tenant_id: Optional[str] = None,
) -> list:
    """Outgoing edges from the record's current status the actor may fire —
    drives the action buttons (edge label = button text)."""
    entity = get_status_entity(entity_type)
    if entity is None:
        raise UnknownStatusEntity(f"Unknown status entity '{entity_type}'.")
    status_repo = StatusRepository(db)
    tier, record_scope_id = _tier_and_scope(status_repo, entity, record, actor, tenant_id)
    edges = StatusTransitionRepository(db).outgoing(getattr(record, entity.status_attr), tier)
    edges = [e for e in edges if _scope_guard(entity, e, record_scope_id)]
    return _filter_fireable(db, entity_type, record, actor, edges)


def _filter_fireable(
    db: Session,
    entity_type: str,
    record: Any,
    actor: Optional[User],
    edges: list,
) -> list:
    """Role check + rule-engine condition check over a candidate edge list —
    facts resolved once per record, and only the keys the trees read."""
    entity = get_status_entity(entity_type)
    # Scoped entities REPURPOSE is_active ("respondent may still edit" —
    # sprint-3/01 D4): an inactive status (Submitted) is a normal transition
    # target there, so the hide-inactive-targets rule applies only unscoped.
    hide_inactive = not (entity is not None and entity.scoped)
    edges = [
        e
        for e in edges
        # Derived status (sprint-4/03 G6): auto edges are system-fired — never
        # offered as user actions on any list/detail surface.
        if e.trigger_mode != "auto"
        and _actor_may_fire(e, actor)
        and (e.to_status.is_active or not hide_inactive)
    ]
    conditioned = [e for e in edges if e.conditions_json]
    if conditioned:
        needed: set = set()
        for edge in conditioned:
            needed |= collect_fact_keys(edge.conditions_json)
        facts = _edge_facts(db, entity_type, record, actor, only_keys=needed)
        edges = [e for e in edges if _conditions_pass(e, facts)]
    return edges


def fireable_edge_ids(
    db: Session,
    entity_type: str,
    records: list,
    actor: Optional[User] = None,
    *,
    tenant_id: Optional[str] = None,
) -> Optional[dict]:
    """Per-record fireable edge ids for LIST surfaces (sprint-2/02 D6, made
    generic in code review) — rule-blocked actions hide per record, and
    conditions are record-specific so clients can't derive this from the
    shared graph. Returns None while NO edge of the entity's resolved tier
    carries conditions (the common case costs one EXISTS probe). Batched:
    ONE edge query for the whole record set, facts resolved per record
    limited to the keys the trees actually read."""
    entity = get_status_entity(entity_type)
    if entity is None:
        raise UnknownStatusEntity(f"Unknown status entity '{entity_type}'.")
    status_repo = StatusRepository(db)
    if entity.scoped:
        # Scoped machines: tenant-owned from birth; records on a list surface
        # are one tenant's but may span scopes — per-record scope filtering
        # happens below against each record's own scope_id.
        tier = tenant_id or (actor.tenant_id if actor else None)
    else:
        scope = None if entity.platform_owned else (tenant_id or (actor.tenant_id if actor else None))
        tier = status_repo.resolve_tier(entity_type, scope)

    tier_filter = (
        StatusTransition.tenant_id.is_(None)
        if tier is None
        else StatusTransition.tenant_id == tier
    )
    has_conditioned = (
        db.query(StatusTransition.id)
        .filter(
            StatusTransition.entity_type == entity_type,
            tier_filter,
            StatusTransition.conditions_json.isnot(None),
            # Auto edges are never offered, so they don't make a list surface
            # "conditioned" (sprint-4/03) — only manual conditioned edges do.
            StatusTransition.trigger_mode != "auto",
        )
        .first()
        is not None
    )
    if not has_conditioned:
        return None

    # ONE query for the tier's whole edge set, grouped by source status.
    edges_by_from: dict = {}
    for edge in (
        db.query(StatusTransition)
        .filter(StatusTransition.entity_type == entity_type, tier_filter)
        .order_by(StatusTransition.sort_order)
        .all()
    ):
        edges_by_from.setdefault(edge.from_status_id, []).append(edge)

    result: dict = {}
    for record in records:
        candidates = edges_by_from.get(getattr(record, entity.status_attr), [])
        if entity.scoped:
            record_scope_id = getattr(record, entity.scope_attr)
            candidates = [e for e in candidates if _scope_guard(entity, e, record_scope_id)]
        fireable = _filter_fireable(db, entity_type, record, actor, list(candidates))
        result[getattr(record, "id", None)] = [e.id for e in fireable]
    return result


# ── derived / computed status (sprint-4/03) ─────────────────────────────────

# Backstop against a pathological auto-edge config that never reaches a fixpoint
# (the no-revisit guard already prevents real oscillation; this caps absurd
# fan-through). A real derivation chain is a handful of hops.
REEVAL_HOP_CAP = 25


def reevaluate(
    db: Session,
    entity_type: str,
    record: Any,
    *,
    tenant_id: Optional[str] = None,
    origin: Optional[dict] = None,
) -> int:
    """Fire any AUTO edges whose conditions now pass — the derived-status driver
    (sprint-4/03 G5). From the record's current status, evaluate outgoing auto
    edges in ``sort_order`` and fire the FIRST whose ``conditions_json`` is true
    via ``transition(actor=None, commit=False)``; re-evaluate from the new
    status; repeat to a fixpoint. Hop-capped + no-revisit (terminates, never
    oscillates). Each hop is a real transition (notifications + ``status_changed``
    emitted), so one big change cascades Issued→Partially→Paid in one settle.

    Runs with ``actor=None``: actor.* facts fail closed BY DESIGN (a derivation
    is system-fired). Caller owns the commit (``commit=False`` throughout); the
    bus subscriber (slice 2) runs this in its own isolated commit.

    Returns the number of hops fired. Tags emitted events with ``origin`` (or the
    DERIVED marker) so the derived subscriber doesn't re-enter on its own writes.
    """
    from app.workflow_engine.entity_events import DERIVED_ORIGIN, set_origin

    entity: Optional[StatusEntity] = get_status_entity(entity_type)
    if entity is None:
        raise UnknownStatusEntity(f"Unknown status entity '{entity_type}'.")

    status_repo = StatusRepository(db)
    tier, record_scope_id = _tier_and_scope(status_repo, entity, record, None, tenant_id)
    repo = StatusTransitionRepository(db)

    prev_origin = set_origin(db, origin or DERIVED_ORIGIN)
    hops = 0
    visited: set = set()
    try:
        while hops < REEVAL_HOP_CAP:
            current = getattr(record, entity.status_attr)
            if current in visited:
                break  # no-revisit — a cycle of passing auto-edges can't loop
            visited.add(current)

            edges = [
                e
                for e in repo.outgoing(current, tier)
                # Fail-safe: an auto edge MUST carry conditions (save-validated);
                # one without (e.g. planted by a direct DB write) never fires —
                # an unconditioned auto edge would otherwise fire always.
                if e.trigger_mode == "auto"
                and e.conditions_json
                and _scope_guard(entity, e, record_scope_id)
            ]
            edges.sort(key=lambda e: e.sort_order)
            if not edges:
                break

            needed: set = set()
            for e in edges:
                needed |= collect_fact_keys(e.conditions_json)
            facts = _edge_facts(db, entity_type, record, None, only_keys=needed)

            fired = next((e for e in edges if _conditions_pass(e, facts)), None)
            if fired is None:
                break
            transition(
                db,
                entity_type,
                record,
                fired.to_status_id,
                actor=None,
                tenant_id=tenant_id,
                commit=False,
            )
            hops += 1
    finally:
        set_origin(db, prev_origin)
    return hops
