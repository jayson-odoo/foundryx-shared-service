"""Rule-engine wire schemas (sprint-2/02) — camelCase."""
from typing import List, Optional

from pydantic import BaseModel


class RuleFactOption(BaseModel):
    value: str
    label: str


class RuleFactItem(BaseModel):
    key: str
    label: str
    type: str
    source: str
    sourceLabel: str
    options: Optional[List[RuleFactOption]] = None


class RuleFactsResponse(BaseModel):
    data: List[RuleFactItem]


class RuleSiteRowItem(BaseModel):
    site: str
    siteLabel: str
    context: str
    summary: str
    # Site-specific locator (e.g. the entity_type for status_transition) —
    # the FRONTEND maps (site, target) to its deep-link route; the backend
    # never hardcodes frontend paths (code-review fix).
    target: str
    updatedAt: Optional[str] = None


class RulesListResponse(BaseModel):
    data: List[RuleSiteRowItem]
    total: int
    page: int
