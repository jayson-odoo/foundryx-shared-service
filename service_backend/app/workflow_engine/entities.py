"""Triggerable / actionable entity registry (plan sprint-2/09 D6).

The v1 instrumented set — ``user``, ``role``, ``tenant``, ``connection``,
``template``, ``workflow`` — each a rule-engine fact source (so IF conditions +
entity triggers can read ``record.*``) plus the metadata the engine needs to
load a record (entity triggers / actions) and patch a whitelisted set of fields
(``entity.update``). Domain entities (Lead/Project/Task…) light up by
registering here as future sprints add their services' ``emit_entity_event``.

Code-side registry like StatusEntity / FactSource — modules append at install.
Registering an entity ALSO registers its ``record:<type>`` fact source (unless
one already exists, e.g. the richer ``record:tenant`` the rule engine owns).
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.lazy_registry import lazy_once


def attr_for(field_key: str) -> str:
    """camelCase field key (as the metadata advertises + the UI sends) → the raw
    snake_case model attribute. The whitelist + emitted change-diff keys live in
    this one canonical space so the security boundary isn't incidental."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", field_key).lower()


@dataclass(frozen=True)
class WorkflowEntity:
    entity_type: str
    label: str
    model: Any
    # Columns surfaced as ``record.*`` facts + entity-trigger record outputs.
    fact_attrs: Tuple[str, ...] = ()
    # Whitelist the ``entity.update`` action may write — NEVER the full schema
    # (email has its own ceremony, credentials are secret, slugs immutable).
    writable: frozenset = field(default_factory=frozenset)
    tenant_scoped: bool = True
    has_status: bool = False
    status_attr: str = "status_id"
    module: str = "core"


_ENTITIES: Dict[str, WorkflowEntity] = {}


def register_workflow_entity(entity: WorkflowEntity, *, register_facts: bool = True) -> None:
    """Idempotent. Also registers a ``record:<type>`` fact source from
    ``fact_attrs`` unless ``register_facts=False`` (the rule engine already owns
    a richer ``record:tenant``)."""
    _ENTITIES[entity.entity_type] = entity
    if register_facts and entity.fact_attrs:
        from app.rule_engine.registry import infer_facts, register_fact_source

        register_fact_source(
            f"record:{entity.entity_type}",
            f"{entity.label} record",
            infer_facts(entity.model, list(entity.fact_attrs), prefix="record"),
        )


def get_workflow_entity(entity_type: str) -> Optional[WorkflowEntity]:
    _ensure_core()
    return _ENTITIES.get(entity_type)


def list_workflow_entities() -> List[WorkflowEntity]:
    _ensure_core()
    return list(_ENTITIES.values())


def load_record(db: Session, entity: WorkflowEntity, tenant_id: str, record_id: str) -> Any:
    """Tenant-scoped record load (defense-in-depth — never resolve a stored id
    unscoped; the polymorphic target_id rule)."""
    query = db.query(entity.model).filter(entity.model.id == record_id)
    if entity.tenant_scoped:
        query = query.filter(entity.model.tenant_id == tenant_id)
    return query.first()


def record_facts(db: Session, entity_type: str, record: Any) -> Dict[str, Any]:
    """Resolve the entity's ``record.*`` facts for a record (run-context seed +
    IF facts). Returns ``{"record.email": ..., ...}`` (empty if unregistered)."""
    from app.rule_engine.registry import resolve_facts

    if get_workflow_entity(entity_type) is None:
        return {}
    return resolve_facts(db, {f"record:{entity_type}": record})


# ---- core entities ("module zero") ----


def _register_core() -> None:
    from app.models.connection import Connection
    from app.models.document import File
    from app.models.role import Role
    from app.models.template import Template
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.models.workflow import Workflow

    register_workflow_entity(
        WorkflowEntity(
            entity_type="user",
            label="User",
            model=User,
            fact_attrs=("email", "name", "status", "created_at"),
            writable=frozenset({"name", "status"}),
        )
    )
    register_workflow_entity(
        WorkflowEntity(
            entity_type="role",
            label="Role",
            model=Role,
            fact_attrs=("name", "description", "is_system"),
            writable=frozenset({"name", "description"}),
        )
    )
    register_workflow_entity(
        WorkflowEntity(
            entity_type="tenant",
            label="Tenant",
            model=Tenant,
            fact_attrs=("name", "slug", "is_platform", "created_at"),
            writable=frozenset({"name"}),
            tenant_scoped=False,  # the record IS a tenant
            has_status=True,
        ),
        # record:tenant is the rule engine's richer source (adds userCount).
        register_facts=False,
    )
    register_workflow_entity(
        WorkflowEntity(
            entity_type="connection",
            label="Connection",
            model=Connection,
            fact_attrs=("provider", "type", "status"),
            writable=frozenset(),  # credentials/config are sensitive — no patch
        )
    )
    register_workflow_entity(
        WorkflowEntity(
            entity_type="template",
            label="Email template",
            model=Template,
            fact_attrs=("name", "key", "context"),
            writable=frozenset({"name", "subject"}),
        )
    )
    register_workflow_entity(
        WorkflowEntity(
            entity_type="workflow",
            label="Workflow",
            model=Workflow,
            fact_attrs=("name", "is_active"),
            writable=frozenset({"name", "description"}),
        )
    )
    # The Drive's File (plan sprint-3/04 D13) — workflows can react to
    # upload/move/rename/delete via entity.created/updated/deleted. No
    # entity.update writes (rename/move have dedicated ops); facts only.
    register_workflow_entity(
        WorkflowEntity(
            entity_type="file",
            label="Document",
            model=File,
            fact_attrs=("name", "folder_id", "created_at"),
            writable=frozenset(),
        )
    )


_ensure_core = lazy_once(_register_core)
