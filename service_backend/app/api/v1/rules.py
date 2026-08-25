"""Rule-engine routes (sprint-2/02).

``GET /rule-facts`` - whitelisted facts for a consumer's builder
(authenticated-only, like /roles/options - D13; config WRITES ride each
consumer's own permission, e.g. statuses.manage for edges).

``GET /rules`` - read-only observability aggregation over the rule-site
registry (D12), gated by ``rules.read``; rows deep-link to the owning editor.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.user import User
from app.rule_engine.registry import get_facts
from app.rule_engine.sites import list_rules
from app.schemas.rules import (
    RuleFactItem,
    RuleFactOption,
    RuleFactsResponse,
    RuleSiteRowItem,
    RulesListResponse,
)

facts_router = APIRouter()
rules_router = APIRouter()


@facts_router.get("", response_model=RuleFactsResponse)
def rule_facts(
    sources: str = Query(..., description="Comma-separated fact sources"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RuleFactsResponse:
    names = [name.strip() for name in sources.split(",") if name.strip()]
    items = []
    for source_name, source_label, fact in get_facts(names):
        options = fact.options
        if callable(options):  # tenant-scoped options (e.g. role names)
            options = options(db, current_user)
        items.append(
            RuleFactItem(
                key=fact.key,
                label=fact.label,
                type=fact.type,
                source=source_name,
                sourceLabel=source_label,
                options=(
                    [RuleFactOption(**option) for option in options]
                    if options
                    else None
                ),
            )
        )
    return RuleFactsResponse(data=items)


@rules_router.get("", response_model=RulesListResponse)
def rules_list(
    page: int = Query(0, ge=0),
    pageSize: int = Query(25, ge=1, le=200),
    search: str = Query(""),
    sortField: str = Query("context"),
    sortDir: str = Query("asc"),
    current_user: User = Depends(require_permission("rules.read")),
    db: Session = Depends(get_db),
) -> RulesListResponse:
    rows = list_rules(db, current_user)

    term = search.strip().lower()
    if term:
        rows = [
            row
            for row in rows
            if term in row["context"].lower()
            or term in row["summary"].lower()
            or term in row["siteLabel"].lower()
        ]

    field = {"site": "siteLabel", "updated": "updatedAt"}.get(sortField, "context")
    rows.sort(key=lambda row: str(row.get(field) or ""), reverse=sortDir == "desc")

    start = page * pageSize
    return RulesListResponse(
        data=[RuleSiteRowItem(**row) for row in rows[start : start + pageSize]],
        total=len(rows),
        page=page,
    )
