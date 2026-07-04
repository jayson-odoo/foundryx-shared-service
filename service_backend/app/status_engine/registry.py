"""Status-entity registry (sprint-2/01 D3) — which tables ride the engine.

Code-side, like the permissions CSV: an entity binds by registering here with
a flat ``entity_type`` and a ``status_id`` FK on its table. Core registers
``tenant``; modules append at install (``register_status_entity`` from their
``install()``), mirroring the permissions.csv pattern. Backs
``GET /status-entities`` and gives the engine record access (count/migrate)
without the engine knowing any domain table.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.lazy_registry import lazy_once


@dataclass(frozen=True)
class StatusEntity:
    """One engine-managed entity.

    ``platform_owned``: the status set belongs to the platform (e.g. tenant
    lifecycle — records span tenants); only operators configure it and there
    is no tenant fork. Tenant-owned entities two-tier instead (D7).

    ``count_records(db, status_id, tenant_id)`` / ``migrate_records(db,
    from_status_id, to_status_id, tenant_id)``: record access for
    block-delete-if-referenced + migrate-records (D8). ``tenant_id`` is None
    for platform-owned entities (cross-tenant by design).

    ``scoped`` (sprint-3/01 D4): one graph PER OWNING RECORD — statuses are
    materialized at scope creation with ``(tenant_id, scope_id)`` set,
    tenant-owned from birth (no two-tier fork). ``scope_attr`` names the
    record attribute holding the scope id (e.g. ``form_id``);
    ``scope_label`` is the owning record's display noun (e.g. "Form").
    Mutually exclusive with ``platform_owned``.
    """

    entity_type: str
    label: str
    module: str
    count_records: Callable[[Session, str, Optional[str]], int]
    migrate_records: Callable[[Session, str, str, Optional[str]], int]
    platform_owned: bool = False
    # Attribute holding the status FK on the record object.
    status_attr: str = "status_id"
    # Display attribute used in notification merge fields.
    record_label_attr: str = "name"
    # Semantic hints the UI surfaces when configuring (e.g. which flags matter).
    required_flags: List[str] = field(default_factory=list)
    # ---- scoped machines (sprint-3/01 D4) ----
    scoped: bool = False
    # Record attribute carrying the scope id (required when scoped).
    scope_attr: Optional[str] = None
    # Display noun for the scope owner ("Form") — error copy + UI.
    scope_label: str = ""
    # ``scope_exists(db, tenant_id, scope_id)`` — does the owning record
    # exist in the caller's tenant? (polymorphic guard class; required for
    # API-driven scoped writes).
    scope_exists: Optional[Callable[[Session, str, str], bool]] = None
    # ---- derived / computed status (sprint-4/03 G4) ----
    # True when this entity has TIME-conditioned auto edges (e.g. invoice
    # Overdue when due_date < now) — event-driven re-eval can't catch the clock
    # advancing, so the scheduler sweep re-evaluates its candidates each tick.
    has_time_auto_edges: bool = False
    # ``time_candidates(db) -> [records]`` — a COARSE, tenant-spanning query of
    # the records the sweep should re-evaluate (e.g. unpaid invoices with a past
    # due_date). reevaluate fail-closes anything that doesn't actually qualify.
    # Required when ``has_time_auto_edges`` is set.
    time_candidates: Optional[Callable[[Session], List]] = None
    # ---- generic derived-status wiring (sprint-4/03) ----
    # The SQLAlchemy model backing this entity. When set on an unscoped,
    # tenant-owned entity it enables (a) the GENERIC self derived-trigger
    # (``derived._on_event`` loads the record + re-evaluates its own auto edges
    # on its created/updated/status_changed) and (b) auto-registration of a
    # ``record:<type>`` rule fact source (so auto-edge conditions can reference
    # the record's own fields, not just ``actor.*``).
    model: Optional[Any] = None
    # Whitelisted columns exposed as ``record:<type>`` rule facts (D7 — never
    # auto-expose the whole schema). Empty = no record facts registered.
    fact_attrs: Sequence[str] = field(default_factory=tuple)
    # Aggregate facts (count/sum/… over child rows, sprint-4/03 G3) appended to
    # the same ``record:<type>`` source — each a code-declared, tenant-scoped
    # ``aggregate_fact`` (the relation/op is whitelisted; the threshold is
    # authored in the RuleBuilder like any other fact). The ESCAPE HATCH for
    # one-off / ``where=``-filtered aggregates; prefer ``aggregatable_relations``.
    aggregate_facts: Sequence[Any] = field(default_factory=tuple)
    # Declarative aggregate whitelist (sprint-4/03 Slice 4): each
    # ``AggregatableRelation`` auto-generates count + column×op facts on the
    # ``record:<type>`` source AND a child→owner ``DerivedTrigger``. Requires
    # ``model`` (the owner is loaded to re-derive it).
    aggregatable_relations: Sequence[Any] = field(default_factory=tuple)

    def load_record(
        self, db: Session, tenant_id: Optional[str], record_id: str
    ) -> Optional[Any]:
        """Load this entity's record by id, tenant-scoped (None when no model is
        declared or the row is absent). Used by the generic self derived-trigger."""
        if self.model is None or record_id is None:
            return None
        q = db.query(self.model).filter(self.model.id == record_id)
        if tenant_id is not None and hasattr(self.model, "tenant_id"):
            q = q.filter(self.model.tenant_id == tenant_id)
        return q.first()

    def __post_init__(self) -> None:
        if self.scoped and self.platform_owned:
            raise ValueError("A scoped entity cannot be platform_owned.")
        if self.scoped and not self.scope_attr:
            raise ValueError("A scoped entity must declare scope_attr.")
        if self.has_time_auto_edges and self.time_candidates is None:
            raise ValueError(
                "An entity with time auto-edges must declare time_candidates."
            )


_REGISTRY: Dict[str, StatusEntity] = {}


def register_status_entity(entity: StatusEntity) -> None:
    """Idempotent — modules re-register on every bootstrap.

    When the entity declares ``fact_attrs`` and/or ``aggregate_facts``, also
    register a ``record:<type>`` rule fact source so its auto-edge / transition
    conditions can reference the record's own fields + child aggregates
    (sprint-4/03). A pre-existing source wins (the rule engine owns the richer
    ``record:tenant``)."""
    _REGISTRY[entity.entity_type] = entity
    if entity.fact_attrs or entity.aggregate_facts or entity.aggregatable_relations:
        from app.rule_engine.registry import (
            get_facts,
            infer_facts,
            register_fact_source,
        )

        source = f"record:{entity.entity_type}"

        # Relations expand to facts + a child→owner DerivedTrigger. Triggers are
        # always (re)registered — register_derived_trigger is idempotent — so a
        # re-bootstrap that skips the source rebuild still wires the trigger.
        relation_facts: list = []
        if entity.aggregatable_relations:
            from app.rule_engine.aggregates import expand_relation
            from app.status_engine.derived import register_derived_trigger

            if entity.model is None:
                raise ValueError(
                    f"Status entity '{entity.entity_type}' declares "
                    "aggregatable_relations but no model."
                )
            for rel in entity.aggregatable_relations:
                facts_r, trigger = expand_relation(entity.entity_type, entity.model, rel)
                relation_facts.extend(facts_r)
                register_derived_trigger(trigger)

        if not get_facts([source]):  # don't clobber a richer hand-written source
            facts = (
                list(infer_facts(entity.model, list(entity.fact_attrs), prefix="record"))
                if entity.model is not None and entity.fact_attrs
                else []
            )
            facts.extend(entity.aggregate_facts)
            facts.extend(relation_facts)
            register_fact_source(source, f"{entity.label} record", facts)


def get_status_entity(entity_type: str) -> Optional[StatusEntity]:
    _ensure_core()
    return _REGISTRY.get(entity_type)


def list_status_entities() -> List[StatusEntity]:
    _ensure_core()
    return sorted(_REGISTRY.values(), key=lambda e: e.label)


# ---- core entities ("module zero") ----


def _tenant_count(db: Session, status_id: str, tenant_id: Optional[str]) -> int:
    from app.models.tenant import Tenant

    return db.query(Tenant).filter(Tenant.status_id == status_id).count()


def _tenant_migrate(
    db: Session, from_status_id: str, to_status_id: str, tenant_id: Optional[str]
) -> int:
    from app.models.tenant import Tenant

    count = (
        db.query(Tenant)
        .filter(Tenant.status_id == from_status_id)
        .update({Tenant.status_id: to_status_id}, synchronize_session=False)
    )
    db.flush()
    return count


def _form_submission_count(db: Session, status_id: str, tenant_id: Optional[str]) -> int:
    from app.models.form import FormSubmission

    q = db.query(FormSubmission).filter(FormSubmission.status_id == status_id)
    if tenant_id is not None:
        q = q.filter(FormSubmission.tenant_id == tenant_id)
    return q.count()


def _form_submission_migrate(
    db: Session, from_status_id: str, to_status_id: str, tenant_id: Optional[str]
) -> int:
    from app.models.form import FormSubmission

    q = db.query(FormSubmission).filter(FormSubmission.status_id == from_status_id)
    if tenant_id is not None:
        q = q.filter(FormSubmission.tenant_id == tenant_id)
    count = q.update({FormSubmission.status_id: to_status_id}, synchronize_session=False)
    db.flush()
    return count


def _form_exists(db: Session, tenant_id: str, scope_id: str) -> bool:
    from app.models.form import Form

    return (
        db.query(Form.id)
        .filter(Form.id == scope_id, Form.tenant_id == tenant_id)
        .first()
        is not None
    )


def _register_core() -> None:
    register_status_entity(
        StatusEntity(
            entity_type="tenant",
            label="Tenant",
            module="core",
            platform_owned=True,
            count_records=_tenant_count,
            migrate_records=_tenant_migrate,
            required_flags=["is_initial", "blocks_access", "is_archived"],
        )
    )
    # Form submissions (sprint-3/01 D4) — the first SCOPED entity: one graph
    # per form, materialized at form creation.
    register_status_entity(
        StatusEntity(
            entity_type="form_submission",
            label="Form Submission",
            module="core",
            count_records=_form_submission_count,
            migrate_records=_form_submission_migrate,
            scoped=True,
            scope_attr="form_id",
            scope_label="Form",
            scope_exists=_form_exists,
            record_label_attr="id",
            required_flags=["is_initial", "is_active"],
        )
    )


_ensure_core = lazy_once(_register_core)
