"""Platform-tier system templates (plan 07 D7) - the engine's day-one content.

Block-doc ports of the legacy Jinja2 transactional mails. Seeded
insert-if-missing by KEY: re-seeding never clobbers operator edits to the
platform tier (the operator maintains these rows through the Templates UI).
"""

import uuid
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models.template import (
    TEMPLATE_TYPE_BADGE,
    TEMPLATE_TYPE_DOCUMENT,
    TEMPLATE_TYPE_EMAIL,
    Template,
)


def _bid() -> str:
    return f"blk_{uuid.uuid4().hex[:6]}"


def _sid() -> str:
    return f"sec_{uuid.uuid4().hex[:6]}"


def _cid() -> str:
    return f"col_{uuid.uuid4().hex[:6]}"


def _doc(heading: str, body_html: str, button_label: str | None, button_href: str | None) -> Dict:
    """Brand header + content + brand footer - mirrors the editor's blank doc."""
    body_blocks: List[Dict] = [
        {"id": _bid(), "type": "heading", "text": heading, "level": 2, "align": "left"},
        {"id": _bid(), "type": "text", "html": body_html, "align": "left"},
    ]
    if button_label and button_href:
        body_blocks.append(
            {
                "id": _bid(),
                "type": "button",
                "label": button_label,
                "href": button_href,
                "align": "left",
                "backgroundColor": None,
                "textColor": None,
                "borderRadius": 6,
            }
        )
    return {
        "schemaVersion": 1,
        "sections": [
            {
                "id": _sid(),
                "layout": "100",
                "background": None,
                "padding": {"top": 0, "bottom": 0, "left": 0, "right": 0},
                "columns": [{"id": _cid(), "blocks": [{"id": _bid(), "type": "brandHeader", "overrides": None}]}],
            },
            {
                "id": _sid(),
                "layout": "100",
                "background": "#FFFFFF",
                "padding": {"top": 24, "bottom": 24, "left": 24, "right": 24},
                "columns": [{"id": _cid(), "blocks": body_blocks}],
            },
            {
                "id": _sid(),
                "layout": "100",
                "background": None,
                "padding": {"top": 0, "bottom": 0, "left": 0, "right": 0},
                "columns": [{"id": _cid(), "blocks": [{"id": _bid(), "type": "brandFooter", "overrides": None}]}],
            },
        ],
    }


SYSTEM_TEMPLATES: List[Dict] = [
    {
        "key": "auth.password_reset",
        "name": "Password reset",
        "context": "auth.password_reset",
        "subject": "Reset your {{tenant.name}} password",
        "doc": _doc(
            "Hi {{recipient.firstName}},",
            "We received a request to reset your password. The link below is valid for "
            "{{expiresInMinutes}} minutes. If you didn't request this, you can safely ignore this email.",
            "Reset password",
            "{{resetLink}}",
        ),
    },
    {
        "key": "auth.invite",
        "name": "User invitation",
        "context": "auth.invite",
        "subject": "You've been invited to {{tenant.name}}",
        "doc": _doc(
            "Welcome!",
            "You've been invited to join <b>{{tenant.name}}</b>. Click below to claim your "
            "account and set a password. The link is valid for {{expiresInDays}} days.",
            "Accept invitation",
            "{{inviteLink}}",
        ),
    },
    {
        "key": "auth.verification",
        "name": "Email verification",
        "context": "auth.verification",
        "subject": "Verify your email address",
        "doc": _doc(
            "Almost there,",
            "Confirm this mailbox to activate your {{tenant.name}} account.",
            "Verify email",
            "{{verifyLink}}",
        ),
    },
    {
        "key": "account.email_change_approve",
        "name": "Email change - approve (old mailbox)",
        "context": "account.email_change_approve",
        "subject": "Approve your email change request",
        "doc": _doc(
            "Hi {{recipient.firstName}},",
            "You asked to change your sign-in email to <b>{{newEmail}}</b>. Approve this "
            "request from your current mailbox to continue. If this wasn't you, you can "
            "ignore this email and your address stays unchanged.",
            "Approve change",
            "{{approveLink}}",
        ),
    },
    {
        "key": "account.email_change_verify",
        "name": "Email change - verify (new mailbox)",
        "context": "account.email_change_verify",
        "subject": "Verify your new email address",
        "doc": _doc(
            "Almost there, {{recipient.firstName}}",
            "Confirm this mailbox to complete your email change.",
            "Verify email",
            "{{verifyLink}}",
        ),
    },
    {
        "key": "account.email_change_notice",
        "name": "Email change - notice",
        "context": "account.email_change_notice",
        "subject": "Your sign-in email was changed",
        "doc": _doc(
            "Hi {{recipient.firstName}},",
            "The sign-in email for your account changed from <b>{{oldEmail}}</b> to "
            "<b>{{newEmail}}</b>. If you didn't expect this, contact your workspace admin "
            "immediately.",
            None,
            None,
        ),
    },
    {
        # Starter template for the status-engine transition-notification picker
        # (BL-081) - gives the picker day-one content; operators clone/edit it.
        "key": "status.transition_notification",
        "name": "Status change notification",
        "context": "status.notification",
        "subject": "{{recordLabel}} moved to {{toStatus}}",
        "doc": _doc(
            "{{recordLabel}} is now {{toStatus}}",
            "The {{entityLabel}} <b>{{recordLabel}}</b> moved from {{fromStatus}} to "
            "<b>{{toStatus}}</b>.",
            None,
            None,
        ),
    },
]


def _invoice_doc() -> Dict:
    """Starter document-surface (PDF) invoice - header + company/bill-to +
    line-item table bound to ``lineItems`` + totals footer (plan sprint-3/03
    D9). Exercises the table/footer expansion ahead of the real Cluster-F
    invoice entity; ``document.invoice_preview`` context supplies the facts."""
    return {
        "schemaVersion": 1,
        "pageSetup": {
            "size": "A4",
            "orientation": "portrait",
            "margins": {"top": 15, "bottom": 15, "left": 15, "right": 15},
        },
        "sections": [
            {
                "id": _sid(),
                "layout": "100",
                "background": None,
                "padding": {"top": 0, "bottom": 0, "left": 0, "right": 0},
                "columns": [{"id": _cid(), "blocks": [{"id": _bid(), "type": "brandHeader", "overrides": None}]}],
            },
            {
                "id": _sid(),
                "layout": "100",
                "background": None,
                "padding": {"top": 8, "bottom": 8, "left": 0, "right": 0},
                "columns": [
                    {
                        "id": _cid(),
                        "blocks": [
                            {"id": _bid(), "type": "heading", "text": "Invoice {{invoiceNumber}}", "level": 1, "align": "left"},
                            {"id": _bid(), "type": "text", "html": "Date: {{invoiceDate}}", "align": "left"},
                        ],
                    }
                ],
            },
            {
                "id": _sid(),
                "layout": "50/50",
                "background": None,
                "padding": {"top": 8, "bottom": 8, "left": 0, "right": 0},
                "columns": [
                    {
                        "id": _cid(),
                        "blocks": [
                            {"id": _bid(), "type": "heading", "text": "From", "level": 3, "align": "left"},
                            {"id": _bid(), "type": "text", "html": "{{companyName}}", "align": "left"},
                        ],
                    },
                    {
                        "id": _cid(),
                        "blocks": [
                            {"id": _bid(), "type": "heading", "text": "Bill to", "level": 3, "align": "left"},
                            {"id": _bid(), "type": "text", "html": "{{recipientName}}", "align": "left"},
                        ],
                    },
                ],
            },
            {
                "id": _sid(),
                "layout": "100",
                "background": None,
                "padding": {"top": 8, "bottom": 8, "left": 0, "right": 0},
                "columns": [
                    {
                        "id": _cid(),
                        "blocks": [
                            {
                                "id": _bid(),
                                "type": "table",
                                "source": "lineItems",
                                "columns": [
                                    {"key": "description", "header": "Item", "align": "left"},
                                    {"key": "qty", "header": "Qty", "align": "center"},
                                    {"key": "amount", "header": "Amount", "align": "right"},
                                ],
                                "footer": [
                                    {"cells": [
                                        {"text": "Subtotal", "align": "right", "span": 2},
                                        {"text": "{{subtotal}}", "align": "right", "span": 1},
                                    ]},
                                    {"cells": [
                                        {"text": "Tax", "align": "right", "span": 2},
                                        {"text": "{{tax}}", "align": "right", "span": 1},
                                    ]},
                                    {"cells": [
                                        {"text": "Total", "align": "right", "span": 2},
                                        {"text": "{{total}}", "align": "right", "span": 1},
                                    ]},
                                ],
                            }
                        ],
                    }
                ],
            },
            {
                "id": _sid(),
                "layout": "100",
                "background": None,
                "padding": {"top": 0, "bottom": 0, "left": 0, "right": 0},
                "columns": [{"id": _cid(), "blocks": [{"id": _bid(), "type": "brandFooter", "overrides": None}]}],
            },
        ],
    }


DOCUMENT_TEMPLATES: List[Dict] = [
    {
        "key": "document.invoice",
        "name": "Invoice",
        "context": "document.invoice_preview",
        "subject": "Invoice {{invoiceNumber}}",
        "doc": _invoice_doc(),
    },
]


def _eid() -> str:
    return f"el_{uuid.uuid4().hex[:6]}"


def _badge_doc() -> Dict:
    """Starter fixed-canvas badge (plan sprint-3/03 D17) - 86×54mm landscape:
    name + role + a QR bound to {{ticketCode}}. Exercises the canvas surface
    ahead of the real Cluster-H attendee entity; ``badge.preview`` supplies the
    facts. Geometry in mm (print-authoritative)."""
    return {
        "schemaVersion": 1,
        "canvas": {"width": 86, "height": 54, "unit": "mm", "orientation": "landscape", "bleed": 3},
        "sides": [
            {
                "name": "front",
                "elements": [
                    {
                        "id": _eid(), "type": "shape", "kind": "rect",
                        "x": 0, "y": 0, "w": 86, "h": 12, "rotation": 0,
                        "fill": "#FF5A00", "stroke": None, "strokeWidth": 0, "radius": 0,
                    },
                    {
                        "id": _eid(), "type": "text",
                        "x": 6, "y": 20, "w": 50, "h": 12, "rotation": 0,
                        "content": "{{attendeeName}}", "fontFamily": "Poppins",
                        "fontSize": 16, "weight": 700, "align": "left",
                        "color": "#18181B", "lineHeight": 1.2,
                    },
                    {
                        "id": _eid(), "type": "text",
                        "x": 6, "y": 33, "w": 50, "h": 8, "rotation": 0,
                        "content": "{{role}} · {{company}}", "fontFamily": "Inter",
                        "fontSize": 10, "weight": 400, "align": "left",
                        "color": "#52525B", "lineHeight": 1.2,
                    },
                    {
                        "id": _eid(), "type": "qr",
                        "x": 62, "y": 26, "w": 20, "h": 20, "rotation": 0,
                        "data": "{{ticketCode}}", "ecLevel": "M",
                    },
                ],
            }
        ],
    }


BADGE_TEMPLATES: List[Dict] = [
    {
        "key": "badge.attendee",
        "name": "Attendee badge",
        "context": "badge.preview",
        "subject": "",
        "doc": _badge_doc(),
    },
]


def _repair_duplicate_ids(db: Session) -> None:
    """One-time fixup: early seeds reused 'col_1' across sections - duplicate
    ids break the editor's drop zones (dnd-kit keeps one droppable per id).
    Reassign unique ids wherever a doc repeats section/column/block ids."""
    import copy

    rows = db.query(Template).all()
    for row in rows:
        # Deep-copy BEFORE mutating: in-place edits mutate the loaded value
        # too, so SQLAlchemy's old==new comparison sees "unchanged" and emits
        # no UPDATE (house JSON-column trap).
        doc = copy.deepcopy(row.doc_json or {})
        seen: set = set()
        changed = False
        for section in doc.get("sections", []):
            for holder, prefix in ((section, "sec"), *[(c, "col") for c in section.get("columns", [])]):
                ident = holder.get("id")
                if ident in seen:
                    holder["id"] = f"{prefix}_{uuid.uuid4().hex[:6]}"
                    changed = True
                seen.add(holder.get("id"))
            for column in section.get("columns", []):
                for block in column.get("blocks", []):
                    ident = block.get("id")
                    if ident in seen:
                        block["id"] = f"blk_{uuid.uuid4().hex[:6]}"
                        changed = True
                    seen.add(block.get("id"))
        if changed:
            row.doc_json = doc
    db.flush()


def seed_platform_templates(db: Session) -> None:
    """Insert-if-missing by key (idempotent; operator edits survive reseed)."""
    _repair_duplicate_ids(db)
    existing = {
        key
        for (key,) in db.query(Template.key).filter(Template.tenant_id.is_(None)).all()
    }
    for spec in SYSTEM_TEMPLATES:
        if spec["key"] in existing:
            continue
        db.add(
            Template(
                tenant_id=None,
                type=TEMPLATE_TYPE_EMAIL,
                key=spec["key"],
                name=spec["name"],
                context=spec["context"],
                subject=spec["subject"],
                doc_json=spec["doc"],
                is_system=True,
            )
        )
    for spec in DOCUMENT_TEMPLATES:
        if spec["key"] in existing:
            continue
        db.add(
            Template(
                tenant_id=None,
                type=TEMPLATE_TYPE_DOCUMENT,
                key=spec["key"],
                name=spec["name"],
                context=spec["context"],
                subject=spec["subject"],
                doc_json=spec["doc"],
                is_system=True,
            )
        )
    for spec in BADGE_TEMPLATES:
        if spec["key"] in existing:
            continue
        db.add(
            Template(
                tenant_id=None,
                type=TEMPLATE_TYPE_BADGE,
                key=spec["key"],
                name=spec["name"],
                context=spec["context"],
                subject=spec["subject"],
                doc_json=spec["doc"],
                is_system=True,
            )
        )
    db.flush()
