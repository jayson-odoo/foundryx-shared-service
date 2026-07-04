"""Finance module bootstrap (sprint-4/05, Cluster D / R3-1) — App-Store contract
+ engine registrations + the cross-module invoice capabilities.

``install_tenant`` seeds the invoice status graph (Draft→Issued→Cancelled; Cluster
F extends with Paid/Overdue/Refunded). Capabilities: ``finance.create_invoice@1``
(EMS-registration + CRM-quotation both mint invoices through it) and
``invoice.resolve@1`` (cross-module header read).
"""
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv
from modules.finance.db import FINANCE_SCHEMA, FinanceBase
from modules.finance.models import (
    INVOICE_ENTITY,
    PAYMENT_ENTITY,
    REFUND_ENTITY,
    SETTLEMENT_ENTITY,
    Invoice,
    InvoiceLine,
    Payment,
    Refund,
    RefundLine,
    Settlement,
    SettlementLine,
)

MODULE_NAME = "finance"
MODULE_CSV = Path(__file__).resolve().parent / "permissions" / "permissions.csv"


# ── derived auto-edge conditions (Cluster F, AC-07-11/13) ────────────────────
# Σ succeeded payments vs invoice total drives Partially Paid / Paid. The
# ``record.paidTotal`` aggregate fact (SUM of Succeeded payment amounts) and
# ``record.total`` field fact are registered on ``record:invoice`` below.
_PARTIALLY_PAID_CONDITIONS = {
    "kind": "group",
    "combinator": "and",
    "rules": [
        {"kind": "condition", "fact": "record.paidTotal", "operator": "gt",
         "valueKind": "literal", "value": 0},
        {"kind": "condition", "fact": "record.paidTotal", "operator": "lt",
         "valueKind": "fact", "value": "record.total"},
    ],
}
_PAID_CONDITIONS = {
    "kind": "group",
    "combinator": "and",
    "rules": [
        {"kind": "condition", "fact": "record.paidTotal", "operator": "gte",
         "valueKind": "fact", "value": "record.total"},
        {"kind": "condition", "fact": "record.total", "operator": "gt",
         "valueKind": "literal", "value": 0},
    ],
}
# Overdue is TIME-derived (AC-07-13): due date is in the past (daysSince > 0) and
# not yet fully paid. The day-count fact is auto-generated from ``due_date``.
_OVERDUE_CONDITIONS = {
    "kind": "group",
    "combinator": "and",
    "rules": [
        {"kind": "condition", "fact": "record.dueDate.daysSince", "operator": "gt",
         "valueKind": "literal", "value": 0},
        {"kind": "condition", "fact": "record.paidTotal", "operator": "lt",
         "valueKind": "fact", "value": "record.total"},
    ],
}
# Refund derivation (Cluster F slice 4, AC-07-43): Σ confirmed refunds vs Σ paid.
# 0 < Σrefunds < Σpaid → Partially Refunded; Σrefunds ≥ Σpaid → Refunded. The
# ``record.refundedTotal`` aggregate fact (SUM of confirmed refund amounts) is
# registered on record:invoice below alongside paidTotal.
_PARTIALLY_REFUNDED_CONDITIONS = {
    "kind": "group",
    "combinator": "and",
    "rules": [
        {"kind": "condition", "fact": "record.refundedTotal", "operator": "gt",
         "valueKind": "literal", "value": 0},
        {"kind": "condition", "fact": "record.refundedTotal", "operator": "lt",
         "valueKind": "fact", "value": "record.paidTotal"},
    ],
}
_REFUNDED_CONDITIONS = {
    "kind": "group",
    "combinator": "and",
    "rules": [
        {"kind": "condition", "fact": "record.refundedTotal", "operator": "gte",
         "valueKind": "fact", "value": "record.paidTotal"},
        {"kind": "condition", "fact": "record.refundedTotal", "operator": "gt",
         "valueKind": "literal", "value": 0},
    ],
}


# ── status seed (tenant-level, unscoped) — Cluster F extends this ────────────
# Edges are 4-tuples (manual) or 6-tuples (fk, tk, label, sort, mode, conditions).

INVOICE_STATUS_SEED = [
    ("draft", "Draft", "gray", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("issued", "Issued", "blue", 2, {"is_active": True}),
    ("partially_paid", "Partially Paid", "amber", 3, {"is_active": True}),
    ("paid", "Paid", "green", 4, {"is_active": True}),
    ("overdue", "Overdue", "amber", 5, {"is_active": True}),
    ("partially_refunded", "Partially Refunded", "amber", 6, {"is_active": True}),
    ("refunded", "Refunded", "red", 7, {"is_terminal": True}),
    ("void", "Void", "red", 8, {"is_terminal": True}),
    ("cancelled", "Cancelled", "red", 9, {"is_terminal": True}),
]
INVOICE_EDGE_SEED = [
    ("draft", "issued", "Issue", 1),
    ("draft", "cancelled", "Cancel", 2),
    ("issued", "void", "Void", 3),
    # Derived (AUTO) edges — fired by the engine when conditions pass, never user
    # actions. Partially Paid / Paid from Σ payments; Overdue from the clock.
    ("issued", "partially_paid", "Partially paid", 10, "auto", _PARTIALLY_PAID_CONDITIONS),
    ("issued", "paid", "Paid", 11, "auto", _PAID_CONDITIONS),
    ("issued", "overdue", "Overdue", 12, "auto", _OVERDUE_CONDITIONS),
    ("partially_paid", "paid", "Paid", 13, "auto", _PAID_CONDITIONS),
    ("partially_paid", "overdue", "Overdue", 14, "auto", _OVERDUE_CONDITIONS),
    # Overdue is a transient flag — once a payment lands it derives back.
    ("overdue", "partially_paid", "Partially paid", 15, "auto", _PARTIALLY_PAID_CONDITIONS),
    ("overdue", "paid", "Paid", 16, "auto", _PAID_CONDITIONS),
    # Refund-derived (Cluster F slice 4, AC-07-43) — fired when a refund confirms
    # (Σrefunds drives the move). From any paid-ish state.
    ("paid", "partially_refunded", "Partially refunded", 20, "auto", _PARTIALLY_REFUNDED_CONDITIONS),
    ("paid", "refunded", "Refunded", 21, "auto", _REFUNDED_CONDITIONS),
    ("partially_paid", "partially_refunded", "Partially refunded", 22, "auto", _PARTIALLY_REFUNDED_CONDITIONS),
    ("partially_paid", "refunded", "Refunded", 23, "auto", _REFUNDED_CONDITIONS),
    ("partially_refunded", "refunded", "Refunded", 24, "auto", _REFUNDED_CONDITIONS),
]

# ── payment status graph (tenant-level, unscoped) ────────────────────────────
# Cluster F slice 3 (AC-07-30/33/36/53) extends pending/succeeded/failed with
# Expired (abandoned-checkout reaper), Disputed (chargeback) and Refunded.
PAYMENT_STATUS_SEED = [
    ("pending", "Pending", "gray", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("succeeded", "Succeeded", "green", 2, {"is_active": True}),
    ("failed", "Failed", "red", 3, {"is_terminal": True}),
    ("expired", "Expired", "gray", 4, {"is_terminal": True}),
    ("disputed", "Disputed", "amber", 5, {"is_active": True}),
    ("refunded", "Refunded", "amber", 6, {"is_terminal": True}),
]
PAYMENT_EDGE_SEED = [
    ("pending", "succeeded", "Succeed", 1),
    ("pending", "failed", "Fail", 2),
    ("pending", "expired", "Expire", 3),
    ("succeeded", "disputed", "Dispute", 4),
    ("succeeded", "refunded", "Refund", 5),
]

# ── refund status graph (Cluster F slice 4, AC-07-37/38) ─────────────────────
# A gateway refund is Pending until the webhook confirms; a manual (CASH/BANK)
# refund confirms immediately. Failed = the gateway rejected the refund.
REFUND_STATUS_SEED = [
    ("pending", "Pending", "amber", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("confirmed", "Confirmed", "green", 2, {"is_terminal": True}),
    ("failed", "Failed", "red", 3, {"is_terminal": True}),
]
REFUND_EDGE_SEED = [
    ("pending", "confirmed", "Confirm", 1),
    ("pending", "failed", "Fail", 2),
]

# ── settlement status graph (Cluster F slice 4, AC-07-47) ────────────────────
SETTLEMENT_STATUS_SEED = [
    ("draft", "Draft", "gray", 1, {"is_initial": True, "is_default": True, "is_active": True}),
    ("approved", "Approved", "blue", 2, {"is_active": True}),
    ("remitted", "Remitted", "green", 3, {"is_terminal": True}),
]
SETTLEMENT_EDGE_SEED = [
    ("draft", "approved", "Approve", 1),
    ("approved", "remitted", "Mark remitted", 2),
]


def create_schema_and_tables(engine: Engine) -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{FINANCE_SCHEMA}"'))
    FinanceBase.metadata.create_all(bind=engine)


def install(engine: Engine, db: Session) -> None:
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))
    _seed_invoice_template(db)


def _seed_invoice_template(db: Session) -> None:
    """Seed the platform-tier ``finance.invoice`` document template (AC-07-17),
    insert-if-missing by key (operator edits survive reseed)."""
    from app.models.template import TEMPLATE_TYPE_DOCUMENT, Template
    from modules.finance.invoice_template import INVOICE_TEMPLATE_CONTEXT, invoice_doc

    exists = (
        db.query(Template.id)
        .filter(Template.tenant_id.is_(None), Template.key == "finance.invoice")
        .first()
    )
    if exists is not None:
        return
    db.add(
        Template(
            tenant_id=None,
            type=TEMPLATE_TYPE_DOCUMENT,
            key="finance.invoice",
            name="Invoice",
            context=INVOICE_TEMPLATE_CONTEXT,
            subject="Invoice {{invoiceNumber}}",
            doc_json=invoice_doc(),
            is_system=True,
        )
    )
    db.flush()


def _add_edge(db, entity_type, tenant_id, from_row, to_row, edge):
    """Add ONE transition. ``edge`` is a 4-tuple (manual) or 6-tuple
    (fk, tk, label, sort, trigger_mode, conditions_json)."""
    from app.models.status_transition import StatusTransition

    label, sort = edge[2], edge[3]
    trigger_mode = edge[4] if len(edge) > 4 else "manual"
    conditions = edge[5] if len(edge) > 5 else None
    db.add(
        StatusTransition(
            id=str(uuid.uuid4()),
            entity_type=entity_type,
            tenant_id=tenant_id,
            from_status_id=from_row.id,
            to_status_id=to_row.id,
            label=label,
            sort_order=sort,
            trigger_mode=trigger_mode,
            conditions_json=conditions,
        )
    )


def _seed_unscoped_graph(db, entity_type, tenant_id, statuses, edges) -> None:
    """Seed a tenant-level (scope_id NULL) status graph if absent. Finance
    statuses are ``is_system=True`` — the engine looks up keys (issued/paid/void/
    draft/succeeded) as a load-bearing code contract (AC-07-53), so keys + flags +
    delete are locked from tenant rename; label/color/order stay editable."""
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


def backfill_graph(db, entity_type, tenant_id, statuses, edges) -> int:
    """Repair an EXISTING tenant graph (AC-07-08): add any seed statuses/edges
    that are missing WITHOUT clobbering operator edits (label/color/flags left
    as-is on rows that exist). Idempotent — the no-op when the graph is already
    complete. Returns the number of rows added. A tenant with no graph at all is
    left to ``_seed_unscoped_graph`` (this only repairs a partial one)."""
    from app.models.status import Status
    from app.models.status_transition import StatusTransition

    rows = (
        db.query(Status)
        .filter(Status.entity_type == entity_type, Status.tenant_id == tenant_id, Status.scope_id.is_(None))
        .all()
    )
    if not rows:
        return 0  # no graph at all → install_tenant seeds it fresh
    by_key = {r.key: r for r in rows}
    added = 0
    for key, label, color, sort, flags in statuses:
        if key in by_key:
            continue
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
        added += 1
    db.flush()
    # Existing edge set (from_status_id, to_status_id) for this tier.
    existing_edges = {
        (e.from_status_id, e.to_status_id)
        for e in db.query(StatusTransition).filter(
            StatusTransition.entity_type == entity_type, StatusTransition.tenant_id == tenant_id
        )
    }
    for edge in edges:
        fk, tk = edge[0], edge[1]
        if fk not in by_key or tk not in by_key:
            continue  # operator renamed a key away — don't synthesize
        if (by_key[fk].id, by_key[tk].id) in existing_edges:
            continue
        _add_edge(db, entity_type, tenant_id, by_key[fk], by_key[tk], edge)
        added += 1
    db.flush()
    return added


def install_tenant(db: Session, tenant_id: str) -> None:
    _seed_unscoped_graph(db, INVOICE_ENTITY, tenant_id, INVOICE_STATUS_SEED, INVOICE_EDGE_SEED)
    _seed_unscoped_graph(db, PAYMENT_ENTITY, tenant_id, PAYMENT_STATUS_SEED, PAYMENT_EDGE_SEED)
    _seed_unscoped_graph(db, REFUND_ENTITY, tenant_id, REFUND_STATUS_SEED, REFUND_EDGE_SEED)
    _seed_unscoped_graph(db, SETTLEMENT_ENTITY, tenant_id, SETTLEMENT_STATUS_SEED, SETTLEMENT_EDGE_SEED)


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    # Self-heal (AC-07-08, AC-07-53): a tenant that installed finance before
    # Cluster F has only Draft/Issued/Cancelled — repair the existing graph in
    # place (adds Void / Partially Paid / Paid / Overdue / Refunded + auto edges)
    # without clobbering operator edits. Seed the payment graph if missing. The
    # legacy-row status_id backfill rides the per-module Alembic migration (live
    # Postgres) — conftest's create_all has no legacy rows. The caller commits.
    backfill_graph(db, INVOICE_ENTITY, tenant_id, INVOICE_STATUS_SEED, INVOICE_EDGE_SEED)
    # Payment graph: seed if missing, else BACKFILL the new Cluster-F slice-3
    # states (Expired / Disputed / Refunded + edges) onto an existing graph
    # (AC-07-53 — seed-if-absent does NOT repair a partial graph).
    _seed_unscoped_graph(db, PAYMENT_ENTITY, tenant_id, PAYMENT_STATUS_SEED, PAYMENT_EDGE_SEED)
    backfill_graph(db, PAYMENT_ENTITY, tenant_id, PAYMENT_STATUS_SEED, PAYMENT_EDGE_SEED)
    # Refund + Settlement graphs (Cluster F slice 4): seed if missing, else
    # backfill the new states/edges onto an existing tenant graph (AC-07-53).
    _seed_unscoped_graph(db, REFUND_ENTITY, tenant_id, REFUND_STATUS_SEED, REFUND_EDGE_SEED)
    backfill_graph(db, REFUND_ENTITY, tenant_id, REFUND_STATUS_SEED, REFUND_EDGE_SEED)
    _seed_unscoped_graph(db, SETTLEMENT_ENTITY, tenant_id, SETTLEMENT_STATUS_SEED, SETTLEMENT_EDGE_SEED)
    backfill_graph(db, SETTLEMENT_ENTITY, tenant_id, SETTLEMENT_STATUS_SEED, SETTLEMENT_EDGE_SEED)
    # Grant sweep (AC-07-53): the new settlements.* keys won't reach an existing
    # tenant's Admin via catalog sync alone. AppStoreService.update calls
    # _grant_admin after this hook (the version bump 1.0→1.1 makes "Update"
    # available), but re-grant here too so any direct update_tenant caller is
    # covered. Idempotent.
    _grant_new_keys_to_admin(db, tenant_id)


def _grant_new_keys_to_admin(db: Session, tenant_id: str) -> None:
    from app.models.permission import Permission
    from app.models.role import Role

    admin = (
        db.query(Role)
        .filter(Role.tenant_id == tenant_id, Role.name == "Admin")
        .first()
    )
    if admin is None:
        return
    held = {p.id for p in admin.permissions}
    for perm in db.query(Permission).filter(Permission.module == MODULE_NAME).all():
        if perm.id not in held:
            admin.permissions.append(perm)
    db.flush()


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    from app.models.status import Status
    from app.models.status_transition import StatusTransition

    # Refunds + settlements (Cluster F slice 4) — wipe this tenant's rows.
    refund_ids = [r.id for r in db.query(Refund.id).filter(Refund.tenant_id == tenant_id)]
    if refund_ids:
        db.query(RefundLine).filter(RefundLine.refund_id.in_(refund_ids)).delete(synchronize_session=False)
    db.query(Refund).filter(Refund.tenant_id == tenant_id).delete(synchronize_session=False)
    settlement_ids = [r.id for r in db.query(Settlement.id).filter(Settlement.tenant_id == tenant_id)]
    if settlement_ids:
        db.query(SettlementLine).filter(SettlementLine.settlement_id.in_(settlement_ids)).delete(synchronize_session=False)
    db.query(Settlement).filter(Settlement.tenant_id == tenant_id).delete(synchronize_session=False)

    ids = [r.id for r in db.query(Invoice.id).filter(Invoice.tenant_id == tenant_id)]
    if ids:
        db.query(InvoiceLine).filter(InvoiceLine.invoice_id.in_(ids)).delete(synchronize_session=False)
        db.query(Payment).filter(Payment.invoice_id.in_(ids)).delete(synchronize_session=False)
    db.query(Invoice).filter(Invoice.tenant_id == tenant_id).delete(synchronize_session=False)
    for entity in (INVOICE_ENTITY, PAYMENT_ENTITY, REFUND_ENTITY, SETTLEMENT_ENTITY):
        db.query(StatusTransition).filter(
            StatusTransition.entity_type == entity, StatusTransition.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        db.query(Status).filter(
            Status.entity_type == entity, Status.tenant_id == tenant_id
        ).delete(synchronize_session=False)
    db.flush()


def tenant_has_data(db: Session, tenant_id: str) -> bool:
    return db.query(Invoice.id).filter(Invoice.tenant_id == tenant_id).first() is not None


# ── engine registrations (boot) ──────────────────────────────────────────────

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


def _paid_total_fact():
    """SUM of Succeeded payment amounts on an invoice (AC-07-11). Owner- and
    tenant-scoped by ``aggregate_fact``'s resolver; filtered to the Succeeded
    payment status via the legacy-portable approach — we resolve the tenant's
    'succeeded' payment status id is NOT portable inside the clause, so we filter
    on a SUCCEEDED marker carried on the row. v1 only ever creates Succeeded
    manual payments + sets paid_at; Pending/Failed rows carry no paid_at, so
    ``paid_at IS NOT NULL`` is the portable Succeeded predicate (gateway Pending
    rows in Slice 3 also have no paid_at until they succeed)."""
    from app.rule_engine.aggregates import aggregate_fact

    return aggregate_fact(
        "record.paidTotal",
        "Paid total",
        child_model=Payment,
        fk_attr="invoice_id",
        op="sum",
        column="amount",
        where=Payment.paid_at.isnot(None),
        type="number",
    )


def _refunded_total_fact():
    """SUM of CONFIRMED refund amounts on an invoice (Cluster F slice 4,
    AC-07-43). A confirmed refund carries ``confirmed_at`` (portable Confirmed
    predicate across tenants, like paid_at on payments). Drives the invoice's
    Partially Refunded / Refunded auto edges."""
    from app.rule_engine.aggregates import aggregate_fact

    return aggregate_fact(
        "record.refundedTotal",
        "Refunded total",
        child_model=Refund,
        fk_attr="invoice_id",
        op="sum",
        column="amount",
        where=Refund.confirmed_at.isnot(None),
        type="number",
    )


def register_engine_entities() -> None:
    from app.numbering.registry import NumberSequenceDef, register_number_sequence
    from app.status_engine.derived import DerivedTrigger, register_derived_trigger
    from app.status_engine.registry import StatusEntity, register_status_entity
    from app.terminology.registry import TermDef, register_term

    # Numbering doc types (sprint-4/07, Cluster F) — finance owns invoice /
    # credit_note / receipt; the running number is assigned at a state-change
    # seam (e.g. Draft → Issued), not at create.
    register_number_sequence(
        NumberSequenceDef("invoice", "Invoice", module=MODULE_NAME,
                          default_prefix="INV-", default_format="{prefix}{YYYY}-{NNNNN}",
                          default_reset="yearly")
    )
    register_number_sequence(
        NumberSequenceDef("credit_note", "Credit note", module=MODULE_NAME,
                          default_prefix="CN-", default_format="{prefix}{YYYY}-{NNNNN}",
                          default_reset="yearly")
    )
    register_number_sequence(
        NumberSequenceDef("receipt", "Receipt", module=MODULE_NAME,
                          default_prefix="RCT-", default_format="{prefix}{YYYY}-{NNNNN}",
                          default_reset="yearly")
    )

    register_status_entity(
        StatusEntity(
            entity_type=INVOICE_ENTITY,
            label="Invoice",
            module=MODULE_NAME,
            count_records=_count_by_status(Invoice),
            migrate_records=_migrate_by_status(Invoice),
            record_label_attr="id",
            required_flags=["is_initial", "is_terminal"],
            # Derived status (AC-07-11/13): the invoice re-evaluates its own auto
            # edges when a payment changes (cross-entity DerivedTrigger below) or
            # the clock advances past due_date (time sweep). ``total`` + the
            # auto-generated ``dueDate.daysSince`` fact + the ``paidTotal``
            # aggregate are the auto-edge condition vocabulary.
            model=Invoice,
            fact_attrs=["total", "due_date", "currency"],
            aggregate_facts=[_paid_total_fact(), _refunded_total_fact()],
            # Time sweep (AC-07-13): event-driven re-eval can't catch the clock
            # passing due_date with no write. Coarse — any non-paid Issued/
            # Partially-Paid/Overdue invoice with a due_date; reevaluate
            # fail-closes the rest.
            has_time_auto_edges=True,
            time_candidates=lambda db: db.query(Invoice)
            .filter(Invoice.due_date.isnot(None))
            .all(),
        )
    )
    register_status_entity(
        StatusEntity(
            entity_type=PAYMENT_ENTITY,
            label="Payment",
            module=MODULE_NAME,
            count_records=_count_by_status(Payment),
            migrate_records=_migrate_by_status(Payment),
            record_label_attr="id",
            required_flags=["is_initial", "is_terminal"],
            model=Payment,
        )
    )
    # Cross-entity re-derive (AC-07-11): a payment change re-evaluates the owning
    # invoice's auto edges. The payment write path emits the payment entity event
    # (notify_entity_event in PaymentService) so this fires.
    def _invoice_owners(db, tenant_id, ev):
        pay = (
            db.query(Payment)
            .filter(Payment.id == ev.get("record_id"), Payment.tenant_id == tenant_id)
            .first()
        )
        if pay is None or not pay.invoice_id:
            return []
        inv = (
            db.query(Invoice)
            .filter(Invoice.id == pay.invoice_id, Invoice.tenant_id == tenant_id)
            .first()
        )
        return [inv] if inv is not None else []

    register_derived_trigger(
        DerivedTrigger(
            owner_entity=INVOICE_ENTITY,
            trigger_entity=PAYMENT_ENTITY,
            resolve_owners=_invoice_owners,
        )
    )

    # Refund + Settlement status entities (Cluster F slice 4, AC-07-37/47).
    register_status_entity(
        StatusEntity(
            entity_type=REFUND_ENTITY,
            label="Refund",
            module=MODULE_NAME,
            count_records=_count_by_status(Refund),
            migrate_records=_migrate_by_status(Refund),
            record_label_attr="id",
            required_flags=["is_initial", "is_terminal"],
            model=Refund,
        )
    )
    register_status_entity(
        StatusEntity(
            entity_type=SETTLEMENT_ENTITY,
            label="Settlement",
            module=MODULE_NAME,
            count_records=_count_by_status(Settlement),
            migrate_records=_migrate_by_status(Settlement),
            record_label_attr="id",
            required_flags=["is_initial", "is_terminal"],
            model=Settlement,
        )
    )

    # Cross-entity re-derive (AC-07-43): a refund change re-evaluates the owning
    # invoice's auto edges (Partially Refunded / Refunded). The refund write path
    # emits the refund status_changed event so this fires.
    def _invoice_owners_of_refund(db, tenant_id, ev):
        r = (
            db.query(Refund)
            .filter(Refund.id == ev.get("record_id"), Refund.tenant_id == tenant_id)
            .first()
        )
        if r is None or not r.invoice_id:
            return []
        inv = (
            db.query(Invoice)
            .filter(Invoice.id == r.invoice_id, Invoice.tenant_id == tenant_id)
            .first()
        )
        return [inv] if inv is not None else []

    register_derived_trigger(
        DerivedTrigger(
            owner_entity=INVOICE_ENTITY,
            trigger_entity=REFUND_ENTITY,
            resolve_owners=_invoice_owners_of_refund,
        )
    )

    register_term(TermDef("invoice", "Invoice", "Invoices", module=MODULE_NAME, group="Finance"))
    register_term(TermDef("settlement", "Settlement", "Settlements", module=MODULE_NAME, group="Finance"))

    # Post-remit refund → ADJUSTMENT settlement (AC-07-48). A separate bus
    # subscriber (not a status DerivedTrigger — it CREATES a record, not a status
    # move) reacts to a confirmed refund. Failure-isolated by the after-commit
    # drain's per-subscriber isolated commit.
    _register_settlement_adjustment_subscriber()

    # Template context (AC-07-17) — the bound invoice render vocabulary.
    from modules.finance.invoice_template import register_invoice_context

    register_invoice_context()


_SETTLEMENT_SUB_REGISTERED = False


def _register_settlement_adjustment_subscriber() -> None:
    """Subscribe a refund→ADJUSTMENT-settlement reaction on the event bus
    (AC-07-48). Idempotent (the bus does NOT dedup by fn identity — guard with a
    module flag). The after-commit drain isolates this in its own commit, so a
    failure here can NEVER 500 the refund request (AC-07-50)."""
    global _SETTLEMENT_SUB_REGISTERED
    if _SETTLEMENT_SUB_REGISTERED:
        return
    from app.workflow_engine.entity_events import register_event_subscriber

    register_event_subscriber(_on_refund_event)
    _SETTLEMENT_SUB_REGISTERED = True


def _on_refund_event(session, ev) -> None:
    import logging as _logging

    if ev.get("entity_type") != REFUND_ENTITY or ev.get("action") != "status_changed":
        return
    tenant_id = ev.get("tenant_id")
    refund_id = ev.get("record_id")
    if not tenant_id or not refund_id:
        return
    refund = (
        session.query(Refund)
        .filter(Refund.id == refund_id, Refund.tenant_id == tenant_id)
        .first()
    )
    if refund is None or refund.confirmed_at is None:
        return  # only a CONFIRMED refund clawback (AC-07-48)
    try:
        from modules.finance.settlement_service import SettlementService

        adj = SettlementService(session).spawn_adjustment_for_refund(tenant_id, refund)
        if adj is not None:
            session.flush()
    except Exception:  # noqa: BLE001 — fully isolated (AC-07-50)
        _logging.getLogger("dreamz.finance.settlement").exception(
            "settlement adjustment for refund %s failed", refund_id
        )


def register_capabilities() -> None:
    from app.module_platform import CapabilityDef, register_capability
    from modules.finance.services import InvoiceService

    def _create_invoice(db, tenant_id, payload):
        return InvoiceService(db).create_from_payload(tenant_id, payload)

    def _resolve_invoice(db, tenant_id, payload):
        return InvoiceService(db).resolve(tenant_id, payload.get("id"))

    # Cluster F slice 3 — the gateway webhook ingest (CORE) calls this to flip
    # the payment + derive the invoice. Tenant-scoped internally.
    def _apply_payment_event(db, tenant_id, payload):
        from modules.finance.payment_service import PaymentService

        return PaymentService(db).apply_payment_event(tenant_id, payload)

    register_capability(CapabilityDef("finance.create_invoice", 1, MODULE_NAME, _create_invoice))
    register_capability(CapabilityDef("invoice.resolve", 1, MODULE_NAME, _resolve_invoice))
    register_capability(CapabilityDef("finance.apply_payment_event", 1, MODULE_NAME, _apply_payment_event))
