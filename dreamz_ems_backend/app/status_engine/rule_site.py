"""Status engine's rule-site lister (sprint-2/02 D12) — one observability
row per conditioned edge on the caller's resolved tier. Visibility mirrors
``GET /status-entities``: tenant callers don't see platform-owned entities.
Imported (and thereby registered) by ``app.rule_engine.sites._ensure_core``.
"""
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.status_transition import StatusTransition
from app.repositories.status_repository import StatusRepository
from app.rule_engine.prose import tree_text
from app.rule_engine.registry import fact_map
from app.rule_engine.sites import register_rule_site
from app.status_engine.registry import list_status_entities

SITE_KEY = "status_transition"
SITE_LABEL = "Status transition"


def _edge_rows(db: Session, current_user: Any) -> List[Dict[str, Any]]:
    is_operator = bool(getattr(current_user.tenant, "is_platform", False))
    status_repo = StatusRepository(db)
    rows: List[Dict[str, Any]] = []

    for entity in list_status_entities():
        if entity.platform_owned and not is_operator:
            continue
        scope = None if entity.platform_owned else current_user.tenant_id
        tier = status_repo.resolve_tier(entity.entity_type, scope)
        edges = (
            db.query(StatusTransition)
            .filter(
                StatusTransition.entity_type == entity.entity_type,
                StatusTransition.tenant_id.is_(None)
                if tier is None
                else StatusTransition.tenant_id == tier,
                StatusTransition.conditions_json.isnot(None),
            )
            .order_by(StatusTransition.sort_order)
            .all()
        )
        if not edges:
            continue
        facts = fact_map(["actor", f"record:{entity.entity_type}"])
        for edge in edges:
            rows.append(
                {
                    "site": SITE_KEY,
                    "siteLabel": SITE_LABEL,
                    "context": (
                        f"{entity.label} · {edge.from_status.label} → {edge.to_status.label}"
                    ),
                    "summary": tree_text(edge.conditions_json, facts),
                    # DATA, not a URL (code-review fix): the backend must not
                    # know frontend routes — the Rules page maps site+target
                    # to its own deep-link.
                    "target": entity.entity_type,
                    "updatedAt": edge.updated_at.isoformat() if edge.updated_at else None,
                }
            )
    return rows


register_rule_site(SITE_KEY, _edge_rows)
