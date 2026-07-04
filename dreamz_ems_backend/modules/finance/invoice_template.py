"""Invoice document template + TemplateContext (sprint-4/07 Cluster F, AC-07-17).

The bound ``invoice`` context declares the merge-fact vocabulary the PDF renders
(scalar header facts + the ``lineItems`` and ``payments`` list facts) and the
required facts (a numberless invoice is a broken document). ``invoice_doc`` is
the F2 document-surface block tree — brand header, header block, from/bill-to,
the line-item table (F2 repeater/table block bound to ``lineItems``), a totals
footer + tax-summary, a payments table (the receipt, AC-07-18) and a Paid stamp.

The doc carries NO visibility conditions — the PDF render builds the facts so
the payments table is empty (renders to nothing) when there are no payments and
the paid stamp text is blank unless Paid; this keeps render deterministic without
rule-object resolution.
"""
import uuid
from typing import Dict

INVOICE_TEMPLATE_CONTEXT = "invoice"


def _bid() -> str:
    return f"blk_{uuid.uuid4().hex[:6]}"


def _sid() -> str:
    return f"sec_{uuid.uuid4().hex[:6]}"


def _cid() -> str:
    return f"col_{uuid.uuid4().hex[:6]}"


def register_invoice_context() -> None:
    """Register the bound ``invoice`` TemplateContext (idempotent)."""
    from app.template_engine.contexts import (
        ContextFact,
        ListFact,
        TemplateContext,
        register_context,
    )

    register_context(
        TemplateContext(
            key=INVOICE_TEMPLATE_CONTEXT,
            label="Finance · Invoice",
            module="finance",
            fact_sources=(),
            facts=(
                ContextFact("companyName", "Your company name", "Acme Events"),
                ContextFact("recipientName", "Bill-to name", "Jordan Lee"),
                ContextFact("buyerTin", "Buyer TIN", ""),
                ContextFact("invoiceNumber", "Invoice number", "INV-2026-00001"),
                ContextFact("invoiceDate", "Invoice date", "12 Jun 2026"),
                ContextFact("dueDate", "Due date", "12 Jul 2026"),
                ContextFact("statusLabel", "Status", "Paid"),
                ContextFact("subtotal", "Subtotal", "$1,400.00"),
                ContextFact("tax", "Tax", "$84.00"),
                ContextFact("total", "Total", "$1,484.00"),
                ContextFact("amountPaid", "Amount paid", "$1,484.00"),
                ContextFact("balanceDue", "Balance due", "$0.00"),
                ContextFact("paidStamp", "Paid stamp", "PAID"),
                ContextFact("notes", "Notes", ""),
            ),
            list_facts=(
                ListFact(
                    key="lineItems",
                    label="Line items",
                    item_facts=(
                        ContextFact("description", "Description", "Booth rental"),
                        ContextFact("qty", "Qty", "1"),
                        ContextFact("unitPrice", "Unit price", "$500.00"),
                        ContextFact("taxLabel", "Tax", "6%"),
                        ContextFact("amount", "Amount", "$500.00"),
                    ),
                    sample=(
                        {"description": "Booth rental", "qty": "1", "unitPrice": "$500.00", "taxLabel": "6%", "amount": "$500.00"},
                    ),
                ),
                ListFact(
                    key="payments",
                    label="Payments",
                    item_facts=(
                        ContextFact("date", "Date", "12 Jun 2026"),
                        ContextFact("method", "Method", "CASH"),
                        ContextFact("amount", "Amount", "$1,484.00"),
                    ),
                    sample=(),
                ),
            ),
            required_facts=("invoiceNumber",),
        )
    )


def invoice_doc() -> Dict:
    """The invoice/receipt document block tree (AC-07-17/18)."""
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
                "padding": {"top": 8, "bottom": 4, "left": 0, "right": 0},
                "columns": [
                    {
                        "id": _cid(),
                        "blocks": [
                            {"id": _bid(), "type": "heading", "text": "Invoice {{invoiceNumber}}", "level": 1, "align": "left"},
                            {"id": _bid(), "type": "text", "html": "Date: {{invoiceDate}} &nbsp;·&nbsp; Due: {{dueDate}} &nbsp;·&nbsp; Status: {{statusLabel}}", "align": "left"},
                        ],
                    }
                ],
            },
            {
                "id": _sid(),
                "layout": "50/50",
                "background": None,
                "padding": {"top": 4, "bottom": 8, "left": 0, "right": 0},
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
                            {"id": _bid(), "type": "text", "html": "{{recipientName}}<br/>{{buyerTin}}", "align": "left"},
                        ],
                    },
                ],
            },
            {
                "id": _sid(),
                "layout": "100",
                "background": None,
                "padding": {"top": 4, "bottom": 8, "left": 0, "right": 0},
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
                                    {"key": "unitPrice", "header": "Unit", "align": "right"},
                                    {"key": "taxLabel", "header": "Tax", "align": "center"},
                                    {"key": "amount", "header": "Amount", "align": "right"},
                                ],
                                "footer": [
                                    {"cells": [
                                        {"text": "Subtotal", "align": "right", "span": 4},
                                        {"text": "{{subtotal}}", "align": "right", "span": 1},
                                    ]},
                                    {"cells": [
                                        {"text": "Tax", "align": "right", "span": 4},
                                        {"text": "{{tax}}", "align": "right", "span": 1},
                                    ]},
                                    {"cells": [
                                        {"text": "Total", "align": "right", "span": 4},
                                        {"text": "{{total}}", "align": "right", "span": 1},
                                    ]},
                                    {"cells": [
                                        {"text": "Amount paid", "align": "right", "span": 4},
                                        {"text": "{{amountPaid}}", "align": "right", "span": 1},
                                    ]},
                                    {"cells": [
                                        {"text": "Balance due", "align": "right", "span": 4},
                                        {"text": "{{balanceDue}}", "align": "right", "span": 1},
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
                "padding": {"top": 4, "bottom": 4, "left": 0, "right": 0},
                "columns": [
                    {
                        "id": _cid(),
                        "blocks": [
                            {"id": _bid(), "type": "heading", "text": "{{paidStamp}}", "level": 2, "align": "right"},
                            {
                                "id": _bid(),
                                "type": "table",
                                "source": "payments",
                                "columns": [
                                    {"key": "date", "header": "Date", "align": "left"},
                                    {"key": "method", "header": "Method", "align": "left"},
                                    {"key": "amount", "header": "Amount", "align": "right"},
                                ],
                            },
                        ],
                    }
                ],
            },
            {
                "id": _sid(),
                "layout": "100",
                "background": None,
                "padding": {"top": 4, "bottom": 0, "left": 0, "right": 0},
                "columns": [{"id": _cid(), "blocks": [{"id": _bid(), "type": "text", "html": "{{notes}}", "align": "left"}]}],
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
