"""CRM module bootstrap (sprint-4/08) — App-Store contract + engine registrations.

Split out of EMS. ``install_tenant`` seeds the client/lead/quotation status
graphs. Registrations: status entities + terminology + importers + workflow
entities + lead/client resolve capabilities + a product reference-guard (a core
product can't be deleted while a quotation line references it).
"""
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv
from modules.crm.db import CRM_SCHEMA, CrmBase
from modules.crm.models import (
    CLIENT_ENTITY,
    LEAD_ENTITY,
    QUOTATION_ENTITY,
    SALES_ORDER_ENTITY,
    Client,
    Lead,
    Quotation,
    QuotationLine,
    SalesOrder,
    SalesOrderLine,
)

MODULE_NAME = "crm"
MODULE_CSV = Path(__file__).resolve().parent / "permissions" / "permissions.csv"


# ── status seeds (tenant-level, unscoped) ────────────────────────────────────

CLIENT_STATUS_SEED = [
    ("active", "Active", "green", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("inactive", "Inactive", "amber", 2, {}),
    ("archived", "Archived", "gray", 3, {"is_archived": True}),
]
CLIENT_EDGE_SEED = [
    ("active", "inactive", "Deactivate", 1),
    ("inactive", "active", "Reactivate", 2),
    ("active", "archived", "Archive", 3),
    ("inactive", "archived", "Archive", 4),
    ("archived", "active", "Restore", 5),
]
LEAD_STATUS_SEED = [
    ("new", "New", "blue", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("contacted", "Contacted", "indigo", 2, {"is_active": True}),
    ("qualified", "Qualified", "teal", 3, {"is_active": True}),
    ("won", "Won", "green", 4, {"is_terminal": True}),
    ("lost", "Lost", "red", 5, {"is_terminal": True}),
]
LEAD_EDGE_SEED = [
    ("new", "contacted", "Contact", 1),
    ("contacted", "qualified", "Qualify", 2),
    ("new", "qualified", "Qualify", 3),
    ("new", "won", "Win", 4),
    ("contacted", "won", "Win", 5),
    ("qualified", "won", "Win", 6),
    ("new", "lost", "Mark lost", 7),
    ("contacted", "lost", "Mark lost", 8),
    ("qualified", "lost", "Mark lost", 9),
]
QUOTATION_STATUS_SEED = [
    ("draft", "Draft", "gray", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("sent", "Sent", "blue", 2, {"is_active": True}),
    ("accepted", "Accepted", "green", 3, {"is_terminal": True}),
    ("rejected", "Rejected", "red", 4, {"is_terminal": True}),
    ("expired", "Expired", "amber", 5, {"is_terminal": True}),
]
QUOTATION_EDGE_SEED = [
    ("draft", "sent", "Send", 1),
    ("sent", "accepted", "Accept", 2),
    ("sent", "rejected", "Reject", 3),
    ("sent", "expired", "Expire", 4),
    ("draft", "expired", "Expire", 5),
]

# ── Sales Order (sprint-4/07, Cluster F slice 2) ─────────────────────────────
# Fulfilled is DERIVED: every line fully invoiced (``invoicedQty >= qty``). The
# ``record.unfulfilledLines`` aggregate (COUNT of lines where invoiced_qty < qty)
# and ``record.lineCount`` are registered on ``record:sales_order`` below. Fired
# by the SO-line→SO DerivedTrigger when a line's invoiced_qty changes (AC-07-23).
_FULFILLED_CONDITIONS = {
    "kind": "group",
    "combinator": "and",
    "rules": [
        {"kind": "condition", "fact": "record.lineCount", "operator": "gt",
         "valueKind": "literal", "value": 0},
        {"kind": "condition", "fact": "record.unfulfilledLines", "operator": "eq",
         "valueKind": "literal", "value": 0},
    ],
}
# SO statuses are ``is_system=True`` — the engine looks up keys (draft/confirmed/
# fulfilled/cancelled) as a load-bearing code contract (AC-07-53), so keys/flags/
# delete are locked from tenant rename; label/color/order stay editable.
SALES_ORDER_STATUS_SEED = [
    ("draft", "Draft", "gray", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("confirmed", "Confirmed", "blue", 2, {"is_active": True}),
    ("fulfilled", "Fulfilled", "green", 3, {"is_terminal": True}),
    ("cancelled", "Cancelled", "red", 4, {"is_terminal": True}),
]
# Edges are 4-tuples (manual) or 6-tuples (fk, tk, label, sort, mode, conditions).
SALES_ORDER_EDGE_SEED = [
    ("draft", "confirmed", "Confirm", 1),
    ("draft", "cancelled", "Cancel", 2),
    ("confirmed", "cancelled", "Cancel", 3),
    # Derived (AUTO) — fired by the engine when every line is fully invoiced.
    ("confirmed", "fulfilled", "Fulfilled", 10, "auto", _FULFILLED_CONDITIONS),
]


def create_schema_and_tables(engine: Engine) -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{CRM_SCHEMA}"'))
    CrmBase.metadata.create_all(bind=engine)


def install(engine: Engine, db: Session) -> None:
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))


def _seed_unscoped_graph(db, entity_type, tenant_id, statuses, edges) -> None:
    from app.models.status import Status
    from app.models.status_transition import StatusTransition

    existing = (
        db.query(Status.id)
        .filter(Status.entity_type == entity_type, Status.tenant_id == tenant_id, Status.scope_id.is_(None))
        .first()
    )
    if existing is not None:
        return
    by_key = {}
    for key, label, color, sort, flags in statuses:
        row = Status(
            id=str(uuid.uuid4()),
            entity_type=entity_type,
            key=key,
            category=key.upper(),
            label=label,
            color=color,
            sort_order=sort,
            is_system=False,
            tenant_id=tenant_id,
            **{f: bool(v) for f, v in flags.items()},
        )
        db.add(row)
        by_key[key] = row
    db.flush()
    for fk, tk, label, sort in edges:
        db.add(
            StatusTransition(
                id=str(uuid.uuid4()),
                entity_type=entity_type,
                tenant_id=tenant_id,
                from_status_id=by_key[fk].id,
                to_status_id=by_key[tk].id,
                label=label,
                sort_order=sort,
            )
        )
    db.flush()


def _add_edge(db, entity_type, tenant_id, from_row, to_row, edge):
    """Add ONE transition. ``edge`` is a 4-tuple (manual) or 6-tuple
    (fk, tk, label, sort, trigger_mode, conditions_json)."""
    from app.models.status_transition import StatusTransition

    db.add(
        StatusTransition(
            id=str(uuid.uuid4()),
            entity_type=entity_type,
            tenant_id=tenant_id,
            from_status_id=from_row.id,
            to_status_id=to_row.id,
            label=edge[2],
            sort_order=edge[3],
            trigger_mode=edge[4] if len(edge) > 4 else "manual",
            conditions_json=edge[5] if len(edge) > 5 else None,
        )
    )


def _seed_system_graph(db, entity_type, tenant_id, statuses, edges) -> None:
    """Seed a tenant-level (scope_id NULL) status graph with ``is_system=True``
    rows + auto-edge support — used by Sales Order (the engine looks up its keys
    as a code contract; AC-07-53)."""
    from app.models.status import Status

    existing = (
        db.query(Status.id)
        .filter(Status.entity_type == entity_type, Status.tenant_id == tenant_id, Status.scope_id.is_(None))
        .first()
    )
    if existing is not None:
        return
    by_key = {}
    for key, label, color, sort, flags in statuses:
        row = Status(
            id=str(uuid.uuid4()),
            entity_type=entity_type,
            key=key,
            category=key.upper(),
            label=label,
            color=color,
            sort_order=sort,
            is_system=True,
            tenant_id=tenant_id,
            **{f: bool(v) for f, v in flags.items()},
        )
        db.add(row)
        by_key[key] = row
    db.flush()
    for edge in edges:
        _add_edge(db, entity_type, tenant_id, by_key[edge[0]], by_key[edge[1]], edge)
    db.flush()


def install_tenant(db: Session, tenant_id: str) -> None:
    _seed_unscoped_graph(db, CLIENT_ENTITY, tenant_id, CLIENT_STATUS_SEED, CLIENT_EDGE_SEED)
    _seed_unscoped_graph(db, LEAD_ENTITY, tenant_id, LEAD_STATUS_SEED, LEAD_EDGE_SEED)
    _seed_unscoped_graph(db, QUOTATION_ENTITY, tenant_id, QUOTATION_STATUS_SEED, QUOTATION_EDGE_SEED)
    _seed_system_graph(db, SALES_ORDER_ENTITY, tenant_id, SALES_ORDER_STATUS_SEED, SALES_ORDER_EDGE_SEED)


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    # SO is new in Cluster F — seed the graph for tenants that had CRM installed
    # before this slice (no legacy SO rows to backfill; idempotent if present).
    _seed_system_graph(db, SALES_ORDER_ENTITY, tenant_id, SALES_ORDER_STATUS_SEED, SALES_ORDER_EDGE_SEED)


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    for table in reversed(CrmBase.metadata.sorted_tables):
        if "tenant_id" in table.c:
            db.execute(table.delete().where(table.c.tenant_id == tenant_id))
    from app.models.status import Status
    from app.models.status_transition import StatusTransition

    ids = [
        r[0]
        for r in db.query(Status.id)
        .filter(
            Status.tenant_id == tenant_id,
            Status.entity_type.in_([CLIENT_ENTITY, LEAD_ENTITY, QUOTATION_ENTITY, SALES_ORDER_ENTITY]),
        )
        .all()
    ]
    if ids:
        db.query(StatusTransition).filter(
            (StatusTransition.from_status_id.in_(ids)) | (StatusTransition.to_status_id.in_(ids))
        ).delete(synchronize_session=False)
        db.query(Status).filter(Status.id.in_(ids)).delete(synchronize_session=False)


def tenant_has_data(db: Session, tenant_id: str) -> bool:
    return db.query(Client.id).filter(Client.tenant_id == tenant_id).first() is not None


# ── engine registrations (boot) ──────────────────────────────────────────────


def register_engine_entities() -> None:
    _register_status_entities()
    _register_terminology()
    _register_importers()
    _register_workflow_entities()
    _register_reference_guards()
    _register_numbering()


def _register_numbering() -> None:
    """CRM numbering doc types (sprint-4/07, Cluster F) — quotation + sales_order.
    The running number is assigned at a state-change seam, not at create."""
    from app.numbering.registry import NumberSequenceDef, register_number_sequence

    register_number_sequence(
        NumberSequenceDef("quotation", "Quotation", module=MODULE_NAME,
                          default_prefix="QUO-", default_format="{prefix}{YYYY}-{NNNNN}",
                          default_reset="yearly")
    )
    register_number_sequence(
        NumberSequenceDef("sales_order", "Sales order", module=MODULE_NAME,
                          default_prefix="SO-", default_format="{prefix}{YYYY}-{NNNNN}",
                          default_reset="yearly")
    )


def _count_by_status(model):
    def counter(db, status_id, tenant_id):
        q = db.query(model).filter(model.status_id == status_id)
        if tenant_id is not None:
            q = q.filter(model.tenant_id == tenant_id)
        return q.count()

    return counter


def _migrate_by_status(model):
    def migrator(db, from_id, to_id, tenant_id):
        q = db.query(model).filter(model.status_id == from_id)
        if tenant_id is not None:
            q = q.filter(model.tenant_id == tenant_id)
        n = q.update({model.status_id: to_id}, synchronize_session=False)
        db.flush()
        return n

    return migrator


def _so_aggregate_facts():
    """Facts driving the Fulfilled auto-edge (AC-07-23): ``lineCount`` (guard
    against an empty SO) + ``unfulfilledLines`` (COUNT of lines still owing qty)."""
    from app.rule_engine.aggregates import aggregate_fact

    return [
        aggregate_fact(
            "record.lineCount", "Line count",
            child_model=SalesOrderLine, fk_attr="sales_order_id", op="count", type="number",
        ),
        aggregate_fact(
            "record.unfulfilledLines", "Unfulfilled lines",
            child_model=SalesOrderLine, fk_attr="sales_order_id", op="count",
            where=SalesOrderLine.invoiced_qty < SalesOrderLine.qty, type="number",
        ),
    ]


def _register_status_entities() -> None:
    from app.status_engine.derived import DerivedTrigger, register_derived_trigger
    from app.status_engine.registry import StatusEntity, register_status_entity

    register_status_entity(
        StatusEntity(
            entity_type=CLIENT_ENTITY,
            label="Client",
            module=MODULE_NAME,
            count_records=_count_by_status(Client),
            migrate_records=_migrate_by_status(Client),
            record_label_attr="name",
            required_flags=["is_initial"],
        )
    )
    register_status_entity(
        StatusEntity(
            entity_type=LEAD_ENTITY,
            label="Lead",
            module=MODULE_NAME,
            count_records=_count_by_status(Lead),
            migrate_records=_migrate_by_status(Lead),
            record_label_attr="title",
            required_flags=["is_initial", "is_terminal"],
        )
    )
    register_status_entity(
        StatusEntity(
            entity_type=QUOTATION_ENTITY,
            label="Quotation",
            module=MODULE_NAME,
            count_records=_count_by_status(Quotation),
            migrate_records=_migrate_by_status(Quotation),
            record_label_attr="id",
            required_flags=["is_initial", "is_terminal"],
        )
    )
    register_status_entity(
        StatusEntity(
            entity_type=SALES_ORDER_ENTITY,
            label="Sales order",
            module=MODULE_NAME,
            count_records=_count_by_status(SalesOrder),
            migrate_records=_migrate_by_status(SalesOrder),
            record_label_attr="id",
            required_flags=["is_initial", "is_terminal"],
            # Derived Fulfilled (AC-07-23): re-evaluate the SO's auto edge when a
            # line's invoiced_qty changes (cross-entity DerivedTrigger below). The
            # aggregate facts are the auto-edge condition vocabulary. fact_attrs +
            # aggregate_facts together own the ``record:sales_order`` source (the
            # workflow entity registers with register_facts=False so it can't
            # clobber the aggregates — last-writer-wins on register_fact_source).
            model=SalesOrder,
            fact_attrs=["currency", "doc_number", "status_id", "created_at"],
            aggregate_facts=_so_aggregate_facts(),
        )
    )

    # Cross-entity re-derive (AC-07-23): a line's invoiced_qty change (written by
    # the finance flow via crm.so_line_invoiced@1, which emits the line event)
    # re-evaluates the owning SO's auto edges.
    def _so_owners(db, tenant_id, ev):
        line = (
            db.query(SalesOrderLine)
            .filter(SalesOrderLine.id == ev.get("record_id"), SalesOrderLine.tenant_id == tenant_id)
            .first()
        )
        if line is None or not line.sales_order_id:
            return []
        so = (
            db.query(SalesOrder)
            .filter(SalesOrder.id == line.sales_order_id, SalesOrder.tenant_id == tenant_id)
            .first()
        )
        return [so] if so is not None else []

    register_derived_trigger(
        DerivedTrigger(
            owner_entity=SALES_ORDER_ENTITY,
            trigger_entity="sales_order_line",
            resolve_owners=_so_owners,
        )
    )


def _register_terminology() -> None:
    from app.terminology.registry import TermDef, register_term

    for key, sing, plur in [
        (CLIENT_ENTITY, "Client", "Clients"),
        (LEAD_ENTITY, "Lead", "Leads"),
        (QUOTATION_ENTITY, "Quotation", "Quotations"),
        (SALES_ORDER_ENTITY, "Sales order", "Sales orders"),
    ]:
        register_term(TermDef(key, sing, plur, module=MODULE_NAME, group="CRM"))


def _register_importers() -> None:
    from modules.crm.importers import register_crm_importers

    register_crm_importers()


def _register_workflow_entities() -> None:
    from app.workflow_engine.entities import WorkflowEntity, register_workflow_entity

    register_workflow_entity(
        WorkflowEntity(
            entity_type=CLIENT_ENTITY,
            label="Client",
            model=Client,
            fact_attrs=("name", "contact_email", "status_id", "created_at"),
            writable=frozenset({"name", "registrationNo", "contactPerson", "contactEmail", "contactPhone"}),
            has_status=True,
            module=MODULE_NAME,
        )
    )
    register_workflow_entity(
        WorkflowEntity(
            entity_type=LEAD_ENTITY,
            label="Lead",
            model=Lead,
            fact_attrs=("title", "source", "contact_email", "status_id", "created_at"),
            writable=frozenset({"title", "source", "contactName", "contactEmail", "contactPhone", "notes"}),
            has_status=True,
            module=MODULE_NAME,
        )
    )
    register_workflow_entity(
        WorkflowEntity(
            entity_type=QUOTATION_ENTITY,
            label="Quotation",
            model=Quotation,
            fact_attrs=("currency", "revision_number", "status_id", "created_at"),
            writable=frozenset({"currency", "notes"}),
            has_status=True,
            module=MODULE_NAME,
        )
    )
    register_workflow_entity(
        WorkflowEntity(
            entity_type=SALES_ORDER_ENTITY,
            label="Sales order",
            model=SalesOrder,
            fact_attrs=("currency", "doc_number", "status_id", "created_at"),
            writable=frozenset({"currency", "notes"}),
            has_status=True,
            module=MODULE_NAME,
        ),
        # The status entity owns the richer ``record:sales_order`` source (it adds
        # the lineCount/unfulfilledLines aggregates the Fulfilled auto-edge needs);
        # don't let the workflow registration clobber it.
        register_facts=False,
    )


def _register_reference_guards() -> None:
    """A core product can't be deleted while a quotation line references it."""
    from app.module_platform import register_reference_guard

    def _product_in_quotations(db, tenant_id, product_id) -> int:
        return (
            db.query(QuotationLine.id)
            .filter(QuotationLine.tenant_id == tenant_id, QuotationLine.product_id == product_id)
            .count()
        )

    register_reference_guard("product", "quotations", _product_in_quotations)


def register_capabilities() -> None:
    """lead.resolve@1 + client.resolve@1 — soft-ref seams for EMS to display a
    project's originating lead/client. crm.so_line_invoiced@1 — the finance flow
    increments an SO line's invoiced_qty through this (AC-07-22; finance is the
    writer, CRM owns the number — NO cross-schema query)."""
    from app.module_platform import CapabilityDef, register_capability

    def _client_resolve(db, tenant_id, payload):
        c = db.query(Client).filter(Client.id == payload["id"], Client.tenant_id == tenant_id).first()
        return None if c is None else {"id": c.id, "name": c.name}

    def _lead_resolve(db, tenant_id, payload):
        ld = db.query(Lead).filter(Lead.id == payload["id"], Lead.tenant_id == tenant_id).first()
        return None if ld is None else {"id": ld.id, "title": ld.title}

    def _so_line_invoiced(db, tenant_id, payload):
        from modules.crm.services import SalesOrderService

        return SalesOrderService(db).apply_line_invoiced(
            tenant_id, payload["soLineId"], payload["qty"]
        )

    register_capability(CapabilityDef("client.resolve", 1, MODULE_NAME, _client_resolve))
    register_capability(CapabilityDef("lead.resolve", 1, MODULE_NAME, _lead_resolve))
    register_capability(CapabilityDef("crm.so_line_invoiced", 1, MODULE_NAME, _so_line_invoiced))
