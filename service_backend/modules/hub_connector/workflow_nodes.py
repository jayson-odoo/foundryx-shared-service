"""Hub Connector workflow actions: what a person sees and does on the Hub
Connector screens can be asked for and done through a workflow (e.g. an
inbound WhatsApp message -> AI Agent -> one of these -> reply), under the
workflow's own authority (authorised at publish with ``workflows.manage``
plus this module's permission) and always inside the workflow's tenant.

- ``hub_connector.customer_view`` (read): what one customer of one hub sees,
  as the hub row ({code, name, brand_name, in_stock, incoming} + price only
  behind the hub's switch) and as a reply-ready ``summary``: one fact per
  line, "Label: value", code on its own line, capped with a "more" line.
- ``hub_connector.sync_now`` (do): run the CRM stock feed sync now.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.repositories.module_repository import ModuleRepository
from app.workflow_engine.context import render_field
from app.workflow_engine.registry import ActionDef, NodeField, NodeOutput, register_action

from .models import HcHub, HcHubCustomer
from .services import hub_service, sync_service
from .services.hub_service import HubError

MODULE_NAME = "hub_connector"
SUMMARY_LIMIT = 10


class ActionError(Exception):
    pass


def _require_active(db: Session, tenant_id: str) -> None:
    if not ModuleRepository(db).is_active(tenant_id, MODULE_NAME):
        raise ActionError("Hub Connector is not active.")


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def summary(rows: List[Dict[str, Any]], total: int, limit: int = SUMMARY_LIMIT) -> str:
    """Reply-ready text (owner chat rules): one fact per line, the code on its
    own line, "Label: value", no separators; a capped list ends with one
    'Reply "more"' line. An empty view says so plainly."""
    if not rows:
        return "No products to show for this customer."
    blocks = []
    for row in rows[:limit]:
        lines = [
            row["code"],
            f"Name: {row['name']}",
            f"Brand: {row['brand_name']}",
            f"In stock: {_yes_no(row['in_stock'])}",
            f"Incoming: {_yes_no(row['incoming'])}",
        ]
        if "list_price" in row:
            lines.append(f"Price: {row.get('currency') or ''} {row['list_price']}".replace("  ", " ").strip())
        blocks.append("\n".join(lines))
    text = "\n\n".join(blocks)
    remaining = total - min(len(rows), limit)
    if remaining > 0:
        text += f'\n\nReply "more" to see the next {min(remaining, limit)}.'
    return text


def customer_view(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    _require_active(db, tenant_id)
    hub_code = render_field(config.get("hubCode"), ctx).strip().lower()
    customer_code = render_field(config.get("customerCode"), ctx).strip()
    codes = [c.strip() for c in render_field(config.get("productCodes"), ctx).split(",") if c.strip()]
    try:
        offset = max(0, int(render_field(config.get("offset"), ctx).strip() or 0))
    except ValueError:
        offset = 0
    hub = db.query(HcHub).filter(HcHub.tenant_id == tenant_id, HcHub.code == hub_code).first()
    if hub is None or not hub.active:
        raise ActionError("Couldn't find that hub.")
    customer = (
        db.query(HcHubCustomer)
        .filter(
            HcHubCustomer.tenant_id == tenant_id,
            HcHubCustomer.hub_id == hub.id,
            HcHubCustomer.customer_code == customer_code,
            HcHubCustomer.active.is_(True),
        )
        .first()
    )
    if customer is None:
        raise ActionError("Couldn't find that customer on this hub.")
    rows, total = hub_service.customer_rows(db, hub, customer, codes=codes[:200] or None, limit=SUMMARY_LIMIT, offset=offset)
    return {
        "customerName": customer.customer_name,
        "total": total,
        "inStockCount": sum(1 for r in rows if r["in_stock"]),
        "rows": rows,
        "summary": summary(rows, max(0, total - offset)),
        "nextOffset": offset + len(rows) if offset + len(rows) < total else None,
    }


def sync_now(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    _require_active(db, tenant_id)
    try:
        state = sync_service.sync_tenant(db, tenant_id)
    except HubError as exc:
        raise ActionError(exc.message) from None
    if state.last_error:
        raise ActionError(state.last_error)
    return {"products": state.products or 0, "queued": state.queued or 0}


def register_workflow_nodes() -> None:
    register_action(
        ActionDef(
            key="hub_connector.customer_view",
            label="Hub customer availability",
            description="What one customer of a hub sees: in stock, incoming, and price when the hub shows it.",
            icon="Share2",
            category="Actions",
            module=MODULE_NAME,
            permission="hub_connector.view",
            executor=customer_view,
            fields=[
                NodeField(key="hubCode", label="Hub code", type="text", required=True, mergeable=True),
                NodeField(key="customerCode", label="Customer code", type="text", required=True, mergeable=True),
                NodeField(key="productCodes", label="Product codes", type="text", mergeable=True),
                NodeField(key="offset", label="Start from", type="text", mergeable=True),
            ],
            outputs=[
                NodeOutput("customerName", "Customer name"),
                NodeOutput("total", "Products shown"),
                NodeOutput("inStockCount", "In stock on this page"),
                NodeOutput("summary", "Reply text"),
                NodeOutput("nextOffset", "Next page starts at"),
            ],
        )
    )
    register_action(
        ActionDef(
            key="hub_connector.sync_now",
            label="Sync hub stock now",
            description="Read the CRM stock feed now and update every hub.",
            icon="RefreshCw",
            category="Actions",
            module=MODULE_NAME,
            permission="hub_connector.manage",
            executor=sync_now,
            outputs=[NodeOutput("products", "Products synced"), NodeOutput("queued", "Hub updates queued")],
        )
    )
