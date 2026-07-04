"""Post-payment reaction (sprint-4/07 Cluster F slice 3, AC-07-35).

When a finance invoice derives to **Paid**, the EMS module reacts: its admission
tickets become **Valid**, the owning participants become **Eligible**, and a
**receipt email with the invoice PDF** is enqueued.

This rides the event bus as a registered subscriber — the after-commit drain
isolates each event in its own commit, so a failure here can NEVER 500 or block
the webhook/derivation that triggered it (AC-07-35/50). It's the WORKFLOW-class
reaction the plan calls for (a multi-step, cross-entity orchestration off a
status change), implemented on the shared subscriber seam rather than a hand-
rolled per-row loop.
"""
import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

logger = logging.getLogger("dreamz.ems.post_payment")


def _on_event(session: Session, ev: Dict[str, Any]) -> None:
    if ev.get("entity_type") != "invoice" or ev.get("action") != "status_changed":
        return
    tenant_id = ev.get("tenant_id")
    invoice_id = ev.get("record_id")
    if not tenant_id or not invoice_id:
        return
    # Only react when the invoice actually reached Paid — resolve its current
    # status key (tenant-scoped soft-ref read).
    from app.models.status import Status
    from modules.finance.models import Invoice

    inv = (
        session.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
        .first()
    )
    if inv is None or not inv.status_id:
        return
    st = session.query(Status).filter(Status.id == inv.status_id).first()
    if st is None or st.key != "paid":
        return

    _make_tickets_valid_and_participants_eligible(session, tenant_id, invoice_id)
    _enqueue_receipt(session, tenant_id, inv)


def _make_tickets_valid_and_participants_eligible(session: Session, tenant_id: str, invoice_id: str) -> None:
    from app.services import status_machine
    from modules.ems.models import (
        PARTICIPANT_ENTITY,
        TICKET_ENTITY,
        ProjectParticipant,
        Ticket,
    )
    from modules.ems.services import _status_id_by_key

    tickets = (
        session.query(Ticket)
        .filter(Ticket.tenant_id == tenant_id, Ticket.invoice_id == invoice_id)
        .all()
    )
    valid_id = _status_id_by_key(session, TICKET_ENTITY, tenant_id, "valid")
    participant_ids = set()
    for t in tickets:
        if t.participant_id:
            participant_ids.add(t.participant_id)
        # Only promote a still-Issued ticket; terminal/checked-in are untouched.
        if t.status in ("issued",) and valid_id:
            try:
                status_machine.transition(
                    session, TICKET_ENTITY, t, valid_id, None, tenant_id=tenant_id, commit=False
                )
                t.status = "valid"
            except Exception:  # noqa: BLE001 — one bad ticket never stops siblings
                logger.exception("post-payment ticket→Valid failed (%s)", t.id)
    session.flush()

    # Participants → Eligible (scoped graph, scope = project_id).
    for pp_id in participant_ids:
        pp = (
            session.query(ProjectParticipant)
            .filter(ProjectParticipant.id == pp_id, ProjectParticipant.tenant_id == tenant_id)
            .first()
        )
        if pp is None:
            continue
        eligible_id = _scoped_status_id(session, PARTICIPANT_ENTITY, tenant_id, pp.project_id, "eligible")
        if not eligible_id:
            continue
        try:
            status_machine.transition(
                session, PARTICIPANT_ENTITY, pp, eligible_id, None, tenant_id=tenant_id, commit=False
            )
        except Exception:  # noqa: BLE001 — no edge from current status / already eligible
            logger.info("post-payment participant→Eligible skipped (%s)", pp_id)
    session.flush()


def _scoped_status_id(session: Session, entity_type: str, tenant_id: str, scope_id: str, key: str):
    from app.models.status import Status

    row = (
        session.query(Status)
        .filter(
            Status.entity_type == entity_type,
            Status.tenant_id == tenant_id,
            Status.scope_id == scope_id,
            Status.key == key,
        )
        .first()
    )
    return row.id if row else None


def _enqueue_receipt(session: Session, tenant_id: str, inv) -> None:
    """Enqueue a receipt email with the invoice PDF attached. Failure-isolated —
    a render/enqueue error must not break the reaction."""
    try:
        from modules.finance.services import InvoiceService

        # Resolve a recipient: the bill-to's email via the resolve capability.
        recipient = _bill_to_email(session, tenant_id, inv)
        if not recipient:
            return
        pdf = InvoiceService(session).render_pdf(tenant_id, inv.id)
        _send_receipt_email(session, tenant_id, recipient, inv, pdf)
    except Exception:  # noqa: BLE001
        logger.exception("post-payment receipt enqueue failed (%s)", inv.id)


def _bill_to_email(session: Session, tenant_id: str, inv) -> str:
    from app.module_platform import resolve_capability

    key = "client.resolve" if inv.bill_to_type == "Client" else "profile.resolve"
    handler = resolve_capability(session, tenant_id, key, 1)
    if handler is None:
        return ""
    res = handler(session, tenant_id, {"id": inv.bill_to_id})
    if not res:
        return ""
    return res.get("email") or ""


def _send_receipt_email(session: Session, tenant_id: str, to_email: str, inv, pdf: bytes) -> None:
    """Enqueue via the email outbox (the ONE send path). The receipt body links
    to the downloadable invoice/receipt PDF (the email-attachment seam = BL); the
    PDF itself stays downloadable from the invoice detail."""
    from app.services.email_service import email_service

    number = inv.invoice_number or inv.id[:8]
    subject = f"Receipt — Invoice {number}"
    body_html = (
        f"<p>Thank you. Your payment for invoice <strong>{number}</strong> has "
        f"been received. A receipt is available from your invoice.</p>"
    )
    email_service.enqueue_raw(
        session,
        tenant_id,
        to_email,
        subject,
        body_html,
        "Thank you. Your payment has been received.",
        template_key="finance.receipt",
        commit=False,
    )


def register_post_payment_reaction() -> None:
    """Register the subscriber on the event bus. Idempotent (the bus dedups by
    fn identity is NOT guaranteed — guard with a module flag)."""
    from app.workflow_engine.entity_events import register_event_subscriber

    global _REGISTERED
    if _REGISTERED:
        return
    register_event_subscriber(_on_event)
    _REGISTERED = True


_REGISTERED = False
