"""Aggregate facts (sprint-4/03 G3) - count/sum/min/max/avg over an owner's
child rows, exposed as a normal ``FactDef`` so derived auto-edge conditions are
authored in the RuleBuilder like any other rule.

The resolver is OWNER- and TENANT-scoped (defense-in-depth, the polymorphic
target_id rule): it counts only children whose ``fk_attr == owner.id`` and,
when both carry one, ``tenant_id == owner.tenant_id``. A raising resolver yields
None upstream (``resolve_facts``) → the condition fails closed (no transition).
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.rule_engine.registry import FactDef, FactType

_AGG = {"sum": func.sum, "min": func.min, "max": func.max, "avg": func.avg}
# Ops allowed on a column (count is the relation-level flag, not a column op).
_COLUMN_OPS = set(_AGG)
_OP_LABEL = {"sum": "Sum", "avg": "Avg", "min": "Min", "max": "Max"}


def aggregate_fact(
    key: str,
    label: str,
    *,
    child_model: Any,
    fk_attr: str,
    op: str = "count",
    column: Optional[str] = None,
    where: Any = None,
    type: FactType = "number",
) -> FactDef:
    """A FactDef whose value aggregates an owner's children.

    ``op`` ∈ count|sum|min|max|avg. ``column`` is required for every op except
    ``count``. ``where`` is an optional extra SQLAlchemy filter clause. ``sum``
    over zero rows returns 0 (so "amount paid" reads 0, not None); min/max/avg
    over zero rows return None (fail closed - no derivation).
    """
    if op not in ({"count"} | set(_AGG)):
        raise ValueError(f"Unknown aggregate op '{op}'.")
    if op != "count" and column is None:
        raise ValueError(f"Aggregate op '{op}' requires a column.")

    def _resolver(owner: Any, db: Session) -> Any:
        q = db.query(child_model).filter(getattr(child_model, fk_attr) == owner.id)
        owner_tenant = getattr(owner, "tenant_id", None)
        if owner_tenant is not None and hasattr(child_model, "tenant_id"):
            q = q.filter(child_model.tenant_id == owner_tenant)
        if where is not None:
            q = q.filter(where)
        if op == "count":
            return q.count()
        value = q.with_entities(_AGG[op](getattr(child_model, column))).scalar()
        if op == "sum" and value is None:
            return 0
        return value

    return FactDef(key=key, label=label, type=type, resolver=_resolver)


# ---- declarative relation whitelist (sprint-4/03 Slice 4) ----


@dataclass(frozen=True)
class AggColumn:
    """A numeric/date column of the child that may be aggregated. ``ops`` is the
    per-column whitelist (⊆ {sum,avg,min,max}); ``type`` is the column's own
    type (drives min/max fact type + the RuleBuilder operator set)."""

    name: str
    label: str
    type: FactType = "number"
    ops: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class AggregatableRelation:
    """A whitelisted owner→child relation (sprint-4/03 Slice 4). Expands into one
    rule ``FactDef`` per (count + column×op) on the owner's ``record:<type>``
    source AND a cross-entity ``DerivedTrigger`` (child change → re-derive owner).

    ``child_entity_type`` is the event-match string the child emits (e.g.
    ``"project_participant"``). The child's write path MUST emit that entity
    event (``notify_entity_event``) or the re-derivation can't fire - that lives
    in the child service, not here (documented contract)."""

    key: str
    label: str
    child_entity_type: str
    child_model: Any
    fk_attr: str
    count: bool = True
    columns: Sequence[AggColumn] = field(default_factory=tuple)


def expand_relation_facts(relation: AggregatableRelation) -> List[FactDef]:
    """Generate the rule facts for a relation (count + each column×op). Validates
    the op whitelist + column existence at registration (loud ValueError)."""
    facts: List[FactDef] = []
    if relation.count:
        facts.append(
            aggregate_fact(
                f"record.{relation.key}.count",
                f"{relation.label} · Count",
                child_model=relation.child_model,
                fk_attr=relation.fk_attr,
                op="count",
                type="number",
            )
        )
    cols = relation.child_model.__table__.columns
    for col in relation.columns:
        if col.name not in cols:
            raise ValueError(
                f"{relation.child_model.__name__} has no column '{col.name}'."
            )
        for op in col.ops:
            if op not in _COLUMN_OPS:
                raise ValueError(
                    f"Unknown aggregate op '{op}' for column '{col.name}'."
                )
            # sum/avg are always numeric; min/max inherit the column's own type.
            fact_type: FactType = "number" if op in ("sum", "avg") else col.type
            facts.append(
                aggregate_fact(
                    f"record.{relation.key}.{op}.{col.name}",
                    f"{relation.label} · {_OP_LABEL[op]} of {col.label}",
                    child_model=relation.child_model,
                    fk_attr=relation.fk_attr,
                    op=op,
                    column=col.name,
                    type=fact_type,
                )
            )
    return facts


def expand_relation(owner_entity: str, owner_model: Any, relation: AggregatableRelation):
    """Return ``(facts, DerivedTrigger)`` for a relation - the facts on the
    owner's source + the child→owner re-derive trigger. Imported lazily by the
    status registry to avoid a cycle."""
    from app.status_engine.derived import DerivedTrigger

    facts = expand_relation_facts(relation)

    child_model = relation.child_model
    fk_attr = relation.fk_attr

    def _owners(db: Session, tenant_id: str, ev) -> list:
        child = (
            db.query(child_model)
            .filter(
                child_model.id == ev.get("record_id"),
                child_model.tenant_id == tenant_id,
            )
            .first()
        )
        if child is None:
            return []
        owner = (
            db.query(owner_model)
            .filter(
                owner_model.id == getattr(child, fk_attr),
                owner_model.tenant_id == tenant_id,
            )
            .first()
        )
        return [owner] if owner is not None else []

    trigger = DerivedTrigger(
        owner_entity=owner_entity,
        trigger_entity=relation.child_entity_type,
        resolve_owners=_owners,
    )
    return facts, trigger
